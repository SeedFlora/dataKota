import 'package:flutter_test/flutter_test.dart';
import 'package:smart_city_reporter_app/features/reports/report_models.dart';

void main() {
  group('IssueCategory', () {
    test('maps known dbValues and falls back to instansiLain', () {
      expect(
        IssueCategory.fromValue('dinas_bina_marga'),
        IssueCategory.dinasBinaMarga,
      );
      expect(IssueCategory.fromValue('unknown'), IssueCategory.instansiLain);
    });

    test('maps cloud label_id integers (0-8) to instansi enum', () {
      expect(IssueCategory.fromCloudId(0), IssueCategory.dinasBinaMarga);
      expect(IssueCategory.fromCloudId(2), IssueCategory.dinasPerhubungan);
      expect(IssueCategory.fromCloudId(8), IssueCategory.instansiLain);
      expect(IssueCategory.fromCloudId(99), IssueCategory.instansiLain);
    });

    test('matches predicted_dinas formal name from cloud response', () {
      expect(
        IssueCategory.fromAnyIdentifier('Dinas Bina Marga'),
        IssueCategory.dinasBinaMarga,
      );
      expect(
        IssueCategory.fromAnyIdentifier('Instansi lain'),
        IssueCategory.instansiLain,
      );
    });
  });

  group('ReportStatus', () {
    test('maps known values and falls back safely', () {
      expect(ReportStatus.fromValue('resolved'), ReportStatus.resolved);
      expect(ReportStatus.fromValue('unexpected'), ReportStatus.submitted);
    });
  });

  group('AiPrediction', () {
    test('exposes the fail-closed review flag used by persistence', () {
      final prediction = AiPrediction(
        category: IssueCategory.dinasBinaMarga,
        confidence: 0.4,
        rawPayload: const {'review_required': true},
      );

      expect(prediction.reviewRequired, isTrue);
      expect(prediction.reviewReasons, isEmpty);

      final withReason = AiPrediction(
        category: IssueCategory.instansiLain,
        confidence: 0.4,
        rawPayload: const {
          'review_required': true,
          'review_reasons': ['catch_all_class'],
        },
      );
      expect(withReason.reviewReasons, ['catch_all_class']);
    });
  });

  group('CityReport', () {
    test('parses backend payload into strongly typed model', () {
      final report = CityReport.fromMap({
        'id': 'report-1',
        'user_id': 'user-1',
        'reporter_name': 'Alex Citizen',
        'reporter_email': 'alex@example.com',
        'category': 'satpol_pp',
        'ai_prediction': 'satpol_pp',
        'ai_confidence': 0.94,
        'ai_export_manifest_sha256':
            'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
        'ai_class_map_sha256':
            'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
        'ai_agency_registry_status': 'verified',
        'ai_inference_method': 'catboost_virtual_ensemble_seed_ensemble',
        'ai_uncertainty_method':
            'joint_training_seed_pgs_component_mutual_information_nats',
        'ai_epistemic_uncertainty': 0.08,
        'ai_predictive_entropy': 0.31,
        'ai_expected_data_entropy': 0.23,
        'ai_epistemic_uncertainty_threshold': 0.1,
        'ai_review_required': true,
        'ai_review_reasons': ['catch_all_class'],
        'ai_prediction_overridden': true,
        'ai_evidence_trusted': true,
        'image_url': 'https://example.com/image.jpg',
        'description': 'Vandalisme di tembok publik',
        'latitude': -6.2,
        'longitude': 106.8,
        'address': 'Jakarta',
        'status': 'verified',
        'created_at': '2026-03-15T10:15:00.000Z',
        'updated_at': '2026-03-15T10:30:00.000Z',
      });

      expect(report.category, IssueCategory.satpolPP);
      expect(report.status, ReportStatus.verified);
      expect(report.aiConfidence, closeTo(0.94, 0.0001));
      expect(report.reporterEmail, 'alex@example.com');
      expect(
        report.aiExportManifestSha256,
        'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
      );
      expect(
        report.aiClassMapSha256,
        'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
      );
      expect(report.aiAgencyRegistryStatus, 'verified');
      expect(
        report.aiInferenceMethod,
        'catboost_virtual_ensemble_seed_ensemble',
      );
      expect(
        report.aiUncertaintyMethod,
        'joint_training_seed_pgs_component_mutual_information_nats',
      );
      expect(report.aiEpistemicUncertainty, closeTo(0.08, 1e-9));
      expect(report.aiReviewRequired, isTrue);
      expect(report.aiReviewReasons, ['catch_all_class']);
      expect(report.aiPredictionOverridden, isTrue);
      expect(report.aiEvidenceTrusted, isTrue);
    });
  });
}
