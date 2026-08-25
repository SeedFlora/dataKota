import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';
import 'package:intl/intl.dart';
import 'package:latlong2/latlong.dart';

import '../../app/theme/app_theme.dart';
import '../../core/l10n/l10n.dart';
import '../../core/services/media_service.dart';
import '../../core/widgets/report_map_view.dart';
import '../../core/widgets/smart_city_ui.dart';
import '../auth/auth_repository.dart';
import '../auth/user_role.dart';
import 'create_report_controller.dart';
import 'report_actions.dart';
import 'report_models.dart';
import 'reports_repository.dart';

class ReportDetailScreen extends ConsumerWidget {
  const ReportDetailScreen({super.key, required this.reportId});

  final String reportId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = context.l10n;
    final reportAsync = ref.watch(reportDetailProvider(reportId));
    final historyAsync = ref.watch(reportHistoryProvider(reportId));
    final role = ref.watch(currentUserRoleProvider);

    return Scaffold(
      appBar: AppBar(title: Text(l10n.detailTitle)),
      bottomNavigationBar: reportAsync.maybeWhen(
        data: (report) => report == null
            ? null
            : _ModeratorActionBar(role: role, report: report),
        orElse: () => null,
      ),
      body: SafeArea(
        child: reportAsync.when(
          data: (report) {
            if (report == null) {
              return Padding(
                padding: pagePadding(context),
                child: EmptyStateCard(
                  icon: Icons.search_off_rounded,
                  title: l10n.reportNotFound,
                  message: l10n.reportNotFoundHint,
                ),
              );
            }

            final aiCategory = IssueCategory.fromValue(report.aiPrediction);
            final didOverride = aiCategory != report.category;

            return ListView(
              padding: pagePadding(context),
              children: [
                ClipRRect(
                  borderRadius: BorderRadius.circular(16),
                  child: SmartCityImage(
                    imagePath: report.imageUrl,
                    height: 160,
                    width: double.infinity,
                    fit: BoxFit.cover,
                  ),
                ),
                const SizedBox(height: 20),
                _DetailHeadline(
                  category: report.category,
                  status: report.status,
                  createdAt: report.createdAt,
                  didOverride: didOverride,
                  aiCategory: aiCategory,
                  aiConfidence: report.aiConfidence,
                ),
                const SizedBox(height: 28),
                Text(
                  l10n.statusTimeline,
                  style: Theme.of(context).textTheme.titleMedium,
                ),
                const SizedBox(height: 12),
                historyAsync.when(
                  data: (entries) => _StatusTimeline(
                    entries: entries,
                    currentStatus: report.status,
                  ),
                  loading: () => const Padding(
                    padding: EdgeInsets.symmetric(vertical: 12),
                    child: Center(child: CircularProgressIndicator()),
                  ),
                  error: (error, _) => Text(error.toString()),
                ),
                const SizedBox(height: 28),
                Text(
                  l10n.descriptionSection,
                  style: Theme.of(context).textTheme.titleMedium,
                ),
                const SizedBox(height: 8),
                Text(
                  report.description,
                  style: Theme.of(context).textTheme.bodyLarge,
                ),
                const SizedBox(height: 28),
                Text(
                  l10n.confirmLocation,
                  style: Theme.of(context).textTheme.titleMedium,
                ),
                const SizedBox(height: 8),
                ClipRRect(
                  borderRadius: BorderRadius.circular(16),
                  child: SizedBox(
                    height: 200,
                    child: ReportMapView(
                      center: LatLng(report.latitude, report.longitude),
                      selectedLocation: ReportLocationData(
                        latitude: report.latitude,
                        longitude: report.longitude,
                        address: report.address,
                      ),
                    ),
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  report.address,
                  style: Theme.of(context).textTheme.bodyMedium,
                ),
                const SizedBox(height: 28),
                _ResolutionEvidenceSection(report: report),
                const SizedBox(height: 28),
                _TechnicalDetails(report: report, aiCategory: aiCategory),
                const SizedBox(height: 32),
              ],
            );
          },
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (error, _) => Padding(
            padding: pagePadding(context),
            child: EmptyStateCard(
              icon: Icons.error_outline_rounded,
              title: l10n.unableToLoad,
              message: error.toString(),
            ),
          ),
        ),
      ),
    );
  }
}

