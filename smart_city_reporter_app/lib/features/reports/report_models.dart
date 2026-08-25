/// Operational instansi (agency) labels emitted by the multimodal classifier.
///
/// `dbValue` is the stable string slug stored in Supabase and used as the
/// lookup key from native bridges. `cloudId` is the integer label id the
/// `serve_model.py` /predict endpoint returns in `predicted_dinas_id`, also
/// matching the `label_id` column in `artifacts/splits/train.csv`.
enum IssueCategory {
  dinasBinaMarga(
    dbValue: 'dinas_bina_marga',
    cloudId: 0,
    label: 'Dinas Bina Marga',
  ),
  satpolPP(
    dbValue: 'satpol_pp',
    cloudId: 1,
    label: 'Satuan Polisi Pamong Praja',
  ),
  dinasPerhubungan(
    dbValue: 'dinas_perhubungan',
    cloudId: 2,
    label: 'Dinas Perhubungan',
  ),
  kelurahan(dbValue: 'kelurahan', cloudId: 3, label: 'Kelurahan'),
  dinasPertamananHutan(
    dbValue: 'dinas_pertamanan_hutan',
    cloudId: 4,
    label: 'Dinas Pertamanan dan Hutan',
  ),
  dinasSDA(dbValue: 'dinas_sda', cloudId: 5, label: 'Dinas Sumber Daya Air'),
  dinasCiptaKarya(
    dbValue: 'dinas_cipta_karya',
    cloudId: 6,
    label: 'Dinas Cipta Karya, Tata Ruang, dan Pertanahan',
  ),
  badanBUMD(
    dbValue: 'badan_bumd',
    cloudId: 7,
    label: 'Badan Pembinaan Badan Usaha Milik Daerah',
  ),
  instansiLain(dbValue: 'instansi_lain', cloudId: 8, label: 'Instansi lain');

  const IssueCategory({
    required this.dbValue,
    required this.cloudId,
    required this.label,
  });

  final String dbValue;
  final int cloudId;
  final String label;

  static IssueCategory fromValue(String value) {
    return IssueCategory.values.firstWhere(
      (category) => category.dbValue == value,
      orElse: () => IssueCategory.instansiLain,
    );
  }

  static IssueCategory fromCloudId(int id) {
    return IssueCategory.values.firstWhere(
      (category) => category.cloudId == id,
      orElse: () => IssueCategory.instansiLain,
    );
  }

  /// Match by either the formal name (`predicted_dinas` from the cloud API)
  /// or the dbValue slug. Returns `instansiLain` for unknown values.
  static IssueCategory fromAnyIdentifier(String value) {
    final trimmed = value.trim();
    for (final category in IssueCategory.values) {
      if (category.dbValue == trimmed || category.label == trimmed) {
        return category;
      }
    }
    return IssueCategory.instansiLain;
  }
}

enum ReportStatus {
  submitted('submitted'),
  verified('verified'),
  inProgress('in_progress'),
  resolved('resolved'),
  rejected('rejected');

  const ReportStatus(this.dbValue);
  final String dbValue;

  String get label => switch (this) {
    ReportStatus.submitted => 'Submitted',
    ReportStatus.verified => 'Verified',
    ReportStatus.inProgress => 'In Progress',
    ReportStatus.resolved => 'Resolved',
    ReportStatus.rejected => 'Rejected',
  };

  static ReportStatus fromValue(String value) {
    return ReportStatus.values.firstWhere(
      (status) => status.dbValue == value,
      orElse: () => ReportStatus.submitted,
    );
  }
}

class AiPrediction {
  const AiPrediction({
    required this.category,
    required this.confidence,
    required this.rawPayload,
    this.assignment,
  });

  final IssueCategory category;

  /// Historical API name for the maximum class score. It is not interpreted
  /// as calibrated correctness probability by the client.
  final double confidence;
  final Map<String, dynamic> rawPayload;
  final ReportAssignment? assignment;

  bool get reviewRequired => rawPayload['review_required'] == true;

  List<String> get reviewReasons =>
      _parseStringList(rawPayload['review_reasons']);

  /// Top-N predictions ordered by descending model score, when the backend
  /// supplies them. Each entry retains the historical field name `confidence`.
  /// Empty when the
  /// backend only returns a single label.
  List<({IssueCategory category, double confidence})> topPredictions({
    int limit = 3,
  }) {
    final raw = rawPayload['top_predictions'];
    if (raw is List && raw.isNotEmpty) {
      final parsed = <({IssueCategory category, double confidence})>[];
      for (final item in raw) {
        if (item is! Map) continue;
        final label = item['label'];
        final score = item['confidence'];
        if (label is! String || score is! num) continue;
        parsed.add((
          category: IssueCategory.fromAnyIdentifier(label),
          confidence: score.toDouble(),
        ));
      }
      if (parsed.isNotEmpty) {
        return parsed.take(limit).toList(growable: false);
      }
    }

    final probs = rawPayload['all_probabilities'];
    if (probs is Map) {
      final entries = <({IssueCategory category, double confidence})>[];
      probs.forEach((key, value) {
        if (key is String && value is num) {
          entries.add((
            category: IssueCategory.fromAnyIdentifier(key),
            confidence: value.toDouble(),
          ));
        }
      });
      entries.sort((a, b) => b.confidence.compareTo(a.confidence));
      return entries.take(limit).toList(growable: false);
    }

    return const [];
  }
}

