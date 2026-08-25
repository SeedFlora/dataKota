import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:latlong2/latlong.dart';

import '../../app/theme/app_theme.dart';
import '../../core/l10n/l10n.dart';
import '../../core/widgets/report_map_view.dart';
import '../../core/widgets/smart_city_ui.dart';
import 'create_report_controller.dart';
import 'report_models.dart';

class AiResultReviewScreen extends ConsumerStatefulWidget {
  const AiResultReviewScreen({super.key});

  @override
  ConsumerState<AiResultReviewScreen> createState() =>
      _AiResultReviewScreenState();
}

class _AiResultReviewScreenState extends ConsumerState<AiResultReviewScreen> {
  Future<void> _handleBack() async {
    final navigator = Navigator.of(context);
    if (navigator.canPop()) {
      navigator.pop();
      return;
    }
    if (mounted) context.go('/create-report');
  }

  @override
  void initState() {
    super.initState();
    ref.listenManual<CreateReportState>(createReportControllerProvider, (
      previous,
      next,
    ) {
      if (next.didSubmit && next.lastCreatedReportId != null && mounted) {
        ScaffoldMessenger.of(context)
          ..hideCurrentSnackBar()
          ..showSnackBar(
            SnackBar(
              content: Text(context.l10n.reportSubmitted),
              behavior: SnackBarBehavior.floating,
            ),
          );
        context.go('/report/${next.lastCreatedReportId}');
      }
    });
  }

  Future<void> _openAgencyPicker(IssueCategory selected) async {
    final notifier = ref.read(createReportControllerProvider.notifier);
    final picked = await showModalBottomSheet<IssueCategory>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      backgroundColor: context.palette.surfaceElevated,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(28)),
      ),
      builder: (ctx) => _AgencyPickerSheet(selected: selected),
    );
    if (picked != null) notifier.updateCategory(picked);
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(createReportControllerProvider);
    final notifier = ref.read(createReportControllerProvider.notifier);
    final l10n = context.l10n;
    final palette = context.palette;

    if (state.imageFile == null || state.prediction == null) {
      return Scaffold(
        appBar: AppBar(),
        body: SafeArea(
          child: Padding(
            padding: pagePadding(context),
            child: EmptyStateCard(
              icon: Icons.auto_awesome_outlined,
              title: l10n.noReviewYet,
              message: l10n.noReviewYetHint,
              action: ElevatedButton(
                onPressed: () => context.go('/create-report'),
                child: Text(l10n.backToForm),
              ),
            ),
          ),
        ),
      );
    }

    final prediction = state.prediction!;
    final selectedCategory = state.selectedCategory ?? prediction.category;
    final isUncertain = prediction.reviewRequired;
    final runnerUps = prediction
        .topPredictions(limit: 4)
        .where((p) => p.category != prediction.category)
        .take(2)
        .toList();
    final locationCenter = state.location == null
        ? const LatLng(-6.2088, 106.8456)
        : LatLng(state.location!.latitude, state.location!.longitude);

    return Scaffold(
      backgroundColor: palette.surface,
      appBar: AppBar(
        leading: IconButton(
          icon: const Icon(Icons.arrow_back_rounded),
          onPressed: _handleBack,
        ),
        title: Text(l10n.reviewTitle),
      ),
      bottomNavigationBar: _SubmitBar(state: state, onSubmit: notifier.submit),
      body: PopScope(
        canPop: false,
        onPopInvokedWithResult: (didPop, result) {
          if (!didPop) _handleBack();
        },
        child: SafeArea(
          bottom: false,
          child: ListView(
            padding: pagePadding(context).copyWith(bottom: 24),
            children: [
              _ResultHero(
                imageFile: File(state.imageFile!.path),
                category: prediction.category,
                confidence: prediction.confidence,
                isUncertain: isUncertain,
              ),
              if (prediction.reviewReasons.isNotEmpty) ...[
                const SizedBox(height: 12),
                _ReviewReasons(reasons: prediction.reviewReasons),
              ],
              if (runnerUps.isNotEmpty) ...[
                const SizedBox(height: 14),
                _RunnerUps(items: runnerUps),
              ],
              const SizedBox(height: 20),
              _RoutingCard(
                aiCategory: prediction.category,
                selected: selectedCategory,
                onChange: () => _openAgencyPicker(selectedCategory),
              ),
              if (!state.prediction!.reviewRequired &&
                  state.prediction!.assignment != null &&
                  selectedCategory == state.prediction!.category) ...[
                const SizedBox(height: 12),
                _AssignmentSummary(assignment: state.prediction!.assignment!),
              ],
              const SizedBox(height: 24),
              _SectionLabel(l10n.confirmLocation),
              const SizedBox(height: 10),
              ClipRRect(
                borderRadius: BorderRadius.circular(18),
                child: SizedBox(
                  height: 200,
                  child: ReportMapView(
                    center: locationCenter,
                    selectedLocation: state.location,
                    onLocationChanged: (latLng) => notifier.updateLocation(
                      latLng.latitude,
                      latLng.longitude,
                    ),
                    showCompassHint: true,
                  ),
                ),
              ),
              const SizedBox(height: 8),
              Text(
                state.location?.address ?? l10n.tapMapHint,
                style: Theme.of(context).textTheme.bodyMedium,
              ),
              Align(
                alignment: Alignment.centerLeft,
                child: TextButton.icon(
                  onPressed: state.isBusy
                      ? null
                      : notifier.captureCurrentLocation,
                  icon: const Icon(Icons.my_location_rounded, size: 18),
                  label: Text(l10n.refreshLocation),
                ),
              ),
              const SizedBox(height: 14),
              _SectionLabel(l10n.descriptionSection),
              const SizedBox(height: 10),
              TextFormField(
                initialValue: state.description,
                minLines: 3,
                maxLines: 5,
                onChanged: notifier.updateDescription,
                decoration: InputDecoration(
                  hintText: l10n.descriptionFieldHint,
                ),
              ),
              if (state.errorMessage != null) ...[
                const SizedBox(height: 16),
                Text(
                  state.errorMessage!,
                  style: TextStyle(color: Theme.of(context).colorScheme.error),
                ),
              ],
              const SizedBox(height: 16),
              _SubmissionChecklist(state: state),
            ],
          ),
        ),
      ),
    );
  }
}

