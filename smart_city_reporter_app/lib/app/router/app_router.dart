import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/widgets/agency_admin_shell.dart';
import '../../core/widgets/app_shell_scaffold.dart';
import '../../core/config/app_config.dart';
import '../../features/admin/agency_admin_profile_screen.dart';
import '../../features/admin/agency_inbox_screen.dart';
import '../../features/admin/agency_registry_screen.dart';
import '../../features/auth/forgot_password_screen.dart';
import '../../features/auth/login_screen.dart';
import '../../features/auth/register_screen.dart';
import '../../features/auth/role_landing.dart';
import '../../features/auth/user_role.dart';
import '../../features/dashboard/home_dashboard_screen.dart';
import '../../features/profile/profile_screen.dart';
import '../../features/reports/ai_result_review_screen.dart';
import '../../features/reports/create_report_screen.dart';
import '../../features/reports/map_view_screen.dart';
import '../../features/reports/my_reports_screen.dart';
import '../../features/reports/report_detail_screen.dart';
import '../../features/settings/settings_screen.dart';
import '../../features/testing/ai_model_testing_screen.dart';
import '../../features/splash/setup_required_screen.dart';
import '../../features/splash/splash_screen.dart';
import '../../features/onboarding/onboarding_screen.dart';
import '../../features/auth/auth_repository.dart';

final _rootNavigatorKey = GlobalKey<NavigatorState>();
final _citizenShellKey = GlobalKey<NavigatorState>();
final _adminShellKey = GlobalKey<NavigatorState>();

final appRouterProvider = Provider<GoRouter>((ref) {
  final config = ref.watch(appConfigProvider);
  return GoRouter(
    navigatorKey: _rootNavigatorKey,
    initialLocation: config.isConfigured ? '/splash' : '/setup',
    redirect: (context, state) {
      if (!config.isConfigured) {
        final testingRoute =
            config.enableTestingMode && state.matchedLocation == '/model-test';
        if (state.matchedLocation == '/setup' || testingRoute) return null;
        return '/setup';
      }
      if (state.matchedLocation == '/setup') return '/splash';
      return null;
    },
    routes: [
      GoRoute(path: '/', redirect: (context, state) => '/splash'),
      GoRoute(
        path: '/splash',
        builder: (context, state) => const SplashScreen(),
      ),
      GoRoute(
        path: '/setup',
        builder: (context, state) => const SetupRequiredScreen(),
      ),
      GoRoute(
        path: '/onboarding',
        builder: (context, state) => const OnboardingScreen(),
      ),
      GoRoute(path: '/login', builder: (context, state) => const LoginScreen()),
      GoRoute(
        path: '/register',
        builder: (context, state) => const RegisterScreen(),
      ),
      GoRoute(
        path: '/forgot-password',
        builder: (context, state) => const ForgotPasswordScreen(),
      ),
      GoRoute(
        path: '/model-test',
        builder: (context, state) => const AiModelTestingScreen(),
      ),
      // Citizen shell.
      StatefulShellRoute.indexedStack(
        parentNavigatorKey: _rootNavigatorKey,
        builder: (context, state, navigationShell) =>
            AppShellScaffold(navigationShell: navigationShell),
        branches: [
          StatefulShellBranch(
            navigatorKey: _citizenShellKey,
            routes: [
              GoRoute(
                path: '/home',
                builder: (context, state) => const AuthAndRoleGate(
                  required: GateRole.citizen,
                  child: HomeDashboardScreen(),
                ),
              ),
            ],
          ),
          StatefulShellBranch(
            routes: [
              GoRoute(
                path: '/map',
                builder: (context, state) => const AuthAndRoleGate(
                  required: GateRole.citizen,
                  child: MapViewScreen(),
                ),
              ),
            ],
          ),
          StatefulShellBranch(
            routes: [
              GoRoute(
                path: '/my-reports',
                builder: (context, state) => const AuthAndRoleGate(
                  required: GateRole.citizen,
                  child: MyReportsScreen(),
                ),
              ),
            ],
          ),
          StatefulShellBranch(
            routes: [
              GoRoute(
                path: '/profile',
                builder: (context, state) =>
                    const AuthAndRoleGate(child: ProfileScreen()),
              ),
            ],
          ),
        ],
      ),
      // Agency-admin / super-admin shell.
      StatefulShellRoute.indexedStack(
        parentNavigatorKey: _rootNavigatorKey,
        builder: (context, state, navigationShell) =>
            AgencyAdminShell(navigationShell: navigationShell),
        branches: [
          StatefulShellBranch(
            navigatorKey: _adminShellKey,
            routes: [
              GoRoute(
                path: '/admin/inbox',
                builder: (context, state) => const AuthAndRoleGate(
                  required: GateRole.admin,
                  child: AgencyInboxScreen(),
                ),
              ),
            ],
          ),
          StatefulShellBranch(
            routes: [
              GoRoute(
                path: '/admin/map',
                builder: (context, state) => const AuthAndRoleGate(
                  required: GateRole.admin,
                  child: MapViewScreen(),
                ),
              ),
            ],
          ),
          StatefulShellBranch(
            routes: [
              GoRoute(
                path: '/admin/profile',
                builder: (context, state) => const AuthAndRoleGate(
                  required: GateRole.admin,
                  child: AgencyAdminProfileScreen(),
                ),
              ),
            ],
          ),
        ],
      ),
      GoRoute(
        path: '/admin/agencies',
        builder: (context, state) => const AuthAndRoleGate(
          required: GateRole.admin,
          child: AgencyRegistryScreen(),
        ),
      ),
      GoRoute(
        path: '/settings',
        builder: (context, state) =>
            const AuthAndRoleGate(child: SettingsScreen()),
      ),
      GoRoute(
        path: '/create-report',
        builder: (context, state) => const AuthAndRoleGate(
          required: GateRole.citizen,
          child: CreateReportScreen(),
        ),
      ),
      GoRoute(
        path: '/review-report',
        builder: (context, state) => const AuthAndRoleGate(
          required: GateRole.citizen,
          child: AiResultReviewScreen(),
        ),
      ),
      GoRoute(
        path: '/report/:reportId',
        builder: (_, state) => AuthAndRoleGate(
          child: ReportDetailScreen(
            reportId: state.pathParameters['reportId']!,
          ),
        ),
      ),
    ],
  );
});

