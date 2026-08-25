import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:latlong2/latlong.dart';

import '../../app/theme/app_theme.dart';
import '../../core/widgets/report_map_view.dart';
import '../../core/widgets/smart_city_ui.dart';
import '../settings/settings_controller.dart';
import 'create_report_controller.dart';
import 'report_models.dart';

class MapViewScreen extends ConsumerStatefulWidget {
  const MapViewScreen({super.key});

  @override
  ConsumerState<MapViewScreen> createState() => _MapViewScreenState();
}

class _MapViewScreenState extends ConsumerState<MapViewScreen> {
  ReportStatus? _statusFilter;

  List<CityReport> _applyFilters(List<CityReport> reports, bool showResolved) {
    var filtered = reports;
    if (!showResolved) {
      filtered = filtered
          .where((r) => r.status != ReportStatus.resolved)
          .toList();
    }
    if (_statusFilter != null) {
      filtered = filtered.where((r) => r.status == _statusFilter).toList();
    }
    return filtered;
  }

  @override
  Widget build(BuildContext context) {
    final reportsAsync = ref.watch(publicReportsProvider);
    final settings = ref.watch(settingsControllerProvider);
    final palette = context.palette;

    return Scaffold(
      backgroundColor: palette.surface,
      body: Stack(
        children: [
          Positioned.fill(
            child: reportsAsync.when(
              data: (reports) {
                final filtered = _applyFilters(
                  reports,
                  settings.showResolvedReports,
                );
                final center = filtered.isNotEmpty
                    ? LatLng(filtered.first.latitude, filtered.first.longitude)
                    : const LatLng(-6.2297, 106.7597);
                return ReportMapView(
                  center: center,
                  expand: true,
                  reports: filtered,
                  onReportTap: (r) => context.push('/report/${r.id}'),
                );
              },
              loading: () => const Center(child: CircularProgressIndicator()),
              error: (error, _) => Center(
                child: Padding(
                  padding: const EdgeInsets.all(24),
                  child: EmptyStateCard(
                    icon: Icons.error_outline_rounded,
                    title: 'Map could not load',
                    message: error.toString(),
                  ),
                ),
              ),
            ),
          ),
          _TopBar(
            palette: palette,
            selected: _statusFilter,
            onChanged: (status) => setState(() => _statusFilter = status),
          ),
          DraggableScrollableSheet(
            initialChildSize: 0.28,
            minChildSize: 0.14,
            maxChildSize: 0.85,
            snap: true,
            snapSizes: const [0.28, 0.6],
            builder: (context, scrollController) {
              return _ResultsSheet(
                scrollController: scrollController,
                reportsAsync: reportsAsync,
                applyFilters: (reports) =>
                    _applyFilters(reports, settings.showResolvedReports),
                statusFilter: _statusFilter,
              );
            },
          ),
        ],
      ),
    );
  }
}

class _TopBar extends StatelessWidget {
  const _TopBar({
    required this.palette,
    required this.selected,
    required this.onChanged,
  });

