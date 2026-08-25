import 'package:flutter_test/flutter_test.dart';
import 'package:smart_city_reporter_app/core/services/cloud_classification_service.dart';

Map<String, double> _probabilities({
  required String winner,
  required double winnerScore,
  String runnerUp = 'Instansi lain',
}) {
  const labels = [
    'Dinas Bina Marga',
    'Satuan Polisi Pamong Praja',
    'Dinas Perhubungan',
    'Kelurahan',
    'Dinas Pertamanan dan Hutan',
    'Dinas Sumber Daya Air',
    'Dinas Cipta Karya, Tata Ruang, dan Pertanahan',
    'Badan Pembinaan Badan Usaha Milik Daerah',
    'Instansi lain',
  ];
  return {
    for (final label in labels) label: 0,
    winner: winnerScore,
    runnerUp: 1 - winnerScore,
  };
}

void main() {
  group('CloudPrediction', () {
    test('parses explicit inference and uncertainty provenance', () {
      final prediction = CloudPrediction.fromJson({
        'predicted_dinas': 'Dinas Perhubungan',
        'predicted_dinas_id': 2,
        'predicted_category_slug': 'dinas_perhubungan',
        'confidence': 0.82,
        'all_probabilities': _probabilities(
          winner: 'Dinas Perhubungan',
          winnerScore: 0.82,
        ),
        'model_name': 'crm',
        'model_version': 'v2',
        'confidence_threshold': 0.7,
        'review_required': true,
        'review_reasons': ['high_epistemic_uncertainty'],
        'inference_method': 'catboost_virtual_ensemble_seed_ensemble',
        'uncertainty_available': true,
        'uncertainty_method':
            'joint_training_seed_pgs_component_mutual_information_nats',
        'epistemic_uncertainty': 0.12,
        'predictive_entropy': 0.47,
        'expected_data_entropy': 0.35,
        'epistemic_uncertainty_threshold': 0.1,
        'export_manifest_sha256': List.filled(64, 'a').join(),
        'class_map_sha256': List.filled(64, 'b').join(),
        'agency_registry_status': 'verified',
      });

      expect(prediction.reviewReasons, ['high_epistemic_uncertainty']);
      expect(
        prediction.inferenceMethod,
        'catboost_virtual_ensemble_seed_ensemble',
      );
      expect(prediction.uncertaintyAvailable, isTrue);
      expect(prediction.epistemicUncertainty, closeTo(0.12, 1e-9));
    });

    test('old server responses without provenance fail closed', () {
      expect(
        () => CloudPrediction.fromJson({
          'predicted_dinas': 'Dinas Bina Marga',
          'predicted_dinas_id': 0,
          'confidence': 0.9,
          'all_probabilities': {'Dinas Bina Marga': 0.9},
        }),
        throwsA(isA<FormatException>()),
      );
    });

    test('accepts a complete point-prediction contract', () {
      final prediction = CloudPrediction.fromJson({
        'predicted_dinas': 'Dinas Bina Marga',
        'predicted_dinas_id': 0,
        'predicted_category_slug': 'dinas_bina_marga',
        'confidence': 0.9,
        'all_probabilities': _probabilities(
          winner: 'Dinas Bina Marga',
          winnerScore: 0.9,
        ),
        'model_name': 'crm',
        'model_version': 'q2-001',
        'confidence_threshold': 0.7,
        'review_required': false,
        'review_reasons': <String>[],
        'inference_method': 'onnx_equal_weight_seed_ensemble',
        'uncertainty_available': false,
        'export_manifest_sha256': List.filled(64, 'c').join(),
        'class_map_sha256': List.filled(64, 'd').join(),
        'agency_registry_status': 'verified',
        'assignment': {
          'agency_id': 'bm-1',
          'agency_name': 'Bina Marga Pusat',
          'agency_category': 'Dinas Bina Marga',
          'agency_category_slug': 'dinas_bina_marga',
          'distance_meters': 123.0,
          'routing_method': 'nearest_by_category_and_location',
        },
      });

      expect(prediction.inferenceMethod, 'onnx_equal_weight_seed_ensemble');
      expect(prediction.uncertaintyAvailable, isFalse);
      expect(prediction.assignment?.agencyId, 'bm-1');
    });

    test('rejects a routable non-review response without an assignment', () {
      expect(
        () => CloudPrediction.fromJson({
          'predicted_dinas': 'Dinas Bina Marga',
          'predicted_dinas_id': 0,
          'predicted_category_slug': 'dinas_bina_marga',
          'confidence': 0.9,
          'all_probabilities': _probabilities(
            winner: 'Dinas Bina Marga',
            winnerScore: 0.9,
          ),
          'model_name': 'crm',
          'model_version': 'q2-001',
          'confidence_threshold': 0.7,
          'review_required': false,
          'review_reasons': <String>[],
          'inference_method': 'onnx_equal_weight_seed_ensemble',
          'uncertainty_available': false,
          'export_manifest_sha256': List.filled(64, 'c').join(),
          'class_map_sha256': List.filled(64, 'd').join(),
          'agency_registry_status': 'verified',
        }),
        throwsA(isA<FormatException>()),
      );
    });

    test('rejects a slug that differs from the frozen label contract', () {
      expect(
        () => CloudPrediction.fromJson({
          'predicted_dinas': 'Dinas Bina Marga',
          'predicted_dinas_id': 0,
          'predicted_category_slug': 'dinas_sda',
        }),
        throwsA(isA<FormatException>()),
      );
    });
  });
}
