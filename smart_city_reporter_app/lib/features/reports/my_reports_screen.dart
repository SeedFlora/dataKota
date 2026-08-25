import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/theme/app_theme.dart';
import '../../core/l10n/l10n.dart';
import '../../core/widgets/smart_city_ui.dart';
import 'create_report_controller.dart';
import 'report_models.dart';

class MyReportsScreen extends ConsumerStatefulWidget {
  const MyReportsScreen({super.key});

  @override
  ConsumerState<MyReportsScreen> createState() => _MyReportsScreenState();
}

class _MyReportsScreenState extends ConsumerState<MyReportsScreen> {
  ReportStatus? _statusFilter;

  @override
  Widget build(BuildContext context) {
    final reportsAsync = ref.watch(myReportsProvider);
    final l10n = context.l10n;

    return AppPage(
      onRefresh: () async => ref.invalidate(myReportsProvider),
      children: [
        PageHeader(
          title: l10n.myReportsTitle,
          subtitle: l10n.myReportsSubtitle,
        ),
        const SizedBox(height: 16),
        AsyncView(
          value: reportsAsync,
          data: (reports) {
            if (reports.isEmpty) {
              return EmptyStateCard(
                icon: Icons.receipt_long_outlined,
                title: l10n.noReports,
                message: l10n.noReportsHint,
              );
            }

            final counts = <ReportStatus, int>{};
            for (final r in reports) {
              counts[r.status] = (counts[r.status] ?? 0) + 1;
            }
            final filtered = _statusFilter == null
                ? reports
                : reports.where((r) => r.status == _statusFilter).toList();

            return Column(
              children: [
                _StatusFilterBar(
                  selected: _statusFilter,
                  totalCount: reports.length,
                  counts: counts,
                  onChanged: (value) => setState(() => _statusFilter = value),
                ),
                const SizedBox(height: 16),
                if (filtered.isEmpty)
                  EmptyStateCard(
                    icon: Icons.filter_list_off_rounded,
                    title: l10n.noReportsForFilter(
                      _statusFilter!.localized(l10n).toLowerCase(),
                    ),
                    message: l10n.tryDifferentFilter,
                  )
                else
                  for (final report in filtered)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 10),
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

class _StatusFilterBar extends StatelessWidget {
  const _StatusFilterBar({
    required this.selected,
    required this.totalCount,
    required this.counts,
    required this.onChanged,
  });

  final ReportStatus? selected;
  final int totalCount;
  final Map<ReportStatus, int> counts;
  final ValueChanged<ReportStatus?> onChanged;

  @override
  Widget build(BuildContext context) {
    final l10n = context.l10n;
    return SizedBox(
      height: 36,
      child: ListView(
        scrollDirection: Axis.horizontal,
        padding: EdgeInsets.zero,
        children: [
          _FilterChipPill(
            label: l10n.filterAll,
            count: totalCount,
            isSelected: selected == null,
            onTap: () => onChanged(null),
          ),
          for (final status in ReportStatus.values) ...[
            const SizedBox(width: 8),
            _FilterChipPill(
              label: status.localized(l10n),
              count: counts[status] ?? 0,
              isSelected: selected == status,
              onTap: () => onChanged(selected == status ? null : status),
            ),
          ],
        ],
      ),
    );
  }
}

class _FilterChipPill extends StatelessWidget {
  const _FilterChipPill({
    required this.label,
    required this.count,
    required this.isSelected,
    required this.onTap,
  });

  final String label;
  final int count;
  final bool isSelected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    final text = Theme.of(context).textTheme;
    final bg = isSelected ? palette.accentCyan : palette.surfaceElevated;
    final fg = isSelected ? Colors.white : palette.inkMuted;
    final borderColor = isSelected ? palette.accentCyan : palette.border;

    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(999),
        child: Ink(
          decoration: BoxDecoration(
            color: bg,
            borderRadius: BorderRadius.circular(999),
            border: Border.all(color: borderColor),
          ),
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                label,
                style: text.labelMedium?.copyWith(
                  color: fg,
                  fontWeight: FontWeight.w600,
                ),
              ),
              const SizedBox(width: 6),
              Text(
                '$count',
                style: text.labelSmall?.copyWith(
                  color: fg.withValues(alpha: 0.75),
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
