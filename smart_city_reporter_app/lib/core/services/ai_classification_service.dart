import 'dart:io';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';

import '../../features/reports/report_models.dart';
import '../config/app_config.dart';
import 'cloud_classification_service.dart';

abstract class AiClassificationService {
  Future<AiPrediction> classify({
    required XFile imageFile,
    required String description,
    required ReportLocationData location,
  });
}

class CloudAiClassificationService implements AiClassificationService {
  CloudAiClassificationService(this._client);

  final CloudClassificationService _client;

  @override
  Future<AiPrediction> classify({
    required XFile imageFile,
    required String description,
    required ReportLocationData location,
  }) async {
    final response = await _client.classify(
      imageFile: File(imageFile.path),
      laporan: description,
      latitude: location.latitude,
      longitude: location.longitude,
    );

    return AiPrediction(
      category: IssueCategory.fromCloudId(response.predictedDinasId),
      confidence: response.confidence,
      assignment: response.assignment,
      rawPayload: {
        'mode': 'cloud',
        'predicted_dinas': response.predictedDinas,
        'predicted_dinas_id': response.predictedDinasId,
        'predicted_category_slug': response.predictedCategorySlug,
        'confidence': response.confidence,
        'all_probabilities': response.allProbabilities,
        'model_name': response.modelName,
        'model_version': response.modelVersion,
        'confidence_threshold': response.confidenceThreshold,
        'review_required': response.reviewRequired,
        'review_reasons': response.reviewReasons,
        'inference_method': response.inferenceMethod,
        'uncertainty_available': response.uncertaintyAvailable,
        'uncertainty_method': response.uncertaintyMethod,
        'epistemic_uncertainty': response.epistemicUncertainty,
        'predictive_entropy': response.predictiveEntropy,
        'expected_data_entropy': response.expectedDataEntropy,
        'epistemic_uncertainty_threshold':
            response.epistemicUncertaintyThreshold,
        'export_manifest_sha256': response.exportManifestSha256,
        'class_map_sha256': response.classMapSha256,
        'agency_registry_status': response.agencyRegistryStatus,
        if (response.assignment != null)
          'assignment': {
            'agency_id': response.assignment!.agencyId,
            'agency_name': response.assignment!.agencyName,
            'agency_category': response.assignment!.agencyCategory.label,
            'agency_category_slug': response.assignment!.agencyCategory.dbValue,
            'distance_meters': response.assignment!.distanceMeters,
            'routing_method': response.assignment!.routingMethod,
          },
      },
    );
  }
}

class DemoAiClassificationService implements AiClassificationService {
  @override
  Future<AiPrediction> classify({
    required XFile imageFile,
    required String description,
    required ReportLocationData location,
  }) async {
    final seed = (imageFile.name + description).hashCode.abs();
    final category = IssueCategory.values[seed % IssueCategory.values.length];
    final confidence = 0.62 + ((seed % 28) / 100);
    return AiPrediction(
      category: category,
      confidence: confidence.clamp(0.62, 0.9),
      rawPayload: {
        'mode': 'demo',
        'predicted_dinas': category.label,
        'predicted_dinas_id': category.cloudId,
        'confidence': confidence,
        'review_required': true,
        'review_reasons': ['testing_mode_demo'],
        'inference_method': 'demo_untrusted',
      },
    );
  }
}

final aiClassificationServiceProvider = Provider<AiClassificationService>((
  ref,
) {
  final config = ref.watch(appConfigProvider);
  if (config.enableTestingMode) {
    return DemoAiClassificationService();
  }
  return CloudAiClassificationService(
    ref.watch(cloudClassificationServiceProvider),
  );
});
