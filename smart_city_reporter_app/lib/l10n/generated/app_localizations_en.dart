// ignore: unused_import
import 'package:intl/intl.dart' as intl;
import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for English (`en`).
class AppLocalizationsEn extends AppLocalizations {
  AppLocalizationsEn([String locale = 'en']) : super(locale);

  @override
  String get appTitle => 'SmartCityApps';

  @override
  String get languageIndonesian => 'Indonesian';

  @override
  String get languageEnglish => 'English';

  @override
  String get greetingFallback => 'Welcome';

  @override
  String greetingNamed(String name) {
    return 'Hi, $name';
  }

  @override
  String get overviewSection => 'Overview';

  @override
  String get nearbyReportsSection => 'Nearby reports';

  @override
  String get recentSubmissionsSection => 'Recent submissions';

  @override
  String get seeAll => 'See all';

  @override
  String get openMap => 'Open map';

  @override
  String get noReportsYet => 'No reports yet';

  @override
  String get noReportsYetHint =>
      'Tap the Report button to create your first city report.';

  @override
  String get reportFab => 'Report';

  @override
  String get settingsTitle => 'Settings';

  @override
  String get settingsLanguage => 'Language';

  @override
  String get settingsLanguageHint => 'Interface language for the app.';

  @override
  String get settingsAutoLocation => 'Auto-capture current location';

  @override
  String get settingsAutoLocationHint =>
      'Prefill GPS when starting a new report.';

  @override
  String get settingsShowResolved => 'Show resolved reports on map';

  @override
  String get settingsShowResolvedHint =>
      'Keep completed reports visible on the map overview.';

  @override
  String get settingsNotifyUpdates => 'Notify me on status updates';

  @override
  String get settingsNotifyUpdatesHint =>
      'Prepare the app for moderation and resolution notifications.';

  @override
  String get createReportTitle => 'Create Report';

  @override
  String get addPhoto => 'Add a photo';

  @override
  String get addPhotoHint => 'Capture live or upload an existing image.';

  @override
  String get noPhotoYet => 'No photo yet';

  @override
  String get tapAddPhoto => 'Tap Camera or Gallery below';

  @override
  String get camera => 'Camera';

  @override
  String get gallery => 'Gallery';

  @override
  String get locationStep => 'Location';

  @override
  String get locationHint =>
      'We use GPS for accuracy. You can fine-tune it on the next screen.';

  @override
  String get noLocationYet => 'No location captured yet.';

  @override
  String get useCurrentLocation => 'Use current location';

  @override
  String get refreshLocation => 'Refresh location';

  @override
  String get shortDescription => 'Short description';

  @override
  String get shortDescriptionHint =>
      'Explain what is happening in one or two sentences.';

  @override
  String get descriptionPlaceholder =>
      'Example: \"Large pothole on the left lane of Jl. Sudirman, near the traffic light.\"';

  @override
  String get descriptionLanguageHint =>
      'Indonesian or English. Specific details (location, size, impact) help the AI pick the right agency.';

  @override
  String get runAiClassification => 'Run AI classification';

  @override
  String get addPhotoFirst => 'Add a photo first';

  @override
  String get addDescriptionFirst => 'Add a description (min. 10 characters)';

  @override
  String get descriptionMinError =>
      'Description must be at least 10 characters — the multimodal model reads both image and text.';

  @override
  String get selectPhotoFirst => 'Select a report photo first.';

  @override
  String get reviewTitle => 'Review AI Result';

  @override
  String get directedTo => 'Report category';

  @override
  String confidence(String percent) {
    return 'Model score $percent';
  }

  @override
  String get aiUncertain => 'This report requires human review';

  @override
  String get aiUncertainHint =>
      'Check the photo, description, category, and review reasons before submitting.';

  @override
  String get topCandidates => 'Top class scores';

  @override
  String get instansiPickerHint => 'Choose report category';

