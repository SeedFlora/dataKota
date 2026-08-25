import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';
import 'package:supabase_flutter/supabase_flutter.dart';
import 'package:uuid/uuid.dart';

import '../../core/config/app_config.dart';
import '../../core/security/image_upload_sanitizer.dart';
import '../auth/user_profile.dart';
import 'report_actions.dart';
import 'report_models.dart';
import 'reports_reader.dart';

class ReportsRepository implements ReportsReader, ReportAdminActions {
  ReportsRepository(
    this._client,
    this._uuid, {
    ImageUploadSanitizer imageSanitizer = const ImageUploadSanitizer(
      maxOutputBytes: ImageUploadSanitizer.reportOutputByteLimit,
    ),
  }) : _imageSanitizer = imageSanitizer;

  final SupabaseClient _client;
  final Uuid _uuid;
  final ImageUploadSanitizer _imageSanitizer;

  static const _bucket = 'report-images';
  static const _publicFeedLimit = 200;
  static const _historyLimit = 100;
  static const _statusUpdateRpc = 'update_report_status';
  static const _submitReportRpc = 'submit_report';
  static const _publicFeedRpc = 'get_public_report_feed';
  static const _reportDetailRpc = 'get_report_detail';
  static const _publicFeedRefreshInterval = Duration(seconds: 30);

  @override
  Stream<List<CityReport>> watchByUser(String userId) {
    return _client
        .from('reports')
        .stream(primaryKey: ['id'])
        .eq('user_id', userId)
        .order('created_at', ascending: false)
        .map((rows) => rows.map(CityReport.fromMap).toList(growable: false));
  }

  @override
  Stream<List<CityReport>> watchByCategory(IssueCategory category) {
    return _client
        .from('reports')
        .stream(primaryKey: ['id'])
        .eq('category', category.dbValue)
        .order('created_at', ascending: false)
        .map(
          (rows) => rows
              .where((row) => row['status'] != ReportStatus.rejected.dbValue)
              .map(CityReport.fromMap)
              .toList(growable: false),
        );
  }

  @override
  Stream<List<CityReport>> watchAll() {
    return _client
        .from('reports')
        .stream(primaryKey: ['id'])
        .order('created_at', ascending: false)
        .limit(_publicFeedLimit)
        .map((rows) => rows.map(CityReport.fromMap).toList(growable: false));
  }

  @override
  Stream<CityReport?> watchById(String reportId) async* {
    while (true) {
      final response = await _client.rpc(
        _reportDetailRpc,
        params: {'p_report_id': reportId},
      );
      if (response == null) {
        yield null;
      } else if (response is Map) {
        yield CityReport.fromMap(Map<String, dynamic>.from(response));
      } else if (response is List &&
          response.isNotEmpty &&
          response.first is Map) {
        yield CityReport.fromMap(
          Map<String, dynamic>.from(response.first as Map),
        );
      } else {
        throw StateError('Unexpected $_reportDetailRpc response: $response');
      }
      await Future<void>.delayed(_publicFeedRefreshInterval);
    }
  }

  @override
  Stream<List<ReportHistoryEntry>> watchHistory(String reportId) {
    return _client
        .from('report_history')
        .stream(primaryKey: ['id'])
        .eq('report_id', reportId)
        .order('created_at', ascending: true)
        .limit(_historyLimit)
        .map(
          (rows) =>
              rows.map(ReportHistoryEntry.fromMap).toList(growable: false),
        );
  }

  // Backwards-compatible aliases used by existing providers.
  Stream<List<CityReport>> watchMyReports(String userId) => watchByUser(userId);
  Stream<List<CityReport>> watchPublicReports() async* {
    // Views/realtime subscriptions over the base reports table would either
    // bypass redaction or be filtered by owner/admin RLS. Poll the explicit
    // SECURITY DEFINER redacted projection instead.
    while (true) {
      final response = await _client.rpc(
        _publicFeedRpc,
        params: const {'p_limit': _publicFeedLimit},
      );
      if (response is! List) {
        throw StateError('Unexpected $_publicFeedRpc response: $response');
      }
      yield response
          .whereType<Map>()
          .map((row) => CityReport.fromMap(Map<String, dynamic>.from(row)))
          .toList(growable: false);
      await Future<void>.delayed(_publicFeedRefreshInterval);
    }
  }

