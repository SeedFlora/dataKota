import 'dart:typed_data';

import 'package:image/image.dart' as img;
import 'package:image_picker/image_picker.dart';

/// A decoded, metadata-free image that is safe to hand to object storage.
class SanitizedImageUpload {
  const SanitizedImageUpload({
    required this.bytes,
    required this.extension,
    required this.contentType,
    required this.width,
    required this.height,
  });

  final Uint8List bytes;
  final String extension;
  final String contentType;
  final int width;
  final int height;
}

class ImageSanitizationException implements Exception {
  const ImageSanitizationException(this.message);

  final String message;

  @override
  String toString() => message;
}

enum _InputImageFormat { jpeg, png, webp }

/// Fail-closed sanitizer shared by every client-to-Storage image upload.
///
/// The filename and picker MIME type are deliberately ignored. The input is
/// capped while streaming, identified by file signature, header-decoded before
/// raster allocation, and accepted only when it is a single-frame JPEG, PNG,
/// or WebP. The first and only frame is orientation-corrected, composited onto
/// an opaque white RGB canvas, and encoded as a fresh JPEG. Re-encoding a fresh
/// raster (rather than the decoded object) removes EXIF/GPS, ICC, text chunks,
/// comments, thumbnails, and other source metadata.
class ImageUploadSanitizer {
  static const reportOutputByteLimit = 10 * 1024 * 1024;
  static const profileOutputByteLimit = 5 * 1024 * 1024;

  const ImageUploadSanitizer({
    this.maxInputBytes = 20 * 1024 * 1024,
    this.maxOutputBytes = reportOutputByteLimit,
    this.maxDimension = 8192,
    this.maxPixels = 24000000,
    this.jpegQuality = 88,
  }) : assert(maxInputBytes > 0),
       assert(maxOutputBytes > 0),
       assert(maxDimension > 0),
       assert(maxPixels > 0),
       assert(jpegQuality >= 1 && jpegQuality <= 100);

  /// Raw picker payload limit: 20 MiB by default.
  final int maxInputBytes;

  /// Sanitized JPEG limit. Call sites set the matching Storage-bucket cap.
  final int maxOutputBytes;

  /// Maximum width or height reported by the decoder header.
  final int maxDimension;

  /// Maximum decoded canvas area (24 megapixels by default).
  final int maxPixels;

  /// Fixed JPEG re-encoding quality. The production default is 88.
  final int jpegQuality;

  Future<SanitizedImageUpload> sanitizeXFile(XFile source) async {
    final declaredLength = await source.length();
    _validateByteCount(declaredLength);

    final builder = BytesBuilder(copy: false);
    var observedLength = 0;
    await for (final chunk in source.openRead()) {
      observedLength += chunk.length;
      _validateByteCount(observedLength);
      builder.add(chunk);
    }

    return sanitizeBytes(builder.takeBytes());
  }

  /// Sanitizes an already bounded in-memory payload.
  ///
  /// Callers that start with a file should use [sanitizeXFile], which enforces
  /// the limit while reading and does not trust a potentially stale size check.
  SanitizedImageUpload sanitizeBytes(Uint8List bytes) {
    _validateByteCount(bytes.length);
    if (bytes.isEmpty) {
      throw const ImageSanitizationException('The selected image is empty.');
    }

    final format = _sniffFormat(bytes);
    if (format == null) {
      throw const ImageSanitizationException(
        'Unsupported image content. Select a JPEG, PNG, or WebP image.',
      );
    }
    if (!_hasCompleteContainer(format, bytes)) {
      throw const ImageSanitizationException(
        'The selected image is malformed or truncated.',
      );
    }

    final decoder = switch (format) {
      _InputImageFormat.jpeg => img.JpegDecoder(),
      _InputImageFormat.png => img.PngDecoder(),
      _InputImageFormat.webp => img.WebPDecoder(),
    };

    img.DecodeInfo? info;
    try {
      info = decoder.startDecode(bytes);
    } catch (_) {
      throw const ImageSanitizationException(
        'The selected image is malformed or truncated.',
      );
    }
    if (info == null) {
      throw const ImageSanitizationException(
        'The selected image is malformed or truncated.',
      );
    }
    _validateCanvas(info.width, info.height);
    if (info.numFrames != 1) {
      throw const ImageSanitizationException(
        'Animated or multi-frame images are not accepted.',
      );
    }

    img.Image? decoded;
    try {
      decoded = decoder.decodeFrame(0);
    } catch (_) {
      throw const ImageSanitizationException(
        'The selected image could not be decoded safely.',
      );
    }
    if (decoded == null) {
      throw const ImageSanitizationException(
        'The selected image could not be decoded safely.',
      );
    }
    final matchesHeader =
        decoded.width == info.width && decoded.height == info.height;
    final matchesOrientationSwap =
        format == _InputImageFormat.jpeg &&
        decoded.width == info.height &&
        decoded.height == info.width;
    if (!matchesHeader && !matchesOrientationSwap) {
      throw const ImageSanitizationException(
        'The decoded image dimensions do not match its header or orientation.',
      );
    }

    final oriented = img.bakeOrientation(decoded);
    _validateCanvas(oriented.width, oriented.height);

    // A new three-channel canvas is intentional: it prevents any decoded
    // metadata object from reaching the encoder and flattens transparency onto
    // a predictable background before JPEG encoding.
    final cleanRaster = img.Image(
      width: oriented.width,
      height: oriented.height,
      numChannels: 3,
    )..clear(img.ColorRgb8(255, 255, 255));
    img.compositeImage(cleanRaster, oriented);
    cleanRaster.exif.clear();
    cleanRaster.iccProfile = null;
    cleanRaster.textData = null;

    final output = img.encodeJpg(
      cleanRaster,
      quality: jpegQuality,
      chroma: img.JpegChroma.yuv420,
    );
    if (output.length > maxOutputBytes) {
      throw ImageSanitizationException(
        'The sanitized image exceeds the ${_formatMiB(maxOutputBytes)} MiB '
        'upload limit.',
      );
    }

    return SanitizedImageUpload(
      bytes: output,
      extension: 'jpg',
      contentType: 'image/jpeg',
      width: oriented.width,
      height: oriented.height,
    );
  }

