import 'dart:convert';
import 'dart:io';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http/http.dart' as http;
import 'package:http_parser/http_parser.dart';

import '../config/app_config.dart';
import '../../features/reports/report_models.dart';

String _requiredNonEmptyString(Map<String, dynamic> json, String key) {
  final value = json[key];
  if (value is! String || value.trim().isEmpty) {
    throw FormatException('Missing or empty $key in classifier response.');
  }
  return value;
}

double _requiredFiniteNumber(
  Map<String, dynamic> json,
  String key, {
  double? minimum,
  double? maximum,
}) {
  final value = json[key];
  if (value is! num) {
    throw FormatException('Missing numeric $key in classifier response.');
  }
  final number = value.toDouble();
  if (!number.isFinite ||
      (minimum != null && number < minimum) ||
      (maximum != null && number > maximum)) {
    throw FormatException('Invalid $key in classifier response.');
  }
  return number;
}

String _requiredSha256(Map<String, dynamic> json, String key) {
  final value = _requiredNonEmptyString(json, key).toLowerCase();
  if (!RegExp(r'^[0-9a-f]{64}$').hasMatch(value)) {
    throw FormatException('$key is not a SHA-256 digest.');
  }
  return value;
}

class CloudPrediction {
  const CloudPrediction({
    required this.predictedDinas,
    required this.predictedDinasId,
    required this.predictedCategorySlug,
    required this.confidence,
    required this.allProbabilities,
    required this.modelName,
    required this.modelVersion,
    required this.confidenceThreshold,
    required this.reviewRequired,
    required this.reviewReasons,
    required this.inferenceMethod,
    required this.uncertaintyAvailable,
    required this.exportManifestSha256,
    required this.classMapSha256,
    required this.agencyRegistryStatus,
    this.uncertaintyMethod,
    this.epistemicUncertainty,
    this.predictiveEntropy,
    this.expectedDataEntropy,
    this.epistemicUncertaintyThreshold,
    this.assignment,
  });

  final String predictedDinas;
  final int predictedDinasId;
  final String predictedCategorySlug;
  final double confidence;
  final Map<String, double> allProbabilities;
  final String modelName;
  final String modelVersion;
  final double confidenceThreshold;
  final bool reviewRequired;
  final List<String> reviewReasons;
  final String inferenceMethod;
  final bool uncertaintyAvailable;
  final String exportManifestSha256;
  final String classMapSha256;
  final String agencyRegistryStatus;
  final String? uncertaintyMethod;
  final double? epistemicUncertainty;
  final double? predictiveEntropy;
  final double? expectedDataEntropy;
  final double? epistemicUncertaintyThreshold;
  final ReportAssignment? assignment;

