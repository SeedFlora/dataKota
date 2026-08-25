import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

class AppTheme {
  /// Resting elevation for cards and grouped surfaces. A single soft, low
  /// shadow (à la Stripe / Linear) reads as "paper lifted a hair off the page"
  /// — depth without the heavy Material drop-shadow.
  static const List<BoxShadow> softShadow = [
    BoxShadow(
      color: Color(0x0F101828), // slate-900 @ ~6%
      blurRadius: 16,
      offset: Offset(0, 6),
    ),
    BoxShadow(
      color: Color(0x0A101828), // slate-900 @ ~4%
      blurRadius: 4,
      offset: Offset(0, 1),
    ),
  ];

  /// Lighter shadow for interactive rows / pressables.
  static const List<BoxShadow> hairShadow = [
    BoxShadow(color: Color(0x0A101828), blurRadius: 10, offset: Offset(0, 4)),
  ];

  // Shared radius scale — pills are fully round, cards 20, controls 14.
  static const double rPill = 999;
  static const double rCard = 20;
  static const double rControl = 14;
  static const double rSheet = 28;

  static ThemeData get lightTheme {
    const palette = AppPalette.light;
    final base = GoogleFonts.plusJakartaSansTextTheme();

    return ThemeData(
      useMaterial3: true,
      scaffoldBackgroundColor: palette.surface,
      colorScheme: ColorScheme.fromSeed(
        seedColor: palette.accentCyan,
        primary: palette.accentCyan,
        onPrimary: Colors.white,
        secondary: palette.accentBlue,
        surface: palette.surfaceElevated,
        onSurface: palette.ink,
        surfaceContainerHighest: palette.surfaceMuted,
        outlineVariant: palette.border,
        error: palette.danger,
      ),
      textTheme: _textTheme(base, palette),
      appBarTheme: AppBarTheme(
        backgroundColor: palette.surface,
        surfaceTintColor: Colors.transparent,
        foregroundColor: palette.ink,
        elevation: 0,
        scrolledUnderElevation: 0,
        centerTitle: false,
        titleTextStyle: GoogleFonts.plusJakartaSans(
          fontSize: 20,
          fontWeight: FontWeight.w700,
          color: palette.ink,
          letterSpacing: -0.2,
        ),
      ),
      cardTheme: CardThemeData(
        elevation: 0,
        color: palette.surfaceElevated,
        surfaceTintColor: Colors.transparent,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(rCard),
          side: BorderSide(color: palette.border),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: palette.surfaceMuted.withValues(alpha: 0.55),
        hintStyle: TextStyle(color: palette.inkSubtle, fontSize: 15),
        labelStyle: TextStyle(color: palette.inkMuted, fontSize: 15),
        floatingLabelStyle: TextStyle(
          color: palette.accentCyan,
          fontWeight: FontWeight.w600,
        ),
        border: _inputBorder(Colors.transparent),
        enabledBorder: _inputBorder(palette.border),
        focusedBorder: _inputBorder(palette.accentCyan, width: 1.5),
        errorBorder: _inputBorder(palette.danger),
        focusedErrorBorder: _inputBorder(palette.danger, width: 1.5),
        contentPadding: const EdgeInsets.symmetric(
          horizontal: 16,
          vertical: 15,
        ),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          minimumSize: const Size.fromHeight(52),
          backgroundColor: palette.accentCyan,
          foregroundColor: Colors.white,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(rControl),
          ),
          textStyle: const TextStyle(
            fontSize: 15,
            fontWeight: FontWeight.w700,
            letterSpacing: 0.1,
          ),
        ),
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          elevation: 0,
          minimumSize: const Size.fromHeight(52),
          backgroundColor: palette.accentCyan,
          foregroundColor: Colors.white,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(rControl),
          ),
          textStyle: const TextStyle(
            fontSize: 15,
            fontWeight: FontWeight.w700,
            letterSpacing: 0.1,
          ),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          minimumSize: const Size.fromHeight(52),
          foregroundColor: palette.ink,
          side: BorderSide(color: palette.border),
          backgroundColor: palette.surfaceElevated,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(rControl),
          ),
          textStyle: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600),
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(
          foregroundColor: palette.accentCyan,
          textStyle: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600),
        ),
      ),
      chipTheme: ChipThemeData(
        backgroundColor: palette.surfaceMuted,
        selectedColor: palette.accentCyan,
        disabledColor: palette.surfaceMuted,
        side: BorderSide(color: palette.border),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(rPill),
        ),
        labelStyle: TextStyle(fontWeight: FontWeight.w600, color: palette.ink),
        secondaryLabelStyle: const TextStyle(
          fontWeight: FontWeight.w700,
          color: Colors.white,
        ),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        showCheckmark: false,
      ),
      dialogTheme: DialogThemeData(
        backgroundColor: palette.surfaceElevated,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(rCard + 4),
        ),
        insetPadding: const EdgeInsets.symmetric(horizontal: 28, vertical: 24),
        titleTextStyle: GoogleFonts.plusJakartaSans(
          fontSize: 19,
          fontWeight: FontWeight.w700,
          color: palette.ink,
          letterSpacing: -0.2,
        ),
        contentTextStyle: GoogleFonts.plusJakartaSans(
          fontSize: 14.5,
          height: 1.5,
          color: palette.inkMuted,
        ),
      ),
      bottomSheetTheme: BottomSheetThemeData(
        backgroundColor: palette.surfaceElevated,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        modalBarrierColor: palette.ink.withValues(alpha: 0.45),
        showDragHandle: true,
        dragHandleColor: palette.border,
        dragHandleSize: const Size(40, 4),
        shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(rSheet)),
        ),
      ),
      popupMenuTheme: PopupMenuThemeData(
        color: palette.surfaceElevated,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(16),
          side: BorderSide(color: palette.border),
        ),
        textStyle: GoogleFonts.plusJakartaSans(
          fontSize: 14,
          fontWeight: FontWeight.w600,
          color: palette.ink,
        ),
      ),
      dividerTheme: DividerThemeData(
        color: palette.border,
        thickness: 1,
        space: 1,
      ),
      navigationBarTheme: NavigationBarThemeData(
        elevation: 0,
        height: 64,
        backgroundColor: palette.surfaceElevated,
        surfaceTintColor: Colors.transparent,
        indicatorColor: palette.accentCyan.withValues(alpha: 0.12),
        labelBehavior: NavigationDestinationLabelBehavior.alwaysShow,
        labelTextStyle: WidgetStateProperty.resolveWith(
          (states) => TextStyle(
            fontSize: 12,
            fontWeight: states.contains(WidgetState.selected)
                ? FontWeight.w700
                : FontWeight.w500,
            color: states.contains(WidgetState.selected)
                ? palette.ink
                : palette.inkMuted,
          ),
        ),
        iconTheme: WidgetStateProperty.resolveWith(
          (states) => IconThemeData(
            color: states.contains(WidgetState.selected)
                ? palette.accentCyan
                : palette.inkMuted,
            size: 24,
          ),
        ),
      ),
      floatingActionButtonTheme: FloatingActionButtonThemeData(
        backgroundColor: palette.accentCyan,
        foregroundColor: Colors.white,
        elevation: 3,
        highlightElevation: 6,
        extendedTextStyle: const TextStyle(
          fontSize: 15,
          fontWeight: FontWeight.w700,
          letterSpacing: 0.1,
        ),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
      ),
      snackBarTheme: SnackBarThemeData(
        behavior: SnackBarBehavior.floating,
        backgroundColor: palette.ink,
        contentTextStyle: const TextStyle(
          color: Colors.white,
          fontWeight: FontWeight.w500,
        ),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(rControl),
        ),
      ),
      dividerColor: palette.border,
      extensions: const [palette],
    );
  }

  static TextTheme _textTheme(TextTheme base, AppPalette palette) {
    TextStyle display(double size, {double spacing = -0.3}) =>
        GoogleFonts.plusJakartaSans(
          fontSize: size,
          fontWeight: FontWeight.w800,
          color: palette.ink,
          letterSpacing: spacing,
        );

    return base.copyWith(
      headlineLarge: display(30),
      headlineMedium: display(26),
      // Greeting / primary header title: 24px semi-bold per the redesign spec.
      headlineSmall: GoogleFonts.plusJakartaSans(
        fontSize: 24,
        fontWeight: FontWeight.w700,
        color: palette.ink,
        letterSpacing: -0.2,
      ),
      titleLarge: GoogleFonts.plusJakartaSans(
        fontSize: 18,
        fontWeight: FontWeight.w700,
        color: palette.ink,
        letterSpacing: -0.1,
      ),
      titleMedium: base.titleMedium?.copyWith(
        fontSize: 16,
        fontWeight: FontWeight.w700,
        color: palette.ink,
      ),
      titleSmall: base.titleSmall?.copyWith(
        fontSize: 13,
        fontWeight: FontWeight.w600,
        color: palette.inkMuted,
      ),
      bodyLarge: base.bodyLarge?.copyWith(
        fontSize: 15,
        height: 1.5,
        color: palette.ink,
      ),
      bodyMedium: base.bodyMedium?.copyWith(
        fontSize: 14,
        height: 1.5,
        color: palette.inkMuted,
      ),
      bodySmall: base.bodySmall?.copyWith(
        fontSize: 12,
        height: 1.45,
        color: palette.inkSubtle,
      ),
      labelLarge: base.labelLarge?.copyWith(
        fontSize: 13,
        fontWeight: FontWeight.w700,
        color: palette.ink,
      ),
      labelMedium: base.labelMedium?.copyWith(
        fontSize: 12,
        fontWeight: FontWeight.w500,
        letterSpacing: 1.0,
        color: palette.inkMuted,
      ),
    );
  }

  static OutlineInputBorder _inputBorder(Color color, {double width = 1}) {
    return OutlineInputBorder(
      borderRadius: BorderRadius.circular(16),
      borderSide: BorderSide(color: color, width: width),
    );
  }
}

