import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/theme/app_theme.dart';
import '../../core/l10n/l10n.dart';
import '../../core/widgets/smart_city_ui.dart';
import '../auth/auth_repository.dart';
import '../auth/user_role.dart';
import '../reports/create_report_controller.dart';
import '../reports/report_models.dart';

class AgencyInboxScreen extends ConsumerStatefulWidget {
  const AgencyInboxScreen({super.key});

  @override
  ConsumerState<AgencyInboxScreen> createState() => _AgencyInboxScreenState();
}

class _AgencyInboxScreenState extends ConsumerState<AgencyInboxScreen> {
  ReportStatus? _statusFilter = ReportStatus.submitted;
  IssueCategory? _categoryFilter; // super-admin only

  @override
  Widget build(BuildContext context) {
    final reportsAsync = ref.watch(scopedReportsProvider);
    final scope = ref.watch(reportsScopeProvider);
    final role = ref.watch(currentUserRoleProvider);
    final l10n = context.l10n;

    return AppPage(
      onRefresh: () async => ref.invalidate(scopedReportsProvider),
      children: [
        PageHeader(
          title: scope.label,
          subtitle: switch (role) {
            AgencyAdmin() => 'Reports routed to your agency.',
            SuperAdmin() => 'All reports across every agency.',
            Citizen() => l10n.myReportsSubtitle,
          },
        ),
        const SizedBox(height: 16),
        AsyncView(
          value: reportsAsync,
          data: (reports) {
            if (reports.isEmpty) {
              return EmptyStateCard(
                icon: Icons.inbox_outlined,
                title: 'Nothing here yet',
                message:
                    'New reports routed to ${scope.label} will show up here.',
              );
            }

            final categoryFiltered = _categoryFilter == null
                ? reports
                : reports.where((r) => r.category == _categoryFilter).toList();

            final counts = <ReportStatus, int>{};
            for (final r in categoryFiltered) {
              counts[r.status] = (counts[r.status] ?? 0) + 1;
            }
            final needsAction = counts[ReportStatus.submitted] ?? 0;
            final filtered = _statusFilter == null
                ? categoryFiltered
                : categoryFiltered
                      .where((r) => r.status == _statusFilter)
                      .toList();

            return Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (role is SuperAdmin) ...[
                  _CategoryDropdown(
                    selected: _categoryFilter,
                    onChanged: (value) =>
                        setState(() => _categoryFilter = value),
                  ),
                  const SizedBox(height: 12),
                ],
                if (needsAction > 0) ...[
                  _TriageBanner(
                    count: needsAction,
                    onTap: () =>
                        setState(() => _statusFilter = ReportStatus.submitted),
                  ),
                  const SizedBox(height: 16),
                ],
                _StatusFilterBar(
                  selected: _statusFilter,
                  totalCount: categoryFiltered.length,
                  counts: counts,
                  onChanged: (value) => setState(() => _statusFilter = value),
                ),
                const SizedBox(height: 16),
                if (filtered.isEmpty)
                  EmptyStateCard(
                    icon: Icons.filter_list_off_rounded,
                    title: 'No reports for this filter',
                    message: 'Try a different status filter.',
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

/// Prominent "what needs me now" banner — the count of reports awaiting
/// verification. Tapping jumps the filter straight to the submitted queue.
class _TriageBanner extends StatelessWidget {
  const _TriageBanner({required this.count, required this.onTap});

  final int count;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final l10n = context.l10n;
    final palette = context.palette;
    final text = Theme.of(context).textTheme;
    final color = ReportStatus.submitted.color(palette);

    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(18),
        child: Ink(
          decoration: BoxDecoration(
            color: color.withValues(alpha: 0.1),
            borderRadius: BorderRadius.circular(18),
            border: Border.all(color: color.withValues(alpha: 0.28)),
          ),
          padding: const EdgeInsets.all(14),
          child: Row(
            children: [
              Container(
                width: 44,
                height: 44,
                decoration: BoxDecoration(color: color, shape: BoxShape.circle),
                alignment: Alignment.center,
                child: const Icon(
                  Icons.notifications_active_rounded,
                  color: Colors.white,
                  size: 22,
                ),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      l10n.needsAction,
                      style: text.titleMedium?.copyWith(color: palette.ink),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      l10n.statusSubmitted,
                      style: text.bodySmall?.copyWith(color: palette.inkMuted),
                    ),
                  ],
                ),
              ),
              Text(
                '$count',
                style: text.headlineSmall?.copyWith(
                  color: color,
                  fontWeight: FontWeight.w800,
                ),
              ),
              const SizedBox(width: 6),
              Icon(Icons.chevron_right_rounded, color: color),
            ],
          ),
        ),
      ),
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
    final palette = context.palette;
    return SizedBox(
      height: 36,
      child: ListView(
        scrollDirection: Axis.horizontal,
        padding: EdgeInsets.zero,
        children: [
          _FilterChipPill(
            label: l10n.filterAll,
            count: totalCount,
            color: palette.accentCyan,
            isSelected: selected == null,
            onTap: () => onChanged(null),
          ),
          for (final status in ReportStatus.values) ...[
            const SizedBox(width: 8),
            _FilterChipPill(
              label: status.localized(l10n),
              count: counts[status] ?? 0,
              color: status.color(palette),
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
    required this.color,
    required this.isSelected,
    required this.onTap,
  });

  final String label;
  final int count;
  final Color color;
  final bool isSelected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    final text = Theme.of(context).textTheme;
    final bg = isSelected ? color : palette.surfaceElevated;
    final fg = isSelected ? Colors.white : palette.inkMuted;
    final borderColor = isSelected ? color : palette.border;

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
              if (!isSelected) ...[
                Container(
                  width: 7,
                  height: 7,
                  decoration: BoxDecoration(
                    color: color,
                    shape: BoxShape.circle,
                  ),
                ),
                const SizedBox(width: 7),
              ],
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

class _CategoryDropdown extends StatelessWidget {
  const _CategoryDropdown({required this.selected, required this.onChanged});

  final IssueCategory? selected;
  final ValueChanged<IssueCategory?> onChanged;

  @override
  Widget build(BuildContext context) {
    return DropdownButtonFormField<IssueCategory?>(
      initialValue: selected,
      isExpanded: true,
      borderRadius: BorderRadius.circular(16),
      decoration: const InputDecoration(labelText: 'Filter by agency'),
      items: <DropdownMenuItem<IssueCategory?>>[
        const DropdownMenuItem(value: null, child: Text('All agencies')),
        for (final category in IssueCategory.values)
          DropdownMenuItem(
            value: category,
            child: Text(
              category.label,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
            ),
          ),
      ],
      onChanged: onChanged,
    );
  }
}
