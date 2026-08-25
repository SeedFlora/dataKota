import 'user_role.dart';

/// Where a user should land after a successful sign-in based on their role.
String landingRouteFor(UserRole role) {
  return switch (role) {
    Citizen() => '/home',
    AgencyAdmin() => '/admin/inbox',
    SuperAdmin() => '/admin/inbox',
  };
}

/// True when [path] belongs to the citizen-only navigation tree.
bool isCitizenRoute(String path) {
  return path == '/home' ||
      path == '/map' ||
      path == '/my-reports' ||
      path.startsWith('/create-report') ||
      path.startsWith('/review-report');
}

/// True when [path] belongs to the moderator-only navigation tree.
bool isAdminRoute(String path) => path.startsWith('/admin');
