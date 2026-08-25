import '../reports/report_models.dart';
import 'user_profile.dart';

const String _roleCitizen = 'citizen';
const String _roleAgencyAdmin = 'agency_admin';
const String _roleSuperAdmin = 'super_admin';

sealed class UserRole {
  const UserRole();

  String get dbValue;

  bool get canSubmitReports => this is Citizen;
  bool get canModerateReports => this is AgencyAdmin || this is SuperAdmin;
  bool get canRecategorizeAndRetriage => this is SuperAdmin;

  static UserRole fromProfile(UserProfile profile) {
    switch (profile.role) {
      case _roleAgencyAdmin:
        final agency = profile.assignedAgency;
        if (agency == null) {
          // Schema constraint should prevent this; fall back to citizen.
          return const Citizen();
        }
        return AgencyAdmin(agency);
      case _roleSuperAdmin:
        return const SuperAdmin();
      case _roleCitizen:
      default:
        return const Citizen();
    }
  }
}

class Citizen extends UserRole {
  const Citizen();
  @override
  String get dbValue => _roleCitizen;
}

class AgencyAdmin extends UserRole {
  const AgencyAdmin(this.agency);
  final IssueCategory agency;
  @override
  String get dbValue => _roleAgencyAdmin;
}

class SuperAdmin extends UserRole {
  const SuperAdmin();
  @override
  String get dbValue => _roleSuperAdmin;
}