class ReportAssignment {
  const ReportAssignment({
    required this.agencyId,
    required this.agencyName,
    required this.agencyCategory,
    required this.distanceMeters,
    required this.routingMethod,
  });

  final String agencyId;
  final String agencyName;
  final IssueCategory agencyCategory;
  final double distanceMeters;
  final String routingMethod;

  factory ReportAssignment.fromMap(Map<String, dynamic> map) {
    return ReportAssignment(
      agencyId: map['agency_id'] as String? ?? '',
      agencyName: map['agency_name'] as String? ?? '',
      agencyCategory: IssueCategory.fromAnyIdentifier(
        map['agency_category'] as String? ?? map['category'] as String? ?? '',
      ),
      distanceMeters: (map['distance_meters'] as num?)?.toDouble() ?? 0,
      routingMethod: map['routing_method'] as String? ?? '',
    );
  }

  factory ReportAssignment.fromReportMap(Map<String, dynamic> map) {
    final agencyId = map['assigned_agency_id'] as String?;
    final agencyName = map['assigned_agency_name'] as String?;
    if (agencyId == null && agencyName == null) {
      return const ReportAssignment(
        agencyId: '',
        agencyName: '',
        agencyCategory: IssueCategory.instansiLain,
        distanceMeters: 0,
        routingMethod: '',
      );
    }
    return ReportAssignment(
      agencyId: agencyId ?? '',
      agencyName: agencyName ?? '',
      agencyCategory: IssueCategory.fromAnyIdentifier(
        map['assigned_agency_category'] as String? ?? '',
      ),
      distanceMeters:
          (map['assigned_distance_meters'] as num?)?.toDouble() ?? 0,
      routingMethod: map['routing_method'] as String? ?? '',
    );
  }

  bool get isEmpty => agencyId.isEmpty && agencyName.isEmpty;
  double get distanceKilometers => distanceMeters / 1000;
}

class ReportLocationData {
  const ReportLocationData({
    required this.latitude,
    required this.longitude,
    required this.address,
  });

  final double latitude;
  final double longitude;
  final String address;

  Map<String, dynamic> toMap() => {
    'latitude': latitude,
    'longitude': longitude,
    'address': address,
  };
}

class CityReport {
  const CityReport({
    required this.id,
    required this.userId,
    required this.reporterName,
    required this.reporterEmail,
    required this.category,
    required this.aiPrediction,
    required this.aiConfidence,
    required this.imageUrl,
    required this.description,
    required this.latitude,
    required this.longitude,
    required this.address,
    required this.status,
    required this.createdAt,
    required this.updatedAt,
    this.aiProbabilities = const {},
    this.aiModelName,
    this.aiModelVersion,
    this.aiExportManifestSha256,
    this.aiClassMapSha256,
    this.aiAgencyRegistryStatus,
    this.aiInferenceMethod = 'legacy_unspecified',
    this.aiUncertaintyMethod,
    this.aiEpistemicUncertainty,
    this.aiPredictiveEntropy,
    this.aiExpectedDataEntropy,
    this.aiEpistemicUncertaintyThreshold,
    this.aiReviewRequired = false,
    this.aiReviewReasons = const [],
    this.aiPredictionOverridden = false,
    this.aiEvidenceTrusted = false,
    this.assignment,
    this.resolutionEvidencePhotoUrl,
    this.resolutionNote,
    this.resolvedBy,
    this.resolvedAt,
  });

  final String id;
  final String userId;
  final String reporterName;
  final String reporterEmail;
  final IssueCategory category;
  final String aiPrediction;
  final double aiConfidence;
  final String imageUrl;
  final String description;
  final double latitude;
  final double longitude;
  final String address;
  final ReportStatus status;
  final DateTime createdAt;
  final DateTime updatedAt;
  final Map<String, double> aiProbabilities;
  final String? aiModelName;
  final String? aiModelVersion;
  final String? aiExportManifestSha256;
  final String? aiClassMapSha256;
  final String? aiAgencyRegistryStatus;
  final String aiInferenceMethod;
  final String? aiUncertaintyMethod;
  final double? aiEpistemicUncertainty;
  final double? aiPredictiveEntropy;
  final double? aiExpectedDataEntropy;
  final double? aiEpistemicUncertaintyThreshold;
  final bool aiReviewRequired;
  final List<String> aiReviewReasons;
  final bool aiPredictionOverridden;

