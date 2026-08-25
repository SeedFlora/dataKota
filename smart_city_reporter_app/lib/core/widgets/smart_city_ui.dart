import 'dart:io';

import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:intl/intl.dart';

import '../../app/theme/app_theme.dart';
import '../../features/reports/report_models.dart';
import '../l10n/l10n.dart';
import '../services/storage_url_service.dart';

export 'app_page.dart' show pagePadding, AppPage, AsyncView;

class SmartCityLogo extends StatelessWidget {
  const SmartCityLogo({super.key, this.size = 58});

  final double size;
  static const String assetPath = 'assets/branding/smart_city_brand.png';

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: size,
      height: size,
      child: Image.asset(assetPath, fit: BoxFit.contain),
    );
  }
}

enum PageHeaderVariant { plain, gradient }

/// Compact page header. Default is a plain title/subtitle block that feels
/// lighter than a full gradient card; [PageHeaderVariant.gradient] keeps the
/// welcome look for the home screen.
class PageHeader extends StatelessWidget {
  const PageHeader({
    super.key,
    required this.title,
    required this.subtitle,
    this.trailing,
    this.variant = PageHeaderVariant.plain,
    this.eyebrow,
  });

  final String title;
  final String subtitle;
  final Widget? trailing;
  final PageHeaderVariant variant;
  final String? eyebrow;

  @override
  Widget build(BuildContext context) {
    if (variant == PageHeaderVariant.gradient) {
      return _GradientHeader(
        title: title,
        subtitle: subtitle,
        trailing: trailing,
        eyebrow: eyebrow,
      );
    }
    return _PlainHeader(
      title: title,
      subtitle: subtitle,
      trailing: trailing,
      eyebrow: eyebrow,
    );
  }
}

class _PlainHeader extends StatelessWidget {
  const _PlainHeader({
    required this.title,
    required this.subtitle,
    this.trailing,
    this.eyebrow,
  });

  final String title;
  final String subtitle;
  final Widget? trailing;
  final String? eyebrow;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    final text = Theme.of(context).textTheme;
    return Padding(
      padding: const EdgeInsets.fromLTRB(4, 8, 4, 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (eyebrow != null) ...[
                  Text(
                    eyebrow!.toUpperCase(),
                    style: text.labelMedium?.copyWith(
                      color: palette.accentCyan,
                      letterSpacing: 1.1,
                    ),
                  ),
                  const SizedBox(height: 6),
                ],
                Text(title, style: text.headlineSmall),
                const SizedBox(height: 6),
                Text(
                  subtitle,
                  style: text.bodyMedium?.copyWith(color: palette.inkMuted),
                ),
              ],
            ),
          ),
          if (trailing != null) ...[const SizedBox(width: 16), trailing!],
        ],
      ),
    );
  }
}

/// Claude-iOS inspired hero: a quiet warm-blue surface with a hairline border.
/// Reads like a sheet of tinted paper resting on the page background — the
/// colour is soft enough that typography carries the hierarchy.
class _GradientHeader extends StatelessWidget {
  const _GradientHeader({
    required this.title,
    required this.subtitle,
    this.trailing,
    this.eyebrow,
  });

  // Warm-blue palette (off-white with a blue cast, not cyan-bright).
  static const Color _surface = Color(0xFFEEF2F8);
  static const Color _border = Color(0xFFD9E2EF);
  static const Color _eyebrow = Color(0xFF3B5578);

