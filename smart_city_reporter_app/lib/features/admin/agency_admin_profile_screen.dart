import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/theme/app_theme.dart';
import '../../core/widgets/smart_city_ui.dart';
import '../auth/auth_repository.dart';
import '../auth/user_role.dart';

class AgencyAdminProfileScreen extends ConsumerWidget {
  const AgencyAdminProfileScreen({super.key});

  Future<void> _confirmLogout(BuildContext context, WidgetRef ref) async {
    final palette = context.palette;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Row(
          children: [
            IconTile(
              icon: Icons.logout_rounded,
              color: palette.danger,
              size: 38,
            ),
            const SizedBox(width: 12),
            const Expanded(child: Text('Log out?')),
          ],
        ),
        content: const Text(
          "You'll need to sign in again to access the inbox.",
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            style: FilledButton.styleFrom(
              backgroundColor: palette.danger,
              minimumSize: const Size(0, 44),
            ),
            child: const Text('Log out'),
          ),
        ],
      ),
    );

    if (confirmed != true || !context.mounted) return;
    await ref.read(authRepositoryProvider).signOut();
    if (context.mounted) context.go('/login');
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final profileAsync = ref.watch(currentUserProfileProvider);
    final role = ref.watch(currentUserRoleProvider);
    final palette = context.palette;

    final (roleLabel, roleScope) = switch (role) {
      AgencyAdmin(:final agency) => ('Agency Admin', agency.label),
      SuperAdmin() => ('Super Admin', 'Akses penuh ke semua instansi'),
      Citizen() => ('Citizen', 'Pelapor warga'),
    };

    return AppPage(
      children: [
        const PageHeader(
          title: 'Account',
          subtitle: 'Your moderator profile and scope.',
        ),
        const SizedBox(height: 20),
        AsyncView(
          value: profileAsync,
          data: (profile) {
            if (profile == null) {
              return const EmptyStateCard(
                icon: Icons.person_off_outlined,
                title: 'Not signed in',
                message: 'Please sign in again.',
              );
            }
            return Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _ProfileHero(
                  name: profile.fullName,
                  email: profile.email,
                  phone: profile.phoneNumber,
                  photoUrl: profile.profilePhotoUrl,
                  roleLabel: roleLabel,
                  roleScope: roleScope,
                ),
                const SizedBox(height: 20),
                GroupedCard(
                  children: [
                    if (role is SuperAdmin)
                      AppTile(
                        icon: Icons.account_balance_rounded,
                        title: 'Kelola Registri Instansi',
                        subtitle: 'Tambah, ubah, dan atur instansi tujuan',
                        onTap: () => context.push('/admin/agencies'),
                      ),
                    AppTile(
                      icon: Icons.logout_rounded,
                      iconColor: palette.danger,
                      titleColor: palette.danger,
                      title: 'Log out',
                      trailing: Icon(
                        Icons.chevron_right_rounded,
                        color: palette.danger.withValues(alpha: 0.6),
                      ),
                      onTap: () => _confirmLogout(context, ref),
                    ),
                  ],
                ),
              ],
            );
          },
        ),
      ],
    );
  }
}

/// Profile hero: avatar, name, contact lines and a role badge — the calm,
/// card-led header used across modern account screens.
class _ProfileHero extends StatelessWidget {
  const _ProfileHero({
    required this.name,
    required this.email,
    required this.phone,
    required this.photoUrl,
    required this.roleLabel,
    required this.roleScope,
  });

  final String name;
  final String email;
  final String phone;
  final String? photoUrl;
  final String roleLabel;
  final String roleScope;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    final text = Theme.of(context).textTheme;
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: palette.surfaceElevated,
        borderRadius: BorderRadius.circular(AppTheme.rCard),
        border: Border.all(color: palette.border),
        boxShadow: AppTheme.softShadow,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              ProfileAvatar(imageUrl: photoUrl, fallbackText: name, radius: 30),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      name,
                      style: text.titleLarge,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                    const SizedBox(height: 6),
                    StatusPill(
                      label: roleLabel,
                      color: palette.accentBlue,
                      showDot: false,
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 18),
          Divider(height: 1, color: palette.border),
          const SizedBox(height: 14),
          _ContactRow(icon: Icons.alternate_email_rounded, value: email),
          if (phone.isNotEmpty) ...[
            const SizedBox(height: 10),
            _ContactRow(icon: Icons.phone_outlined, value: phone),
          ],
          const SizedBox(height: 10),
          _ContactRow(icon: Icons.shield_outlined, value: roleScope),
        ],
      ),
    );
  }
}

class _ContactRow extends StatelessWidget {
  const _ContactRow({required this.icon, required this.value});

  final IconData icon;
  final String value;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    return Row(
      children: [
        Icon(icon, size: 18, color: palette.inkSubtle),
        const SizedBox(width: 12),
        Expanded(
          child: Text(
            value,
            style: Theme.of(
              context,
            ).textTheme.bodyMedium?.copyWith(color: palette.ink),
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
          ),
        ),
      ],
    );
  }
}