  /// True only after server-side service-role attestation. Client classifier
  /// payloads are retained for audit but are not operationally trusted.
  final bool aiEvidenceTrusted;
  final ReportAssignment? assignment;
  final String? resolutionEvidencePhotoUrl;
  final String? resolutionNote;
  final String? resolvedBy;
  final DateTime? resolvedAt;

  factory CityReport.fromMap(Map<String, dynamic> map) {
    final assignment = ReportAssignment.fromReportMap(map);
    return CityReport(
      id: map['id'] as String,
      userId: map['user_id'] as String,
      reporterName: map['reporter_name'] as String? ?? '',
      reporterEmail: map['reporter_email'] as String? ?? '',
      category: IssueCategory.fromValue(
        map['category'] as String? ?? 'instansi_lain',
      ),
      aiPrediction: map['ai_prediction'] as String? ?? '',
      aiConfidence: (map['ai_confidence'] as num?)?.toDouble() ?? 0,
      imageUrl: map['image_url'] as String? ?? '',
      description: map['description'] as String? ?? '',
      latitude: (map['latitude'] as num?)?.toDouble() ?? 0,
      longitude: (map['longitude'] as num?)?.toDouble() ?? 0,
      address: map['address'] as String? ?? '',
      status: ReportStatus.fromValue(map['status'] as String? ?? 'submitted'),
      createdAt: DateTime.parse(map['created_at'] as String),
      updatedAt: DateTime.parse(map['updated_at'] as String),
      aiProbabilities: _parseProbabilityMap(map['ai_probabilities']),
      aiModelName: map['ai_model_name'] as String?,
      aiModelVersion: map['ai_model_version'] as String?,
      aiExportManifestSha256: map['ai_export_manifest_sha256'] as String?,
      aiClassMapSha256: map['ai_class_map_sha256'] as String?,
      aiAgencyRegistryStatus: map['ai_agency_registry_status'] as String?,
      aiInferenceMethod:
          map['ai_inference_method'] as String? ?? 'legacy_unspecified',
      aiUncertaintyMethod: map['ai_uncertainty_method'] as String?,
      aiEpistemicUncertainty: (map['ai_epistemic_uncertainty'] as num?)
          ?.toDouble(),
      aiPredictiveEntropy: (map['ai_predictive_entropy'] as num?)?.toDouble(),
      aiExpectedDataEntropy: (map['ai_expected_data_entropy'] as num?)
          ?.toDouble(),
      aiEpistemicUncertaintyThreshold:
          (map['ai_epistemic_uncertainty_threshold'] as num?)?.toDouble(),
      aiReviewRequired: map['ai_review_required'] as bool? ?? false,
      aiReviewReasons: _parseStringList(map['ai_review_reasons']),
      aiPredictionOverridden: map['ai_prediction_overridden'] as bool? ?? false,
      aiEvidenceTrusted: map['ai_evidence_trusted'] as bool? ?? false,
      assignment: assignment.isEmpty ? null : assignment,
      resolutionEvidencePhotoUrl:
          map['resolution_evidence_photo_url'] as String?,
      resolutionNote: map['resolution_note'] as String?,
      resolvedBy: map['resolved_by'] as String?,
      resolvedAt: _parseDateTime(map['resolved_at']),
    );
  }
}

Map<String, double> _parseProbabilityMap(dynamic value) {
  if (value is! Map) return const {};
  return value.map((key, item) {
    final parsed = item is num ? item.toDouble() : 0.0;
    return MapEntry(key.toString(), parsed);
  });
}

List<String> _parseStringList(dynamic value) {
  if (value is! List) return const [];
  return value.whereType<String>().toList(growable: false);
}

DateTime? _parseDateTime(dynamic value) {
  if (value is! String || value.isEmpty) return null;
  return DateTime.tryParse(value);
}

class ReportHistoryEntry {
  const ReportHistoryEntry({
    required this.id,
    required this.reportId,
    required this.status,
    required this.note,
    required this.createdAt,
    this.updatedBy,
  });

  final String id;
  final String reportId;
  final ReportStatus status;
  final String note;
  final DateTime createdAt;
  final String? updatedBy;

  factory ReportHistoryEntry.fromMap(Map<String, dynamic> map) {
    return ReportHistoryEntry(
      id: map['id'] as String,
      reportId: map['report_id'] as String,
      status: ReportStatus.fromValue(map['status'] as String),
      note: map['note'] as String? ?? '',
      createdAt: DateTime.parse(map['created_at'] as String),
      updatedBy: map['updated_by'] as String?,
    );
  }
}