  final String title;
  final String subtitle;
  final Widget? trailing;
  final String? eyebrow;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final palette = context.palette;
    return Container(
      padding: const EdgeInsets.fromLTRB(20, 22, 20, 22),
      decoration: BoxDecoration(
        color: _surface,
        border: Border.all(color: _border, width: 1),
        borderRadius: BorderRadius.circular(20),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (eyebrow != null) ...[
                  Text(
                    eyebrow!.toUpperCase(),
                    style: GoogleFonts.plusJakartaSans(
                      fontSize: 11,
                      fontWeight: FontWeight.w600,
                      letterSpacing: 1.4,
                      color: _eyebrow,
                    ),
                  ),
                  const SizedBox(height: 10),
                ],
                Text(
                  title,
                  style: GoogleFonts.plusJakartaSans(
                    fontSize: 26,
                    fontWeight: FontWeight.w700,
                    height: 1.15,
                    letterSpacing: -0.4,
                    color: palette.ink,
                  ),
                ),
                const SizedBox(height: 6),
                Text(
                  subtitle,
                  style: text.bodyMedium?.copyWith(
                    fontSize: 14,
                    color: palette.inkMuted,
                    height: 1.45,
                  ),
                ),
              ],
            ),
          ),
          if (trailing != null) ...[const SizedBox(width: 16), trailing!],
        ],
      ),
    );
  }
}

/// Backward-compat alias; prefer [PageHeader].
class GradientHeroHeader extends StatelessWidget {
  const GradientHeroHeader({
    super.key,
    required this.title,
    required this.subtitle,
    this.trailing,
  });

  final String title;
  final String subtitle;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) => PageHeader(
    title: title,
    subtitle: subtitle,
    trailing: trailing,
    variant: PageHeaderVariant.gradient,
  );
}

class SectionCard extends StatelessWidget {
  const SectionCard({
    super.key,
    required this.child,
    this.padding = const EdgeInsets.all(18),
  });

  final Widget child;
  final EdgeInsets padding;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(padding: padding, child: child),
    );
  }
}

class SectionHeader extends StatelessWidget {
  const SectionHeader({
    super.key,
    required this.title,
    required this.subtitle,
    this.trailing,
  });

  final String title;
  final String subtitle;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return Row(
      crossAxisAlignment: CrossAxisAlignment.center,
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(title, style: text.titleLarge),
              const SizedBox(height: 2),
              Text(subtitle, style: text.bodyMedium),
            ],
          ),
        ),
        ?trailing,
      ],
    );
  }
}

/// Status tile used in the dashboard 2x2 grid. Pure white background, 16px
/// radius, soft drop shadow, and a tinted circular icon — the accent colour
/// lives only on the icon so a wall of cards doesn't become a colour collage.
class MetricCard extends StatelessWidget {
  const MetricCard({
    super.key,
    required this.label,
    required this.value,
    required this.color,
    required this.icon,
  });

  final String label;
  final String value;
  final Color color;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final palette = context.palette;
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: palette.surfaceElevated,
        borderRadius: BorderRadius.circular(16),
        boxShadow: const [
          BoxShadow(
            color: Color(0x0D000000), // rgba(0,0,0,0.05)
            blurRadius: 12,
            offset: Offset(0, 4),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Container(
            width: 40,
            height: 40,
            decoration: BoxDecoration(
              color: color.withValues(alpha: 0.12),
              shape: BoxShape.circle,
            ),
            alignment: Alignment.center,
            child: Icon(icon, color: color, size: 20),
          ),
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                value,
                style: GoogleFonts.plusJakartaSans(
                  fontSize: 28,
                  fontWeight: FontWeight.w700,
                  color: palette.ink,
                  letterSpacing: -0.5,
                  height: 1.1,
                ),
              ),
              const SizedBox(height: 2),
              Text(
                label,
                style: text.bodyMedium?.copyWith(
                  fontSize: 13,
                  fontWeight: FontWeight.w500,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

/// Tone of an [InlineNotice] — drives colour and the default icon.
enum NoticeTone { error, warning, success, info }

/// Inline, in-context feedback banner for forms (auth errors, validation,
/// success). Calmer and more discoverable than a transient SnackBar: it sits
/// where the user is looking and explains what to do next.
class InlineNotice extends StatelessWidget {
  const InlineNotice({
    super.key,
    required this.message,
    this.title,
    this.tone = NoticeTone.error,
    this.icon,
    this.onClose,
  });

  final String message;
  final String? title;
  final NoticeTone tone;
  final IconData? icon;
  final VoidCallback? onClose;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    final text = Theme.of(context).textTheme;
    final color = switch (tone) {
      NoticeTone.error => palette.danger,
      NoticeTone.warning => palette.warning,
      NoticeTone.success => palette.success,
      NoticeTone.info => palette.accentBlue,
    };
    final glyph =
        icon ??
        switch (tone) {
          NoticeTone.error => Icons.error_outline_rounded,
          NoticeTone.warning => Icons.warning_amber_rounded,
          NoticeTone.success => Icons.check_circle_outline_rounded,
          NoticeTone.info => Icons.info_outline_rounded,
        };
    final heading = title;
    return Container(
      padding: const EdgeInsets.fromLTRB(14, 12, 10, 12),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: color.withValues(alpha: 0.24)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(glyph, color: color, size: 20),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (heading != null) ...[
                  Text(
                    heading,
                    style: text.titleSmall?.copyWith(
                      color: palette.ink,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  const SizedBox(height: 2),
                ],
                Text(
                  message,
                  style: text.bodySmall?.copyWith(
                    color: palette.inkMuted,
                    height: 1.4,
                  ),
                ),
              ],
            ),
          ),
          if (onClose != null)
            GestureDetector(
              onTap: onClose,
              behavior: HitTestBehavior.opaque,
              child: Padding(
                padding: const EdgeInsets.only(left: 4, top: 1),
                child: Icon(
                  Icons.close_rounded,
                  size: 18,
                  color: palette.inkSubtle,
                ),
              ),
            ),
        ],
      ),
    );
  }
}

