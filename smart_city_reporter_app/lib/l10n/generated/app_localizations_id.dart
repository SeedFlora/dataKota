// ignore: unused_import
import 'package:intl/intl.dart' as intl;
import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for Indonesian (`id`).
class AppLocalizationsId extends AppLocalizations {
  AppLocalizationsId([String locale = 'id']) : super(locale);

  @override
  String get appTitle => 'SmartCityApps';

  @override
  String get languageIndonesian => 'Indonesia';

  @override
  String get languageEnglish => 'English';

  @override
  String get greetingFallback => 'Selamat datang';

  @override
  String greetingNamed(String name) {
    return 'Hi, $name';
  }

  @override
  String get overviewSection => 'Ringkasan';

  @override
  String get nearbyReportsSection => 'Laporan terdekat';

  @override
  String get recentSubmissionsSection => 'Laporan terbaru';

  @override
  String get seeAll => 'Lihat semua';

  @override
  String get openMap => 'Buka peta';

  @override
  String get noReportsYet => 'Belum ada laporan';

  @override
  String get noReportsYetHint =>
      'Tap tombol Lapor untuk membuat laporan kota pertama Anda.';

  @override
  String get reportFab => 'Lapor';

  @override
  String get settingsTitle => 'Pengaturan';

  @override
  String get settingsLanguage => 'Bahasa';

  @override
  String get settingsLanguageHint => 'Bahasa antarmuka aplikasi.';

  @override
  String get settingsAutoLocation => 'Auto-isi lokasi saat ini';

  @override
  String get settingsAutoLocationHint =>
      'Ambil GPS otomatis saat membuat laporan baru.';

  @override
  String get settingsShowResolved => 'Tampilkan laporan selesai di peta';

  @override
  String get settingsShowResolvedHint =>
      'Pertahankan laporan yang sudah selesai tetap terlihat di peta.';

  @override
  String get settingsNotifyUpdates => 'Beri tahu saya saat status berubah';

  @override
  String get settingsNotifyUpdatesHint =>
      'Siapkan aplikasi untuk notifikasi moderasi dan resolusi.';

  @override
  String get createReportTitle => 'Buat Laporan';

  @override
  String get addPhoto => 'Tambahkan foto';

  @override
  String get addPhotoHint => 'Ambil foto langsung atau pilih dari galeri.';

  @override
  String get noPhotoYet => 'Belum ada foto';

  @override
  String get tapAddPhoto => 'Tap Kamera atau Galeri di bawah';

  @override
  String get camera => 'Kamera';

  @override
  String get gallery => 'Galeri';

  @override
  String get locationStep => 'Lokasi';

  @override
  String get locationHint =>
      'GPS untuk akurasi. Bisa disesuaikan di layar berikut.';

  @override
  String get noLocationYet => 'Lokasi belum diambil.';

  @override
  String get useCurrentLocation => 'Gunakan lokasi saat ini';

  @override
  String get refreshLocation => 'Refresh lokasi';

  @override
  String get shortDescription => 'Deskripsi singkat';

  @override
  String get shortDescriptionHint =>
      'Jelaskan apa yang terjadi dalam satu-dua kalimat.';

  @override
  String get descriptionPlaceholder =>
      'Contoh: \"Lubang besar di lajur kiri Jl. Sudirman, dekat lampu merah.\"';

  @override
  String get descriptionLanguageHint =>
      'Bahasa Indonesia atau English. Detail spesifik (lokasi, ukuran, dampak) bantu model memilih instansi yang tepat.';

  @override
  String get runAiClassification => 'Klasifikasi dengan AI';

  @override
  String get addPhotoFirst => 'Tambahkan foto dulu';

  @override
  String get addDescriptionFirst => 'Tambahkan deskripsi (min. 10 karakter)';

  @override
  String get descriptionMinError =>
      'Tulis deskripsi minimal 10 karakter — model multimodal membaca gambar dan teks.';

  @override
  String get selectPhotoFirst => 'Pilih foto laporan terlebih dahulu.';

  @override
  String get reviewTitle => 'Review Hasil AI';

  @override
  String get directedTo => 'Kategori laporan';

  @override
  String confidence(String percent) {
    return 'Skor model $percent';
  }

  @override
  String get aiUncertain => 'Laporan memerlukan tinjauan manual';

  @override
  String get aiUncertainHint =>
      'Periksa foto, deskripsi, kategori, dan alasan tinjauan sebelum mengirim.';

  @override
  String get topCandidates => 'Skor kelas teratas';

  @override
  String get instansiPickerHint => 'Pilih kategori laporan';