enum GateRole { any, citizen, admin }

class AuthAndRoleGate extends ConsumerWidget {
  const AuthAndRoleGate({
    super.key,
    required this.child,
    this.required = GateRole.any,
  });

  final Widget child;
  final GateRole required;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    ref.listen(currentSessionProvider, (_, next) {
      if (next == null && context.mounted) context.go('/login');
    });
    final session = ref.watch(currentSessionProvider);
    if (session == null) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (context.mounted) context.go('/login');
      });
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }

    if (required == GateRole.any) return child;

    final profileAsync = ref.watch(currentUserProfileProvider);
    return profileAsync.when(
      data: (_) {
        final role = ref.watch(currentUserRoleProvider);
        final isAdminUser = role is AgencyAdmin || role is SuperAdmin;

        if (required == GateRole.admin && !isAdminUser) {
          WidgetsBinding.instance.addPostFrameCallback((_) {
            if (context.mounted) context.go(landingRouteFor(role));
          });
          return const Scaffold(
            body: Center(child: CircularProgressIndicator()),
          );
        }
        if (required == GateRole.citizen && isAdminUser) {
          WidgetsBinding.instance.addPostFrameCallback((_) {
            if (context.mounted) context.go(landingRouteFor(role));
          });
          return const Scaffold(
            body: Center(child: CircularProgressIndicator()),
          );
        }
        return child;
      },
      loading: () =>
          const Scaffold(body: Center(child: CircularProgressIndicator())),
      error: (e, _) =>
          Scaffold(body: Center(child: Text('Failed to load profile: $e'))),
    );
  }
}
