import 'package:image_picker/image_picker.dart';

import 'report_models.dart';

abstract class ReportAdminActions {
  Future<CityReport> verify(String reportId, {String note = ''});
  Future<CityReport> markInProgress(String reportId, {String note = ''});
  Future<CityReport> markResolved(
    String reportId, {
    required XFile evidencePhoto,
    String note = '',
  });
  Future<CityReport> reject(String reportId, {required String reason});

  /// Super-admin only. Changes the category and returns the report to triage.
  ///
  /// This does not select a destination agency. The database clears the
  /// current assignment so a later trusted triage step can route the report.
  Future<CityReport> recategorizeAndRetriage(
    String reportId, {
    required IssueCategory newCategory,
    required String note,
  });
}
