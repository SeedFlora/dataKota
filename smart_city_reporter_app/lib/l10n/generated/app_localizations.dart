import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:intl/intl.dart' as intl;

import 'app_localizations_en.dart';
import 'app_localizations_id.dart';

// ignore_for_file: type=lint

/// Callers can lookup localized strings with an instance of AppLocalizations
/// returned by `AppLocalizations.of(context)`.
///
/// Applications need to include `AppLocalizations.delegate()` in their app's
/// `localizationDelegates` list, and the locales they support in the app's
/// `supportedLocales` list. For example:
///
/// ```dart
/// import 'generated/app_localizations.dart';
///
/// return MaterialApp(
///   localizationsDelegates: AppLocalizations.localizationsDelegates,
///   supportedLocales: AppLocalizations.supportedLocales,
///   home: MyApplicationHome(),
/// );
/// ```
///
/// ## Update pubspec.yaml
///
/// Please make sure to update your pubspec.yaml to include the following
/// packages:
///
/// ```yaml
/// dependencies:
///   # Internationalization support.
///   flutter_localizations:
///     sdk: flutter
///   intl: any # Use the pinned version from flutter_localizations
///
///   # Rest of dependencies
/// ```
///
/// ## iOS Applications
///
/// iOS applications define key application metadata, including supported
/// locales, in an Info.plist file that is built into the application bundle.
/// To configure the locales supported by your app, you’ll need to edit this
/// file.
///
/// First, open your project’s ios/Runner.xcworkspace Xcode workspace file.
/// Then, in the Project Navigator, open the Info.plist file under the Runner
/// project’s Runner folder.
///
/// Next, select the Information Property List item, select Add Item from the
/// Editor menu, then select Localizations from the pop-up menu.
///
/// Select and expand the newly-created Localizations item then, for each
/// locale your application supports, add a new item and select the locale
/// you wish to add from the pop-up menu in the Value field. This list should
/// be consistent with the languages listed in the AppLocalizations.supportedLocales
/// property.
abstract class AppLocalizations {
  AppLocalizations(String locale)
    : localeName = intl.Intl.canonicalizedLocale(locale.toString());

  final String localeName;

  static AppLocalizations? of(BuildContext context) {
    return Localizations.of<AppLocalizations>(context, AppLocalizations);
  }

  static const LocalizationsDelegate<AppLocalizations> delegate =
      _AppLocalizationsDelegate();

  /// A list of this localizations delegate along with the default localizations
  /// delegates.
  ///
  /// Returns a list of localizations delegates containing this delegate along with
  /// GlobalMaterialLocalizations.delegate, GlobalCupertinoLocalizations.delegate,
  /// and GlobalWidgetsLocalizations.delegate.
  ///
  /// Additional delegates can be added by appending to this list in
  /// MaterialApp. This list does not have to be used at all if a custom list
  /// of delegates is preferred or required.
  static const List<LocalizationsDelegate<dynamic>> localizationsDelegates =
      <LocalizationsDelegate<dynamic>>[
        delegate,
        GlobalMaterialLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
      ];

  /// A list of this localizations delegate's supported locales.
  static const List<Locale> supportedLocales = <Locale>[
    Locale('en'),
    Locale('id'),
  ];

  /// No description provided for @appTitle.
  ///
  /// In id, this message translates to:
  /// **'SmartCityApps'**
  String get appTitle;

  /// No description provided for @languageIndonesian.
  ///
  /// In id, this message translates to:
  /// **'Indonesia'**
  String get languageIndonesian;

  /// No description provided for @languageEnglish.
  ///
  /// In id, this message translates to:
  /// **'English'**
  String get languageEnglish;

  /// No description provided for @greetingFallback.
  ///
  /// In id, this message translates to:
  /// **'Selamat datang'**
  String get greetingFallback;

  /// No description provided for @greetingNamed.
  ///
  /// In id, this message translates to:
  /// **'Hi, {name}'**
  String greetingNamed(String name);

  /// No description provided for @overviewSection.
  ///
  /// In id, this message translates to:
  /// **'Ringkasan'**
  String get overviewSection;

  /// No description provided for @nearbyReportsSection.
  ///
  /// In id, this message translates to:
  /// **'Laporan terdekat'**
  String get nearbyReportsSection;

  /// No description provided for @recentSubmissionsSection.
  ///
  /// In id, this message translates to:
  /// **'Laporan terbaru'**
  String get recentSubmissionsSection;

