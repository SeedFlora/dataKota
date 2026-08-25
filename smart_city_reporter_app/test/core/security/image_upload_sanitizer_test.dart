import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:image/image.dart' as img;
import 'package:image_picker/image_picker.dart';
import 'package:smart_city_reporter_app/core/security/image_upload_sanitizer.dart';

void main() {
  group('ImageUploadSanitizer', () {
    test('matches the report and profile Storage byte limits', () {
      expect(ImageUploadSanitizer.reportOutputByteLimit, 10485760);
      expect(ImageUploadSanitizer.profileOutputByteLimit, 5242880);
    });

    test(
      'sniffs content, ignores a spoofed extension, and emits safe JPEG',
      () async {
        final source = img.Image(width: 3, height: 2)
          ..clear(img.ColorRgba8(10, 20, 30, 128));
        final png = img.encodePng(source);
        final file = XFile.fromData(
          png,
          path: 'spoofed.heic',
          name: 'spoofed.heic',
          mimeType: 'image/heic',
        );

        final result = await const ImageUploadSanitizer().sanitizeXFile(file);

        expect(result.extension, 'jpg');
        expect(result.contentType, 'image/jpeg');
        expect(result.width, 3);
        expect(result.height, 2);
        expect(result.bytes.take(3), <int>[0xff, 0xd8, 0xff]);
        final decoded = img.decodeJpg(result.bytes);
        expect(decoded, isNotNull);
        expect(decoded!.numChannels, 3);
      },
    );

    test('rejects unsupported and malformed payloads', () {
      const sanitizer = ImageUploadSanitizer();
      final completeJpeg = img.encodeJpg(img.Image(width: 2, height: 2));
      final truncatedJpeg = Uint8List.sublistView(
        completeJpeg,
        0,
        completeJpeg.length - 2,
      );

      expect(
        () => sanitizer.sanitizeBytes(Uint8List.fromList(<int>[1, 2, 3])),
        throwsA(isA<ImageSanitizationException>()),
      );
      expect(
        () => sanitizer.sanitizeBytes(
          Uint8List.fromList(<int>[0xff, 0xd8, 0xff, 0x00]),
        ),
        throwsA(isA<ImageSanitizationException>()),
      );
      expect(
        () => sanitizer.sanitizeBytes(truncatedJpeg),
        throwsA(isA<ImageSanitizationException>()),
      );
    });

    test('enforces the byte cap before decoding', () {
      const sanitizer = ImageUploadSanitizer(maxInputBytes: 16);

      expect(
        () => sanitizer.sanitizeBytes(Uint8List(17)),
        throwsA(isA<ImageSanitizationException>()),
      );
    });

    test(
      'enforces observed stream bytes even when declared length is stale',
      () async {
        const sanitizer = ImageUploadSanitizer(maxInputBytes: 16);
        final file = XFile.fromData(Uint8List(17), length: 1);

        await expectLater(
          sanitizer.sanitizeXFile(file),
          throwsA(isA<ImageSanitizationException>()),
        );
      },
    );

    test('enforces maximum dimensions and pixel area from decoder header', () {
      final wide = img.encodePng(img.Image(width: 11, height: 2));
      final dense = img.encodePng(img.Image(width: 8, height: 8));

      expect(
        () => const ImageUploadSanitizer(maxDimension: 10).sanitizeBytes(wide),
        throwsA(isA<ImageSanitizationException>()),
      );
      expect(
        () => const ImageUploadSanitizer(maxPixels: 63).sanitizeBytes(dense),
        throwsA(isA<ImageSanitizationException>()),
      );
    });

    test('rejects animated input instead of silently selecting a frame', () {
      final animated = img.Image(width: 2, height: 2)
        ..clear(img.ColorRgb8(255, 0, 0))
        ..addFrame(
          img.Image(width: 2, height: 2)..clear(img.ColorRgb8(0, 0, 255)),
        );
      final input = img.encodePng(animated);
      expect(img.PngDecoder().startDecode(input)?.numFrames, 2);

      expect(
        () => const ImageUploadSanitizer().sanitizeBytes(input),
        throwsA(isA<ImageSanitizationException>()),
      );
    });

    test('bakes EXIF orientation and removes source metadata', () {
      final source = img.Image(width: 2, height: 3)
        ..clear(img.ColorRgb8(40, 80, 120));
      final exif = img.ExifData();
      exif.imageIfd['Orientation'] = 6;
      exif.imageIfd['ImageDescription'] = 'SENSITIVE_GPS_FIXTURE';
      final nullableWithExif = img.injectJpgExif(img.encodeJpg(source), exif);
      expect(nullableWithExif, isNotNull);
      final withExif = nullableWithExif!;
      expect(img.decodeJpgExif(withExif)?.isEmpty, isFalse);

      final result = const ImageUploadSanitizer().sanitizeBytes(withExif);

      expect(result.width, 3);
      expect(result.height, 2);
      final outputExif = img.decodeJpgExif(result.bytes);
      expect(outputExif == null || outputExif.isEmpty, isTrue);
      expect(
        _containsSequence(
          result.bytes,
          Uint8List.fromList('SENSITIVE_GPS_FIXTURE'.codeUnits),
        ),
        isFalse,
      );
    });

    test('rejects output that exceeds its independent upload cap', () {
      final input = img.encodePng(img.Image(width: 32, height: 32));

      expect(
        () =>
            const ImageUploadSanitizer(maxOutputBytes: 8).sanitizeBytes(input),
        throwsA(isA<ImageSanitizationException>()),
      );
    });
  });
}

bool _containsSequence(Uint8List haystack, Uint8List needle) {
  if (needle.isEmpty || needle.length > haystack.length) return false;
  for (var offset = 0; offset <= haystack.length - needle.length; offset++) {
    var matches = true;
    for (var index = 0; index < needle.length; index++) {
      if (haystack[offset + index] != needle[index]) {
        matches = false;
        break;
      }
    }
    if (matches) return true;
  }
  return false;
}
