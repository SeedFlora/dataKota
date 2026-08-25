import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/config/app_config.dart';
import '../../core/widgets/smart_city_ui.dart';

class SetupRequiredScreen extends ConsumerWidget {
  const SetupRequiredScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final config = ref.watch(appConfigProvider);
    final missing = <String>[
      if (!config.hasSupabaseConfig)
        'a valid SUPABASE_URL and SUPABASE_ANON_KEY',
      if (!config.hasInferenceConfig)
        'a valid HTTPS CRM_API_URL (or explicit testing mode)',
    ];

    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: pagePadding(context),
          child: Column(
            children: [
              const SizedBox(height: 24),
              const SmartCityLogo(size: 64),
              const SizedBox(height: 20),
              Text(
                'Setup required',
                style: Theme.of(context).textTheme.headlineMedium,
              ),
              const SizedBox(height: 10),
              Text(
                'Missing configuration: ${missing.join(' and ')}. The app stays fail-closed instead of connecting to a built-in service or entering an unauthenticated flow.',
                style: Theme.of(context).textTheme.bodyLarge,
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 20),
              const SectionCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('Required flags'),
                    SizedBox(height: 12),
                    SelectableText('--dart-define=SUPABASE_URL=...'),
                    SelectableText('--dart-define=SUPABASE_ANON_KEY=...'),
                    SelectableText('--dart-define=CRM_API_URL=https://...'),
                    SelectableText(
                      '--dart-define=ALLOW_INSECURE_HTTP=true (local development only)',
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 20),
              if (config.enableTestingMode) ...[
                const SizedBox(height: 20),
                OutlinedButton.icon(
                  onPressed: () => context.go('/model-test'),
                  icon: const Icon(Icons.science_outlined),
                  label: const Text('Open AI Testing Mode'),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
