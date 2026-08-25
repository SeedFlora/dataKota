import '../auth/user_role.dart';
import 'report_models.dart';
import 'reports_reader.dart';

/// Strategy for "which reports does the current user see?".
sealed class ReportsScope {
  const ReportsScope();

  Stream<List<CityReport>> watch(ReportsReader reader);

  /// Pretty label for the UI ("All agencies", "Dinas Bina Marga", "My reports").
  String get label;

  static ReportsScope forRole(UserRole role, {required String userId}) {
    return switch (role) {
      Citizen() => CitizenScope(userId),
      AgencyAdmin(:final agency) => AgencyScope(agency),
      SuperAdmin() => const GlobalScope(),
    };
  }
}

class CitizenScope extends ReportsScope {
  const CitizenScope(this.userId);
  final String userId;

  @override
  Stream<List<CityReport>> watch(ReportsReader reader) =>
      reader.watchByUser(userId);

  @override
  String get label => 'My reports';
}

class AgencyScope extends ReportsScope {
  const AgencyScope(this.agency);
  final IssueCategory agency;

  @override
  Stream<List<CityReport>> watch(ReportsReader reader) =>
      reader.watchByCategory(agency);

  @override
  String get label => agency.label;
}

class GlobalScope extends ReportsScope {
  const GlobalScope();

  @override
  Stream<List<CityReport>> watch(ReportsReader reader) => reader.watchAll();

  @override
  String get label => 'All agencies';
}