  /// No description provided for @seeAll.
  ///
  /// In id, this message translates to:
  /// **'Lihat semua'**
  String get seeAll;

  /// No description provided for @openMap.
  ///
  /// In id, this message translates to:
  /// **'Buka peta'**
  String get openMap;

  /// No description provided for @noReportsYet.
  ///
  /// In id, this message translates to:
  /// **'Belum ada laporan'**
  String get noReportsYet;

  /// No description provided for @noReportsYetHint.
  ///
  /// In id, this message translates to:
  /// **'Tap tombol Lapor untuk membuat laporan kota pertama Anda.'**
  String get noReportsYetHint;

  /// No description provided for @reportFab.
  ///
  /// In id, this message translates to:
  /// **'Lapor'**
  String get reportFab;

  /// No description provided for @settingsTitle.
  ///
  /// In id, this message translates to:
  /// **'Pengaturan'**
  String get settingsTitle;

  /// No description provided for @settingsLanguage.
  ///
  /// In id, this message translates to:
  /// **'Bahasa'**
  String get settingsLanguage;

  /// No description provided for @settingsLanguageHint.
  ///
  /// In id, this message translates to:
  /// **'Bahasa antarmuka aplikasi.'**
  String get settingsLanguageHint;

  /// No description provided for @settingsAutoLocation.
  ///
  /// In id, this message translates to:
  /// **'Auto-isi lokasi saat ini'**
  String get settingsAutoLocation;

  /// No description provided for @settingsAutoLocationHint.
  ///
  /// In id, this message translates to:
  /// **'Ambil GPS otomatis saat membuat laporan baru.'**
  String get settingsAutoLocationHint;

  /// No description provided for @settingsShowResolved.
  ///
  /// In id, this message translates to:
  /// **'Tampilkan laporan selesai di peta'**
  String get settingsShowResolved;

  /// No description provided for @settingsShowResolvedHint.
  ///
  /// In id, this message translates to:
  /// **'Pertahankan laporan yang sudah selesai tetap terlihat di peta.'**
  String get settingsShowResolvedHint;

  /// No description provided for @settingsNotifyUpdates.
  ///
  /// In id, this message translates to:
  /// **'Beri tahu saya saat status berubah'**
  String get settingsNotifyUpdates;

  /// No description provided for @settingsNotifyUpdatesHint.
  ///
  /// In id, this message translates to:
  /// **'Siapkan aplikasi untuk notifikasi moderasi dan resolusi.'**
  String get settingsNotifyUpdatesHint;

  /// No description provided for @createReportTitle.
  ///
  /// In id, this message translates to:
  /// **'Buat Laporan'**
  String get createReportTitle;

  /// No description provided for @addPhoto.
  ///
  /// In id, this message translates to:
  /// **'Tambahkan foto'**
  String get addPhoto;

  /// No description provided for @addPhotoHint.
  ///
  /// In id, this message translates to:
  /// **'Ambil foto langsung atau pilih dari galeri.'**
  String get addPhotoHint;

  /// No description provided for @noPhotoYet.
  ///
  /// In id, this message translates to:
  /// **'Belum ada foto'**
  String get noPhotoYet;

  /// No description provided for @tapAddPhoto.
  ///
  /// In id, this message translates to:
  /// **'Tap Kamera atau Galeri di bawah'**
  String get tapAddPhoto;

  /// No description provided for @camera.
  ///
  /// In id, this message translates to:
  /// **'Kamera'**
  String get camera;

  /// No description provided for @gallery.
  ///
  /// In id, this message translates to:
  /// **'Galeri'**
  String get gallery;

  /// No description provided for @locationStep.
  ///
  /// In id, this message translates to:
  /// **'Lokasi'**
  String get locationStep;

  /// No description provided for @locationHint.
  ///
  /// In id, this message translates to:
  /// **'GPS untuk akurasi. Bisa disesuaikan di layar berikut.'**
  String get locationHint;

  /// No description provided for @noLocationYet.
  ///
  /// In id, this message translates to:
  /// **'Lokasi belum diambil.'**
  String get noLocationYet;

  /// No description provided for @useCurrentLocation.
  ///
  /// In id, this message translates to:
  /// **'Gunakan lokasi saat ini'**
  String get useCurrentLocation;

  /// No description provided for @refreshLocation.
  ///
  /// In id, this message translates to:
  /// **'Refresh lokasi'**
  String get refreshLocation;

  /// No description provided for @shortDescription.
  ///
  /// In id, this message translates to:
  /// **'Deskripsi singkat'**
  String get shortDescription;