/// Small rounded-square icon tile — a tinted background with a centred glyph.
/// The generic sibling of [CategoryAvatar]; used in list rows, sheet headers
/// and dialogs so iconography stays consistent across the app.
class IconTile extends StatelessWidget {
  const IconTile({
    super.key,
    required this.icon,
    required this.color,
    this.size = 44,
    this.solid = false,
  });

  final IconData icon;
  final Color color;
  final double size;

  /// When true the tile is a solid fill with a white glyph (for emphasis);
  /// otherwise a soft tint of [color].
  final bool solid;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        color: solid ? color : color.withValues(alpha: 0.13),
        borderRadius: BorderRadius.circular(size * 0.32),
      ),
      alignment: Alignment.center,
      child: Icon(icon, color: solid ? Colors.white : color, size: size * 0.48),
    );
  }
}

/// Generic status pill: a dot + label in a soft tinted (or solid) capsule.
/// [ReportStatusBadge] handles report statuses; this is for everything else
/// (active/inactive, counts, generic tags).
class StatusPill extends StatelessWidget {
  const StatusPill({
    super.key,
    required this.label,
    required this.color,
    this.showDot = true,
    this.solid = false,
  });

  final String label;
  final Color color;
  final bool showDot;
  final bool solid;

  @override
  Widget build(BuildContext context) {
    final fg = solid ? Colors.white : color;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: solid ? color : color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (showDot) ...[
            Container(
              width: 6,
              height: 6,
              decoration: BoxDecoration(color: fg, shape: BoxShape.circle),
            ),
            const SizedBox(width: 6),
          ],
          Text(
            label,
            style: Theme.of(context).textTheme.labelMedium?.copyWith(
              color: fg,
              fontWeight: FontWeight.w700,
              letterSpacing: 0.1,
            ),
          ),
        ],
      ),
    );
  }
}

/// Header for modal bottom sheets: an optional icon tile, a title and an
/// optional one-line subtitle. The drag handle is supplied by the theme.
class SheetHeader extends StatelessWidget {
  const SheetHeader({
    super.key,
    required this.title,
    this.subtitle,
    this.icon,
    this.iconColor,
  });

  final String title;
  final String? subtitle;
  final IconData? icon;
  final Color? iconColor;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final palette = context.palette;
    final sub = subtitle;
    return Row(
      crossAxisAlignment: CrossAxisAlignment.center,
      children: [
        if (icon != null) ...[
          IconTile(icon: icon!, color: iconColor ?? palette.accentCyan),
          const SizedBox(width: 14),
        ],
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(title, style: text.titleLarge),
              if (sub != null) ...[
                const SizedBox(height: 2),
                Text(sub, style: text.bodyMedium),
              ],
            ],
          ),
        ),
      ],
    );
  }
}

