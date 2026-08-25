import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:latlong2/latlong.dart';

import '../../app/theme/app_theme.dart';
import '../../core/l10n/l10n.dart';
import '../../core/widgets/report_map_view.dart';
import '../../core/widgets/smart_city_ui.dart';
import '../auth/auth_repository.dart';
import '../reports/create_report_controller.dart';
import '../reports/report_models.dart';

class HomeDashboardScreen extends ConsumerWidget {
  const HomeDashboardScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final profileAsync = ref.watch(currentUserProfileProvider);
    final reportsAsync = ref.watch(myReportsProvider);
    final publicReportsAsync = ref.watch(publicReportsProvider);
    final palette = context.palette;
    final l10n = context.l10n;

    return AppPage(
      onRefresh: () async {
        ref.invalidate(currentUserProfileProvider);
        ref.invalidate(myReportsProvider);
        ref.invalidate(publicReportsProvider);
      },
      children: [
        AsyncView(
          value: profileAsync,
          loading: const _Greeting(name: null, photoUrl: null),
          data: (profile) => _Greeting(
            name: profile?.fullName.split(' ').first,
            photoUrl: profile?.profilePhotoUrl,
            fallbackText: profile?.fullName ?? 'SC',
          ),
        ),
        const SizedBox(height: 24),
        _SectionLabel(
          title: l10n.overviewSection,
          actionText: l10n.seeAll,
          onAction: () => context.go('/my-reports'),
        ),
        const SizedBox(height: 12),
        AsyncView(
          value: reportsAsync,
          data: (reports) => _MetricsGrid(reports: reports, palette: palette),
        ),
        const SizedBox(height: 24),
        _SectionLabel(
          title: l10n.nearbyReportsSection,
          actionText: l10n.openMap,
          onAction: () => context.go('/map'),
        ),
        const SizedBox(height: 12),
        AsyncView(
          value: publicReportsAsync,
          loading: const SizedBox(
            height: 220,
            child: Center(child: CircularProgressIndicator()),
          ),
          data: (reports) {
            final center = reports.isNotEmpty
                ? LatLng(reports.first.latitude, reports.first.longitude)
                : const LatLng(-6.2297, 106.7597);
            return ReportMapView(
              center: center,
              height: 220,
              reports: reports.take(12).toList(),
              onReportTap: (r) => context.push('/report/${r.id}'),
            );
          },
        ),
        const SizedBox(height: 24),
        _SectionLabel(title: l10n.recentSubmissionsSection),
        const SizedBox(height: 12),
        AsyncView(
          value: reportsAsync,
          data: (reports) {
            if (reports.isEmpty) {
              return EmptyStateCard(
                icon: Icons.mark_unread_chat_alt_outlined,
                title: l10n.noReportsYet,
                message: l10n.noReportsYetHint,
              );
            }
            return Column(
              children: [
                for (final report in reports.take(3))
                  Padding(
                    padding: const EdgeInsets.only(bottom: 8),
                    child: ReportListTileCard(
                      report: report,
                      onTap: () => context.push('/report/${report.id}'),
                    ),
                  ),
              ],
            );
          },
        ),
      ],
    );
  }
}

class _Greeting extends StatelessWidget {
  const _Greeting({
    required this.name,
    required this.photoUrl,
    this.fallbackText = 'SC',
  });

  final String? name;
  final String? photoUrl;
  final String fallbackText;

  @override
  Widget build(BuildContext context) {
    final l10n = context.l10n;
    final palette = context.palette;
    final headline = name == null || name!.isEmpty
        ? l10n.greetingFallback
        : l10n.greetingNamed(name!);

    return Row(
      crossAxisAlignment: CrossAxisAlignment.center,
      children: [
        Expanded(
          child: Text(
            headline,
            style: GoogleFonts.plusJakartaSans(
              fontSize: 28,
              fontWeight: FontWeight.w700,
              color: palette.ink,
              letterSpacing: -0.3,
              height: 1.15,
            ),
          ),
        ),
        const SizedBox(width: 12),
        ProfileAvatar(
          imageUrl: photoUrl,
          fallbackText: fallbackText,
          radius: 20,
        ),
      ],
    );
  }
}

class _SectionLabel extends StatelessWidget {
  const _SectionLabel({required this.title, this.actionText, this.onAction});

  final String title;
  final String? actionText;
  final VoidCallback? onAction;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    return Row(
      children: [
        Expanded(
          child: Text(title, style: Theme.of(context).textTheme.titleLarge),
        ),
        if (actionText != null && onAction != null)
          TextButton(
            onPressed: onAction,
            style: TextButton.styleFrom(
              foregroundColor: palette.inkMuted,
              padding: const EdgeInsets.symmetric(horizontal: 8),
              minimumSize: const Size(0, 32),
              tapTargetSize: MaterialTapTargetSize.shrinkWrap,
              textStyle: Theme.of(context).textTheme.labelLarge?.copyWith(
                fontSize: 14,
                fontWeight: FontWeight.w500,
              ),
            ),
            child: Text('$actionText ›'),
          ),
      ],
    );
  }
}

/// Borderless horizontal strip of 4 metrics. No card backgrounds, no borders,
/// no shadows — the numbers themselves carry the visual weight.
class _MetricsGrid extends StatelessWidget {
  const _MetricsGrid({required this.reports, required this.palette});

  final List<CityReport> reports;
  final AppPalette palette;

  int _count(ReportStatus status) =>
      reports.where((r) => r.status == status).length;

  @override
  Widget build(BuildContext context) {
    final l10n = context.l10n;
    final cells = <_MetricCellData>[
      _MetricCellData(
        label: l10n.statusSubmitted,
        value: '${reports.length}',
        color: palette.accentBlue,
        icon: Icons.receipt_long_rounded,
      ),
      _MetricCellData(
        label: l10n.statusVerified,
        value: '${_count(ReportStatus.verified)}',
        color: palette.success,
        icon: Icons.verified_rounded,
      ),
      _MetricCellData(
        label: l10n.statusInProgress,
        value: '${_count(ReportStatus.inProgress)}',
        color: palette.warning,
        icon: Icons.construction_rounded,
      ),
      _MetricCellData(
        label: l10n.statusResolved,
        value: '${_count(ReportStatus.resolved)}',
        color: palette.accentTeal,
        icon: Icons.task_alt_rounded,
      ),
    ];

    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [for (final cell in cells) _MetricCell(data: cell)],
    );
  }
}

class _MetricCellData {
  const _MetricCellData({
    required this.label,
    required this.value,
    required this.color,
    required this.icon,
  });

  final String label;
  final String value;
  final Color color;
  final IconData icon;
}

class _MetricCell extends StatelessWidget {
  const _MetricCell({required this.data});

  final _MetricCellData data;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final palette = context.palette;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Icon(data.icon, color: data.color, size: 18),
        const SizedBox(height: 10),
        Text(
          data.value,
          style: GoogleFonts.plusJakartaSans(
            fontSize: 26,
            fontWeight: FontWeight.w700,
            color: palette.ink,
            letterSpacing: -0.5,
            height: 1.1,
          ),
        ),
        const SizedBox(height: 2),
        Text(
          data.label,
          style: text.bodySmall?.copyWith(
            color: palette.inkMuted,
            fontSize: 12,
            fontWeight: FontWeight.w500,
          ),
        ),
      ],
    );
  }
}
