import 'report_models.dart';

abstract class ReportsReader {
  Stream<List<CityReport>> watchByUser(String userId);
  Stream<List<CityReport>> watchByCategory(IssueCategory category);
  Stream<List<CityReport>> watchAll();
  Stream<CityReport?> watchById(String reportId);
  Stream<List<ReportHistoryEntry>> watchHistory(String reportId);
}
