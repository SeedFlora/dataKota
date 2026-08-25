import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

/// A user-facing description of an auth failure: a short headline, a one-line
/// explanation of what to do next, and an icon. Built by [describeAuthError],
/// which maps raw Supabase / network exceptions to friendly copy so screens
/// never surface `Exception: AuthApiException(...)` to people.
class AuthFailure {
  const AuthFailure({
    required this.title,
    required this.message,
    this.icon = Icons.error_outline_rounded,
  });

  final String title;
  final String message;
  final IconData icon;
}

/// Translate any thrown error from an auth call into an [AuthFailure].
///
/// Supabase deliberately returns the same "invalid login credentials" for a
/// missing account and a wrong password (to avoid leaking which emails are
/// registered), so we surface a single combined message for that case.
AuthFailure describeAuthError(Object error) {
  if (_isNetworkError(error)) {
    return const AuthFailure(
      title: 'No internet connection',
      message:
          'We couldn\'t reach the server. Check your connection and try again.',
      icon: Icons.wifi_off_rounded,
    );
  }

  if (error is AuthException) {
    final code = error.code?.toLowerCase();
    final msg = error.message.toLowerCase();

    if (code == 'invalid_credentials' ||
        msg.contains('invalid login credentials') ||
        msg.contains('invalid credentials')) {
      return const AuthFailure(
        title: 'Incorrect email or password',
        message:
            'No account matches those details. Double-check your email and password, or create a new account.',
        icon: Icons.lock_outline_rounded,
      );
    }

    if (code == 'email_not_confirmed' || msg.contains('not confirmed')) {
      return const AuthFailure(
        title: 'Email not verified yet',
        message:
            'Open the verification link we emailed you, then sign in again.',
        icon: Icons.mark_email_unread_outlined,
      );
    }

    if (code == 'user_already_exists' ||
        code == 'email_exists' ||
        msg.contains('already registered') ||
        msg.contains('already been registered') ||
        msg.contains('user already')) {
      return const AuthFailure(
        title: 'Account already exists',
        message: 'This email is already registered. Try signing in instead.',
        icon: Icons.how_to_reg_outlined,
      );
    }

    if (code == 'weak_password' ||
        msg.contains('password should be') ||
        msg.contains('password is too')) {
      return const AuthFailure(
        title: 'Password too weak',
        message: 'Use at least 6 characters with a mix of letters and numbers.',
        icon: Icons.password_rounded,
      );
    }

    if (code != null && code.contains('rate_limit') ||
        error.statusCode == '429' ||
        msg.contains('rate limit') ||
        msg.contains('too many')) {
      return const AuthFailure(
        title: 'Too many attempts',
        message: 'Please wait a moment before trying again.',
        icon: Icons.hourglass_bottom_rounded,
      );
    }

    // Known auth error we don't have bespoke copy for — show the server's
    // message, which is already human-readable, just capitalised.
    return AuthFailure(
      title: 'Sign-in failed',
      message: _capitalize(error.message),
    );
  }

  if (error is PostgrestException) {
    return const AuthFailure(
      title: 'Something went wrong',
      message: 'We couldn\'t load your account data. Please try again.',
    );
  }

  return const AuthFailure(
    title: 'Something went wrong',
    message: 'An unexpected error occurred. Please try again in a moment.',
  );
}

bool _isNetworkError(Object error) {
  if (error is SocketException ||
      error is TimeoutException ||
      error is AuthRetryableFetchException) {
    return true;
  }
  final text = error.toString().toLowerCase();
  return text.contains('socketexception') ||
      text.contains('failed host lookup') ||
      text.contains('connection refused') ||
      text.contains('connection closed') ||
      text.contains('network is unreachable') ||
      text.contains('clientexception');
}

String _capitalize(String value) {
  final trimmed = value.trim();
  if (trimmed.isEmpty) return 'Please try again.';
  return trimmed[0].toUpperCase() + trimmed.substring(1);
}
