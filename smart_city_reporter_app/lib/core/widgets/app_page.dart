import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/theme/app_theme.dart';
import 'smart_city_ui.dart' show EmptyStateCard;

/// 8-point grid: 24px horizontal on phones, 32px on tablets/desktop.
EdgeInsets pagePadding(BuildContext context) {
  final width = MediaQuery.sizeOf(context).width;
  return EdgeInsets.symmetric(horizontal: width >= 520 ? 32 : 24, vertical: 16);
}

/// Standard scrollable page with safe-area, refresh, and bottom padding
/// that keeps content above the floating action button.
class AppPage extends StatelessWidget {
  const AppPage({
    super.key,
    required this.children,
    this.onRefresh,
    this.bottomPadding = 110,
    this.floatingActionButton,
  });

  final List<Widget> children;
  final Future<void> Function()? onRefresh;
  final double bottomPadding;
  final Widget? floatingActionButton;

  @override
  Widget build(BuildContext context) {
    final content = ListView(
      padding: pagePadding(context).copyWith(bottom: bottomPadding),
      children: children,
    );

    // Cap content width on tablets / web so cards don't stretch edge-to-edge
    // on a 10" screen. Phones (<720px) are unaffected by the constraint.
    final constrained = Align(
      alignment: Alignment.topCenter,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 720),
        child: content,
      ),
    );

    return Scaffold(
      backgroundColor: context.palette.surface,
      body: SafeArea(
        bottom: false,
        child: onRefresh == null
            ? constrained
            : RefreshIndicator(onRefresh: onRefresh!, child: constrained),
      ),
      floatingActionButton: floatingActionButton,
    );
  }
}

/// Unified renderer for a Riverpod [AsyncValue] that replaces the repeated
/// `async.when(data:, loading:, error:)` boilerplate. Keeps error UX
/// consistent across screens.
class AsyncView<T> extends StatelessWidget {
  const AsyncView({
    super.key,
    required this.value,
    required this.data,
    this.loading,
    this.errorTitle = 'Something went wrong',
    this.errorIcon = Icons.error_outline_rounded,
  });

  final AsyncValue<T> value;
  final Widget Function(T data) data;
  final Widget? loading;
  final String errorTitle;
  final IconData errorIcon;

  @override
  Widget build(BuildContext context) {
    return value.when(
      data: data,
      loading: () =>
          loading ??
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 40),
            child: Center(child: CircularProgressIndicator()),
          ),
      error: (error, _) => EmptyStateCard(
        icon: errorIcon,
        title: errorTitle,
        message: error.toString(),
      ),
    );
  }
}
