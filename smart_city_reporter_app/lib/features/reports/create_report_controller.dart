import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';

import '../../core/services/ai_classification_service.dart';
import '../../core/services/location_service.dart';
import '../../core/services/media_service.dart';
import '../auth/auth_repository.dart';
import 'report_models.dart';
import 'reports_repository.dart';
import 'reports_scope.dart';

class CreateReportState {
  const CreateReportState({
    this.imageFile,
    this.prediction,
    this.selectedCategory,
    this.didEditCategory = false,
    this.location,
    this.description = '',
    this.isBusy = false,
    this.isLocating = false,
    this.errorMessage,
    this.didSubmit = false,
    this.lastCreatedReportId,
  });

  final XFile? imageFile;
  final AiPrediction? prediction;
  final IssueCategory? selectedCategory;
  final bool didEditCategory;
  final ReportLocationData? location;
  final String description;

  /// Blocks photo/classify/submit buttons (image pick, classify, upload).
  final bool isBusy;

  /// Only blocks the location card — photo + classify buttons stay live so
  /// the user isn't locked out while GPS is warming up.
  final bool isLocating;
  final String? errorMessage;
  final bool didSubmit;
  final String? lastCreatedReportId;

  bool get canReview => imageFile != null && prediction != null;

  /// Minimum description length, kept in sync with the classify gate so a
  /// report can't be downgraded to an empty/too-short description on review.
  static const int minDescriptionLength = 10;

  bool get hasEnoughDescription =>
      description.trim().length >= minDescriptionLength;

  bool get canSubmit =>
      imageFile != null &&
      selectedCategory != null &&
      location != null &&
      hasEnoughDescription;

  CreateReportState copyWith({
    XFile? imageFile,
    AiPrediction? prediction,
    IssueCategory? selectedCategory,
    bool? didEditCategory,
    ReportLocationData? location,
    String? description,
    bool? isBusy,
    bool? isLocating,
    String? errorMessage,
    bool clearError = false,
    bool? didSubmit,
    String? lastCreatedReportId,
  }) {
    return CreateReportState(
      imageFile: imageFile ?? this.imageFile,
      prediction: prediction ?? this.prediction,
      selectedCategory: selectedCategory ?? this.selectedCategory,
      didEditCategory: didEditCategory ?? this.didEditCategory,
      location: location ?? this.location,
      description: description ?? this.description,
      isBusy: isBusy ?? this.isBusy,
      isLocating: isLocating ?? this.isLocating,
      errorMessage: clearError ? null : errorMessage ?? this.errorMessage,
      didSubmit: didSubmit ?? this.didSubmit,
      lastCreatedReportId: lastCreatedReportId ?? this.lastCreatedReportId,
    );
  }

  CreateReportState clearSubmission() => CreateReportState(
    imageFile: imageFile,
    prediction: prediction,
    selectedCategory: selectedCategory,
    didEditCategory: didEditCategory,
    location: location,
    description: description,
  );
}

class CreateReportController extends Notifier<CreateReportState> {
  late final MediaService _mediaService = ref.read(mediaServiceProvider);
  late final LocationService _locationService = ref.read(
    locationServiceProvider,
  );
  late final AiClassificationService _aiService = ref.read(
    aiClassificationServiceProvider,
  );
  late final ReportsRepository _reportsRepository = ref.read(
    reportsRepositoryProvider,
  );

  Timer? _geocodeDebounce;

  @override
  CreateReportState build() {
    ref.onDispose(() => _geocodeDebounce?.cancel());
    return const CreateReportState();
  }

  Future<void> pickFromCamera() => _pick(_mediaService.pickFromCamera);
  Future<void> pickFromGallery() => _pick(_mediaService.pickFromGallery);

  Future<void> _pick(Future<XFile?> Function() pick) async {
    final file = await pick();
    if (file == null) {
      return;
    }
    // New photo invalidates the prediction (it was for the previous image),
    // but we keep description and location so the user doesn't re-type them.
    state = CreateReportState(
      imageFile: file,
      location: state.location,
      description: state.description,
    );
  }

  Future<void> classifyImage() async {
    if (state.imageFile == null) {
      state = state.copyWith(errorMessage: 'photo-required');
      return;
    }
    if (!state.hasEnoughDescription) {
      state = state.copyWith(errorMessage: 'description-min-10');
      return;
    }
    if (state.location == null) {
      state = state.copyWith(errorMessage: 'location-required');
      return;
    }

    state = state.copyWith(isBusy: true, clearError: true);
    try {
      final prediction = await _aiService.classify(
        imageFile: state.imageFile!,
        description: state.description.trim(),
        location: state.location!,
      );
      state = state.copyWith(
        isBusy: false,
        prediction: prediction,
        selectedCategory: prediction.category,
        didEditCategory: false,
      );
    } catch (error) {
      state = state.copyWith(isBusy: false, errorMessage: error.toString());
    }
  }

