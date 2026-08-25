import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/l10n/l10n.dart' show AppLocalizations;
import '../features/settings/settings_controller.dart';
import 'auth_flow_listener.dart';
import 'router/app_router.dart';
import 'theme/app_theme.dart';

class SmartCityReporterApp extends ConsumerWidget {
  const SmartCityReporterApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final router = ref.watch(appRouterProvider);
    final locale = ref.watch(
      settingsControllerProvider.select((s) => s.locale),
    );

    return MaterialApp.router(
      onGenerateTitle: (ctx) => AppLocalizations.of(ctx)!.appTitle,
      debugShowCheckedModeBanner: false,
      theme: AppTheme.lightTheme,
      routerConfig: router,
      locale: locale,
      supportedLocales: SettingsController.supportedLocales,
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      builder: (context, child) =>
          AuthFlowListener(child: child ?? const SizedBox.shrink()),
    );
  }
}
