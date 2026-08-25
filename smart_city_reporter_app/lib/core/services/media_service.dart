import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';

class MediaService {
  MediaService(this._picker);

  final ImagePicker _picker;

  // 1280px / q85 keeps plenty of detail for the DINOv3 classifier (which
  // downscales internally anyway) and for display, while roughly halving the
  // bytes that get uploaded twice per report (CRM /predict + Supabase storage).
  static const int _maxWidth = 1280;
  static const int _quality = 85;

  Future<XFile?> pickFromCamera() {
    return _picker.pickImage(
      source: ImageSource.camera,
      maxWidth: _maxWidth.toDouble(),
      imageQuality: _quality,
    );
  }

  Future<XFile?> pickFromGallery() {
    return _picker.pickImage(
      source: ImageSource.gallery,
      maxWidth: _maxWidth.toDouble(),
      imageQuality: _quality,
    );
  }
}

final mediaServiceProvider = Provider<MediaService>((ref) {
  return MediaService(ImagePicker());
});