class _ResolutionEvidenceSection extends StatelessWidget {
  const _ResolutionEvidenceSection({required this.report});

  final CityReport report;

  @override
  Widget build(BuildContext context) {
    final evidenceUrl = report.resolutionEvidencePhotoUrl;
    if (report.status != ReportStatus.resolved || evidenceUrl == null) {
      return const SizedBox.shrink();
    }

    final note = report.resolutionNote;
    final resolvedAt = report.resolvedAt;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'Resolution evidence',
          style: Theme.of(context).textTheme.titleMedium,
        ),
        const SizedBox(height: 8),
        ClipRRect(
          borderRadius: BorderRadius.circular(16),
          child: SmartCityImage(
            imagePath: evidenceUrl,
            height: 160,
            width: double.infinity,
            fit: BoxFit.cover,
          ),
        ),
        if (note != null && note.isNotEmpty) ...[
          const SizedBox(height: 8),
          Text(note, style: Theme.of(context).textTheme.bodyMedium),
        ],
        if (resolvedAt != null) ...[
          const SizedBox(height: 4),
          Text(
            'Resolved at ${DateFormat('d MMM yyyy, HH:mm').format(resolvedAt)}',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ],
      ],
    );
  }
}

class _DetailHeadline extends StatelessWidget {
  const _DetailHeadline({
    required this.category,
    required this.status,
    required this.createdAt,
    required this.didOverride,
    required this.aiCategory,
    required this.aiConfidence,
  });

  final IssueCategory category;
  final ReportStatus status;
  final DateTime createdAt;
  final bool didOverride;
  final IssueCategory aiCategory;
  final double aiConfidence;

  @override
  Widget build(BuildContext context) {
    final l10n = context.l10n;
    final theme = Theme.of(context);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(l10n.directedTo, style: theme.textTheme.bodySmall),
        const SizedBox(height: 2),
        Text(category.label, style: theme.textTheme.headlineSmall),
        const SizedBox(height: 12),
        Row(
          children: [
            ReportStatusBadge(status),
            const SizedBox(width: 10),
            Expanded(
              child: Text(
                DateFormat('d MMM yyyy, HH:mm').format(createdAt),
                style: theme.textTheme.bodySmall,
              ),
            ),
          ],
        ),
        if (didOverride) ...[
          const SizedBox(height: 8),
          Text(
            '↳ ${l10n.aiOriginallySuggested(aiCategory.label, '${(aiConfidence * 100).toStringAsFixed(0)}%')}',
            style: theme.textTheme.bodySmall,
          ),
        ],
      ],
    );
  }
}

class _StatusTimeline extends StatelessWidget {
  const _StatusTimeline({required this.entries, required this.currentStatus});

  final List<ReportHistoryEntry> entries;
  final ReportStatus currentStatus;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    final reachedStatuses = entries.map((e) => e.status).toSet();
    reachedStatuses.add(currentStatus);

    final timeline = <_TimelinePoint>[];
    for (final status in ReportStatus.values) {
      if (status == ReportStatus.rejected &&
          !reachedStatuses.contains(status)) {
        continue;
      }
      final entry = entries.lastWhere(
        (e) => e.status == status,
        orElse: () => ReportHistoryEntry(
          id: '',
          reportId: '',
          status: status,
          note: '',
          createdAt: DateTime.fromMillisecondsSinceEpoch(0),
        ),
      );
      final reached = reachedStatuses.contains(status);
      timeline.add(
        _TimelinePoint(
          status: status,
          reached: reached,
          createdAt: entry.id.isEmpty ? null : entry.createdAt,
          note: entry.note,
        ),
      );
    }

    return Column(
      children: [
        for (var i = 0; i < timeline.length; i++)
          _TimelineRow(
            point: timeline[i],
            isLast: i == timeline.length - 1,
            color: palette.accentCyan,
            inactiveColor: palette.inkSubtle,
          ),
      ],
    );
  }
}

class _TimelinePoint {
  const _TimelinePoint({
    required this.status,
    required this.reached,
    required this.createdAt,
    required this.note,
  });