  factory CloudPrediction.fromJson(Map<String, dynamic> json) {
    final predictedDinas = _requiredNonEmptyString(json, 'predicted_dinas');
    final predictedDinasId = json['predicted_dinas_id'];
    if (predictedDinasId is! int) {
      throw const FormatException(
        'Missing integer predicted_dinas_id in classifier response.',
      );
    }
    final matchingCategories = IssueCategory.values
        .where((category) => category.cloudId == predictedDinasId)
        .toList(growable: false);
    if (matchingCategories.length != 1 ||
        matchingCategories.single.label != predictedDinas) {
      throw const FormatException(
        'Classifier label id/name differs from the app class contract.',
      );
    }
    final predictedCategorySlug = _requiredNonEmptyString(
      json,
      'predicted_category_slug',
    );
    if (predictedCategorySlug != matchingCategories.single.dbValue) {
      throw const FormatException(
        'Classifier enum slug differs from its label id/name.',
      );
    }

    final rawProbabilities = json['all_probabilities'];
    if (rawProbabilities is! Map) {
      throw const FormatException(
        'Missing all_probabilities in classifier response.',
      );
    }
    final allProbabilities = <String, double>{};
    final expectedLabels = IssueCategory.values
        .map((category) => category.label)
        .toSet();
    if (rawProbabilities.length != expectedLabels.length ||
        !rawProbabilities.keys.every(expectedLabels.contains)) {
      throw const FormatException(
        'Classifier probability labels differ from the app class contract.',
      );
    }
    for (final label in expectedLabels) {
      final value = rawProbabilities[label];
      if (value is! num ||
          !value.toDouble().isFinite ||
          value < 0 ||
          value > 1) {
        throw FormatException('Invalid probability for $label.');
      }
      allProbabilities[label] = value.toDouble();
    }
    final probabilitySum = allProbabilities.values.fold<double>(
      0,
      (sum, value) => sum + value,
    );
    if ((probabilitySum - 1).abs() > 1e-5) {
      throw const FormatException(
        'Classifier probabilities do not sum to one.',
      );
    }
    final confidence = _requiredFiniteNumber(
      json,
      'confidence',
      minimum: 0,
      maximum: 1,
    );
    final predictedProbability = allProbabilities[predictedDinas]!;
    final maximumProbability = allProbabilities.values.reduce(
      (left, right) => left > right ? left : right,
    );
    var deterministicTop = IssueCategory.values.first;
    for (final category in IssueCategory.values.skip(1)) {
      if (allProbabilities[category.label]! >
          allProbabilities[deterministicTop.label]!) {
        deterministicTop = category;
      }
    }
    if ((confidence - predictedProbability).abs() > 1e-6 ||
        predictedProbability < maximumProbability - 1e-12 ||
        deterministicTop != matchingCategories.single) {
      throw const FormatException(
        'Classifier confidence/top label is internally inconsistent.',
      );
    }
    final confidenceThreshold = _requiredFiniteNumber(
      json,
      'confidence_threshold',
      minimum: 0,
      maximum: 1,
    );

    final reviewRequired = json['review_required'];
    final uncertaintyAvailable = json['uncertainty_available'];
    if (reviewRequired is! bool || uncertaintyAvailable is! bool) {
      throw const FormatException(
        'Classifier review/uncertainty flags must be explicit booleans.',
      );
    }
    final rawReasons = json['review_reasons'];
    if (rawReasons is! List ||
        rawReasons.any(
          (reason) => reason is! String || reason.trim().isEmpty,
        )) {
      throw const FormatException('Invalid classifier review reasons.');
    }
    final reviewReasons = rawReasons.cast<String>().toList(growable: false);
    if (reviewRequired != reviewReasons.isNotEmpty) {
      throw const FormatException(
        'Classifier review flag and reasons are inconsistent.',
      );
    }

    final inferenceMethod = _requiredNonEmptyString(json, 'inference_method');
    final uncertaintyMethod = json['uncertainty_method'] as String?;
    final epistemicUncertainty = (json['epistemic_uncertainty'] as num?)
        ?.toDouble();
    final predictiveEntropy = (json['predictive_entropy'] as num?)?.toDouble();
    final expectedDataEntropy = (json['expected_data_entropy'] as num?)
        ?.toDouble();
    final epistemicUncertaintyThreshold =
        (json['epistemic_uncertainty_threshold'] as num?)?.toDouble();
    final uncertaintyValues = [
      epistemicUncertainty,
      predictiveEntropy,
      expectedDataEntropy,
      epistemicUncertaintyThreshold,
    ];
    if (uncertaintyValues.whereType<double>().any(
      (value) => !value.isFinite || value < 0,
    )) {
      throw const FormatException('Invalid classifier uncertainty value.');
    }
    if (uncertaintyAvailable) {
      if (inferenceMethod != 'catboost_virtual_ensemble_seed_ensemble' ||
          uncertaintyMethod !=
              'joint_training_seed_pgs_component_mutual_information_nats' ||
          epistemicUncertainty == null ||
          predictiveEntropy == null ||
          expectedDataEntropy == null ||
          epistemicUncertaintyThreshold == null ||
          (epistemicUncertainty - (predictiveEntropy - expectedDataEntropy))
                  .abs() >
              1e-6) {
        throw const FormatException(
          'Virtual-ensemble uncertainty provenance is incomplete.',
        );
      }
    } else if (inferenceMethod != 'onnx_equal_weight_seed_ensemble' ||
        uncertaintyMethod != null ||
        uncertaintyValues.whereType<double>().isNotEmpty) {
      throw const FormatException(
        'Point prediction response contains inconsistent uncertainty metadata.',
      );
    }

    final assignmentJson = json['assignment'];
    ReportAssignment? assignment;
    if (assignmentJson != null) {
      if (assignmentJson is! Map) {
        throw const FormatException('Invalid classifier assignment payload.');
      }
      assignment = ReportAssignment.fromMap(
        Map<String, dynamic>.from(assignmentJson),
      );
      final assignmentCategorySlug = assignmentJson['agency_category_slug'];
      if (reviewRequired ||
          assignmentCategorySlug is! String ||
          assignmentCategorySlug != assignment.agencyCategory.dbValue ||
          assignment.agencyId.isEmpty ||
          assignment.agencyName.isEmpty ||
          assignment.routingMethod.isEmpty ||
          !assignment.distanceMeters.isFinite ||
          assignment.distanceMeters < 0 ||
          assignment.agencyCategory != matchingCategories.single) {
        throw const FormatException(
          'Classifier assignment is incomplete, mismatched, or review-blocked.',
        );
      }
    }
    final agencyRegistryStatus = _requiredNonEmptyString(
      json,
      'agency_registry_status',
    );
    const registryStatuses = {
      'verified',
      'incomplete',
      'untrusted_fallback',
      'unavailable',
    };
    if (!registryStatuses.contains(agencyRegistryStatus)) {
      throw const FormatException('Unknown agency registry status.');
    }
    if (assignment != null && agencyRegistryStatus != 'verified') {
      throw const FormatException(
        'Unverified agency registry cannot authorize an assignment candidate.',
      );
    }
    final policyRequiresReview =
        confidence < confidenceThreshold ||
        matchingCategories.single == IssueCategory.instansiLain ||
        agencyRegistryStatus != 'verified' ||
        (epistemicUncertaintyThreshold != null &&
            epistemicUncertainty! > epistemicUncertaintyThreshold);
    if (policyRequiresReview && !reviewRequired) {
      throw const FormatException(
        'Classifier response bypasses a frozen human-review gate.',
      );
    }
    if (!reviewRequired && assignment == null) {
      throw const FormatException(
        'A routable non-review response must include a complete assignment.',
      );
    }

    return CloudPrediction(
      predictedDinas: predictedDinas,
      predictedDinasId: predictedDinasId,
      predictedCategorySlug: predictedCategorySlug,
      confidence: confidence,
      allProbabilities: allProbabilities,
      modelName: _requiredNonEmptyString(json, 'model_name'),
      modelVersion: _requiredNonEmptyString(json, 'model_version'),
      confidenceThreshold: confidenceThreshold,
      reviewRequired: reviewRequired,
      reviewReasons: reviewReasons,
      inferenceMethod: inferenceMethod,
      uncertaintyAvailable: uncertaintyAvailable,
      exportManifestSha256: _requiredSha256(json, 'export_manifest_sha256'),
      classMapSha256: _requiredSha256(json, 'class_map_sha256'),
      agencyRegistryStatus: agencyRegistryStatus,
      uncertaintyMethod: uncertaintyMethod,
      epistemicUncertainty: epistemicUncertainty,
      predictiveEntropy: predictiveEntropy,
      expectedDataEntropy: expectedDataEntropy,
      epistemicUncertaintyThreshold: epistemicUncertaintyThreshold,
      assignment: assignment,
    );
  }
}

