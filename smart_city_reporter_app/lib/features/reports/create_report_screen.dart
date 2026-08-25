import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:image_picker/image_picker.dart';

import '../../app/theme/app_theme.dart';
import '../../core/l10n/l10n.dart';
import '../../core/widgets/smart_city_ui.dart';
import '../settings/settings_controller.dart';
import 'create_report_controller.dart';
import 'report_models.dart';

class CreateReportScreen extends ConsumerStatefulWidget {
  const CreateReportScreen({super.key});

  @override
  ConsumerState<CreateReportScreen> createState() => _CreateReportScreenState();
}

class _CreateReportScreenState extends ConsumerState<CreateReportScreen> {
  bool _requestedAutoLocation = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_requestedAutoLocation) return;
    _requestedAutoLocation = true;
    final settings = ref.read(settingsControllerProvider);
    final state = ref.read(createReportControllerProvider);
    if (settings.autoUseCurrentLocation && state.location == null) {
      Future<void>.microtask(
        () => ref
            .read(createReportControllerProvider.notifier)
            .captureCurrentLocation(),
      );
    }
  }

  Future<void> _classifyAndContinue() async {
    final notifier = ref.read(createReportControllerProvider.notifier);
    await notifier.classifyImage();
    final state = ref.read(createReportControllerProvider);
    if (!mounted) return;
    if (state.canReview) context.push('/review-report');
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(createReportControllerProvider);
    final palette = context.palette;
    final l10n = context.l10n;

    return Scaffold(
      backgroundColor: palette.surface,
      appBar: AppBar(title: Text(l10n.createReportTitle)),
      body: SafeArea(
        top: false,
        child: ListView(
          padding: pagePadding(context).copyWith(bottom: 40),
          children: [
            _SectionLabel(l10n.addPhoto),
            const SizedBox(height: 4),
            Text(
              l10n.addPhotoHint,
              style: Theme.of(context).textTheme.bodySmall,
            ),
            const SizedBox(height: 12),
            _PhotoPicker(
              imageFile: state.imageFile,
              busy: state.isBusy,
              onCamera: () => ref
                  .read(createReportControllerProvider.notifier)
                  .pickFromCamera(),
              onGallery: () => ref
                  .read(createReportControllerProvider.notifier)
                  .pickFromGallery(),
            ),
            const SizedBox(height: 28),
            _SectionLabel(l10n.locationStep),
            const SizedBox(height: 4),
            Text(
              l10n.locationHint,
              style: Theme.of(context).textTheme.bodySmall,
            ),
            const SizedBox(height: 12),
            _LocationCard(
              location: state.location,
              locating: state.isLocating,
              onUseCurrent: () => ref
                  .read(createReportControllerProvider.notifier)
                  .captureCurrentLocation(),
            ),
            const SizedBox(height: 28),
            _SectionLabel(l10n.shortDescription),
            const SizedBox(height: 4),
            Text(
              l10n.shortDescriptionHint,
              style: Theme.of(context).textTheme.bodySmall,
            ),
            const SizedBox(height: 12),
            TextField(
              minLines: 3,
              maxLines: 5,
              onChanged: ref
                  .read(createReportControllerProvider.notifier)
                  .updateDescription,
              decoration: InputDecoration(
                hintText: l10n.descriptionPlaceholder,
              ),
            ),
            const SizedBox(height: 6),
            Text(
              l10n.descriptionLanguageHint,
              style: Theme.of(context).textTheme.bodySmall,
            ),
            if (state.errorMessage != null) ...[
              const SizedBox(height: 16),
              _ErrorCard(message: _localizeError(context, state.errorMessage!)),
            ],
            const SizedBox(height: 28),
            Builder(
              builder: (context) {
                final ready =
                    state.imageFile != null &&
                    state.location != null &&
                    state.description.trim().length >= 10;
                final label = ready
                    ? l10n.runAiClassification
                    : state.imageFile == null
                    ? l10n.addPhotoFirst
                    : state.location == null
                    ? l10n.useCurrentLocation
                    : l10n.addDescriptionFirst;
                return ElevatedButton.icon(
                  onPressed: state.isBusy || !ready
                      ? null
                      : _classifyAndContinue,
                  icon: state.isBusy
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            color: Colors.white,
                          ),
                        )
                      : const Icon(Icons.auto_awesome_rounded),
                  label: Text(label),
                );
              },
            ),
          ],
        ),
      ),
    );
  }
}

class _SectionLabel extends StatelessWidget {
  const _SectionLabel(this.text);
  final String text;

  @override
  Widget build(BuildContext context) {
    return Text(text, style: Theme.of(context).textTheme.titleMedium);
  }
}

