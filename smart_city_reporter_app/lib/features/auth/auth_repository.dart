import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import '../../core/config/app_config.dart';
import '../../core/security/image_upload_sanitizer.dart';
import '../reports/reports_scope.dart';
import 'user_profile.dart';
import 'user_role.dart';

class LocalAuthSession {
  const LocalAuthSession({required this.userId});

  final String userId;
}

class SignUpResult {
  const SignUpResult({
    required this.user,
    required this.requiresEmailConfirmation,
  });

  final UserProfile? user;
  final bool requiresEmailConfirmation;
}

class AuthRepository {
  AuthRepository(
    this._client, {
    required String authRedirectUrl,
    ImageUploadSanitizer imageSanitizer = const ImageUploadSanitizer(
      maxOutputBytes: ImageUploadSanitizer.profileOutputByteLimit,
    ),
  }) : _authRedirectUrl = authRedirectUrl,
       _imageSanitizer = imageSanitizer;

  final SupabaseClient _client;
  final ImageUploadSanitizer _imageSanitizer;

  static const _updateOwnProfileRpc = 'update_own_profile';

  /// Deep link Supabase Auth redirects back to after the user clicks the
  /// email confirmation or password-reset link (see [AppConfig.authRedirectUrl]).
  final String _authRedirectUrl;

  LocalAuthSession? get currentSession {
    final session = _client.auth.currentSession;
    if (session == null) return null;
    return LocalAuthSession(userId: session.user.id);
  }

  Stream<LocalAuthSession?> authStateChanges() {
    return _client.auth.onAuthStateChange.map((state) {
      final user = state.session?.user;
      if (user == null) return null;
      return LocalAuthSession(userId: user.id);
    });
  }

  Future<SignUpResult> signUp({
    required String fullName,
    required String email,
    required String phoneNumber,
    required String password,
    XFile? profilePhoto,
  }) async {
    final normalizedEmail = email.trim().toLowerCase();
    final normalizedFullName = fullName.trim();
    final normalizedPhone = phoneNumber.trim();

    final response = await _client.auth.signUp(
      email: normalizedEmail,
      password: password,
      emailRedirectTo: _authRedirectUrl,
      data: {'full_name': normalizedFullName, 'phone_number': normalizedPhone},
    );

    final user = response.user;
    if (user == null) {
      throw Exception('Sign-up failed. Please try again.');
    }

    final requiresConfirmation = response.session == null;

    if (profilePhoto != null && response.session != null) {
      await _uploadAndBindProfilePhoto(user.id, profilePhoto);
    }

    UserProfile? profile;
    if (response.session != null) {
      profile = await fetchCurrentUserProfile();
    }

    return SignUpResult(
      user: profile,
      requiresEmailConfirmation: requiresConfirmation,
    );
  }

  Future<void> signIn({required String email, required String password}) async {
    final normalizedEmail = email.trim().toLowerCase();
    await _client.auth.signInWithPassword(
      email: normalizedEmail,
      password: password,
    );
  }

  Future<void> signOut() async {
    await _client.auth.signOut();
  }

  Future<void> sendPasswordReset(String email) async {
    final normalizedEmail = email.trim().toLowerCase();
    await _client.auth.resetPasswordForEmail(
      normalizedEmail,
      redirectTo: _authRedirectUrl,
    );
  }

  Future<UserProfile?> fetchCurrentUserProfile() async {
    final user = _client.auth.currentUser;
    if (user == null) return null;

    final row = await _client
        .from('profiles')
        .select()
        .eq('id', user.id)
        .maybeSingle();

    if (row == null) return null;
    return UserProfile.fromMap(row);
  }

  Future<UserProfile> updateProfilePhoto(XFile imageFile) async {
    final user = _client.auth.currentUser;
    if (user == null) {
      throw Exception('You need to be logged in.');
    }

    await _uploadAndBindProfilePhoto(user.id, imageFile);

    final profile = await fetchCurrentUserProfile();
    if (profile == null) {
      throw Exception('Unable to refresh your profile.');
    }
    return profile;
  }

  Future<String> _uploadProfilePhoto(String userId, XFile imageFile) async {
    final sanitized = await _imageSanitizer.sanitizeXFile(imageFile);
    final path =
        '$userId/${DateTime.now().millisecondsSinceEpoch}.${sanitized.extension}';
    await _client.storage
        .from('profile-photos')
        .uploadBinary(
          path,
          sanitized.bytes,
          fileOptions: FileOptions(
            upsert: true,
            contentType: sanitized.contentType,
          ),
        );
    // Private bucket: store bucket/object_path; UI mints signed URLs on read.
    return 'profile-photos/$path';
  }

  Future<void> _uploadAndBindProfilePhoto(
    String userId,
    XFile imageFile,
  ) async {
    final photoReference = await _uploadProfilePhoto(userId, imageFile);
    try {
      await _client.rpc(
        _updateOwnProfileRpc,
        params: {'p_profile_photo_url': photoReference},
      );
    } catch (_) {
      const prefix = 'profile-photos/';
      final objectPath = photoReference.substring(prefix.length);
      await _client.storage
          .from('profile-photos')
          .remove([objectPath])
          .catchError((_) => <FileObject>[]);
      rethrow;
    }
  }
}

final authRepositoryProvider = Provider<AuthRepository>((ref) {
  return AuthRepository(
    ref.watch(supabaseClientProvider),
    authRedirectUrl: ref.watch(appConfigProvider).authRedirectUrl,
  );
});

final authSessionProvider = StreamProvider<LocalAuthSession?>((ref) {
  return ref.watch(authRepositoryProvider).authStateChanges();
});

final currentSessionProvider = Provider<LocalAuthSession?>((ref) {
  final sessionAsync = ref.watch(authSessionProvider);
  return sessionAsync.asData?.value ??
      ref.watch(authRepositoryProvider).currentSession;
});

final currentUserProfileProvider = FutureProvider<UserProfile?>((ref) async {
  final session = ref.watch(currentSessionProvider);
  if (session == null) return null;
  return ref.watch(authRepositoryProvider).fetchCurrentUserProfile();
});

final currentUserRoleProvider = Provider<UserRole>((ref) {
  final profile = ref.watch(currentUserProfileProvider).asData?.value;
  if (profile == null) return const Citizen();
  return UserRole.fromProfile(profile);
});

final reportsScopeProvider = Provider<ReportsScope>((ref) {
  final profile = ref.watch(currentUserProfileProvider).asData?.value;
  final role = ref.watch(currentUserRoleProvider);
  return ReportsScope.forRole(role, userId: profile?.id ?? '');
});