/// Tappable settings/action row: a tinted icon tile, title (+ optional
/// subtitle) and a trailing widget (defaults to a chevron). Designed to sit
/// inside a [GroupedCard].
class AppTile extends StatelessWidget {
  const AppTile({
    super.key,
    required this.icon,
    required this.title,
    this.subtitle,
    this.iconColor,
    this.titleColor,
    this.trailing,
    this.onTap,
  });

  final IconData icon;
  final String title;
  final String? subtitle;
  final Color? iconColor;
  final Color? titleColor;
  final Widget? trailing;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    final text = Theme.of(context).textTheme;
    final sub = subtitle;
    final tile = Padding(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      child: Row(
        children: [
          IconTile(
            icon: icon,
            color: iconColor ?? palette.accentCyan,
            size: 40,
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: text.titleMedium?.copyWith(color: titleColor),
                ),
                if (sub != null) ...[
                  const SizedBox(height: 2),
                  Text(
                    sub,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: text.bodySmall,
                  ),
                ],
              ],
            ),
          ),
          const SizedBox(width: 8),
          trailing ??
              (onTap != null
                  ? Icon(Icons.chevron_right_rounded, color: palette.inkSubtle)
                  : const SizedBox.shrink()),
        ],
      ),
    );

    if (onTap == null) return tile;
    return Material(
      color: Colors.transparent,
      child: InkWell(onTap: onTap, child: tile),
    );
  }
}

/// A single elevated surface that groups rows with hairline dividers between
/// them — the "settings group" pattern (iOS Settings / Linear). Children are
/// usually [AppTile]s but any widget works.
class GroupedCard extends StatelessWidget {
  const GroupedCard({super.key, required this.children, this.padding});

  final List<Widget> children;
  final EdgeInsets? padding;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    final rows = <Widget>[];
    for (var i = 0; i < children.length; i++) {
      if (i > 0) {
        rows.add(
          Divider(height: 1, thickness: 1, indent: 68, color: palette.border),
        );
      }
      rows.add(children[i]);
    }
    return Container(
      padding: padding,
      decoration: BoxDecoration(
        color: palette.surfaceElevated,
        borderRadius: BorderRadius.circular(AppTheme.rCard),
        border: Border.all(color: palette.border),
        boxShadow: AppTheme.softShadow,
      ),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(AppTheme.rCard),
        child: Column(mainAxisSize: MainAxisSize.min, children: rows),
      ),
    );
  }
}

/// Styled note-capture dialog used by moderation actions (verify, start work,
/// reject, recategorize/re-triage). Returns the trimmed text, or null if
/// dismissed. When
/// [requireText] is true the confirm button stays disabled until text is
/// entered.
Future<String?> showNoteDialog(
  BuildContext context, {
  required String title,
  String? message,
  String hint = 'Optional note',
  String confirmLabel = 'Confirm',
  String cancelLabel = 'Cancel',
  IconData icon = Icons.edit_note_rounded,
  Color? accentColor,
  bool requireText = false,
}) {
  final controller = TextEditingController();
  return showDialog<String?>(
    context: context,
    builder: (ctx) {
      final palette = ctx.palette;
      final text = Theme.of(ctx).textTheme;
      final accent = accentColor ?? palette.accentCyan;
      final msg = message;
      return AlertDialog(
        titlePadding: const EdgeInsets.fromLTRB(22, 22, 22, 0),
        contentPadding: const EdgeInsets.fromLTRB(22, 14, 22, 0),
        actionsPadding: const EdgeInsets.fromLTRB(16, 12, 16, 16),
        title: Row(
          children: [
            IconTile(icon: icon, color: accent, size: 38),
            const SizedBox(width: 12),
            Expanded(child: Text(title)),
          ],
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (msg != null) ...[
              Text(msg, style: text.bodyMedium),
              const SizedBox(height: 14),
            ],
            TextField(
              controller: controller,
              autofocus: true,
              minLines: 2,
              maxLines: 5,
              textInputAction: TextInputAction.newline,
              decoration: InputDecoration(hintText: hint),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, null),
            child: Text(cancelLabel),
          ),
          ValueListenableBuilder<TextEditingValue>(
            valueListenable: controller,
            builder: (ctx, value, _) {
              final enabled = !requireText || value.text.trim().isNotEmpty;
              return FilledButton(
                onPressed: enabled
                    ? () => Navigator.pop(ctx, controller.text.trim())
                    : null,
                style: FilledButton.styleFrom(
                  backgroundColor: accent,
                  minimumSize: const Size(0, 44),
                ),
                child: Text(confirmLabel),
              );
            },
          ),
        ],
      );
    },
  );
}

