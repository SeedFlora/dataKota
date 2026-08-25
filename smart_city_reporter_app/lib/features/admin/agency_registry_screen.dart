import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/theme/app_theme.dart';
import '../../core/widgets/smart_city_ui.dart';
import '../auth/auth_repository.dart';
import '../auth/user_role.dart';
import '../reports/report_models.dart';
import 'agency_registry_repository.dart';

/// Super-admin-only CRUD over the `public.agencies` routing registry.
///
/// Writes hit Supabase (system of record). Applying them to the inference
/// server is intentionally a trusted backend/deployment operation; the mobile
/// binary never contains the server reload credential.
class AgencyRegistryScreen extends ConsumerWidget {
  const AgencyRegistryScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final role = ref.watch(currentUserRoleProvider);
    if (role is! SuperAdmin) {
      return Scaffold(
        appBar: AppBar(title: const Text('Registri Instansi')),
        body: const Padding(
          padding: EdgeInsets.all(16),
          child: EmptyStateCard(
            icon: Icons.lock_outline,
            title: 'Khusus Super Admin',
            message:
                'Hanya super admin yang dapat mengelola registri instansi.',
          ),
        ),
      );
    }

    final agenciesAsync = ref.watch(agencyRegistryListProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('Registri Instansi')),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => _openEditor(context, ref, null),
        icon: const Icon(Icons.add_rounded),
        label: const Text('Tambah'),
      ),
      body: agenciesAsync.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Padding(
          padding: const EdgeInsets.all(24),
          child: EmptyStateCard(
            icon: Icons.cloud_off_rounded,
            title: 'Gagal memuat registri',
            message: '$e',
            action: FilledButton.icon(
              onPressed: () => ref.invalidate(agencyRegistryListProvider),
              icon: const Icon(Icons.refresh_rounded),
              label: const Text('Coba lagi'),
            ),
          ),
        ),
        data: (agencies) {
          if (agencies.isEmpty) {
            return const Padding(
              padding: EdgeInsets.all(24),
              child: EmptyStateCard(
                icon: Icons.account_balance_outlined,
                title: 'Belum ada instansi',
                message: 'Tambahkan kantor instansi tujuan routing.',
              ),
            );
          }
          final activeCount = agencies.where((a) => a.isActive).length;
          return RefreshIndicator(
            onRefresh: () async => ref.invalidate(agencyRegistryListProvider),
            child: ListView.separated(
              padding: const EdgeInsets.fromLTRB(20, 12, 20, 104),
              itemCount: agencies.length + 1,
              separatorBuilder: (_, i) => SizedBox(height: i == 0 ? 14 : 12),
              itemBuilder: (context, i) {
                if (i == 0) {
                  return _RegistrySummary(
                    total: agencies.length,
                    active: activeCount,
                  );
                }
                final a = agencies[i - 1];
                return _AgencyCard(
                  agency: a,
                  onToggle: (v) => _setActive(context, ref, a, v),
                  onEdit: () => _openEditor(context, ref, a),
                  onDelete: () => _confirmDelete(context, ref, a),
                );
              },
            ),
          );
        },
      ),
    );
  }

  Future<void> _setActive(
    BuildContext context,
    WidgetRef ref,
    Agency a,
    bool value,
  ) async {
    final messenger = ScaffoldMessenger.of(context);
    try {
      await ref
          .read(agencyRegistryRepositoryProvider)
          .setActive(a.id, isActive: value);
      ref.invalidate(agencyRegistryListProvider);
    } catch (e) {
      messenger.showSnackBar(SnackBar(content: Text('Gagal memperbarui: $e')));
    }
  }

  Future<void> _confirmDelete(
    BuildContext context,
    WidgetRef ref,
    Agency a,
  ) async {
    final messenger = ScaffoldMessenger.of(context);
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Hapus instansi?'),
        content: Text('"${a.name}" akan dihapus dari registri.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Batal'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Hapus'),
          ),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await ref.read(agencyRegistryRepositoryProvider).delete(a.id);
      ref.invalidate(agencyRegistryListProvider);
    } catch (e) {
      messenger.showSnackBar(SnackBar(content: Text('Gagal menghapus: $e')));
    }
  }

  Future<void> _openEditor(
    BuildContext context,
    WidgetRef ref,
    Agency? existing,
  ) async {
    final saved = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      builder: (_) => _AgencyEditSheet(existing: existing),
    );
    if (saved == true) ref.invalidate(agencyRegistryListProvider);
  }
}