  Stream<CityReport?> watchReportById(String reportId) => watchById(reportId);
  Stream<List<ReportHistoryEntry>> watchReportHistory(String reportId) =>
      watchHistory(reportId);

  // ---------------------------------------------------------------------------
  // Admin actions
  // ---------------------------------------------------------------------------

  @override
  Future<CityReport> verify(String reportId, {String note = ''}) =>
      _runStatusUpdate(reportId, ReportStatus.verified, note);

  @override
  Future<CityReport> markInProgress(String reportId, {String note = ''}) =>
      _runStatusUpdate(reportId, ReportStatus.inProgress, note);

  @override
  Future<CityReport> markResolved(
    String reportId, {
    required XFile evidencePhoto,
    String note = '',
  }) async {
    final actorId = _client.auth.currentUser?.id;
    if (actorId == null) {
      throw StateError('You need to log in again.');
    }

    final sanitized = await _imageSanitizer.sanitizeXFile(evidencePhoto);
    final objectPath =
        '$actorId/resolution-evidence/$reportId-${DateTime.now().millisecondsSinceEpoch}.${sanitized.extension}';

    await _client.storage
        .from(_bucket)
        .uploadBinary(
          objectPath,
          sanitized.bytes,
          fileOptions: FileOptions(
            upsert: true,
            contentType: sanitized.contentType,
          ),
        );

    try {
      return await _runStatusUpdate(
        reportId,
        ReportStatus.resolved,
        note,
        resolutionPhotoUrl: '$_bucket/$objectPath',
        resolutionNote: note,
      );
    } catch (_) {
      await _client.storage
          .from(_bucket)
          .remove([objectPath])
          .catchError((_) => <FileObject>[]);
      rethrow;
    }
  }

  @override
  Future<CityReport> reject(String reportId, {required String reason}) =>
      _runStatusUpdate(reportId, ReportStatus.rejected, reason);

  @override
  Future<CityReport> recategorizeAndRetriage(
    String reportId, {
    required IssueCategory newCategory,
    required String note,
  }) => _runStatusUpdate(
    reportId,
    ReportStatus.verified,
    note,
    newCategory: newCategory,
  );

  Future<CityReport> _runStatusUpdate(
    String reportId,
    ReportStatus status,
    String note, {
    IssueCategory? newCategory,
    String? resolutionPhotoUrl,
    String? resolutionNote,
  }) async {
    final params = <String, dynamic>{
      'p_report_id': reportId,
      'p_new_status': status.dbValue,
      'p_note': note,
      // p_new_category recategorizes the report. The RPC deliberately clears
      // its current assignment; it does not accept or select a target agency.
      if (newCategory != null) 'p_new_category': newCategory.dbValue,
    };
    if (resolutionPhotoUrl != null) {
      params['p_resolution_photo_url'] = resolutionPhotoUrl;
    }
    if (resolutionNote != null) {
      params['p_resolution_note'] = resolutionNote;
    }

    final response = await _client.rpc(_statusUpdateRpc, params: params);

    if (response is Map<String, dynamic>) {
      return CityReport.fromMap(response);
    }
    if (response is Map) {
      return CityReport.fromMap(Map<String, dynamic>.from(response));
    }
    if (response is List && response.isNotEmpty && response.first is Map) {
      return CityReport.fromMap(
        Map<String, dynamic>.from(response.first as Map),
      );
    }
    throw StateError('Unexpected $_statusUpdateRpc response: $response');
  }

  // ---------------------------------------------------------------------------
  // Submit
  // ---------------------------------------------------------------------------

