import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/config/app_config.dart';

class SettingsState {
  const SettingsState({
    required this.locale,
    required this.autoUseCurrentLocation,
    required this.showResolvedReports,
    required this.notifyStatusUpdates,
  });

  final Locale locale;
  final bool autoUseCurrentLocation;
  final bool showResolvedReports;
  final bool notifyStatusUpdates;

  SettingsState copyWith({
    Locale? locale,
    bool? autoUseCurrentLocation,
    bool? showResolvedReports,
    bool? notifyStatusUpdates,
  }) {
    return SettingsState(
      locale: locale ?? this.locale,
      autoUseCurrentLocation:
          autoUseCurrentLocation ?? this.autoUseCurrentLocation,
      showResolvedReports: showResolvedReports ?? this.showResolvedReports,
      notifyStatusUpdates: notifyStatusUpdates ?? this.notifyStatusUpdates,
    );
  }
}

class SettingsController extends Notifier<SettingsState> {
  static const _localeKey = 'settings_locale';
  static const _locationKey = 'settings_auto_location';
  static const _resolvedKey = 'settings_show_resolved';
  static const _notifyKey = 'settings_notify_updates';

  static const supportedLocales = <Locale>[Locale('id'), Locale('en')];
  static const _defaultLocale = Locale('id');

  @override
  SettingsState build() {
    final prefs = ref.read(sharedPreferencesProvider);
    return SettingsState(
      locale: _readLocale(prefs.getString(_localeKey)),
      autoUseCurrentLocation: prefs.getBool(_locationKey) ?? true,
      showResolvedReports: prefs.getBool(_resolvedKey) ?? true,
      notifyStatusUpdates: prefs.getBool(_notifyKey) ?? true,
    );
  }

  Future<void> setLocale(Locale locale) async {
    if (!supportedLocales.contains(locale)) return;
    await ref
        .read(sharedPreferencesProvider)
        .setString(_localeKey, locale.languageCode);
    state = state.copyWith(locale: locale);
  }

  Future<void> toggleAutoLocation(bool value) async {
    await ref.read(sharedPreferencesProvider).setBool(_locationKey, value);
    state = state.copyWith(autoUseCurrentLocation: value);
  }

  Future<void> toggleShowResolved(bool value) async {
    await ref.read(sharedPreferencesProvider).setBool(_resolvedKey, value);
    state = state.copyWith(showResolvedReports: value);
  }

  Future<void> toggleStatusNotifications(bool value) async {
    await ref.read(sharedPreferencesProvider).setBool(_notifyKey, value);
    state = state.copyWith(notifyStatusUpdates: value);
  }

  Locale _readLocale(String? code) {
    if (code == null) return _defaultLocale;
    return supportedLocales.firstWhere(
      (l) => l.languageCode == code,
      orElse: () => _defaultLocale,
    );
  }
}

final settingsControllerProvider =
    NotifierProvider<SettingsController, SettingsState>(SettingsController.new);