/// Compact "x of y active" strip above the list.
class _RegistrySummary extends StatelessWidget {
  const _RegistrySummary({required this.total, required this.active});

  final int total;
  final int active;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    final text = Theme.of(context).textTheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Text(
              '$total instansi',
              style: text.titleMedium?.copyWith(color: palette.ink),
            ),
            const SizedBox(width: 8),
            Container(
              width: 3,
              height: 3,
              decoration: BoxDecoration(
                color: palette.inkSubtle,
                shape: BoxShape.circle,
              ),
            ),
            const SizedBox(width: 8),
            Text('$active aktif', style: text.bodyMedium),
            const Spacer(),
            Icon(Icons.swipe_down_rounded, size: 16, color: palette.inkSubtle),
            const SizedBox(width: 4),
            Text('tarik untuk muat ulang', style: text.bodySmall),
          ],
        ),
        const SizedBox(height: 8),
        Text(
          'Sinkronisasi ke server routing dijalankan oleh backend tepercaya, bukan dari aplikasi.',
          style: text.bodySmall?.copyWith(color: palette.inkSubtle),
        ),
      ],
    );
  }
}

/// Icon-tile registry row: tinted agency glyph, name + category + coordinates,
/// an active/inactive pill, an inline switch and an overflow menu.
class _AgencyCard extends StatelessWidget {
  const _AgencyCard({
    required this.agency,
    required this.onToggle,
    required this.onEdit,
    required this.onDelete,
  });

