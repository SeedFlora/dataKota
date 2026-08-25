import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/l10n/l10n.dart';
import '../../core/widgets/smart_city_ui.dart';
import '../auth/auth_repository.dart';
import '../auth/role_landing.dart';
import '../onboarding/onboarding_controller.dart';

class SplashScreen extends ConsumerStatefulWidget {
  const SplashScreen({super.key});

  @override
  ConsumerState<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends ConsumerState<SplashScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _bootstrap());
  }

  Future<void> _bootstrap() async {
    if (!mounted) {
      return;
    }

    final onboardingDone = ref.read(onboardingControllerProvider);
    final session = ref.read(currentSessionProvider);

    if (!onboardingDone) {
      context.go('/onboarding');
      return;
    }
    if (session == null) {
      context.go('/login');
      return;
    }

    // Resolve the profile so we can route admins straight to the inbox.
    try {
      await ref.read(currentUserProfileProvider.future);
    } catch (_) {
      // Fall through to the citizen landing if the profile fails to load.
    }
    if (!mounted) return;
    final role = ref.read(currentUserRoleProvider);
    context.go(landingRouteFor(role));
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Container(
        decoration: const BoxDecoration(
          gradient: LinearGradient(
            colors: [Color(0xFF082F49), Color(0xFF0E7490), Color(0xFF1D4ED8)],
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
          ),
        ),
        child: Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const SmartCityLogo(size: 72),
              const SizedBox(height: 22),
              Text(
                context.l10n.appTitle,
                style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                  color: Colors.white,
                  fontWeight: FontWeight.w800,
                ),
              ),
              const SizedBox(height: 10),
              Text(
                'Trusted citizen reporting with AI, maps, and accountability.',
                style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                  color: Colors.white.withValues(alpha: 0.86),
                ),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 28),
              const CircularProgressIndicator(color: Colors.white),
            ],
          ),
        ),
      ),
    );
  }
}