class _SectionLabel extends StatelessWidget {
  const _SectionLabel(this.text);
  final String text;

  @override
  Widget build(BuildContext context) {
    return Text(text, style: Theme.of(context).textTheme.titleMedium);
  }
}

/// Filled hero card tinted in the agency's brand hue. The ring is the raw top
/// class score; it is explicitly labelled as uncalibrated and never decides
/// whether review is required.
class _ResultHero extends StatelessWidget {
  const _ResultHero({
    required this.imageFile,
    required this.category,
    required this.confidence,
    required this.isUncertain,
  });

  final File imageFile;
  final IssueCategory category;
  final double confidence;
  final bool isUncertain;

  @override
  Widget build(BuildContext context) {
    final l10n = context.l10n;
    final palette = context.palette;
    final text = Theme.of(context).textTheme;
    final accent = isUncertain ? palette.warning : category.color;
    final level = ConfidenceLevel.of(confidence);

    return Container(
      decoration: BoxDecoration(
        color: accent.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(24),
        border: Border.all(color: accent.withValues(alpha: 0.22)),
      ),
      padding: const EdgeInsets.all(12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Stack(
            clipBehavior: Clip.none,
            children: [
              ClipRRect(
                borderRadius: BorderRadius.circular(16),
                child: Image.file(
                  imageFile,
                  height: 200,
                  width: double.infinity,
                  fit: BoxFit.cover,
                  cacheWidth:
                      (MediaQuery.sizeOf(context).width *
                              MediaQuery.devicePixelRatioOf(context))
                          .round(),
                ),
              ),
              Positioned(
                right: 10,
                bottom: -22,
                child: Container(
                  padding: const EdgeInsets.all(5),
                  decoration: BoxDecoration(
                    color: palette.surfaceElevated,
                    shape: BoxShape.circle,
                    boxShadow: const [
                      BoxShadow(
                        color: Color(0x1A0F172A),
                        blurRadius: 14,
                        offset: Offset(0, 6),
                      ),
                    ],
                  ),
                  child: ConfidenceRing(value: confidence, size: 72),
                ),
              ),
            ],
          ),
          const SizedBox(height: 30),
          Padding(
            padding: const EdgeInsets.fromLTRB(4, 0, 4, 4),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                CategoryAvatar(category: category, size: 46),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        isUncertain ? l10n.aiUncertain : l10n.aiTopPick,
                        style: text.labelMedium?.copyWith(
                          color: accent,
                          fontWeight: FontWeight.w700,
                          letterSpacing: 0.3,
                        ),
                      ),
                      const SizedBox(height: 3),
                      Text(
                        category.label,
                        style: text.titleLarge?.copyWith(height: 1.15),
                      ),
                      const SizedBox(height: 8),
                      _ConfidencePill(level: level),
                      if (isUncertain) ...[
                        const SizedBox(height: 8),
                        Text(
                          l10n.aiUncertainHint,
                          style: text.bodySmall?.copyWith(
                            color: palette.warning,
                          ),
                        ),
                      ],
                    ],
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

class _ConfidencePill extends StatelessWidget {
  const _ConfidencePill({required this.level});

  final ConfidenceLevel level;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    final color = level.color(palette);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.14),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 7,
            height: 7,
            decoration: BoxDecoration(color: color, shape: BoxShape.circle),
          ),
          const SizedBox(width: 7),
          Flexible(
            child: Text(
              level.label(context.l10n),
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: Theme.of(context).textTheme.labelMedium?.copyWith(
                color: color,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _ReviewReasons extends StatelessWidget {
  const _ReviewReasons({required this.reasons});

  final List<String> reasons;

  static String _label(String reason, {required bool isIndonesian}) =>
      switch (reason) {
        'low_confidence' =>
          isIndonesian
              ? 'Skor model di bawah ambang validasi'
              : 'Model score is below the validation threshold',
        'catch_all_class' =>
          isIndonesian
              ? 'Kelas catch-all memerlukan pemeriksaan'
              : 'The catch-all class requires review',
        'high_epistemic_uncertainty' =>
          isIndonesian
              ? 'Dispersi ensembel melewati ambang validasi'
              : 'Ensemble dispersion exceeds the validation threshold',
        'routing_registry_incomplete' =>
          isIndonesian
              ? 'Registri kantor belum lengkap'
              : 'The office registry is incomplete',
        'agency_registry_untrusted' =>
          isIndonesian
              ? 'Registri kantor belum terverifikasi'
              : 'The office registry is not verified',
        'routing_registry_gap' =>
          isIndonesian
              ? 'Tidak ada kantor aktif untuk kategori ini'
              : 'No active office covers this category',
        'user_category_override' =>
          isIndonesian
              ? 'Kategori dikoreksi oleh pelapor'
              : 'The reporter corrected the category',
        'testing_mode_demo' =>
          isIndonesian
              ? 'Mode demo tidak boleh membuat penugasan'
              : 'Demo mode cannot create an assignment',
        _ => reason.replaceAll('_', ' '),
      };

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    final isIndonesian = Localizations.localeOf(context).languageCode == 'id';
    return SectionCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            isIndonesian ? 'Alasan tinjauan manusia' : 'Human-review reasons',
            style: Theme.of(context).textTheme.titleSmall,
          ),
          const SizedBox(height: 8),
          for (final reason in reasons)
            Padding(
              padding: const EdgeInsets.only(bottom: 4),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Icon(
                    Icons.info_outline_rounded,
                    size: 18,
                    color: palette.warning,
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(_label(reason, isIndonesian: isIndonesian)),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}

/// Alternative predictions (#2, #3) — colour-coded so the user can tell at a
/// glance which other agencies the model considered.
class _RunnerUps extends StatelessWidget {
  const _RunnerUps({required this.items});

  final List<({IssueCategory category, double confidence})> items;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final palette = context.palette;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.only(left: 4, bottom: 8),
          child: Text(
            context.l10n.runnerUp,
            style: text.labelMedium?.copyWith(
              color: palette.inkMuted,
              letterSpacing: 0.6,
            ),
          ),
        ),
        for (final item in items)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Row(
              children: [
                CategoryAvatar(category: item.category, size: 34),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        item.category.label,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: text.bodyMedium?.copyWith(
                          color: palette.ink,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                      const SizedBox(height: 5),
                      ClipRRect(
                        borderRadius: BorderRadius.circular(999),
                        child: LinearProgressIndicator(
                          value: item.confidence.clamp(0.0, 1.0),
                          minHeight: 4,
                          backgroundColor: palette.surfaceMuted,
                          valueColor: AlwaysStoppedAnimation(
                            item.category.color,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(width: 10),
                Text(
                  '${(item.confidence * 100).toStringAsFixed(0)}%',
                  style: text.labelMedium?.copyWith(color: palette.inkMuted),
                ),
              ],
            ),
          ),
      ],
    );
  }
}

/// Where the report will actually be routed. Defaults to the AI pick; the user
/// can override it. Shows a note when the selection differs from the AI.
class _RoutingCard extends StatelessWidget {
  const _RoutingCard({
    required this.aiCategory,
    required this.selected,
    required this.onChange,
  });

  final IssueCategory aiCategory;
  final IssueCategory selected;
  final VoidCallback onChange;

  @override
  Widget build(BuildContext context) {
    final l10n = context.l10n;
    final text = Theme.of(context).textTheme;
    final palette = context.palette;
    final overridden = selected != aiCategory;

    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: palette.surfaceElevated,
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: palette.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              CategoryAvatar(category: selected, size: 44),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(l10n.directedTo, style: text.bodySmall),
                    const SizedBox(height: 2),
                    Text(
                      selected.label,
                      style: text.titleMedium,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              TextButton.icon(
                onPressed: onChange,
                icon: const Icon(Icons.edit_rounded, size: 16),
                label: Text(l10n.changeAgency),
                style: TextButton.styleFrom(
                  foregroundColor: selected.color,
                  padding: const EdgeInsets.symmetric(horizontal: 8),
                ),
              ),
            ],
          ),
          if (overridden) ...[
            const SizedBox(height: 8),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
              decoration: BoxDecoration(
                color: palette.surfaceMuted,
                borderRadius: BorderRadius.circular(12),
              ),
              child: Row(
                children: [
                  Icon(
                    Icons.info_outline_rounded,
                    size: 15,
                    color: palette.inkMuted,
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      l10n.aiSuggestedAgency(aiCategory.label),
                      style: text.bodySmall,
                    ),
                  ),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _AgencyPickerSheet extends StatelessWidget {
  const _AgencyPickerSheet({required this.selected});

  final IssueCategory selected;

  @override
  Widget build(BuildContext context) {
    final l10n = context.l10n;
    final text = Theme.of(context).textTheme;
    final palette = context.palette;
    return SafeArea(
      top: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(20, 4, 20, 16),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(l10n.instansiPickerHint, style: text.titleLarge),
            const SizedBox(height: 2),
            Text(
              l10n.instansiPickerSubhint,
              style: text.bodySmall?.copyWith(color: palette.inkMuted),
            ),
            const SizedBox(height: 12),
            Flexible(
              child: ListView(
                shrinkWrap: true,
                children: [
                  for (final category in IssueCategory.values)
                    _AgencyOption(
                      category: category,
                      isSelected: category == selected,
                      onTap: () => Navigator.pop(context, category),
                    ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _AgencyOption extends StatelessWidget {
  const _AgencyOption({
    required this.category,
    required this.isSelected,
    required this.onTap,
  });

  final IssueCategory category;
  final bool isSelected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    final color = category.color;
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(16),
          child: Ink(
            decoration: BoxDecoration(
              color: isSelected
                  ? color.withValues(alpha: 0.1)
                  : palette.surfaceElevated,
              borderRadius: BorderRadius.circular(16),
              border: Border.all(
                color: isSelected ? color : palette.border,
                width: isSelected ? 1.4 : 1,
              ),
            ),
            padding: const EdgeInsets.all(10),
            child: Row(
              children: [
                CategoryAvatar(category: category, size: 40),
                const SizedBox(width: 12),
                Expanded(
                  child: Text(
                    category.label,
                    style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                      fontWeight: isSelected
                          ? FontWeight.w700
                          : FontWeight.w500,
                    ),
                  ),
                ),
                if (isSelected)
                  Icon(Icons.check_circle_rounded, color: color, size: 22),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _AssignmentSummary extends StatelessWidget {
  const _AssignmentSummary({required this.assignment});

  final ReportAssignment assignment;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: palette.surfaceElevated,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: palette.border),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(Icons.alt_route_rounded, color: palette.accentCyan),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Saran routing — menunggu verifikasi server',
                  style: Theme.of(
                    context,
                  ).textTheme.labelMedium?.copyWith(color: palette.inkSubtle),
                ),
                const SizedBox(height: 4),
                Text(
                  assignment.agencyName,
                  style: Theme.of(context).textTheme.titleSmall,
                ),
                const SizedBox(height: 4),
                Text(
                  'Jarak estimasi ${assignment.distanceKilometers.toStringAsFixed(2)} km. Belum menjadi penugasan resmi.',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// Sticky bottom CTA. Surfaces the single primary action (submit) and, when the
/// form is incomplete, the count of remaining steps instead of a dead button.
class _SubmitBar extends StatelessWidget {
  const _SubmitBar({required this.state, required this.onSubmit});

  final CreateReportState state;
  final Future<void> Function() onSubmit;

  @override
  Widget build(BuildContext context) {
    final l10n = context.l10n;
    final palette = context.palette;
    final ready = state.canSubmit;
    return Container(
      decoration: BoxDecoration(
        color: palette.surfaceElevated,
        border: Border(top: BorderSide(color: palette.border)),
      ),
      child: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 12, 20, 12),
          child: ElevatedButton.icon(
            onPressed: state.isBusy || !ready ? null : onSubmit,
            icon: state.isBusy
                ? const SizedBox(
                    width: 20,
                    height: 20,
                    child: CircularProgressIndicator(
                      strokeWidth: 2,
                      color: Colors.white,
                    ),
                  )
                : const Icon(Icons.cloud_upload_rounded),
            label: Text(state.isBusy ? l10n.submitting : l10n.submitReport),
          ),
        ),
      ),
    );
  }
}

class _SubmissionChecklist extends StatelessWidget {
  const _SubmissionChecklist({required this.state});

  final CreateReportState state;

  @override
  Widget build(BuildContext context) {
    final l10n = context.l10n;
    final palette = context.palette;
    final items = <(bool, String)>[
      (state.imageFile != null, l10n.checklistPhoto),
      (state.selectedCategory != null, l10n.checklistInstansi),
      (state.location != null, l10n.checklistLocation),
      (state.hasEnoughDescription, l10n.checklistDescription),
    ];

    if (items.every((item) => item.$1)) {
      return const SizedBox.shrink();
    }

    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: palette.warning.withValues(alpha: 0.07),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: palette.warning.withValues(alpha: 0.22)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            l10n.almostThere,
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: 8),
          for (final item in items)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 3),
              child: Row(
                children: [
                  Icon(
                    item.$1
                        ? Icons.check_circle_rounded
                        : Icons.radio_button_unchecked_rounded,
                    size: 18,
                    color: item.$1 ? palette.success : palette.inkSubtle,
                  ),
                  const SizedBox(width: 10),
                  Text(item.$2, style: Theme.of(context).textTheme.bodyMedium),
                ],
              ),
            ),
        ],
      ),
    );
  }
}
