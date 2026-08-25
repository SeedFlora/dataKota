import 'package:flutter_test/flutter_test.dart';
import 'package:smart_city_reporter_app/features/reports/classification_routing.dart';
import 'package:smart_city_reporter_app/features/reports/report_models.dart';

void main() {
  group('buildRoutingGuidanceFromPrediction', () {
    test('routes Bina Marga prediction to road infrastructure agency', () {
      final guidance = buildRoutingGuidanceFromPrediction(
        const AiPrediction(
          category: IssueCategory.dinasBinaMarga,
          confidence: 0.92,
          rawPayload: {'predicted_dinas': 'Dinas Bina Marga'},
        ),
      );

      expect(guidance.category, IssueCategory.dinasBinaMarga);
      expect(guidance.agencies.first.name, 'Dinas Bina Marga');
      expect(guidance.isUncertain, isFalse);
    });

    test('honours user-edited category over the prediction', () {
      final guidance = buildRoutingGuidanceFromPrediction(
        const AiPrediction(
          category: IssueCategory.satpolPP,
          confidence: 0.71,
          rawPayload: {'predicted_dinas': 'Satuan Polisi Pamong Praja'},
        ),
        selectedCategory: IssueCategory.dinasPertamananHutan,
      );

      expect(guidance.category, IssueCategory.dinasPertamananHutan);
      expect(guidance.agencies.first.name, 'Dinas Pertamanan dan Hutan');
    });

    test('marks Instansi Lain as uncertain so the UI flags manual review', () {
      final guidance = buildRoutingGuidanceFromPrediction(
        const AiPrediction(
          category: IssueCategory.instansiLain,
          confidence: 0.41,
          rawPayload: {'predicted_dinas': 'Instansi lain'},
        ),
      );

      expect(guidance.category, IssueCategory.instansiLain);
      expect(guidance.isUncertain, isTrue);
      expect(guidance.reviewNote, isNotNull);
    });
  });

  group('AiPrediction.topPredictions', () {
    test('parses all_probabilities map from cloud response', () {
      const prediction = AiPrediction(
        category: IssueCategory.dinasBinaMarga,
        confidence: 0.71,
        rawPayload: {
          'all_probabilities': {
            'Dinas Bina Marga': 0.71,
            'Dinas Perhubungan': 0.18,
            'Dinas Sumber Daya Air': 0.06,
            'Instansi lain': 0.05,
          },
        },
      );

      final top = prediction.topPredictions(limit: 3);
      expect(top, hasLength(3));
      expect(top.first.category, IssueCategory.dinasBinaMarga);
      expect(top.first.confidence, closeTo(0.71, 1e-6));
      expect(top.last.category, IssueCategory.dinasSDA);
    });
  });
}