  void _validateByteCount(int byteCount) {
    if (byteCount < 0 || byteCount > maxInputBytes) {
      throw ImageSanitizationException(
        'The selected image exceeds the ${_formatMiB(maxInputBytes)} MiB '
        'input limit.',
      );
    }
  }

  void _validateCanvas(int width, int height) {
    if (width <= 0 || height <= 0) {
      throw const ImageSanitizationException(
        'The selected image has invalid dimensions.',
      );
    }
    if (width > maxDimension || height > maxDimension) {
      throw ImageSanitizationException(
        'The selected image exceeds the $maxDimension-pixel dimension limit.',
      );
    }
    if (width * height > maxPixels) {
      throw ImageSanitizationException(
        'The selected image exceeds the $maxPixels-pixel canvas limit.',
      );
    }
  }

  _InputImageFormat? _sniffFormat(Uint8List bytes) {
    if (bytes.length >= 3 &&
        bytes[0] == 0xff &&
        bytes[1] == 0xd8 &&
        bytes[2] == 0xff) {
      return _InputImageFormat.jpeg;
    }
    if (bytes.length >= 8 &&
        bytes[0] == 0x89 &&
        bytes[1] == 0x50 &&
        bytes[2] == 0x4e &&
        bytes[3] == 0x47 &&
        bytes[4] == 0x0d &&
        bytes[5] == 0x0a &&
        bytes[6] == 0x1a &&
        bytes[7] == 0x0a) {
      return _InputImageFormat.png;
    }
    if (bytes.length >= 12 &&
        bytes[0] == 0x52 &&
        bytes[1] == 0x49 &&
        bytes[2] == 0x46 &&
        bytes[3] == 0x46 &&
        bytes[8] == 0x57 &&
        bytes[9] == 0x45 &&
        bytes[10] == 0x42 &&
        bytes[11] == 0x50) {
      return _InputImageFormat.webp;
    }
    return null;
  }

  bool _hasCompleteContainer(_InputImageFormat format, Uint8List bytes) {
    switch (format) {
      case _InputImageFormat.jpeg:
        // The image decoder intentionally tolerates incomplete JPEG streams;
        // uploads do not. Requiring EOI also rejects appended polyglot data.
        return bytes.length >= 4 &&
            bytes[bytes.length - 2] == 0xff &&
            bytes[bytes.length - 1] == 0xd9;
      case _InputImageFormat.png:
        const iend = <int>[
          0x00,
          0x00,
          0x00,
          0x00,
          0x49,
          0x45,
          0x4e,
          0x44,
          0xae,
          0x42,
          0x60,
          0x82,
        ];
        if (bytes.length < iend.length) return false;
        final offset = bytes.length - iend.length;
        for (var index = 0; index < iend.length; index++) {
          if (bytes[offset + index] != iend[index]) return false;
        }
        return true;
      case _InputImageFormat.webp:
        // RIFF length excludes the initial "RIFF" tag and length word.
        final declaredRiffLength =
            bytes[4] | (bytes[5] << 8) | (bytes[6] << 16) | (bytes[7] << 24);
        return declaredRiffLength + 8 == bytes.length;
    }
  }

  String _formatMiB(int bytes) => (bytes / (1024 * 1024)).toStringAsFixed(0);
}
