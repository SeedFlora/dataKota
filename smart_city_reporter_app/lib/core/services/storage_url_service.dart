import 'package:supabase_flutter/supabase_flutter.dart';

/// Resolves stored Supabase Storage references into displayable URLs.
///
/// Buckets are private, so the database stores `bucket/object_path` (not a final
/// URL) and the client mints short-lived signed URLs on demand. This also parses
/// legacy public/signed URLs so rows written before the migration still resolve.
///
/// Resolution never throws: on any failure it returns the original value so the
/// image widget's `errorWidget` degrades to a placeholder instead of crashing.
class StorageUrls {
  StorageUrls._();

  static const int _ttlSeconds = 3600;
  static const List<String> _bucketPrefixes = [
    'report-images/',
    'profile-photos/',
  ];

  static final Map<String, _CachedUrl> _cache = {};

  /// True when [value] is a Storage reference (a remote URL or `bucket/path`)
  /// rather than an empty string or a local file path.
  static bool isStorageRef(String value) {
    final v = value.trim();
    if (v.isEmpty) return false;
    final lower = v.toLowerCase();
    if (lower.startsWith('http://') || lower.startsWith('https://'))
      return true;
    return _bucketPrefixes.any(v.startsWith);
  }

  /// Returns a short-lived signed URL for [stored]. Falls back to [stored] when
  /// it cannot be parsed or signed.
  static Future<String> signed(String stored) async {
    final value = stored.trim();
    if (value.isEmpty) return '';

    final cached = _cache[value];
    if (cached != null && cached.expiry.isAfter(DateTime.now())) {
      return cached.url;
    }

    final ref = _parse(value);
    if (ref == null) return value;

    try {
      final url = await Supabase.instance.client.storage
          .from(ref.bucket)
          .createSignedUrl(ref.path, _ttlSeconds);
      _cache[value] = _CachedUrl(
        url,
        DateTime.now().add(const Duration(seconds: _ttlSeconds - 60)),
      );
      return url;
    } catch (_) {
      return value;
    }
  }

  static _StorageRef? _parse(String value) {
    String rest;
    if (value.contains('/object/public/')) {
      rest = value.split('/object/public/').last;
    } else if (value.contains('/object/sign/')) {
      rest = value.split('/object/sign/').last.split('?').first;
    } else {
      rest = value;
    }
    final slash = rest.indexOf('/');
    if (slash <= 0 || slash == rest.length - 1) return null;
    return _StorageRef(rest.substring(0, slash), rest.substring(slash + 1));
  }
}

class _StorageRef {
  const _StorageRef(this.bucket, this.path);
  final String bucket;
  final String path;
}

class _CachedUrl {
  const _CachedUrl(this.url, this.expiry);
  final String url;
  final DateTime expiry;
}
