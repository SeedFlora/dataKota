import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../features/auth/auth_repository.dart';
import '../core/config/app_config.dart';
import 'router/app_router.dart';

/// Routes the user into the app once an authenticated session appears while
/// they are still on a public auth screen.
///
/// This is the reaction half of the email-confirmation flow: registration
/// sends the user to `/login` and the confirmation link (a deep link, see
/// [AppConfig.authRedirectUrl]) re-opens the app. `supabase_flutter` exchanges
/// the link's code and emits a signed-in session; this listener observes that
/// transition and forwards the user to `/home`. The existing
/// [AuthAndRoleGate] then redirects agency/admin users to their own landing,
/// so this widget stays role-agnostic (single responsibility).
///
/// Manual logins are unaffected: [LoginScreen] navigates itself, so by the
/// time the session emits the location is no longer a public auth route and
/// this listener is a no-op.
class AuthFlowListener extends ConsumerWidget {
  const AuthFlowListener({super.key, required this.child});

  final Widget child;

  /// Public auth routes the user may be sitting on when a session is
  /// established out-of-band by the confirmation deep link.
  static const _publicAuthRoutes = {'/login', '/register', '/forgot-password'};

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final config = ref.watch(appConfigProvider);
    if (!config.hasSupabaseConfig) return child;
    ref.listen<AsyncValue<LocalAuthSession?>>(authSessionProvider, (
      previous,
      next,
    ) {
      final wasSignedOut = previous?.asData?.value == null;
      final isSignedIn = next.asData?.value != null;
      if (!wasSignedOut || !isSignedIn) return;

      final router = ref.read(appRouterProvider);
      final location = router.routeInformationProvider.value.uri.path;
      if (_publicAuthRoutes.contains(location)) {
        router.go('/home');
      }
    });

    return child;
  }
}
