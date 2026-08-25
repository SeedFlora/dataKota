import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/config/app_config.dart';

class OnboardingController extends Notifier<bool> {
  static const _key = 'onboarding_completed';

  @override
  bool build() {
    return ref.read(sharedPreferencesProvider).getBool(_key) ?? false;
  }

  Future<void> complete() async {
    await ref.read(sharedPreferencesProvider).setBool(_key, true);
    state = true;
  }
}

final onboardingControllerProvider =
    NotifierProvider<OnboardingController, bool>(OnboardingController.new);
