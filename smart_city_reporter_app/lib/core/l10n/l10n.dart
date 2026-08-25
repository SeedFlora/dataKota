import 'package:flutter/widgets.dart';

import '../../features/reports/report_models.dart';
import '../../l10n/generated/app_localizations.dart';

export '../../l10n/generated/app_localizations.dart';

extension LocalizedBuildContext on BuildContext {
  AppLocalizations get l10n => AppLocalizations.of(this)!;
}

extension LocalizedReportStatus on ReportStatus {
  String localized(AppLocalizations l) => switch (this) {
    ReportStatus.submitted => l.statusSubmitted,
    ReportStatus.verified => l.statusVerified,
    ReportStatus.inProgress => l.statusInProgress,
    ReportStatus.resolved => l.statusResolved,
    ReportStatus.rejected => l.statusRejected,
  };
}
