class Validators {
  static String? requiredField(
    String? value, {
    String fieldName = 'This field',
  }) {
    if (value == null || value.trim().isEmpty) {
      return '$fieldName is required.';
    }
    return null;
  }

  static String? email(String? value) {
    final required = requiredField(value, fieldName: 'Email');
    if (required != null) {
      return required;
    }
    final emailRegExp = RegExp(r'^[^@\s]+@[^@\s]+\.[^@\s]+$');
    if (!emailRegExp.hasMatch(value!.trim())) {
      return 'Enter a valid email address.';
    }
    return null;
  }

  static String? password(String? value) {
    final required = requiredField(value, fieldName: 'Password');
    if (required != null) {
      return required;
    }
    final normalized = value!.trim();
    if (normalized.length < 8) {
      return 'Password must be at least 8 characters.';
    }
    if (!RegExp(r'[A-Z]').hasMatch(normalized) ||
        !RegExp(r'[a-z]').hasMatch(normalized) ||
        !RegExp(r'[0-9]').hasMatch(normalized)) {
      return 'Use upper, lower, and numeric characters.';
    }
    return null;
  }

  static String? phone(String? value) {
    final required = requiredField(value, fieldName: 'Phone number');
    if (required != null) {
      return required;
    }
    final normalized = value!.replaceAll(RegExp(r'[^0-9+]'), '');
    if (normalized.length < 10 || normalized.length > 15) {
      return 'Enter a valid phone number.';
    }
    return null;
  }
}
