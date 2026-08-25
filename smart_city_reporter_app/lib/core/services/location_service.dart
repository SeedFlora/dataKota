import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:geocoding/geocoding.dart';
import 'package:geolocator/geolocator.dart';

class LocationService {
  /// Fast path: returns coordinates only (no reverse geocode). Use when you
  /// want to render a pin immediately and fill in the address asynchronously.
  Future<({double latitude, double longitude})> getCoordinates() async {
    final isEnabled = await Geolocator.isLocationServiceEnabled();
    if (!isEnabled) {
      throw Exception('Location services are disabled.');
    }

    var permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.denied) {
      permission = await Geolocator.requestPermission();
    }

    if (permission == LocationPermission.denied ||
        permission == LocationPermission.deniedForever) {
      throw Exception('Location permission is required to create a report.');
    }

    // `.high` (≈10m) is enough for a street-level pin and is noticeably
    // faster than `.best`. `timeLimit` prevents a bad sky view from hanging
    // the whole upload flow.
    final position = await Geolocator.getCurrentPosition(
      locationSettings: const LocationSettings(
        accuracy: LocationAccuracy.high,
        timeLimit: Duration(seconds: 8),
      ),
    );

    return (latitude: position.latitude, longitude: position.longitude);
  }

  Future<String> reverseGeocode({
    required double latitude,
    required double longitude,
  }) async {
    final placemarks = await placemarkFromCoordinates(latitude, longitude);
    if (placemarks.isEmpty) {
      return 'Address unavailable';
    }

    final place = placemarks.first;
    final segments = [
      place.street,
      place.subLocality,
      place.locality,
      place.administrativeArea,
      place.country,
    ].where((segment) => (segment ?? '').trim().isNotEmpty).cast<String>();

    return segments.join(', ');
  }
}

final locationServiceProvider = Provider<LocationService>((ref) {
  return LocationService();
});
