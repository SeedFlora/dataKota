import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/utils/validators.dart';
import '../../core/widgets/smart_city_ui.dart';
import 'auth_error.dart';
import 'auth_repository.dart';
import 'role_landing.dart';

class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key});

  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen> {
  final _formKey = GlobalKey<FormState>();
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();
  bool _submitting = false;
  AuthFailure? _error;

  @override
  void dispose() {
    _emailController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    FocusScope.of(context).unfocus();
    if (!_formKey.currentState!.validate()) {
      return;
    }

    setState(() {
      _submitting = true;
      _error = null;
    });
    try {
      await ref
          .read(authRepositoryProvider)
          .signIn(
            email: _emailController.text,
            password: _passwordController.text,
          );
      // Force the profile (and therefore role) to refresh after a sign-in
      // so the landing route reflects the new session.
      ref.invalidate(currentUserProfileProvider);
      try {
        await ref.read(currentUserProfileProvider.future);
      } catch (_) {}
      if (!mounted) {
        return;
      }
      final role = ref.read(currentUserRoleProvider);
      context.go(landingRouteFor(role));
    } catch (error) {
      if (!mounted) {
        return;
      }
      setState(() => _error = describeAuthError(error));
    } finally {
      if (mounted) {
        setState(() => _submitting = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: SingleChildScrollView(
          padding: pagePadding(context),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const SizedBox(height: 10),
              const GradientHeroHeader(
                title: 'Welcome back',
                subtitle:
                    'Sign in to create verified reports and see nearby incidents on the map.',
                trailing: SmartCityLogo(size: 60),
              ),
              const SizedBox(height: 22),
              SectionCard(
                child: Form(
                  key: _formKey,
                  onChanged: () {
                    if (_error != null) setState(() => _error = null);
                  },
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const SectionHeader(
                        title: 'Secure sign in',
                        subtitle:
                            'Every report is linked to an authenticated account.',
                      ),
                      if (_error != null) ...[
                        const SizedBox(height: 16),
                        InlineNotice(
                          title: _error!.title,
                          message: _error!.message,
                          icon: _error!.icon,
                          onClose: () => setState(() => _error = null),
                        ),
                      ],
                      const SizedBox(height: 18),
                      TextFormField(
                        controller: _emailController,
                        keyboardType: TextInputType.emailAddress,
                        decoration: const InputDecoration(
                          labelText: 'Email',
                          prefixIcon: Icon(Icons.mail_outline_rounded),
                        ),
                        validator: Validators.email,
                      ),
                      const SizedBox(height: 14),
                      PasswordField(
                        controller: _passwordController,
                        validator: Validators.password,
                        autofillHints: const [AutofillHints.password],
                      ),
                      const SizedBox(height: 8),
                      Align(
                        alignment: Alignment.centerRight,
                        child: TextButton(
                          onPressed: () => context.push('/forgot-password'),
                          child: const Text('Forgot password?'),
                        ),
                      ),
                      const SizedBox(height: 8),
                      ElevatedButton(
                        onPressed: _submitting ? null : _submit,
                        child: _submitting
                            ? const SizedBox(
                                width: 20,
                                height: 20,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                ),
                              )
                            : const Text('Log In'),
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 18),
              Center(
                child: Wrap(
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: [
                    const Text('New here? '),
                    TextButton(
                      onPressed: () => context.push('/register'),
                      child: const Text('Create an account'),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