  final Agency agency;
  final ValueChanged<bool> onToggle;
  final VoidCallback onEdit;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    final text = Theme.of(context).textTheme;
    final hasCoords = agency.latitude != null && agency.longitude != null;
    final coords = hasCoords
        ? '${agency.latitude!.toStringAsFixed(4)}, ${agency.longitude!.toStringAsFixed(4)}'
        : 'Koordinat belum diatur';
    final active = agency.isActive;

    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onEdit,
        borderRadius: BorderRadius.circular(AppTheme.rCard),
        child: Ink(
          decoration: BoxDecoration(
            color: palette.surfaceElevated,
            borderRadius: BorderRadius.circular(AppTheme.rCard),
            border: Border.all(color: palette.border),
            boxShadow: AppTheme.softShadow,
          ),
          padding: const EdgeInsets.fromLTRB(14, 14, 6, 14),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Opacity(
                    opacity: active ? 1 : 0.45,
                    child: CategoryAvatar(category: agency.category, size: 46),
                  ),
                  const SizedBox(width: 14),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          agency.name,
                          style: text.titleMedium,
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                        ),
                        const SizedBox(height: 3),
                        Text(
                          agency.category.label,
                          style: text.bodySmall,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                        ),
                      ],
                    ),
                  ),
                  PopupMenuButton<String>(
                    tooltip: 'Aksi',
                    icon: Icon(
                      Icons.more_vert_rounded,
                      color: palette.inkMuted,
                    ),
                    onSelected: (v) {
                      if (v == 'edit') onEdit();
                      if (v == 'delete') onDelete();
                    },
                    itemBuilder: (_) => [
                      const PopupMenuItem(
                        value: 'edit',
                        child: Row(
                          children: [
                            Icon(Icons.edit_outlined, size: 20),
                            SizedBox(width: 12),
                            Text('Ubah'),
                          ],
                        ),
                      ),
                      PopupMenuItem(
                        value: 'delete',
                        child: Row(
                          children: [
                            Icon(
                              Icons.delete_outline_rounded,
                              size: 20,
                              color: palette.danger,
                            ),
                            const SizedBox(width: 12),
                            Text(
                              'Hapus',
                              style: TextStyle(color: palette.danger),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ],
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  Icon(
                    Icons.place_outlined,
                    size: 15,
                    color: palette.inkSubtle,
                  ),
                  const SizedBox(width: 4),
                  Expanded(
                    child: Text(
                      coords,
                      style: text.bodySmall?.copyWith(
                        color: hasCoords ? palette.inkMuted : palette.warning,
                      ),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                  const SizedBox(width: 8),
                  StatusPill(
                    label: active ? 'Aktif' : 'Nonaktif',
                    color: active ? palette.success : palette.inkSubtle,
                  ),
                  const SizedBox(width: 6),
                  Transform.scale(
                    scale: 0.82,
                    child: Switch(value: active, onChanged: onToggle),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _AgencyEditSheet extends ConsumerStatefulWidget {
  const _AgencyEditSheet({this.existing});

  final Agency? existing;

  @override
  ConsumerState<_AgencyEditSheet> createState() => _AgencyEditSheetState();
}

class _AgencyEditSheetState extends ConsumerState<_AgencyEditSheet> {
  final _formKey = GlobalKey<FormState>();
  late final TextEditingController _id;
  late final TextEditingController _name;
  late final TextEditingController _lat;
  late final TextEditingController _lng;
  late IssueCategory _category;
  late bool _active;
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    final e = widget.existing;
    _id = TextEditingController(text: e?.id ?? '');
    _name = TextEditingController(text: e?.name ?? '');
    _lat = TextEditingController(text: e?.latitude?.toString() ?? '');
    _lng = TextEditingController(text: e?.longitude?.toString() ?? '');
    _category = e?.category ?? IssueCategory.values.first;
    _active = e?.isActive ?? true;
  }

  @override
  void dispose() {
    _id.dispose();
    _name.dispose();
    _lat.dispose();
    _lng.dispose();
    super.dispose();
  }

  String? _numValidator(String? v) {
    if (v == null || v.trim().isEmpty) return 'Wajib diisi';
    return double.tryParse(v.trim()) == null ? 'Angka tidak valid' : null;
  }

  Future<void> _save() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() => _saving = true);
    final messenger = ScaffoldMessenger.of(context);
    try {
      final agency = Agency(
        id: _id.text.trim(),
        name: _name.text.trim(),
        category: _category,
        latitude: double.tryParse(_lat.text.trim()),
        longitude: double.tryParse(_lng.text.trim()),
        isActive: _active,
      );
      await ref.read(agencyRegistryRepositoryProvider).save(agency);
      if (mounted) Navigator.pop(context, true);
    } catch (e) {
      messenger.showSnackBar(SnackBar(content: Text('Gagal menyimpan: $e')));
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final isNew = widget.existing == null;
    final palette = context.palette;
    return Padding(
      padding: EdgeInsets.only(
        left: 20,
        right: 20,
        top: 4,
        bottom: MediaQuery.of(context).viewInsets.bottom + 20,
      ),
      child: SingleChildScrollView(
        child: Form(
          key: _formKey,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              SheetHeader(
                icon: isNew ? Icons.add_business_rounded : _category.glyph,
                iconColor: isNew ? palette.accentCyan : _category.color,
                title: isNew ? 'Tambah Instansi' : 'Ubah Instansi',
                subtitle: isNew
                    ? 'Daftarkan kantor tujuan routing'
                    : widget.existing!.name,
              ),
              const SizedBox(height: 20),
              _FieldLabel('ID (slug unik)'),
              TextFormField(
                controller: _id,
                enabled: isNew,
                decoration: const InputDecoration(
                  hintText: 'mis. bina-marga-pusat',
                ),
                validator: (v) =>
                    (v == null || v.trim().isEmpty) ? 'Wajib diisi' : null,
              ),
              const SizedBox(height: 14),
              _FieldLabel('Nama kantor'),
              TextFormField(
                controller: _name,
                decoration: const InputDecoration(
                  hintText: 'mis. Dinas Bina Marga DKI Jakarta',
                ),
                validator: (v) =>
                    (v == null || v.trim().isEmpty) ? 'Wajib diisi' : null,
              ),
              const SizedBox(height: 14),
              _FieldLabel('Kategori instansi'),
              DropdownButtonFormField<IssueCategory>(
                initialValue: _category,
                isExpanded: true,
                decoration: const InputDecoration(),
                borderRadius: BorderRadius.circular(16),
                items: IssueCategory.values
                    .map(
                      (c) => DropdownMenuItem(
                        value: c,
                        child: Row(
                          children: [
                            Icon(c.glyph, size: 18, color: c.color),
                            const SizedBox(width: 10),
                            Flexible(
                              child: Text(
                                c.label,
                                overflow: TextOverflow.ellipsis,
                              ),
                            ),
                          ],
                        ),
                      ),
                    )
                    .toList(),
                onChanged: (v) => setState(() => _category = v ?? _category),
              ),
              const SizedBox(height: 14),
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        _FieldLabel('Latitude'),
                        TextFormField(
                          controller: _lat,
                          keyboardType: const TextInputType.numberWithOptions(
                            decimal: true,
                            signed: true,
                          ),
                          decoration: const InputDecoration(
                            hintText: '-6.1823',
                          ),
                          validator: _numValidator,
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        _FieldLabel('Longitude'),
                        TextFormField(
                          controller: _lng,
                          keyboardType: const TextInputType.numberWithOptions(
                            decimal: true,
                            signed: true,
                          ),
                          decoration: const InputDecoration(
                            hintText: '106.8113',
                          ),
                          validator: _numValidator,
                        ),
                      ],
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 16),
              _ActiveToggleRow(
                value: _active,
                onChanged: (v) => setState(() => _active = v),
              ),
              const SizedBox(height: 20),
              FilledButton.icon(
                onPressed: _saving ? null : _save,
                icon: _saving
                    ? const SizedBox(
                        width: 18,
                        height: 18,
                        child: CircularProgressIndicator(
                          strokeWidth: 2,
                          color: Colors.white,
                        ),
                      )
                    : Icon(isNew ? Icons.add_rounded : Icons.save_outlined),
                label: Text(isNew ? 'Tambah instansi' : 'Simpan perubahan'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Small uppercase field caption above an input.
class _FieldLabel extends StatelessWidget {
  const _FieldLabel(this.text);

  final String text;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    return Padding(
      padding: const EdgeInsets.only(left: 2, bottom: 6),
      child: Text(
        text,
        style: Theme.of(context).textTheme.labelMedium?.copyWith(
          color: palette.inkMuted,
          fontWeight: FontWeight.w600,
          letterSpacing: 0.2,
        ),
      ),
    );
  }
}

/// Active/inactive toggle styled as a tinted row rather than a bare
/// SwitchListTile.
class _ActiveToggleRow extends StatelessWidget {
  const _ActiveToggleRow({required this.value, required this.onChanged});

  final bool value;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    final text = Theme.of(context).textTheme;
    final color = value ? palette.success : palette.inkSubtle;
    return Container(
      padding: const EdgeInsets.fromLTRB(14, 10, 8, 10),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: color.withValues(alpha: 0.22)),
      ),
      child: Row(
        children: [
          Icon(
            value
                ? Icons.check_circle_rounded
                : Icons.pause_circle_outline_rounded,
            color: color,
            size: 22,
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Aktif untuk routing',
                  style: text.titleSmall?.copyWith(
                    color: palette.ink,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                Text(
                  value
                      ? 'Menerima laporan baru'
                      : 'Tidak menerima laporan baru',
                  style: text.bodySmall,
                ),
              ],
            ),
          ),
          Switch(value: value, onChanged: onChanged),
        ],
      ),
    );
  }
}