  @override
  String get instansiPickerSubhint =>
      'Default mengikuti rekomendasi model. Ganti bila kategorinya tidak sesuai laporan.';

  @override
  String get confirmLocation => 'Konfirmasi lokasi';

  @override
  String get confirmLocationHint =>
      'Tap peta atau geser pin biru untuk presisi.';

  @override
  String get tapMapHint => 'Tap peta atau gunakan lokasi GPS Anda.';

  @override
  String get descriptionSection => 'Deskripsi';

  @override
  String get descriptionSectionHint =>
      'Anda masih bisa menyempurnakan deskripsi sebelum disimpan.';

  @override
  String get descriptionFieldHint =>
      'Tambahkan konteks bermanfaat untuk petugas.';

  @override
  String get submitReport => 'Submit laporan';

  @override
  String get submitting => 'Mengirim…';

  @override
  String get almostThere => 'Hampir selesai';

  @override
  String get checklistPhoto => 'Foto terlampir';

  @override
  String get checklistInstansi => 'Kategori terkonfirmasi';

  @override
  String get checklistLocation => 'Lokasi terkonfirmasi';

  @override
  String get checklistDescription => 'Deskripsi terisi';

  @override
  String get reportSubmitted => 'Laporan terkirim';

  @override
  String get noReviewYet => 'Belum ada hasil untuk direview';

  @override
  String get noReviewYetHint =>
      'Pilih foto, isi deskripsi, lalu jalankan klasifikasi AI.';

  @override
  String get backToForm => 'Kembali ke form laporan';

  @override
  String get detailTitle => 'Detail Laporan';

  @override
  String get statusTimeline => 'Status laporan';

  @override
  String get technicalDetails => 'Detail teknis';

  @override
  String get reporterLabel => 'Pelapor';

  @override
  String get emailLabel => 'Email';

  @override
  String get aiPredictionLabel => 'Prediksi AI';

  @override
  String get aiConfidenceLabel => 'Skor model AI';

  @override
  String get createdLabel => 'Dibuat';

  @override
  String get updatedLabel => 'Diperbarui';

  @override
  String aiOriginallySuggested(String instansi, String confidence) {
    return 'AI semula menyarankan $instansi ($confidence)';
  }

  @override
  String get reportNotFound => 'Laporan tidak ditemukan';

  @override
  String get reportNotFoundHint =>
      'Laporan ini mungkin sudah dihapus atau tidak tersedia.';

  @override
  String get unableToLoad => 'Tidak dapat memuat laporan';

  @override
  String get myReportsTitle => 'Laporan Saya';

  @override
  String get myReportsSubtitle =>
      'Setiap kiriman, status, dan lokasi dalam satu tempat.';

  @override
  String get noReports => 'Belum ada laporan';

  @override
  String get noReportsHint =>
      'Tap tombol Lapor untuk mulai menambahkan riwayat.';

  @override
  String get filterAll => 'Semua';

  @override
  String noReportsForFilter(String status) {
    return 'Tidak ada laporan $status';
  }

  @override
  String get tryDifferentFilter =>
      'Tidak ada yang cocok dengan filter ini. Coba status lain.';

  @override
  String get confidenceHigh => 'Skor model ≥ 70% (belum terkalibrasi)';

  @override
  String get confidenceMedium => 'Skor model 45–70% (belum terkalibrasi)';

  @override
  String get confidenceLow => 'Skor model < 45% (belum terkalibrasi)';

  @override
  String get changeAgency => 'Ganti kategori';

  @override
  String aiSuggestedAgency(String instansi) {
    return 'Saran kategori model: $instansi';
  }

  @override
  String get aiTopPick => 'Kandidat skor teratas';

  @override
  String get runnerUp => 'Alternatif';

  @override
  String get needsAction => 'Perlu tindakan';

  @override
  String get modVerify => 'Verifikasi';

  @override
  String get modInProgress => 'Mulai proses';

  @override
  String get modResolved => 'Tandai selesai';

  @override
  String get modReject => 'Tolak';

  @override
  String get modRecategorizeAndRetriage => 'Ubah kategori & triase ulang';

  @override
  String get modUpdated => 'Laporan diperbarui';

  @override
  String modActionFailed(String error) {
    return 'Tindakan gagal: $error';
  }

  @override
  String get statusSubmitted => 'Terkirim';

  @override
  String get statusVerified => 'Terverifikasi';

  @override
  String get statusInProgress => 'Diproses';

  @override
  String get statusResolved => 'Selesai';

  @override
  String get statusRejected => 'Ditolak';
}