  @override
  String get instansiPickerSubhint =>
      'The default follows the model recommendation. Change it when the category does not fit the report.';

  @override
  String get confirmLocation => 'Confirm location';

  @override
  String get confirmLocationHint =>
      'Tap the map or drag the blue pin for precision.';

  @override
  String get tapMapHint => 'Tap the map or use your GPS location.';

  @override
  String get descriptionSection => 'Description';

  @override
  String get descriptionSectionHint =>
      'You can still refine the description before saving.';

  @override
  String get descriptionFieldHint => 'Add useful context for responders.';

  @override
  String get submitReport => 'Submit report';

  @override
  String get submitting => 'Submitting…';

  @override
  String get almostThere => 'Almost there';

  @override
  String get checklistPhoto => 'Photo attached';

  @override
  String get checklistInstansi => 'Category confirmed';

  @override
  String get checklistLocation => 'Location confirmed';

  @override
  String get checklistDescription => 'Description added';

  @override
  String get reportSubmitted => 'Report submitted';

  @override
  String get noReviewYet => 'Nothing to review yet';

  @override
  String get noReviewYetHint =>
      'Pick a photo, write a description, then run AI classification.';

  @override
  String get backToForm => 'Back to report form';

  @override
  String get detailTitle => 'Report Detail';

  @override
  String get statusTimeline => 'Report status';

  @override
  String get technicalDetails => 'Technical details';

  @override
  String get reporterLabel => 'Reporter';

  @override
  String get emailLabel => 'Email';

  @override
  String get aiPredictionLabel => 'AI prediction';

  @override
  String get aiConfidenceLabel => 'AI model score';

  @override
  String get createdLabel => 'Created';

  @override
  String get updatedLabel => 'Updated';

  @override
  String aiOriginallySuggested(String instansi, String confidence) {
    return 'AI originally suggested $instansi ($confidence)';
  }

  @override
  String get reportNotFound => 'Report not found';

  @override
  String get reportNotFoundHint =>
      'This report may have been removed or is no longer available.';

  @override
  String get unableToLoad => 'Unable to load report';

  @override
  String get myReportsTitle => 'My Reports';

  @override
  String get myReportsSubtitle =>
      'Every submission, status, and location in one place.';

  @override
  String get noReports => 'No reports yet';

  @override
  String get noReportsHint =>
      'Tap the Report button to start building your history.';

  @override
  String get filterAll => 'All';

  @override
  String noReportsForFilter(String status) {
    return 'No $status reports';
  }

  @override
  String get tryDifferentFilter =>
      'Nothing matches this filter yet. Try a different status.';

  @override
  String get confidenceHigh => 'Model score ≥ 70% (uncalibrated)';

  @override
  String get confidenceMedium => 'Model score 45–70% (uncalibrated)';

  @override
  String get confidenceLow => 'Model score < 45% (uncalibrated)';

  @override
  String get changeAgency => 'Change category';

  @override
  String aiSuggestedAgency(String instansi) {
    return 'Model category suggestion: $instansi';
  }

  @override
  String get aiTopPick => 'Top-score candidate';

  @override
  String get runnerUp => 'Runner-up';

  @override
  String get needsAction => 'Needs action';

  @override
  String get modVerify => 'Verify';

  @override
  String get modInProgress => 'Start progress';

  @override
  String get modResolved => 'Mark resolved';

  @override
  String get modReject => 'Reject';

  @override
  String get modRecategorizeAndRetriage => 'Recategorize & re-triage';

  @override
  String get modUpdated => 'Report updated';

  @override
  String modActionFailed(String error) {
    return 'Action failed: $error';
  }

  @override
  String get statusSubmitted => 'Submitted';

  @override
  String get statusVerified => 'Verified';

  @override
  String get statusInProgress => 'In Progress';

  @override
  String get statusResolved => 'Resolved';

  @override
  String get statusRejected => 'Rejected';
}