  /// No description provided for @shortDescriptionHint.
  ///
  /// In id, this message translates to:
  /// **'Jelaskan apa yang terjadi dalam satu-dua kalimat.'**
  String get shortDescriptionHint;

  /// No description provided for @descriptionPlaceholder.
  ///
  /// In id, this message translates to:
  /// **'Contoh: \"Lubang besar di lajur kiri Jl. Sudirman, dekat lampu merah.\"'**
  String get descriptionPlaceholder;

  /// No description provided for @descriptionLanguageHint.
  ///
  /// In id, this message translates to:
  /// **'Bahasa Indonesia atau English. Detail spesifik (lokasi, ukuran, dampak) bantu model memilih instansi yang tepat.'**
  String get descriptionLanguageHint;

  /// No description provided for @runAiClassification.
  ///
  /// In id, this message translates to:
  /// **'Klasifikasi dengan AI'**
  String get runAiClassification;

  /// No description provided for @addPhotoFirst.
  ///
  /// In id, this message translates to:
  /// **'Tambahkan foto dulu'**
  String get addPhotoFirst;

  /// No description provided for @addDescriptionFirst.
  ///
  /// In id, this message translates to:
  /// **'Tambahkan deskripsi (min. 10 karakter)'**
  String get addDescriptionFirst;

  /// No description provided for @descriptionMinError.
  ///
  /// In id, this message translates to:
  /// **'Tulis deskripsi minimal 10 karakter — model multimodal membaca gambar dan teks.'**
  String get descriptionMinError;

  /// No description provided for @selectPhotoFirst.
  ///
  /// In id, this message translates to:
  /// **'Pilih foto laporan terlebih dahulu.'**
  String get selectPhotoFirst;

  /// No description provided for @reviewTitle.
  ///
  /// In id, this message translates to:
  /// **'Review Hasil AI'**
  String get reviewTitle;

  /// No description provided for @directedTo.
  ///
  /// In id, this message translates to:
  /// **'Kategori laporan'**
  String get directedTo;

  /// No description provided for @confidence.
  ///
  /// In id, this message translates to:
  /// **'Skor model {percent}'**
  String confidence(String percent);

  /// No description provided for @aiUncertain.
  ///
  /// In id, this message translates to:
  /// **'Laporan memerlukan tinjauan manual'**
  String get aiUncertain;

  /// No description provided for @aiUncertainHint.
  ///
  /// In id, this message translates to:
  /// **'Periksa foto, deskripsi, kategori, dan alasan tinjauan sebelum mengirim.'**
  String get aiUncertainHint;

  /// No description provided for @topCandidates.
  ///
  /// In id, this message translates to:
  /// **'Skor kelas teratas'**
  String get topCandidates;

  /// No description provided for @instansiPickerHint.
  ///
  /// In id, this message translates to:
  /// **'Pilih kategori laporan'**
  String get instansiPickerHint;

  /// No description provided for @instansiPickerSubhint.
  ///
  /// In id, this message translates to:
  /// **'Default mengikuti rekomendasi model. Ganti bila kategorinya tidak sesuai laporan.'**
  String get instansiPickerSubhint;

  /// No description provided for @confirmLocation.
  ///
  /// In id, this message translates to:
  /// **'Konfirmasi lokasi'**
  String get confirmLocation;

  /// No description provided for @confirmLocationHint.
  ///
  /// In id, this message translates to:
  /// **'Tap peta atau geser pin biru untuk presisi.'**
  String get confirmLocationHint;

  /// No description provided for @tapMapHint.
  ///
  /// In id, this message translates to:
  /// **'Tap peta atau gunakan lokasi GPS Anda.'**
  String get tapMapHint;

  /// No description provided for @descriptionSection.
  ///
  /// In id, this message translates to:
  /// **'Deskripsi'**
  String get descriptionSection;

  /// No description provided for @descriptionSectionHint.
  ///
  /// In id, this message translates to:
  /// **'Anda masih bisa menyempurnakan deskripsi sebelum disimpan.'**
  String get descriptionSectionHint;

  /// No description provided for @descriptionFieldHint.
  ///
  /// In id, this message translates to:
  /// **'Tambahkan konteks bermanfaat untuk petugas.'**
  String get descriptionFieldHint;

  /// No description provided for @submitReport.
  ///
  /// In id, this message translates to:
  /// **'Submit laporan'**
  String get submitReport;

  /// No description provided for @submitting.
  ///
  /// In id, this message translates to:
  /// **'Mengirim…'**
  String get submitting;