  final ReportStatus status;
  final bool reached;
  final DateTime? createdAt;
  final String note;
}

class _TimelineRow extends StatelessWidget {
  const _TimelineRow({
    required this.point,
    required this.isLast,
    required this.color,
    required this.inactiveColor,
  });

  final _TimelinePoint point;
  final bool isLast;
  final Color color;
  final Color inactiveColor;

  @override
  Widget build(BuildContext context) {
    final l10n = context.l10n;
    final theme = Theme.of(context);
    final dotColor = point.reached ? color : inactiveColor;

    return IntrinsicHeight(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Column(
            children: [
              Container(
                width: 12,
                height: 12,
                margin: const EdgeInsets.only(top: 4),
                decoration: BoxDecoration(
                  color: point.reached ? dotColor : Colors.transparent,
                  border: Border.all(color: dotColor, width: 2),
                  shape: BoxShape.circle,
                ),
              ),
              if (!isLast)
                Expanded(
                  child: Container(
                    width: 2,
                    color: point.reached
                        ? color
                        : inactiveColor.withValues(alpha: 0.3),
                  ),
                ),
            ],
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Padding(
              padding: EdgeInsets.only(bottom: isLast ? 0 : 16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: Text(
                          point.status.localized(l10n),
                          style: theme.textTheme.bodyLarge?.copyWith(
                            fontWeight: point.reached
                                ? FontWeight.w700
                                : FontWeight.w500,
                            color: point.reached
                                ? theme.textTheme.bodyLarge?.color
                                : inactiveColor,
                          ),
                        ),
                      ),
                      if (point.createdAt != null)
                        Text(
                          DateFormat('d MMM, HH:mm').format(point.createdAt!),
                          style: theme.textTheme.bodySmall,
                        ),
                    ],
                  ),
                  if (point.reached && point.note.isNotEmpty) ...[
                    const SizedBox(height: 2),
                    Text(point.note, style: theme.textTheme.bodySmall),
                  ],
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _TechnicalDetails extends StatelessWidget {
  const _TechnicalDetails({required this.report, required this.aiCategory});

  final CityReport report;
  final IssueCategory aiCategory;

  @override
  Widget build(BuildContext context) {
    final l10n = context.l10n;
    final palette = context.palette;
    final fmt = DateFormat('d MMM yyyy, HH:mm');

    final rows = <(String, String)>[
      (l10n.reporterLabel, report.reporterName),
      (l10n.emailLabel, report.reporterEmail),
      (l10n.aiPredictionLabel, aiCategory.label),
      (
        l10n.aiConfidenceLabel,
        '${(report.aiConfidence * 100).toStringAsFixed(1)}%',
      ),
      (
        'AI evidence',
        report.aiEvidenceTrusted
            ? 'Server-attested'
            : 'Client claim — not operationally trusted',
      ),
      if (report.aiEvidenceTrusted && report.assignment != null) ...[
        ('Assigned agency', report.assignment!.agencyName),
        (
          'Assignment distance',
          '${report.assignment!.distanceKilometers.toStringAsFixed(2)} km',
        ),
      ],
      if (report.aiModelName != null) ('Model', report.aiModelName!),
      if (report.aiModelVersion != null)
        ('Model version', report.aiModelVersion!),
      ('Inference method', report.aiInferenceMethod),
      if (report.aiAgencyRegistryStatus != null)
        ('Registry status', report.aiAgencyRegistryStatus!),
      if (report.aiExportManifestSha256 != null)
        ('Export manifest SHA-256', report.aiExportManifestSha256!),
      if (report.aiClassMapSha256 != null)
        ('Class-map SHA-256', report.aiClassMapSha256!),
      if (report.aiReviewReasons.isNotEmpty)
        ('Review reasons', report.aiReviewReasons.join(', ')),
      (l10n.createdLabel, fmt.format(report.createdAt)),
      (l10n.updatedLabel, fmt.format(report.updatedAt)),
    ];

    return Theme(
      data: Theme.of(context).copyWith(
        dividerColor: Colors.transparent,
        splashColor: Colors.transparent,
        highlightColor: Colors.transparent,
      ),
      child: ExpansionTile(
        tilePadding: EdgeInsets.zero,
        childrenPadding: const EdgeInsets.only(top: 4, bottom: 8),
        iconColor: palette.inkMuted,
        collapsedIconColor: palette.inkMuted,
        title: Text(
          l10n.technicalDetails,
          style: Theme.of(context).textTheme.titleMedium,
        ),
        children: [
          for (final (label, value) in rows)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 6),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  SizedBox(
                    width: 130,
                    child: Text(
                      label,
                      style: Theme.of(context).textTheme.bodyMedium,
                    ),
                  ),
                  Expanded(
                    child: Text(
                      value,
                      style: Theme.of(context).textTheme.bodyLarge,
                    ),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}

class _ModeratorActionBar extends ConsumerStatefulWidget {
  const _ModeratorActionBar({required this.role, required this.report});

  final UserRole role;
  final CityReport report;

  @override
  ConsumerState<_ModeratorActionBar> createState() =>
      _ModeratorActionBarState();
}

class _ModeratorActionBarState extends ConsumerState<_ModeratorActionBar> {
  bool _busy = false;

  bool get _canModerate {
    final role = widget.role;
    if (role is SuperAdmin) return true;
    if (role is AgencyAdmin) {
      return role.agency == widget.report.category;
    }
    return false;
  }

  Future<void> _run(
    Future<CityReport> Function(ReportAdminActions actions) op,
  ) async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      final actions = ref.read(reportActionsProvider);
      await op(actions);
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(context.l10n.modUpdated)));
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(context.l10n.modActionFailed(e.toString()))),
        );
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<String?> _promptNote({
    required String title,
    String hint = 'Optional note',
    bool required = false,
    IconData icon = Icons.edit_note_rounded,
    Color? accentColor,
    String confirmLabel = 'Confirm',
  }) {
    return showNoteDialog(
      context,
      title: title,
      hint: hint,
      requireText: required,
      icon: icon,
      accentColor: accentColor,
      confirmLabel: confirmLabel,
    );
  }

  Future<_ResolutionEvidenceInput?> _promptResolutionEvidence() {
    final noteController = TextEditingController();
    XFile? evidencePhoto;

    return showModalBottomSheet<_ResolutionEvidenceInput>(
      context: context,
      isScrollControlled: true,
      builder: (ctx) {
        return StatefulBuilder(
          builder: (ctx, setModalState) {
            Future<void> pick(Future<XFile?> Function() picker) async {
              final photo = await picker();
              if (photo != null) {
                setModalState(() => evidencePhoto = photo);
              }
            }

            return SafeArea(
              child: Padding(
                padding: EdgeInsets.fromLTRB(
                  16,
                  16,
                  16,
                  MediaQuery.of(ctx).viewInsets.bottom + 16,
                ),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    SheetHeader(
                      icon: Icons.task_alt_rounded,
                      iconColor: ReportStatus.resolved.color(ctx.palette),
                      title: 'Resolution evidence',
                      subtitle: 'Lampirkan foto bukti penyelesaian',
                    ),
                    const SizedBox(height: 16),
                    TextField(
                      controller: noteController,
                      minLines: 2,
                      maxLines: 4,
                      decoration: const InputDecoration(
                        labelText: 'Resolution note',
                      ),
                    ),
                    const SizedBox(height: 12),
                    Row(
                      children: [
                        Expanded(
                          child: OutlinedButton.icon(
                            onPressed: () => pick(
                              ref.read(mediaServiceProvider).pickFromCamera,
                            ),
                            icon: const Icon(Icons.photo_camera_rounded),
                            label: const Text('Camera'),
                          ),
                        ),
                        const SizedBox(width: 10),
                        Expanded(
                          child: OutlinedButton.icon(
                            onPressed: () => pick(
                              ref.read(mediaServiceProvider).pickFromGallery,
                            ),
                            icon: const Icon(Icons.photo_library_rounded),
                            label: const Text('Gallery'),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 8),
                    Text(
                      evidencePhoto == null
                          ? 'Upload foto bukti penyelesaian wajib diisi sebelum laporan dapat ditandai selesai.'
                          : evidencePhoto!.name,
                      style: Theme.of(ctx).textTheme.bodySmall,
                    ),
                    const SizedBox(height: 16),
                    Row(
                      mainAxisAlignment: MainAxisAlignment.end,
                      children: [
                        TextButton(
                          onPressed: () => Navigator.pop(ctx),
                          child: const Text('Cancel'),
                        ),
                        const SizedBox(width: 8),
                        FilledButton(
                          style: FilledButton.styleFrom(
                            minimumSize: const Size(0, 48),
                          ),
                          onPressed: () {
                            final photo = evidencePhoto;
                            if (photo == null) {
                              ScaffoldMessenger.of(ctx).showSnackBar(
                                const SnackBar(
                                  content: Text(
                                    'Resolution evidence photo is required.',
                                  ),
                                ),
                              );
                              return;
                            }
                            Navigator.pop(
                              ctx,
                              _ResolutionEvidenceInput(
                                photo: photo,
                                note: noteController.text.trim(),
                              ),
                            );
                          },
                          child: const Text('Mark resolved'),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            );
          },
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    if (!_canModerate) return const SizedBox.shrink();

    final l10n = context.l10n;
    final palette = context.palette;
    final report = widget.report;
    final canReject =
        report.status == ReportStatus.submitted ||
        report.status == ReportStatus.verified;

    // The single next-step action for the current status, coloured by the
    // status it advances the report into.
    final (_PrimaryAction? primary) = switch (report.status) {
      ReportStatus.submitted => _PrimaryAction(
        label: l10n.modVerify,
        icon: Icons.verified_rounded,
        color: ReportStatus.verified.color(palette),
        onPressed: () async {
          final note = await _promptNote(
            title: l10n.modVerify,
            icon: Icons.verified_rounded,
            accentColor: ReportStatus.verified.color(palette),
            confirmLabel: l10n.modVerify,
          );
          if (note == null) return;
          await _run((a) => a.verify(report.id, note: note));
        },
      ),
      ReportStatus.verified => _PrimaryAction(
        label: l10n.modInProgress,
        icon: Icons.play_arrow_rounded,
        color: ReportStatus.inProgress.color(palette),
        onPressed: () async {
          final note = await _promptNote(
            title: l10n.modInProgress,
            icon: Icons.play_arrow_rounded,
            accentColor: ReportStatus.inProgress.color(palette),
            confirmLabel: l10n.modInProgress,
          );
          if (note == null) return;
          await _run((a) => a.markInProgress(report.id, note: note));
        },
      ),
      ReportStatus.inProgress => _PrimaryAction(
        label: l10n.modResolved,
        icon: Icons.task_alt_rounded,
        color: ReportStatus.resolved.color(palette),
        onPressed: () async {
          final evidence = await _promptResolutionEvidence();
          if (evidence == null) return;
          await _run(
            (a) => a.markResolved(
              report.id,
              evidencePhoto: evidence.photo,
              note: evidence.note,
            ),
          );
        },
      ),
      ReportStatus.resolved || ReportStatus.rejected => null,
    };

    final secondary = <Widget>[
      if (canReject)
        OutlinedButton.icon(
          onPressed: _busy
              ? null
              : () async {
                  final reason = await _promptNote(
                    title: l10n.modReject,
                    hint: 'Reason (required)',
                    required: true,
                    icon: Icons.cancel_outlined,
                    accentColor: palette.danger,
                    confirmLabel: l10n.modReject,
                  );
                  if (reason == null || reason.isEmpty) return;
                  await _run((a) => a.reject(report.id, reason: reason));
                },
          icon: const Icon(Icons.cancel_outlined, size: 18),
          label: Text(l10n.modReject),
          style: OutlinedButton.styleFrom(foregroundColor: palette.danger),
        ),
      if (widget.role.canRecategorizeAndRetriage)
        OutlinedButton.icon(
          onPressed: _busy
              ? null
              : () => _showRecategorizeAndRetriageSheet(report),
          icon: const Icon(Icons.alt_route_rounded, size: 18),
          label: Text(l10n.modRecategorizeAndRetriage),
        ),
    ];

    if (primary == null && secondary.isEmpty) return const SizedBox.shrink();

    return SafeArea(
      top: false,
      child: Container(
        padding: const EdgeInsets.fromLTRB(20, 12, 20, 12),
        decoration: BoxDecoration(
          color: palette.surfaceElevated,
          border: Border(top: BorderSide(color: palette.border)),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (primary != null)
              SizedBox(
                width: double.infinity,
                child: FilledButton.icon(
                  onPressed: _busy ? null : primary.onPressed,
                  style: FilledButton.styleFrom(
                    backgroundColor: primary.color,
                    minimumSize: const Size.fromHeight(50),
                  ),
                  icon: _busy
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            color: Colors.white,
                          ),
                        )
                      : Icon(primary.icon),
                  label: Text(primary.label),
                ),
              ),
            if (primary != null && secondary.isNotEmpty)
              const SizedBox(height: 8),
            if (secondary.isNotEmpty)
              Row(
                children: [
                  for (var i = 0; i < secondary.length; i++) ...[
                    if (i > 0) const SizedBox(width: 8),
                    Expanded(child: secondary[i]),
                  ],
                ],
              ),
          ],
        ),
      ),
    );
  }

  Future<void> _showRecategorizeAndRetriageSheet(CityReport report) async {
    final selected = await showModalBottomSheet<IssueCategory>(
      context: context,
      isScrollControlled: true,
      builder: (ctx) {
        final targets = IssueCategory.values
            .where((c) => c != report.category)
            .toList();
        return SafeArea(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(20, 4, 20, 16),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const SheetHeader(
                  icon: Icons.alt_route_rounded,
                  title: 'Ubah kategori dan triase ulang',
                  subtitle:
                      'Pilih kategori baru, bukan instansi tujuan. Penugasan '
                      'saat ini akan dikosongkan untuk triase ulang.',
                ),
                const SizedBox(height: 16),
                Flexible(
                  child: ListView.separated(
                    shrinkWrap: true,
                    itemCount: targets.length,
                    separatorBuilder: (_, _) => const SizedBox(height: 8),
                    itemBuilder: (_, i) {
                      final category = targets[i];
                      return _RecategorizeOption(
                        category: category,
                        onTap: () => Navigator.pop(ctx, category),
                      );
                    },
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
    if (selected == null) return;
    if (!mounted) return;
    final note = await _promptNote(
      title: 'Ubah kategori ke ${selected.label}',
      hint: 'Alasan perubahan kategori (wajib)',
      required: true,
      icon: Icons.alt_route_rounded,
      confirmLabel: 'Ubah & triase ulang',
    );
    if (note == null || note.isEmpty) return;
    await _run(
      (actions) => actions.recategorizeAndRetriage(
        report.id,
        newCategory: selected,
        note: note,
      ),
    );
  }
}

class _ResolutionEvidenceInput {
  const _ResolutionEvidenceInput({required this.photo, required this.note});

  final XFile photo;
  final String note;
}

/// A selectable category row in the recategorize-and-re-triage sheet.
class _RecategorizeOption extends StatelessWidget {
  const _RecategorizeOption({required this.category, required this.onTap});

  final IssueCategory category;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    final text = Theme.of(context).textTheme;
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(16),
        child: Ink(
          decoration: BoxDecoration(
            color: palette.surfaceElevated,
            borderRadius: BorderRadius.circular(16),
            border: Border.all(color: palette.border),
          ),
          padding: const EdgeInsets.all(10),
          child: Row(
            children: [
              CategoryAvatar(category: category, size: 40),
              const SizedBox(width: 12),
              Expanded(
                child: Text(
                  category.label,
                  style: text.titleSmall?.copyWith(
                    color: palette.ink,
                    fontWeight: FontWeight.w700,
                  ),
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              const SizedBox(width: 8),
              Icon(Icons.chevron_right_rounded, color: palette.inkSubtle),
            ],
          ),
        ),
      ),
    );
  }
}

/// The single primary moderation action available for the report's current
/// status, rendered as a full-width coloured button.
class _PrimaryAction {
  const _PrimaryAction({
    required this.label,
    required this.icon,
    required this.color,
    required this.onPressed,
  });

  final String label;
  final IconData icon;
  final Color color;
  final Future<void> Function() onPressed;
}
