import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/l10n/l10n.dart';
import '../../core/widgets/smart_city_ui.dart';
import '../auth/auth_repository.dart';
import 'onboarding_controller.dart';

class OnboardingScreen extends ConsumerStatefulWidget {
  const OnboardingScreen({super.key});

  @override
  ConsumerState<OnboardingScreen> createState() => _OnboardingScreenState();
}

class _OnboardingScreenState extends ConsumerState<OnboardingScreen> {
  final _controller = PageController();
  int _pageIndex = 0;

  static const _pages = [
    (
      icon: Icons.document_scanner_outlined,
      title: 'Report issues in seconds',
      subtitle:
          'Snap a photo, let AI suggest the issue type, and submit a structured report in one guided flow.',
    ),
    (
      icon: Icons.map_outlined,
      title: 'Pin the exact location',
      subtitle:
          'Capture your current GPS location, drag the pin on the map, and provide a readable address.',
    ),
    (
      icon: Icons.verified_user_outlined,
      title: 'Trusted civic accountability',
      subtitle:
          'Every report is tied to a verified account, making prank reports easier to moderate and trace.',
    ),
  ];

  Future<void> _finish() async {
    await ref.read(onboardingControllerProvider.notifier).complete();
    final session = ref.read(currentSessionProvider);
    if (!mounted) {
      return;
    }
    context.go(session == null ? '/login' : '/home');
  }

  @override
  Widget build(BuildContext context) {
    final padding = pagePadding(context);

    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: padding,
          child: Column(
            children: [
              const SizedBox(height: 16),
              Row(
                children: [
                  const SmartCityLogo(),
                  const SizedBox(width: 14),
                  Expanded(
                    child: Text(
                      context.l10n.appTitle,
                      style: Theme.of(context).textTheme.titleLarge,
                    ),
                  ),
                  TextButton(onPressed: _finish, child: const Text('Skip')),
                ],
              ),
              const SizedBox(height: 28),
              Expanded(
                child: PageView.builder(
                  controller: _controller,
                  itemCount: _pages.length,
                  onPageChanged: (index) => setState(() => _pageIndex = index),
                  itemBuilder: (context, index) {
                    final page = _pages[index];
                    return Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Expanded(
                          child: Container(
                            decoration: BoxDecoration(
                              borderRadius: BorderRadius.circular(34),
                              gradient: const LinearGradient(
                                colors: [
                                  Color(0xFF082F49),
                                  Color(0xFF0E7490),
                                  Color(0xFF1D4ED8),
                                ],
                                begin: Alignment.topLeft,
                                end: Alignment.bottomRight,
                              ),
                            ),
                            child: Center(
                              child: Icon(
                                page.icon,
                                color: Colors.white,
                                size: 94,
                              ),
                            ),
                          ),
                        ),
                        const SizedBox(height: 28),
                        Text(
                          page.title,
                          style: Theme.of(context).textTheme.headlineMedium,
                        ),
                        const SizedBox(height: 12),
                        Text(
                          page.subtitle,
                          style: Theme.of(context).textTheme.bodyLarge,
                        ),
                      ],
                    );
                  },
                ),
              ),
              const SizedBox(height: 22),
              Row(
                children: List.generate(
                  _pages.length,
                  (index) => AnimatedContainer(
                    duration: const Duration(milliseconds: 250),
                    margin: const EdgeInsets.only(right: 8),
                    width: _pageIndex == index ? 28 : 10,
                    height: 10,
                    decoration: BoxDecoration(
                      color: _pageIndex == index
                          ? Theme.of(context).colorScheme.primary
                          : const Color(0xFFCBD5E1),
                      borderRadius: BorderRadius.circular(999),
                    ),
                  ),
                ),
              ),
              const SizedBox(height: 18),
              ElevatedButton(
                onPressed: _pageIndex == _pages.length - 1
                    ? _finish
                    : () => _controller.nextPage(
                        duration: const Duration(milliseconds: 320),
                        curve: Curves.easeOut,
                      ),
                child: Text(
                  _pageIndex == _pages.length - 1
                      ? 'Start Reporting'
                      : 'Continue',
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
