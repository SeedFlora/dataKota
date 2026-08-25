import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/theme/app_theme.dart';
import '../../core/l10n/l10n.dart';
import '../../core/widgets/smart_city_ui.dart';
import 'settings_controller.dart';

class SettingsScreen extends ConsumerWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final settings = ref.watch(settingsControllerProvider);
    final controller = ref.read(settingsControllerProvider.notifier);
    final l10n = context.l10n;

    return Scaffold(
      appBar: AppBar(title: Text(l10n.settingsTitle)),
      body: SafeArea(
        child: ListView(
          padding: pagePadding(context),
          children: [
            _SectionLabel(l10n.settingsLanguage),
            const SizedBox(height: 4),
            Text(
              l10n.settingsLanguageHint,
              style: Theme.of(context).textTheme.bodySmall,
            ),
            const SizedBox(height: 12),
            _LanguageToggle(
              current: settings.locale,
              onChanged: controller.setLocale,
            ),
            const SizedBox(height: 28),
            _SettingTile(
              title: l10n.settingsAutoLocation,
              subtitle: l10n.settingsAutoLocationHint,
              value: settings.autoUseCurrentLocation,
              onChanged: controller.toggleAutoLocation,
            ),
            const SizedBox(height: 8),
            _SettingTile(
              title: l10n.settingsShowResolved,
              subtitle: l10n.settingsShowResolvedHint,
              value: settings.showResolvedReports,
              onChanged: controller.toggleShowResolved,
            ),
            const SizedBox(height: 8),
            _SettingTile(
              title: l10n.settingsNotifyUpdates,
              subtitle: l10n.settingsNotifyUpdatesHint,
              value: settings.notifyStatusUpdates,
              onChanged: controller.toggleStatusNotifications,
            ),
          ],
        ),
      ),
    );
  }
}

class _SectionLabel extends StatelessWidget {
  const _SectionLabel(this.text);
  final String text;

  @override
  Widget build(BuildContext context) {
    return Text(text, style: Theme.of(context).textTheme.titleMedium);
  }
}

class _LanguageToggle extends StatelessWidget {
  const _LanguageToggle({required this.current, required this.onChanged});

  final Locale current;
  final ValueChanged<Locale> onChanged;

  @override
  Widget build(BuildContext context) {
    final l10n = context.l10n;
    return SegmentedButton<Locale>(
      segments: [
        ButtonSegment(
          value: const Locale('id'),
          label: Text(l10n.languageIndonesian),
        ),
        ButtonSegment(
          value: const Locale('en'),
          label: Text(l10n.languageEnglish),
        ),
      ],
      selected: {current},
      onSelectionChanged: (set) => onChanged(set.first),
      showSelectedIcon: false,
    );
  }
}

class _SettingTile extends StatelessWidget {
  const _SettingTile({
    required this.title,
    required this.subtitle,
    required this.value,
    required this.onChanged,
  });

  final String title;
  final String subtitle;
  final bool value;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    return InkWell(
      onTap: () => onChanged(!value),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 8),
        child: Row(
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(title, style: Theme.of(context).textTheme.bodyLarge),
                  const SizedBox(height: 2),
                  Text(subtitle, style: Theme.of(context).textTheme.bodySmall),
                ],
              ),
            ),
            const SizedBox(width: 12),
            Switch.adaptive(
              value: value,
              activeThumbColor: palette.accentCyan,
              onChanged: onChanged,
            ),
          ],
        ),
      ),
    );
  }
}
