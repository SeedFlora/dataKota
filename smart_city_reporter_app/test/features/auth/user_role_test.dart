import 'package:flutter_test/flutter_test.dart';
import 'package:smart_city_reporter_app/features/auth/user_profile.dart';
import 'package:smart_city_reporter_app/features/auth/user_role.dart';
import 'package:smart_city_reporter_app/features/reports/report_models.dart';
import 'package:smart_city_reporter_app/features/reports/reports_scope.dart';

UserProfile _profile({required String role, IssueCategory? agency}) {
  return UserProfile(
    id: 'u1',
    fullName: 'Test',
    email: 't@example.com',
    phoneNumber: '0',
    role: role,
    assignedAgency: agency,
  );
}

void main() {
  group('UserRole.fromProfile', () {
    test('citizen profile resolves to Citizen', () {
      final role = UserRole.fromProfile(_profile(role: 'citizen'));
      expect(role, isA<Citizen>());
      expect(role.canModerateReports, isFalse);
      expect(role.canSubmitReports, isTrue);
    });

    test('agency_admin profile with agency resolves to AgencyAdmin', () {
      final role = UserRole.fromProfile(
        _profile(role: 'agency_admin', agency: IssueCategory.dinasBinaMarga),
      );
      expect(role, isA<AgencyAdmin>());
      expect((role as AgencyAdmin).agency, IssueCategory.dinasBinaMarga);
      expect(role.canModerateReports, isTrue);
      expect(role.canRecategorizeAndRetriage, isFalse);
    });

    test('agency_admin without assigned_agency falls back to Citizen', () {
      final role = UserRole.fromProfile(_profile(role: 'agency_admin'));
      expect(role, isA<Citizen>());
    });

    test('super_admin can recategorize and return a report to triage', () {
      final role = UserRole.fromProfile(_profile(role: 'super_admin'));
      expect(role, isA<SuperAdmin>());
      expect(role.canModerateReports, isTrue);
      expect(role.canRecategorizeAndRetriage, isTrue);
    });

    test('unknown role string defaults to Citizen', () {
      final role = UserRole.fromProfile(_profile(role: 'mystery'));
      expect(role, isA<Citizen>());
    });
  });

  group('ReportsScope.forRole', () {
    test('citizen → CitizenScope with userId', () {
      final scope = ReportsScope.forRole(const Citizen(), userId: 'u1');
      expect(scope, isA<CitizenScope>());
      expect((scope as CitizenScope).userId, 'u1');
      expect(scope.label, 'My reports');
    });

    test('agency admin → AgencyScope using their agency', () {
      final scope = ReportsScope.forRole(
        const AgencyAdmin(IssueCategory.satpolPP),
        userId: 'u1',
      );
      expect(scope, isA<AgencyScope>());
      expect((scope as AgencyScope).agency, IssueCategory.satpolPP);
      expect(scope.label, IssueCategory.satpolPP.label);
    });

    test('super admin → GlobalScope', () {
      final scope = ReportsScope.forRole(const SuperAdmin(), userId: 'u1');
      expect(scope, isA<GlobalScope>());
      expect(scope.label, 'All agencies');
    });
  });
}