@immutable
class AppPalette extends ThemeExtension<AppPalette> {
  const AppPalette({
    required this.surface,
    required this.surfaceElevated,
    required this.surfaceMuted,
    required this.border,
    required this.ink,
    required this.inkMuted,
    required this.inkSubtle,
    required this.accentCyan,
    required this.accentBlue,
    required this.accentTeal,
    required this.success,
    required this.warning,
    required this.danger,
  });

  static const light = AppPalette(
    surface: Color(0xFFFAF9F7),
    surfaceElevated: Colors.white,
    surfaceMuted: Color(0xFFF2F0EC),
    border: Color(0xFFEAE6DF),
    ink: Color(0xFF18191B),
    inkMuted: Color(0xFF6B6962),
    inkSubtle: Color(0xFF9C9A92),
    accentCyan: Color(0xFF0E7490),
    accentBlue: Color(0xFF1D4ED8),
    accentTeal: Color(0xFF0D9488),
    success: Color(0xFF15803D),
    warning: Color(0xFFD97706),
    danger: Color(0xFFDC2626),
  );

  final Color surface;
  final Color surfaceElevated;
  final Color surfaceMuted;
  final Color border;
  final Color ink;
  final Color inkMuted;
  final Color inkSubtle;
  final Color accentCyan;
  final Color accentBlue;
  final Color accentTeal;
  final Color success;
  final Color warning;
  final Color danger;