  Future<CityReport> submitReport({
    required UserProfile profile,
    required XFile image,
    required IssueCategory category,
    required AiPrediction? prediction,
    required String description,
    required ReportLocationData location,
  }) async {
    final actorId = _client.auth.currentUser?.id;
    if (actorId == null) {
      throw StateError('You need to log in again.');
    }
    if (profile.id != actorId) {
      throw StateError('The report profile does not match the active session.');
    }
    final reportId = _uuid.v4();
    final sanitized = await _imageSanitizer.sanitizeXFile(image);
    final objectPath = '$actorId/$reportId.${sanitized.extension}';

    await _client.storage
        .from(_bucket)
        .uploadBinary(
          objectPath,
          sanitized.bytes,
          fileOptions: FileOptions(
            upsert: true,
            contentType: sanitized.contentType,
          ),
        );

    dynamic response;
    try {
      // The RPC derives identity from auth.uid(), forces submitted/untrusted
      // state, clears routing fields, and inserts initial history atomically.
      response = await _client.rpc(
        _submitReportRpc,
        params: {
          'p_report_id': reportId,
          'p_category': category.dbValue,
          'p_image_url': '$_bucket/$objectPath',
          'p_description': description.trim(),
          'p_latitude': location.latitude,
          'p_longitude': location.longitude,
          'p_address': location.address,
          'p_ai_prediction': prediction?.category.dbValue ?? category.dbValue,
          'p_ai_confidence': prediction?.confidence ?? 0,
          'p_ai_probabilities':
              prediction?.rawPayload['all_probabilities'] ?? <String, double>{},
          'p_ai_model_name': prediction?.rawPayload['model_name'],
          'p_ai_model_version': prediction?.rawPayload['model_version'],
          'p_ai_export_manifest_sha256':
              prediction?.rawPayload['export_manifest_sha256'],
          'p_ai_class_map_sha256': prediction?.rawPayload['class_map_sha256'],
          'p_ai_agency_registry_status':
              prediction?.rawPayload['agency_registry_status'],
          'p_ai_inference_method':
              prediction?.rawPayload['inference_method'] ?? 'client_unattested',
          'p_ai_uncertainty_method':
              prediction?.rawPayload['uncertainty_method'],
          'p_ai_epistemic_uncertainty':
              prediction?.rawPayload['epistemic_uncertainty'],
          'p_ai_predictive_entropy':
              prediction?.rawPayload['predictive_entropy'],
          'p_ai_expected_data_entropy':
              prediction?.rawPayload['expected_data_entropy'],
          'p_ai_epistemic_uncertainty_threshold':
              prediction?.rawPayload['epistemic_uncertainty_threshold'],
          'p_ai_review_required':
              prediction?.rawPayload['review_required'] ?? false,
          'p_ai_review_reasons':
              prediction?.rawPayload['review_reasons'] ?? <String>[],
        },
      );
    } catch (_) {
      // Roll back the orphaned storage object so a retry doesn't pile up bytes.
      await _client.storage
          .from(_bucket)
          .remove([objectPath])
          .catchError((_) => <FileObject>[]);
      rethrow;
    }

    // Do not delete the evidence after a successful transaction merely because
    // a proxy returned an unexpected representation. Linked evidence is
    // intentionally immutable; surface the protocol error for reconciliation.
    if (response is Map<String, dynamic>) {
      return CityReport.fromMap(response);
    }
    if (response is Map) {
      return CityReport.fromMap(Map<String, dynamic>.from(response));
    }
    if (response is List && response.isNotEmpty && response.first is Map) {
      return CityReport.fromMap(
        Map<String, dynamic>.from(response.first as Map),
      );
    }
    throw StateError('Unexpected $_submitReportRpc response: $response');
  }
}

final reportsRepositoryProvider = Provider<ReportsRepository>((ref) {
  return ReportsRepository(ref.watch(supabaseClientProvider), const Uuid());
});

/// Read-only view of [ReportsRepository] for citizen / admin list screens.
final reportsReaderProvider = Provider<ReportsReader>(
  (ref) => ref.watch(reportsRepositoryProvider),
);

/// Mutation surface for moderator and super-admin screens.
final reportActionsProvider = Provider<ReportAdminActions>(
  (ref) => ref.watch(reportsRepositoryProvider),
);