class ReportStatusBadge extends StatelessWidget {
  const ReportStatusBadge(this.status, {super.key, this.onDarkSurface = false});

  final ReportStatus status;

  /// When true, renders a solid-fill pill with white text — readable on dark
  /// hero backgrounds. Default (false) keeps the subtle tinted pill used in
  /// list rows and cards.
  final bool onDarkSurface;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    final color = status.color(palette);

    if (onDarkSurface) {
      return Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
        decoration: BoxDecoration(
          color: color,
          borderRadius: BorderRadius.circular(999),
        ),
        child: Text(
          status.localized(context.l10n),
          style: Theme.of(context).textTheme.labelMedium?.copyWith(
            color: Colors.white,
            fontWeight: FontWeight.w700,
            letterSpacing: 0.2,
          ),
        ),
      );
    }

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 6,
            height: 6,
            decoration: BoxDecoration(color: color, shape: BoxShape.circle),
          ),
          const SizedBox(width: 6),
          Text(
            status.localized(context.l10n),
            style: Theme.of(context).textTheme.labelMedium?.copyWith(
              color: color,
              fontWeight: FontWeight.w700,
            ),
          ),
        ],
      ),
    );
  }
}

class EmptyStateCard extends StatelessWidget {
  const EmptyStateCard({
    super.key,
    required this.icon,
    required this.title,
    required this.message,
    this.action,
  });

  final IconData icon;
  final String title;
  final String message;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    return SectionCard(
      padding: const EdgeInsets.all(22),
      child: Column(
        children: [
          Container(
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(
              color: palette.accentCyan.withValues(alpha: 0.1),
              shape: BoxShape.circle,
            ),
            child: Icon(icon, size: 28, color: palette.accentCyan),
          ),
          const SizedBox(height: 14),
          Text(title, style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 6),
          Text(
            message,
            textAlign: TextAlign.center,
            style: Theme.of(context).textTheme.bodyMedium,
          ),
          if (action != null) ...[const SizedBox(height: 16), action!],
        ],
      ),
    );
  }
}

class ReportListTileCard extends StatelessWidget {
  const ReportListTileCard({
    super.key,
    required this.report,
    required this.onTap,
  });