  @override
  ThemeExtension<AppPalette> copyWith({
    Color? surface,
    Color? surfaceElevated,
    Color? surfaceMuted,
    Color? border,
    Color? ink,
    Color? inkMuted,
    Color? inkSubtle,
    Color? accentCyan,
    Color? accentBlue,
    Color? accentTeal,
    Color? success,
    Color? warning,
    Color? danger,
  }) {
    return AppPalette(
      surface: surface ?? this.surface,
      surfaceElevated: surfaceElevated ?? this.surfaceElevated,
      surfaceMuted: surfaceMuted ?? this.surfaceMuted,
      border: border ?? this.border,
      ink: ink ?? this.ink,
      inkMuted: inkMuted ?? this.inkMuted,
      inkSubtle: inkSubtle ?? this.inkSubtle,
      accentCyan: accentCyan ?? this.accentCyan,
      accentBlue: accentBlue ?? this.accentBlue,
      accentTeal: accentTeal ?? this.accentTeal,
      success: success ?? this.success,
      warning: warning ?? this.warning,
      danger: danger ?? this.danger,
    );
  }

  @override
  ThemeExtension<AppPalette> lerp(covariant AppPalette? other, double t) {
    if (other == null) return this;
    Color l(Color a, Color b) => Color.lerp(a, b, t) ?? a;
    return AppPalette(
      surface: l(surface, other.surface),
      surfaceElevated: l(surfaceElevated, other.surfaceElevated),
      surfaceMuted: l(surfaceMuted, other.surfaceMuted),
      border: l(border, other.border),
      ink: l(ink, other.ink),
      inkMuted: l(inkMuted, other.inkMuted),
      inkSubtle: l(inkSubtle, other.inkSubtle),
      accentCyan: l(accentCyan, other.accentCyan),
      accentBlue: l(accentBlue, other.accentBlue),
      accentTeal: l(accentTeal, other.accentTeal),
      success: l(success, other.success),
      warning: l(warning, other.warning),
      danger: l(danger, other.danger),
    );
  }
}

extension AppPaletteX on BuildContext {
  AppPalette get palette => Theme.of(this).extension<AppPalette>()!;
}