  Future<void> captureCurrentLocation() async {
    state = state.copyWith(isLocating: true, clearError: true);
    try {
      // Fast path: coordinates only. Shows a pin on the map immediately.
      final coords = await _locationService.getCoordinates();
      state = state.copyWith(
        isLocating: false,
        location: ReportLocationData(
          latitude: coords.latitude,
          longitude: coords.longitude,
          address: '',
        ),
      );

      // Slow path: fill in the reverse-geocoded address once it arrives.
      // Failures here are non-fatal — the user can still submit with just
      // coordinates; the server also has the address column defaulting to ''.
      try {
        final address = await _locationService.reverseGeocode(
          latitude: coords.latitude,
          longitude: coords.longitude,
        );
        final current = state.location;
        if (current != null &&
            current.latitude == coords.latitude &&
            current.longitude == coords.longitude) {
          state = state.copyWith(
            location: ReportLocationData(
              latitude: coords.latitude,
              longitude: coords.longitude,
              address: address,
            ),
          );
        }
      } catch (_) {
        // Swallow — coords already captured, address is cosmetic.
      }
    } catch (error) {
      state = state.copyWith(isLocating: false, errorMessage: error.toString());
    }
  }

  Future<void> updateLocation(double latitude, double longitude) async {
    // Show the new pin position immediately so the map feels responsive,
    // then debounce the reverse-geocode network call so dragging doesn't
    // fire one request per pixel.
    state = state.copyWith(
      clearError: true,
      location: ReportLocationData(
        latitude: latitude,
        longitude: longitude,
        address: state.location?.address ?? '',
      ),
    );

    _geocodeDebounce?.cancel();
    _geocodeDebounce = Timer(const Duration(milliseconds: 400), () async {
      try {
        final address = await _locationService.reverseGeocode(
          latitude: latitude,
          longitude: longitude,
        );
        // Bail if the user has since moved the pin elsewhere.
        final current = state.location;
        if (current == null ||
            current.latitude != latitude ||
            current.longitude != longitude) {
          return;
        }
        state = state.copyWith(
          location: ReportLocationData(
            latitude: latitude,
            longitude: longitude,
            address: address,
          ),
        );
      } catch (error) {
        state = state.copyWith(errorMessage: error.toString());
      }
    });
  }

  void updateDescription(String description) {
    state = state.copyWith(description: description, clearError: true);
  }

  void updateCategory(IssueCategory category) {
    state = state.copyWith(
      selectedCategory: category,
      didEditCategory: true,
      clearError: true,
    );
  }

  Future<void> submit() async {
    if (!state.canSubmit) {
      state = state.copyWith(
        errorMessage:
            'Please complete the photo, category, location, and description.',
      );
      return;
    }

    final profile = await ref.read(currentUserProfileProvider.future);
    if (profile == null) {
      state = state.copyWith(errorMessage: 'You need to log in again.');
      return;
    }

    state = state.copyWith(isBusy: true, clearError: true);
    try {
      final report = await _reportsRepository.submitReport(
        profile: profile,
        image: state.imageFile!,
        category: state.selectedCategory!,
        prediction: state.prediction,
        description: state.description,
        location: state.location!,
      );
      state = CreateReportState(
        didSubmit: true,
        lastCreatedReportId: report.id,
      );
    } catch (error) {
      state = state.copyWith(isBusy: false, errorMessage: error.toString());
    }
  }

  void reset() {
    state = const CreateReportState();
  }
}

final createReportControllerProvider =
    NotifierProvider<CreateReportController, CreateReportState>(
      CreateReportController.new,
    );

final myReportsProvider = StreamProvider.autoDispose<List<CityReport>>((ref) {
  final profile = ref.watch(currentUserProfileProvider).asData?.value;
  if (profile == null) {
    return const Stream.empty();
  }
  return ref.watch(reportsRepositoryProvider).watchMyReports(profile.id);
});

final publicReportsProvider = StreamProvider.autoDispose<List<CityReport>>((
  ref,
) {
  return ref.watch(reportsRepositoryProvider).watchPublicReports();
});

final reportDetailProvider = StreamProvider.autoDispose
    .family<CityReport?, String>((ref, reportId) {
      return ref.watch(reportsRepositoryProvider).watchReportById(reportId);
    });

final reportHistoryProvider = StreamProvider.autoDispose
    .family<List<ReportHistoryEntry>, String>((ref, reportId) {
      return ref.watch(reportsRepositoryProvider).watchReportHistory(reportId);
    });

/// Reports filtered by the current user's role-derived scope.
/// Citizen → own reports. AgencyAdmin → reports for their agency.
/// SuperAdmin → all reports.
final scopedReportsProvider = StreamProvider.autoDispose<List<CityReport>>((
  ref,
) {
  final scope = ref.watch(reportsScopeProvider);
  if (scope is CitizenScope && scope.userId.isEmpty) {
    return const Stream.empty();
  }
  return scope.watch(ref.watch(reportsReaderProvider));
});