class CloudClassificationService {
  CloudClassificationService({
    required this.baseUrl,
    this.timeout = const Duration(seconds: 90),
  });

  final String baseUrl;
  final Duration timeout;

  Future<CloudPrediction> classify({
    required File imageFile,
    required String laporan,
    required double latitude,
    required double longitude,
  }) async {
    final uri = Uri.parse('$baseUrl/predict');
    final request = http.MultipartRequest('POST', uri)
      ..fields['laporan'] = laporan
      ..fields['latitude'] = latitude.toString()
      ..fields['longitude'] = longitude.toString()
      ..files.add(
        await http.MultipartFile.fromPath(
          'image',
          imageFile.path,
          contentType: MediaType('image', 'jpeg'),
        ),
      );

    final streamed = await request.send().timeout(timeout);
    final response = await http.Response.fromStream(streamed);

    if (response.statusCode != 200) {
      throw Exception(
        'Classify failed (${response.statusCode}): ${response.body}',
      );
    }
    return CloudPrediction.fromJson(
      jsonDecode(response.body) as Map<String, dynamic>,
    );
  }

  Future<bool> healthCheck() async {
    try {
      final response = await http
          .get(Uri.parse('$baseUrl/health'))
          .timeout(const Duration(seconds: 5));
      return response.statusCode == 200;
    } catch (_) {
      return false;
    }
  }
}

final cloudClassificationServiceProvider = Provider<CloudClassificationService>(
  (ref) {
    final config = ref.watch(appConfigProvider);
    return CloudClassificationService(baseUrl: config.crmApiUrl);
  },
);