  /// No description provided for @almostThere.
  ///
  /// In id, this message translates to:
  /// **'Hampir selesai'**
  String get almostThere;

  /// No description provided for @checklistPhoto.
  ///
  /// In id, this message translates to:
  /// **'Foto terlampir'**
  String get checklistPhoto;

  /// No description provided for @checklistInstansi.
  ///
  /// In id, this message translates to:
  /// **'Kategori terkonfirmasi'**
  String get checklistInstansi;

  /// No description provided for @checklistLocation.
  ///
  /// In id, this message translates to:
  /// **'Lokasi terkonfirmasi'**
  String get checklistLocation;

  /// No description provided for @checklistDescription.
  ///
  /// In id, this message translates to:
  /// **'Deskripsi terisi'**
  String get checklistDescription;

  /// No description provided for @reportSubmitted.
  ///
  /// In id, this message translates to:
  /// **'Laporan terkirim'**
  String get reportSubmitted;

  /// No description provided for @noReviewYet.
  ///
  /// In id, this message translates to:
  /// **'Belum ada hasil untuk direview'**
  String get noReviewYet;

  /// No description provided for @noReviewYetHint.
  ///
  /// In id, this message translates to:
  /// **'Pilih foto, isi deskripsi, lalu jalankan klasifikasi AI.'**
  String get noReviewYetHint;

  /// No description provided for @backToForm.
  ///
  /// In id, this message translates to:
  /// **'Kembali ke form laporan'**
  String get backToForm;

  /// No description provided for @detailTitle.
  ///
  /// In id, this message translates to:
  /// **'Detail Laporan'**
  String get detailTitle;

  /// No description provided for @statusTimeline.
  ///
  /// In id, this message translates to:
  /// **'Status laporan'**
  String get statusTimeline;

  /// No description provided for @technicalDetails.
  ///
  /// In id, this message translates to:
  /// **'Detail teknis'**
  String get technicalDetails;

  /// No description provided for @reporterLabel.
  ///
  /// In id, this message translates to:
  /// **'Pelapor'**
  String get reporterLabel;

  /// No description provided for @emailLabel.
  ///
  /// In id, this message translates to:
  /// **'Email'**
  String get emailLabel;

  /// No description provided for @aiPredictionLabel.
  ///
  /// In id, this message translates to:
  /// **'Prediksi AI'**
  String get aiPredictionLabel;

  /// No description provided for @aiConfidenceLabel.
  ///
  /// In id, this message translates to:
  /// **'Skor model AI'**
  String get aiConfidenceLabel;

  /// No description provided for @createdLabel.
  ///
  /// In id, this message translates to:
  /// **'Dibuat'**
  String get createdLabel;

  /// No description provided for @updatedLabel.
  ///
  /// In id, this message translates to:
  /// **'Diperbarui'**
  String get updatedLabel;

  /// No description provided for @aiOriginallySuggested.
  ///
  /// In id, this message translates to:
  /// **'AI semula menyarankan {instansi} ({confidence})'**
  String aiOriginallySuggested(String instansi, String confidence);

  /// No description provided for @reportNotFound.
  ///
  /// In id, this message translates to:
  /// **'Laporan tidak ditemukan'**
  String get reportNotFound;

  /// No description provided for @reportNotFoundHint.
  ///
  /// In id, this message translates to:
  /// **'Laporan ini mungkin sudah dihapus atau tidak tersedia.'**
  String get reportNotFoundHint;

  /// No description provided for @unableToLoad.
  ///
  /// In id, this message translates to:
  /// **'Tidak dapat memuat laporan'**
  String get unableToLoad;

  /// No description provided for @myReportsTitle.
  ///
  /// In id, this message translates to:
  /// **'Laporan Saya'**
  String get myReportsTitle;

  /// No description provided for @myReportsSubtitle.
  ///
  /// In id, this message translates to:
  /// **'Setiap kiriman, status, dan lokasi dalam satu tempat.'**
  String get myReportsSubtitle;

  /// No description provided for @noReports.
  ///
  /// In id, this message translates to:
  /// **'Belum ada laporan'**
  String get noReports;

  /// No description provided for @noReportsHint.
  ///
  /// In id, this message translates to:
  /// **'Tap tombol Lapor untuk mulai menambahkan riwayat.'**
  String get noReportsHint;

  /// No description provided for @filterAll.
  ///
  /// In id, this message translates to:
  /// **'Semua'**
  String get filterAll;