  final CityReport report;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final palette = context.palette;
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(22),
        child: Ink(
          decoration: BoxDecoration(
            color: palette.surfaceElevated,
            borderRadius: BorderRadius.circular(22),
            border: Border.all(color: palette.border),
          ),
          padding: const EdgeInsets.all(14),
          child: IntrinsicHeight(
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // Agency-coloured accent so a wall of reports is scannable by
                // category at a glance.
                Container(
                  width: 4,
                  decoration: BoxDecoration(
                    color: report.category.color,
                    borderRadius: BorderRadius.circular(4),
                  ),
                ),
                const SizedBox(width: 12),
                ClipRRect(
                  borderRadius: BorderRadius.circular(16),
                  child: SmartCityImage(
                    imagePath: report.imageUrl,
                    width: 68,
                    height: 68,
                  ),
                ),
                const SizedBox(width: 14),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        report.category.label,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: text.titleMedium,
                      ),
                      const SizedBox(height: 4),
                      Text(
                        report.address,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: text.bodyMedium,
                      ),
                      const SizedBox(height: 10),
                      Row(
                        children: [
                          ReportStatusBadge(report.status),
                          const Spacer(),
                          Text(
                            DateFormat('MMM d').format(report.createdAt),
                            style: text.labelMedium,
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class ProfileAvatar extends StatelessWidget {
  const ProfileAvatar({
    super.key,
    this.imageUrl,
    required this.fallbackText,
    this.radius = 24,
    this.onDarkSurface = false,
  });

  final String? imageUrl;
  final String fallbackText;
  final double radius;

  /// When true, the initials tile uses a white background with deep-blue text
  /// so it keeps WCAG 4.5:1 contrast over the gradient header.
  final bool onDarkSurface;

  @override
  Widget build(BuildContext context) {
    final value = imageUrl;
    if (value != null && value.isNotEmpty) {
      if (StorageUrls.isStorageRef(value)) {
        return FutureBuilder<String>(
          future: StorageUrls.signed(value),
          builder: (context, snapshot) {
            final url = snapshot.data;
            if (url == null || url.isEmpty) return _initials(context);
            return _avatar(CachedNetworkImageProvider(url));
          },
        );
      }
      return _avatar(FileImage(File(value)));
    }
    return _initials(context);
  }

  Widget _avatar(ImageProvider provider) {
    if (!onDarkSurface) {
      return CircleAvatar(radius: radius, backgroundImage: provider);
    }
    // Thin white ring to separate the photo from a coloured background.
    return Container(
      padding: const EdgeInsets.all(2),
      decoration: const BoxDecoration(
        color: Colors.white,
        shape: BoxShape.circle,
      ),
      child: CircleAvatar(radius: radius, backgroundImage: provider),
    );
  }

  Widget _initials(BuildContext context) {
    final initials = fallbackText
        .split(' ')
        .where((part) => part.isNotEmpty)
        .take(2)
        .map((part) => part[0].toUpperCase())
        .join();
    final palette = context.palette;
    final bg = onDarkSurface
        ? Colors.white
        : palette.accentCyan.withValues(alpha: 0.16);
    final fg = onDarkSurface ? palette.accentBlue : palette.accentCyan;
    return CircleAvatar(
      radius: radius,
      backgroundColor: bg,
      child: Text(
        initials.isEmpty ? '?' : initials,
        style: Theme.of(context).textTheme.titleMedium?.copyWith(
          color: fg,
          fontWeight: FontWeight.w800,
        ),
      ),
    );
  }
}

class SmartCityImage extends StatelessWidget {
  const SmartCityImage({
    super.key,
    required this.imagePath,
    this.width,
    this.height,
    this.fit = BoxFit.cover,
    this.borderRadius,
  });

  final String imagePath;
  final double? width;
  final double? height;
  final BoxFit fit;
  final BorderRadius? borderRadius;

  @override
  Widget build(BuildContext context) {
    Widget placeholder() => _ImagePlaceholder(width: width, height: height);

    Widget child;
    if (imagePath.trim().isEmpty) {
      child = placeholder();
    } else if (StorageUrls.isStorageRef(imagePath)) {
      child = FutureBuilder<String>(
        future: StorageUrls.signed(imagePath),
        builder: (context, snapshot) {
          final url = snapshot.data;
          if (url == null || url.isEmpty) return placeholder();
          return CachedNetworkImage(
            imageUrl: url,
            width: width,
            height: height,
            fit: fit,
            errorWidget: (_, _, _) => placeholder(),
          );
        },
      );
    } else {
      // Decode only as many pixels as we'll paint. Source photos are ~1280px;
      // a 72px list thumbnail otherwise inflates a full-size bitmap into memory.
      final dpr = MediaQuery.devicePixelRatioOf(context);
      final requestedWidth = width;
      final targetWidth = requestedWidth != null && requestedWidth.isFinite
          ? requestedWidth
          : MediaQuery.sizeOf(context).width;
      final scaledWidth = targetWidth * dpr;
      child = Image.file(
        File(imagePath),
        width: width,
        height: height,
        fit: fit,
        cacheWidth: scaledWidth.isFinite && scaledWidth > 0
            ? scaledWidth.round().clamp(1, 8192)
            : null,
        errorBuilder: (_, _, _) => placeholder(),
      );
    }

    if (borderRadius == null) return child;
    return ClipRRect(borderRadius: borderRadius!, child: child);
  }
}

/// Password input with a tap-to-reveal eye icon.
/// Visibility state is local — a parent rebuild does not reset it.
class PasswordField extends StatefulWidget {
  const PasswordField({
    super.key,
    required this.controller,
    this.label = 'Password',
    this.prefixIcon = Icons.lock_outline_rounded,
    this.validator,
    this.textInputAction,
    this.onFieldSubmitted,
    this.autofillHints,
  });

  final TextEditingController controller;
  final String label;
  final IconData prefixIcon;
  final String? Function(String?)? validator;
  final TextInputAction? textInputAction;
  final ValueChanged<String>? onFieldSubmitted;
  final Iterable<String>? autofillHints;

  @override
  State<PasswordField> createState() => _PasswordFieldState();
}

class _PasswordFieldState extends State<PasswordField> {
  bool _obscure = true;

  @override
  Widget build(BuildContext context) {
    return TextFormField(
      controller: widget.controller,
      obscureText: _obscure,
      autofillHints: widget.autofillHints,
      textInputAction: widget.textInputAction,
      onFieldSubmitted: widget.onFieldSubmitted,
      validator: widget.validator,
      decoration: InputDecoration(
        labelText: widget.label,
        prefixIcon: Icon(widget.prefixIcon),
        suffixIcon: IconButton(
          tooltip: _obscure ? 'Show password' : 'Hide password',
          icon: Icon(
            _obscure
                ? Icons.visibility_outlined
                : Icons.visibility_off_outlined,
          ),
          onPressed: () => setState(() => _obscure = !_obscure),
        ),
      ),
    );
  }
}

class _ImagePlaceholder extends StatelessWidget {
  const _ImagePlaceholder({this.width, this.height});

  final double? width;
  final double? height;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    return Container(
      width: width,
      height: height,
      color: palette.surfaceMuted,
      alignment: Alignment.center,
      child: Icon(Icons.image_outlined, color: palette.inkSubtle),
    );
  }
}

// ─────────────────────── Category + raw model-score kit ──────────────────────
//
// Each agency owns one hue. The numeric ring is the model's maximum class score,
// not calibrated correctness probability. Review status comes from the backend
// contract and is never inferred from these display-only score bands.

extension IssueCategoryVisuals on IssueCategory {
  /// One saturated brand hue per agency. Used for chips, avatars and accents.
  Color get color => switch (this) {
    IssueCategory.dinasBinaMarga => const Color(0xFFEA580C), // orange — roads
    IssueCategory.satpolPP => const Color(0xFF4F46E5), // indigo — public order
    IssueCategory.dinasPerhubungan => const Color(0xFF2563EB), // blue — transit
    IssueCategory.kelurahan => const Color(0xFF0D9488), // teal — admin office
    IssueCategory.dinasPertamananHutan => const Color(0xFF16A34A), // green
    IssueCategory.dinasSDA => const Color(0xFF0891B2), // cyan — water
    IssueCategory.dinasCiptaKarya => const Color(
      0xFF7C3AED,
    ), // violet — spatial
    IssueCategory.badanBUMD => const Color(0xFFDB2777), // pink — enterprise
    IssueCategory.instansiLain => const Color(0xFF64748B), // slate — other
  };

  IconData get glyph => switch (this) {
    IssueCategory.dinasBinaMarga => Icons.add_road_rounded,
    IssueCategory.satpolPP => Icons.shield_rounded,
    IssueCategory.dinasPerhubungan => Icons.directions_bus_rounded,
    IssueCategory.kelurahan => Icons.account_balance_rounded,
    IssueCategory.dinasPertamananHutan => Icons.park_rounded,
    IssueCategory.dinasSDA => Icons.water_drop_rounded,
    IssueCategory.dinasCiptaKarya => Icons.apartment_rounded,
    IssueCategory.badanBUMD => Icons.business_center_rounded,
    IssueCategory.instansiLain => Icons.more_horiz_rounded,
  };
}

extension ReportStatusVisuals on ReportStatus {
  Color color(AppPalette palette) => switch (this) {
    ReportStatus.submitted => palette.accentCyan,
    ReportStatus.verified => palette.success,
    ReportStatus.inProgress => palette.warning,
    ReportStatus.resolved => const Color(0xFF16A34A),
    ReportStatus.rejected => palette.danger,
  };
}

/// Rounded-square agency badge: a tinted tile with the agency hue + glyph.
class CategoryAvatar extends StatelessWidget {
  const CategoryAvatar({super.key, required this.category, this.size = 48});

  final IssueCategory category;
  final double size;

  @override
  Widget build(BuildContext context) {
    final color = category.color;
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.14),
        borderRadius: BorderRadius.circular(size * 0.3),
      ),
      alignment: Alignment.center,
      child: Icon(category.glyph, color: color, size: size * 0.5),
    );
  }
}

enum ConfidenceLevel {
  high,
  medium,
  low;

