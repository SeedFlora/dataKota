import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/services/media_service.dart';
import '../../core/widgets/smart_city_ui.dart';
import '../auth/auth_repository.dart';

class ProfileScreen extends ConsumerWidget {
  const ProfileScreen({super.key});

  Future<void> _popWithSelectedImage(
    BuildContext modalContext,
    Future Function() picker,
  ) async {
    final selected = await picker();
    if (modalContext.mounted) {
      Navigator.pop(modalContext, selected);
    }
  }

  Future<void> _changePhoto(BuildContext context, WidgetRef ref) async {
    final media = ref.read(mediaServiceProvider);
    final file = await showModalBottomSheet(
      context: context,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(28)),
      ),
      builder: (context) {
        return SafeArea(
          child: Padding(
            padding: const EdgeInsets.all(20),
            child: Wrap(
              children: [
                ListTile(
                  leading: const Icon(Icons.photo_camera_outlined),
                  title: const Text('Take photo'),
                  onTap: () =>
                      _popWithSelectedImage(context, media.pickFromCamera),
                ),
                ListTile(
                  leading: const Icon(Icons.photo_library_outlined),
                  title: const Text('Choose from gallery'),
                  onTap: () =>
                      _popWithSelectedImage(context, media.pickFromGallery),
                ),
              ],
            ),
          ),
        );
      },
    );

    if (file == null) {
      return;
    }

    await ref.read(authRepositoryProvider).updateProfilePhoto(file);
    ref.invalidate(currentUserProfileProvider);
  }

  Future<void> _confirmLogout(BuildContext context, WidgetRef ref) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Log out?'),
        content: const Text(
          "You'll need to sign in again to see your reports.",
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Log out'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;

    await ref.read(authRepositoryProvider).signOut();
    if (context.mounted) {
      context.go('/login');
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final profileAsync = ref.watch(currentUserProfileProvider);

    return Scaffold(
      body: SafeArea(
        child: ListView(
          padding: pagePadding(context),
          children: [
            profileAsync.when(
              data: (profile) {
                if (profile == null) {
                  return const EmptyStateCard(
                    icon: Icons.person_off_outlined,
                    title: 'Profile unavailable',
                    message:
                        'Please sign in again to reload your account data.',
                  );
                }

                return Column(
                  children: [
                    GradientHeroHeader(
                      title: profile.fullName,
                      subtitle: profile.email,
                      trailing: GestureDetector(
                        onTap: () => _changePhoto(context, ref),
                        child: ProfileAvatar(
                          imageUrl: profile.profilePhotoUrl,
                          fallbackText: profile.fullName,
                          radius: 30,
                        ),
                      ),
                    ),
                    const SizedBox(height: 20),
                    SectionCard(
                      child: Column(
                        children: [
                          _InfoRow(label: 'Full name', value: profile.fullName),
                          const Divider(height: 26),
                          _InfoRow(label: 'Email', value: profile.email),
                          const Divider(height: 26),
                          _InfoRow(label: 'Phone', value: profile.phoneNumber),
                          const Divider(height: 26),
                          _InfoRow(
                            label: 'Role',
                            value: profile.isModerator
                                ? 'Moderator'
                                : 'Citizen reporter',
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 20),
                    SectionCard(
                      child: Column(
                        children: [
                          ListTile(
                            contentPadding: EdgeInsets.zero,
                            leading: const Icon(Icons.settings_outlined),
                            title: const Text('Settings'),
                            trailing: const Icon(Icons.chevron_right_rounded),
                            onTap: () => context.push('/settings'),
                          ),
                          const Divider(),
                          ListTile(
                            contentPadding: EdgeInsets.zero,
                            leading: const Icon(Icons.logout_rounded),
                            title: const Text('Log out'),
                            trailing: const Icon(Icons.chevron_right_rounded),
                            onTap: () => _confirmLogout(context, ref),
                          ),
                        ],
                      ),
                    ),
                  ],
                );
              },
              loading: () => const Center(child: CircularProgressIndicator()),
              error: (error, _) => EmptyStateCard(
                icon: Icons.error_outline_rounded,
                title: 'Could not load profile',
                message: error.toString(),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _InfoRow extends StatelessWidget {
  const _InfoRow({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(
          child: Text(label, style: Theme.of(context).textTheme.bodyMedium),
        ),
        Expanded(
          child: Text(
            value,
            textAlign: TextAlign.end,
            style: Theme.of(context).textTheme.titleMedium,
          ),
        ),
      ],
    );
  }
}