  /// No description provided for @noReportsForFilter.
  ///
  /// In id, this message translates to:
  /// **'Tidak ada laporan {status}'**
  String noReportsForFilter(String status);

  /// No description provided for @tryDifferentFilter.
  ///
  /// In id, this message translates to:
  /// **'Tidak ada yang cocok dengan filter ini. Coba status lain.'**
  String get tryDifferentFilter;

  /// No description provided for @confidenceHigh.
  ///
  /// In id, this message translates to:
  /// **'Skor model ≥ 70% (belum terkalibrasi)'**
  String get confidenceHigh;

  /// No description provided for @confidenceMedium.
  ///
  /// In id, this message translates to:
  /// **'Skor model 45–70% (belum terkalibrasi)'**
  String get confidenceMedium;

  /// No description provided for @confidenceLow.
  ///
  /// In id, this message translates to:
  /// **'Skor model < 45% (belum terkalibrasi)'**
  String get confidenceLow;

  /// No description provided for @changeAgency.
  ///
  /// In id, this message translates to:
  /// **'Ganti kategori'**
  String get changeAgency;

  /// No description provided for @aiSuggestedAgency.
  ///
  /// In id, this message translates to:
  /// **'Saran kategori model: {instansi}'**
  String aiSuggestedAgency(String instansi);

  /// No description provided for @aiTopPick.
  ///
  /// In id, this message translates to:
  /// **'Kandidat skor teratas'**
  String get aiTopPick;

  /// No description provided for @runnerUp.
  ///
  /// In id, this message translates to:
  /// **'Alternatif'**
  String get runnerUp;

  /// No description provided for @needsAction.
  ///
  /// In id, this message translates to:
  /// **'Perlu tindakan'**
  String get needsAction;

  /// No description provided for @modVerify.
  ///
  /// In id, this message translates to:
  /// **'Verifikasi'**
  String get modVerify;

  /// No description provided for @modInProgress.
  ///
  /// In id, this message translates to:
  /// **'Mulai proses'**
  String get modInProgress;

  /// No description provided for @modResolved.
  ///
  /// In id, this message translates to:
  /// **'Tandai selesai'**
  String get modResolved;

  /// No description provided for @modReject.
  ///
  /// In id, this message translates to:
  /// **'Tolak'**
  String get modReject;

  /// No description provided for @modRecategorizeAndRetriage.
  ///
  /// In id, this message translates to:
  /// **'Ubah kategori & triase ulang'**
  String get modRecategorizeAndRetriage;

  /// No description provided for @modUpdated.
  ///
  /// In id, this message translates to:
  /// **'Laporan diperbarui'**
  String get modUpdated;

  /// No description provided for @modActionFailed.
  ///
  /// In id, this message translates to:
  /// **'Tindakan gagal: {error}'**
  String modActionFailed(String error);

  /// No description provided for @statusSubmitted.
  ///
  /// In id, this message translates to:
  /// **'Terkirim'**
  String get statusSubmitted;

  /// No description provided for @statusVerified.
  ///
  /// In id, this message translates to:
  /// **'Terverifikasi'**
  String get statusVerified;

  /// No description provided for @statusInProgress.
  ///
  /// In id, this message translates to:
  /// **'Diproses'**
  String get statusInProgress;

  /// No description provided for @statusResolved.
  ///
  /// In id, this message translates to:
  /// **'Selesai'**
  String get statusResolved;

  /// No description provided for @statusRejected.
  ///
  /// In id, this message translates to:
  /// **'Ditolak'**
  String get statusRejected;
}

class _AppLocalizationsDelegate
    extends LocalizationsDelegate<AppLocalizations> {
  const _AppLocalizationsDelegate();

  @override
  Future<AppLocalizations> load(Locale locale) {
    return SynchronousFuture<AppLocalizations>(lookupAppLocalizations(locale));
  }

  @override
  bool isSupported(Locale locale) =>
      <String>['en', 'id'].contains(locale.languageCode);

  @override
  bool shouldReload(_AppLocalizationsDelegate old) => false;
}

AppLocalizations lookupAppLocalizations(Locale locale) {
  // Lookup logic when only language code is specified.
  switch (locale.languageCode) {
    case 'en':
      return AppLocalizationsEn();
    case 'id':
      return AppLocalizationsId();
  }

  throw FlutterError(
    'AppLocalizations.delegate failed to load unsupported locale "$locale". This is likely '
    'an issue with the localizations generation tool. Please file an issue '
    'on GitHub with a reproducible sample app and the gen-l10n configuration '
    'that was used.',
  );
}
