import 'package:flutter_test/flutter_test.dart';
import 'package:smart_city_reporter_app/core/utils/validators.dart';

void main() {
  group('Validators', () {
    test('email validates required and proper format', () {
      expect(Validators.email(''), 'Email is required.');
      expect(Validators.email('not-an-email'), 'Enter a valid email address.');
      expect(Validators.email('citizen@example.com'), isNull);
    });

    test('password enforces strength rules', () {
      expect(
        Validators.password('short'),
        'Password must be at least 8 characters.',
      );
      expect(
        Validators.password('lowercaseonly123'),
        'Use upper, lower, and numeric characters.',
      );
      expect(Validators.password('StrongPass123'), isNull);
    });

    test('phone normalizes separators and validates length', () {
      expect(Validators.phone('12345'), 'Enter a valid phone number.');
      expect(Validators.phone('+62 812-3456-7890'), isNull);
    });
  });
}
