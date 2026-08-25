import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

class AppConfig {
  const AppConfig({
    required this.supabaseUrl,
    required this.supabaseAnonKey,
    required this.enableTestingMode,
    required this.crmApiUrl,
    required this.authRedirectUrl,
    required this.allowInsecureHttp,
  });

  factory AppConfig.fromEnvironment() {
    return const AppConfig(
      supabaseUrl: String.fromEnvironment('SUPABASE_URL'),
      supabaseAnonKey: String.fromEnvironment('SUPABASE_ANON_KEY'),
      enableTestingMode: bool.fromEnvironment('ENABLE_TESTING_MODE'),
      crmApiUrl: String.fromEnvironment('CRM_API_URL'),
      authRedirectUrl: String.fromEnvironment(
        'AUTH_REDIRECT_URL',
        defaultValue: 'smartcityapps://login-callback',
      ),
      allowInsecureHttp: bool.fromEnvironment('ALLOW_INSECURE_HTTP'),
    );
  }

  final String supabaseUrl;
  final String supabaseAnonKey;
  final bool enableTestingMode;
  final String crmApiUrl;

  /// Deep link that Supabase Auth redirects to after email confirmation or
  /// password reset. Must match the Android intent-filter and the Supabase
  /// dashboard "Redirect URLs" allow-list.
  final String authRedirectUrl;
  final bool allowInsecureHttp;

  bool _validServiceUrl(String raw) {
    if (raw.isEmpty || raw.contains('<') || raw.contains('>')) return false;
    final uri = Uri.tryParse(raw);
    if (uri == null || !uri.hasAuthority || uri.host.isEmpty) return false;
    if (uri.scheme == 'https') return true;
    return allowInsecureHttp && uri.scheme == 'http';
  }

  bool get hasSupabaseConfig =>
      _validServiceUrl(supabaseUrl) &&
      supabaseAnonKey.isNotEmpty &&
      !supabaseAnonKey.contains('<') &&
      !supabaseAnonKey.contains('>');

  bool get hasInferenceConfig =>
      enableTestingMode || _validServiceUrl(crmApiUrl);

  bool get isConfigured => hasSupabaseConfig && hasInferenceConfig;
}

final appConfigProvider = Provider<AppConfig>((ref) {
  throw UnimplementedError('AppConfig must be overridden at startup.');
});

final sharedPreferencesProvider = Provider<SharedPreferences>((ref) {
  throw UnimplementedError('SharedPreferences must be overridden at startup.');
});

final supabaseClientProvider = Provider<SupabaseClient>(
  (ref) => Supabase.instance.client,
);