  final AppPalette palette;
  final ReportStatus? selected;
  final ValueChanged<ReportStatus?> onChanged;

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
              decoration: BoxDecoration(
                color: palette.surfaceElevated,
                borderRadius: BorderRadius.circular(18),
                boxShadow: const [
                  BoxShadow(
                    color: Color(0x140F172A),
                    blurRadius: 20,
                    offset: Offset(0, 6),
                  ),
                ],
              ),
              child: Row(
                children: [
                  Container(
                    padding: const EdgeInsets.all(8),
                    decoration: BoxDecoration(
                      color: palette.accentCyan.withValues(alpha: 0.12),
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: Icon(
                      Icons.map_rounded,
                      color: palette.accentCyan,
                      size: 20,
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'City reports',
                          style: Theme.of(context).textTheme.titleMedium,
                        ),
                        Text(
                          'Nearby incidents',
                          style: Theme.of(context).textTheme.bodySmall,
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 12),
            SizedBox(
              height: 40,
              child: _StatusFilterStrip(
                selected: selected,
                onChanged: onChanged,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _StatusFilterStrip extends StatelessWidget {
  const _StatusFilterStrip({required this.selected, required this.onChanged});

  final ReportStatus? selected;
  final ValueChanged<ReportStatus?> onChanged;

  @override
  Widget build(BuildContext context) {
    final items = <({ReportStatus? status, String label})>[
      (status: null, label: 'All'),
      ...ReportStatus.values.map((s) => (status: s, label: s.label)),
    ];

    return ListView.separated(
      scrollDirection: Axis.horizontal,
      padding: const EdgeInsets.symmetric(horizontal: 2),
      itemBuilder: (context, index) {
        final item = items[index];
        return _StatusPill(
          label: item.label,
          selected: item.status == selected,
          onTap: () => onChanged(item.status),
        );
      },
      separatorBuilder: (_, _) => const SizedBox(width: 8),
      itemCount: items.length,
    );
  }
}

class _StatusPill extends StatelessWidget {
  const _StatusPill({
    required this.label,
    required this.selected,
    required this.onTap,
  });

  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(999),
        onTap: onTap,
        child: Ink(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
          decoration: BoxDecoration(
            color: selected ? palette.accentCyan : palette.surfaceElevated,
            borderRadius: BorderRadius.circular(999),
            border: Border.all(
              color: selected ? palette.accentCyan : palette.border,
            ),
            boxShadow: selected
                ? null
                : const [
                    BoxShadow(
                      color: Color(0x0F0F172A),
                      blurRadius: 10,
                      offset: Offset(0, 2),
                    ),
                  ],
          ),
          child: Text(
            label,
            style: Theme.of(context).textTheme.labelLarge?.copyWith(
              color: selected ? Colors.white : palette.ink,
              fontWeight: FontWeight.w600,
            ),
          ),
        ),
      ),
    );
  }
}

class _ResultsSheet extends StatelessWidget {
  const _ResultsSheet({
    required this.scrollController,
    required this.reportsAsync,
    required this.applyFilters,
    required this.statusFilter,
  });

  final ScrollController scrollController;
  final AsyncValue<List<CityReport>> reportsAsync;
  final List<CityReport> Function(List<CityReport>) applyFilters;
  final ReportStatus? statusFilter;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    return Container(
      decoration: BoxDecoration(
        color: palette.surfaceElevated,
        borderRadius: const BorderRadius.vertical(top: Radius.circular(28)),
        boxShadow: const [
          BoxShadow(
            color: Color(0x1A0F172A),
            blurRadius: 30,
            offset: Offset(0, -8),
          ),
        ],
      ),
      child: Column(
        children: [
          Padding(
            padding: const EdgeInsets.only(top: 10, bottom: 6),
            child: Container(
              width: 44,
              height: 4,
              decoration: BoxDecoration(
                color: palette.border,
                borderRadius: BorderRadius.circular(999),
              ),
            ),
          ),
          Expanded(
            child: reportsAsync.when(
              data: (reports) {
                final filtered = applyFilters(reports);
                return _SheetContent(
                  scrollController: scrollController,
                  reports: filtered,
                  statusFilter: statusFilter,
                );
              },
              loading: () => const Center(child: CircularProgressIndicator()),
              error: (error, _) => ListView(
                controller: scrollController,
                padding: const EdgeInsets.all(20),
                children: [
                  EmptyStateCard(
                    icon: Icons.cloud_off_rounded,
                    title: 'Unable to load reports',
                    message: error.toString(),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _SheetContent extends StatelessWidget {
  const _SheetContent({
    required this.scrollController,
    required this.reports,
    required this.statusFilter,
  });

  final ScrollController scrollController;
  final List<CityReport> reports;
  final ReportStatus? statusFilter;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    final text = Theme.of(context).textTheme;

    if (reports.isEmpty) {
      return ListView(
        controller: scrollController,
        padding: const EdgeInsets.fromLTRB(20, 8, 20, 40),
        children: const [
          EmptyStateCard(
            icon: Icons.search_off_rounded,
            title: 'No reports for this filter',
            message:
                'Try another status or be the first to report in this area.',
          ),
        ],
      );
    }

    return ListView.separated(
      controller: scrollController,
      padding: const EdgeInsets.fromLTRB(20, 4, 20, 120),
      itemCount: reports.length + 1,
      separatorBuilder: (_, _) => const SizedBox(height: 10),
      itemBuilder: (context, index) {
        if (index == 0) {
          return Padding(
            padding: const EdgeInsets.only(bottom: 4),
            child: Row(
              children: [
                Icon(Icons.place_rounded, size: 18, color: palette.accentCyan),
                const SizedBox(width: 6),
                Text(
                  '${reports.length} ${reports.length == 1 ? 'report' : 'reports'}',
                  style: text.titleMedium,
                ),
                const SizedBox(width: 6),
                Text(
                  statusFilter == null
                      ? '· all statuses'
                      : '· ${statusFilter!.label.toLowerCase()}',
                  style: text.bodySmall,
                ),
              ],
            ),
          );
        }
        final report = reports[index - 1];
        return ReportListTileCard(
          report: report,
          onTap: () => context.push('/report/${report.id}'),
        );
      },
    );
  }
}
