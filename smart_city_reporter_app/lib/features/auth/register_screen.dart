import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:image_picker/image_picker.dart';

import '../../core/services/media_service.dart';
import '../../core/utils/validators.dart';
import '../../core/widgets/smart_city_ui.dart';
import 'auth_error.dart';
import 'auth_repository.dart';

class RegisterScreen extends ConsumerStatefulWidget {
  const RegisterScreen({super.key});

  @override
  ConsumerState<RegisterScreen> createState() => _RegisterScreenState();
}

class _RegisterScreenState extends ConsumerState<RegisterScreen> {
  final _formKey = GlobalKey<FormState>();
  final _fullNameController = TextEditingController();
  final _emailController = TextEditingController();
  final _phoneController = TextEditingController();
  final _passwordController = TextEditingController();
  final _confirmPasswordController = TextEditingController();

  XFile? _profilePhoto;
  bool _submitting = false;
  AuthFailure? _error;

  @override
  void dispose() {
    _fullNameController.dispose();
    _emailController.dispose();
    _phoneController.dispose();
    _passwordController.dispose();
    _confirmPasswordController.dispose();
    super.dispose();
  }

  Future<void> _popWithSelectedImage(
    BuildContext modalContext,
    Future<XFile?> Function() picker,
  ) async {
    final selected = await picker();
    if (modalContext.mounted) {
      Navigator.pop(modalContext, selected);
    }
  }

  Future<void> _pickProfilePhoto() async {
    final mediaService = ref.read(mediaServiceProvider);
    final selected = await showModalBottomSheet<XFile?>(
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
                  onTap: () => _popWithSelectedImage(
                    context,
                    mediaService.pickFromCamera,
                  ),
                ),
                ListTile(
                  leading: const Icon(Icons.photo_library_outlined),
                  title: const Text('Choose from gallery'),
                  onTap: () => _popWithSelectedImage(
                    context,
                    mediaService.pickFromGallery,
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );

    if (selected != null && mounted) {
      setState(() => _profilePhoto = selected);
    }
  }

  Future<void> _submit() async {
    FocusScope.of(context).unfocus();
    if (!_formKey.currentState!.validate()) {
      return;
    }

    if (_passwordController.text.trim() !=
        _confirmPasswordController.text.trim()) {
      setState(
        () => _error = const AuthFailure(
          title: 'Passwords don\'t match',
          message: 'Re-enter your password so both fields are identical.',
          icon: Icons.password_rounded,
        ),
      );
      return;
    }

    setState(() {
      _submitting = true;
      _error = null;
    });
    try {
      final result = await ref
          .read(authRepositoryProvider)
          .signUp(
            fullName: _fullNameController.text,
            email: _emailController.text,
            phoneNumber: _phoneController.text,
            password: _passwordController.text,
            profilePhoto: _profilePhoto,
          );

      if (!mounted) {
        return;
      }

      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Account created. Check your email to verify.'),
        ),
      );
      context.go(result.requiresEmailConfirmation ? '/login' : '/home');
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
              IconButton(
                onPressed: () => context.pop(),
                icon: const Icon(Icons.arrow_back_rounded),
              ),
              const SizedBox(height: 8),
              const GradientHeroHeader(
                title: 'Create your civic account',
                subtitle:
                    'Create a local account stored on this phone so every report still stays tied to a known identity.',
                trailing: SmartCityLogo(size: 58),
              ),
              const SizedBox(height: 22),
              SectionCard(
                child: Form(
                  key: _formKey,
                  onChanged: () {
                    if (_error != null) setState(() => _error = null);
                  },
                  child: Column(
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
                      GestureDetector(
                        onTap: _pickProfilePhoto,
                        child: Column(
                          children: [
                            CircleAvatar(
                              radius: 36,
                              backgroundColor: Theme.of(
                                context,
                              ).colorScheme.primary.withValues(alpha: 0.12),
                              backgroundImage: _profilePhoto == null
                                  ? null
                                  : FileImage(File(_profilePhoto!.path)),
                              child: _profilePhoto == null
                                  ? Icon(
                                      Icons.add_a_photo_outlined,
                                      color: Theme.of(
                                        context,
                                      ).colorScheme.primary,
                                    )
                                  : null,
                            ),
                            const SizedBox(height: 10),
                            Text(
                              'Optional profile photo',
                              style: Theme.of(context).textTheme.bodyMedium,
                            ),
                          ],
                        ),
                      ),
                      const SizedBox(height: 18),
                      TextFormField(
                        controller: _fullNameController,
                        decoration: const InputDecoration(
                          labelText: 'Full name',
                          prefixIcon: Icon(Icons.badge_outlined),
                        ),
                        validator: (value) => Validators.requiredField(
                          value,
                          fieldName: 'Full name',
                        ),
                      ),
                      const SizedBox(height: 14),
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
                      TextFormField(
                        controller: _phoneController,
                        keyboardType: TextInputType.phone,
                        decoration: const InputDecoration(
                          labelText: 'Phone number',
                          prefixIcon: Icon(Icons.phone_outlined),
                        ),
                        validator: Validators.phone,
                      ),
                      const SizedBox(height: 14),
                      PasswordField(
                        controller: _passwordController,
                        validator: Validators.password,
                        autofillHints: const [AutofillHints.newPassword],
                      ),
                      const SizedBox(height: 14),
                      PasswordField(
                        controller: _confirmPasswordController,
                        label: 'Confirm password',
                        prefixIcon: Icons.verified_user_outlined,
                        validator: Validators.password,
                        autofillHints: const [AutofillHints.newPassword],
                      ),
                      const SizedBox(height: 20),
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
                            : const Text('Register'),
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