  /// Display-only bins. They must not be used as review or routing policy.
  static ConfidenceLevel of(double value) => value >= 0.70
      ? ConfidenceLevel.high
      : value >= 0.45
      ? ConfidenceLevel.medium
      : ConfidenceLevel.low;

  Color color(AppPalette palette) => palette.accentCyan;

  String label(AppLocalizations l) => switch (this) {
    ConfidenceLevel.high => l.confidenceHigh,
    ConfidenceLevel.medium => l.confidenceMedium,
    ConfidenceLevel.low => l.confidenceLow,
  };
}

/// Circular gauge for the uncalibrated top-class model score.
class ConfidenceRing extends StatelessWidget {
  const ConfidenceRing({
    super.key,
    required this.value,
    this.size = 88,
    this.strokeWidth = 9,
  });

  final double value;
  final double size;
  final double strokeWidth;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    final clamped = value.clamp(0.0, 1.0);
    final color = ConfidenceLevel.of(clamped).color(palette);
    return SizedBox(
      width: size,
      height: size,
      child: CustomPaint(
        painter: _RingPainter(
          value: clamped,
          color: color,
          track: palette.surfaceMuted,
          strokeWidth: strokeWidth,
        ),
        child: Center(
          child: Text(
            '${(clamped * 100).round()}%',
            style: GoogleFonts.plusJakartaSans(
              fontSize: size * 0.26,
              fontWeight: FontWeight.w800,
              letterSpacing: -0.5,
              color: palette.ink,
              height: 1,
            ),
          ),
        ),
      ),
    );
  }
}

class _RingPainter extends CustomPainter {
  _RingPainter({
    required this.value,
    required this.color,
    required this.track,
    required this.strokeWidth,
  });

  final double value;
  final Color color;
  final Color track;
  final double strokeWidth;

  @override
  void paint(Canvas canvas, Size size) {
    final center = size.center(Offset.zero);
    final radius = (size.shortestSide - strokeWidth) / 2;
    final trackPaint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = strokeWidth
      ..color = track;
    final valuePaint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = strokeWidth
      ..strokeCap = StrokeCap.round
      ..color = color;

    canvas.drawCircle(center, radius, trackPaint);
    canvas.drawArc(
      Rect.fromCircle(center: center, radius: radius),
      -1.5707963, // 12 o'clock
      6.2831853 * value, // 2π · value
      false,
      valuePaint,
    );
  }

  @override
  bool shouldRepaint(_RingPainter old) =>
      old.value != value || old.color != color || old.track != track;
}
