import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import '../../core/config/app_config.dart';
import '../reports/report_models.dart';

/// One row of the `public.agencies` registry — the routing system of record.
///
/// `category` maps to the `issue_category` enum column (stored as the slug
/// [IssueCategory.dbValue]); the inference server converts it back to the
/// [IssueCategory.label] used by the nearest-agency routing algorithm.
class Agency {
  const Agency({
    required this.id,
    required this.name,
    required this.category,
    this.latitude,
    this.longitude,
    this.isActive = true,
  });

  final String id;
  final String name;
  final IssueCategory category;
  final double? latitude;
  final double? longitude;
  final bool isActive;

  factory Agency.fromMap(Map<String, dynamic> map) {
    return Agency(
      id: map['id'] as String,
      name: map['name'] as String? ?? '',
      category: IssueCategory.fromValue(map['category'] as String? ?? ''),
      latitude: (map['latitude'] as num?)?.toDouble(),
      longitude: (map['longitude'] as num?)?.toDouble(),
      isActive: map['is_active'] as bool? ?? true,
    );
  }

  Map<String, dynamic> toMap() => {
    'id': id,
    'name': name,
    'category': category.dbValue,
    'latitude': latitude,
    'longitude': longitude,
    'is_active': isActive,
  };
}

class AgencyRegistryRepository {
  AgencyRegistryRepository(this._client);

  final SupabaseClient _client;

  Future<List<Agency>> fetchAll() async {
    final rows = await _client
        .from('agencies')
        .select()
        .order('category')
        .order('name');
    return (rows as List)
        .map((r) => Agency.fromMap(Map<String, dynamic>.from(r as Map)))
        .toList(growable: false);
  }

  /// Insert or update (writes are gated to super_admin by the
  /// `agencies_write_super_admin` RLS policy, so a non-super-admin call fails).
  Future<void> save(Agency agency) async {
    await _client.from('agencies').upsert(agency.toMap());
  }

  Future<void> setActive(String id, {required bool isActive}) async {
    await _client.from('agencies').update({'is_active': isActive}).eq('id', id);
  }

  Future<void> delete(String id) async {
    await _client.from('agencies').delete().eq('id', id);
  }

  // Deliberately no direct /reload-agencies call here. That endpoint requires
  // a server-held credential; embedding it in a Flutter binary would disclose
  // the secret. Reload is a trusted deployment/Edge Function operation.
}

final agencyRegistryRepositoryProvider = Provider<AgencyRegistryRepository>((
  ref,
) {
  return AgencyRegistryRepository(ref.watch(supabaseClientProvider));
});

final agencyRegistryListProvider = FutureProvider<List<Agency>>((ref) {
  return ref.watch(agencyRegistryRepositoryProvider).fetchAll();
});