String _localizeError(BuildContext context, String code) {
  final l10n = context.l10n;
  return switch (code) {
    'photo-required' => l10n.selectPhotoFirst,
    'description-min-10' => l10n.descriptionMinError,
    'location-required' =>
      'Capture latitude and longitude before classification.',
    _ => code,
  };
}

class _PhotoPicker extends StatelessWidget {
  const _PhotoPicker({
    required this.imageFile,
    required this.busy,
    required this.onCamera,
    required this.onGallery,
  });

  final XFile? imageFile;
  final bool busy;
  final VoidCallback onCamera;
  final VoidCallback onGallery;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    final file = imageFile;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        AspectRatio(
          aspectRatio: 4 / 3,
          child: ClipRRect(
            borderRadius: BorderRadius.circular(20),
            child: file != null
                ? Image.file(
                    File(file.path),
                    fit: BoxFit.cover,
                    // Cap decode at the on-screen width rather than the full
                    // ~1280px capture, so the preview doesn't hold a large
                    // bitmap in memory.
                    cacheWidth:
                        (MediaQuery.sizeOf(context).width *
                                MediaQuery.devicePixelRatioOf(context))
                            .round(),
                  )
                : _EmptyPhoto(palette: palette),
          ),
        ),
        const SizedBox(height: 12),
        Row(
          children: [
            Expanded(
              child: ElevatedButton.icon(
                onPressed: busy ? null : onCamera,
                icon: const Icon(Icons.photo_camera_rounded),
                label: Text(context.l10n.camera),
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: OutlinedButton.icon(
                onPressed: busy ? null : onGallery,
                icon: const Icon(Icons.photo_library_rounded),
                label: Text(context.l10n.gallery),
              ),
            ),
          ],
        ),
      ],
    );
  }
}

class _EmptyPhoto extends StatelessWidget {
  const _EmptyPhoto({required this.palette});

  final AppPalette palette;

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: BoxDecoration(
        gradient: LinearGradient(
          colors: [
            palette.accentCyan.withValues(alpha: 0.08),
            palette.accentBlue.withValues(alpha: 0.08),
          ],
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
        ),
        border: Border.all(color: palette.border),
        borderRadius: BorderRadius.circular(20),
      ),
      child: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: palette.surfaceElevated,
                shape: BoxShape.circle,
                boxShadow: const [
                  BoxShadow(
                    color: Color(0x140F172A),
                    blurRadius: 12,
                    offset: Offset(0, 4),
                  ),
                ],
              ),
              child: Icon(
                Icons.add_a_photo_rounded,
                size: 26,
                color: palette.accentCyan,
              ),
            ),
            const SizedBox(height: 10),
            Text(
              context.l10n.noPhotoYet,
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 2),
            Text(
              context.l10n.tapAddPhoto,
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ],
        ),
      ),
    );
  }
}

class _LocationCard extends StatelessWidget {
  const _LocationCard({
    required this.location,
    required this.locating,
    required this.onUseCurrent,
  });

  final ReportLocationData? location;
  final bool locating;
  final VoidCallback onUseCurrent;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    final text = Theme.of(context).textTheme;
    final hasCoords = location != null;
    final hasAddress = hasCoords && location!.address.isNotEmpty;

    final String label;
    if (hasAddress) {
      label = location!.address;
    } else if (hasCoords) {
      label =
          '${location!.latitude.toStringAsFixed(5)}, ${location!.longitude.toStringAsFixed(5)}';
    } else {
      label = context.l10n.noLocationYet;
    }

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: palette.surfaceElevated,
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: palette.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (locating)
                const SizedBox(
                  width: 20,
                  height: 20,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              else
                Icon(
                  hasCoords
                      ? Icons.location_on_rounded
                      : Icons.location_off_rounded,
                  color: hasCoords ? palette.accentCyan : palette.inkSubtle,
                  size: 20,
                ),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  label,
                  style: hasAddress ? text.bodyLarge : text.bodyMedium,
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          OutlinedButton.icon(
            onPressed: locating ? null : onUseCurrent,
            icon: const Icon(Icons.my_location_rounded),
            label: Text(
              hasCoords
                  ? context.l10n.refreshLocation
                  : context.l10n.useCurrentLocation,
            ),
          ),
        ],
      ),
    );
  }
}

class _ErrorCard extends StatelessWidget {
  const _ErrorCard({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: palette.danger.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: palette.danger.withValues(alpha: 0.24)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(Icons.error_outline_rounded, color: palette.danger, size: 20),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              message,
              style: Theme.of(
                context,
              ).textTheme.bodyMedium?.copyWith(color: palette.danger),
            ),
          ),
        ],
      ),
    );
  }
}
