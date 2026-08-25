import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/theme/app_theme.dart';
import '../../core/utils/validators.dart';
import '../../core/widgets/smart_city_ui.dart';
import 'auth_error.dart';
import 'auth_repository.dart';

class ForgotPasswordScreen extends ConsumerStatefulWidget {
  const ForgotPasswordScreen({super.key});

  @override
  ConsumerState<ForgotPasswordScreen> createState() =>
      _ForgotPasswordScreenState();
}

class _ForgotPasswordScreenState extends ConsumerState<ForgotPasswordScreen> {
  final _formKey = GlobalKey<FormState>();
  final _emailController = TextEditingController();
  bool _submitting = false;
  bool _sent = false;
  AuthFailure? _error;

  @override
  void dispose() {
    _emailController.dispose();
    super.dispose();
  }

  Future<void> _sendReset() async {
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
          .sendPasswordReset(_emailController.text);
      if (!mounted) {
        return;
      }
      setState(() => _sent = true);
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
      appBar: AppBar(),
      body: SafeArea(
        child: Padding(
          padding: pagePadding(context),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const GradientHeroHeader(
                title: 'Reset your password',
                subtitle:
                    'Enter your email and we will send a secure reset link.',
              ),
              const SizedBox(height: 22),
              SectionCard(
                child: _sent
                    ? _ResetSentView(
                        email: _emailController.text.trim(),
                        onBack: () => context.pop(),
                      )
                    : Form(
                        key: _formKey,
                        onChanged: () {
                          if (_error != null) setState(() => _error = null);
                        },
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            if (_error != null) ...[
                              InlineNotice(
                                title: _error!.title,
                                message: _error!.message,
                                icon: _error!.icon,
                                onClose: () => setState(() => _error = null),
                              ),
                              const SizedBox(height: 18),
                            ],
                            TextFormField(
                              controller: _emailController,
                              keyboardType: TextInputType.emailAddress,
                              decoration: const InputDecoration(
                                labelText: 'Email',
                                prefixIcon: Icon(Icons.mail_outline_rounded),
                              ),
                              validator: Validators.email,
                            ),
                            const SizedBox(height: 20),
                            ElevatedButton(
                              onPressed: _submitting ? null : _sendReset,
                              child: _submitting
                                  ? const SizedBox(
                                      width: 20,
                                      height: 20,
                                      child: CircularProgressIndicator(
                                        strokeWidth: 2,
                                      ),
                                    )
                                  : const Text('Send reset link'),
                            ),
                          ],
                        ),
                      ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Confirmation shown after a reset link is requested. Supabase doesn't reveal
/// whether the email exists, so the copy is deliberately neutral.
class _ResetSentView extends StatelessWidget {
  const _ResetSentView({required this.email, required this.onBack});

  final String email;
  final VoidCallback onBack;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    final text = Theme.of(context).textTheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        IconTile(
          icon: Icons.mark_email_read_outlined,
          color: palette.success,
          size: 52,
        ),
        const SizedBox(height: 16),
        Text('Check your inbox', style: text.titleLarge),
        const SizedBox(height: 6),
        Text(
          email.isEmpty
              ? 'If an account exists for that email, a secure reset link is on its way.'
              : 'If an account exists for $email, a secure reset link is on its way. The link expires after a short while.',
          style: text.bodyMedium,
        ),
        const SizedBox(height: 20),
        ElevatedButton(onPressed: onBack, child: const Text('Back to sign in')),
      ],
    );
  }
}
