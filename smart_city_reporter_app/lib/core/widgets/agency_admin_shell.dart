import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/theme/app_theme.dart';
import '../../features/auth/auth_repository.dart';
import '../../features/auth/user_role.dart';

class AgencyAdminShell extends ConsumerWidget {
  const AgencyAdminShell({super.key, required this.navigationShell});

  final StatefulNavigationShell navigationShell;

  void _goBranch(int index) {
    navigationShell.goBranch(
      index,
      initialLocation: index == navigationShell.currentIndex,
    );
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final palette = context.palette;
    final role = ref.watch(currentUserRoleProvider);

    return Scaffold(
      extendBody: true,
      backgroundColor: palette.surface,
      body: navigationShell,
      // No FloatingActionButton — agency admins don't submit reports.
      bottomNavigationBar: Container(
        decoration: BoxDecoration(
          color: palette.surfaceElevated,
          border: Border(top: BorderSide(color: palette.border)),
        ),
        child: SafeArea(
          top: false,
          child: NavigationBar(
            selectedIndex: navigationShell.currentIndex,
            onDestinationSelected: _goBranch,
            destinations: [
              NavigationDestination(
                icon: const Icon(Icons.inbox_outlined),
                selectedIcon: const Icon(Icons.inbox_rounded),
                label: switch (role) {
                  AgencyAdmin() => 'Inbox',
                  SuperAdmin() => 'All reports',
                  Citizen() => 'Inbox',
                },
              ),
              const NavigationDestination(
                icon: Icon(Icons.map_outlined),
                selectedIcon: Icon(Icons.map_rounded),
                label: 'Map',
              ),
              const NavigationDestination(
                icon: Icon(Icons.person_outline_rounded),
                selectedIcon: Icon(Icons.person_rounded),
                label: 'Profile',
              ),
            ],
          ),
        ),
      ),
    );
  }
}
