-- Phase: make the agency registry the real source of truth for routing.
--
-- Motivation (thesis/viva consistency): the ERD and Bab 3 already describe
-- `public.agencies` as the agency registry referenced by report_assignments,
-- but (a) the table carried no coordinates (the 20260614 backfill seeded only
-- id/name/category from existing reports), and (b) `report_assignments.agency_id`
-- was plain text with no enforced foreign key despite the ERD showing
-- `<<FK agencies>>`. The routing-critical coordinates lived only in the
-- hardcoded Python list in serve_model.py.
--
-- This migration: (1) seeds `agencies` with the 16 offices + coordinates from
-- the single source of truth `smartCityReport/agencies_seed.json` (the same file
-- serve_model.py loads at startup), and (2) enforces the agency_id foreign key.
--
-- Idempotent: safe to re-run. Coordinates are PLACEHOLDER pending replacement
-- with official DKI Jakarta office coordinates; provenance lives in the JSON.

-- ===================================================================
-- 1. Seed / upsert the agency registry (keep in sync with agencies_seed.json)
-- ===================================================================

insert into public.agencies (id, name, category, latitude, longitude, is_active) values
  ('bina-marga-pusat',    'Dinas Bina Marga - Jakarta Pusat',                            'dinas_bina_marga',       -6.1823, 106.8113, true),
  ('bina-marga-selatan',  'Suku Dinas Bina Marga - Jakarta Selatan',                     'dinas_bina_marga',       -6.2491, 106.8080, true),
  ('bina-marga-timur',    'Suku Dinas Bina Marga - Jakarta Timur',                       'dinas_bina_marga',       -6.2140, 106.9447, true),
  ('satpol-pp-pusat',     'Satuan Polisi Pamong Praja - Jakarta Pusat',                  'satpol_pp',              -6.1813, 106.8286, true),
  ('satpol-pp-selatan',   'Satuan Polisi Pamong Praja - Jakarta Selatan',               'satpol_pp',              -6.2491, 106.8080, true),
  ('dishub-pusat',        'Dinas Perhubungan - Jakarta Pusat',                           'dinas_perhubungan',      -6.1823, 106.8113, true),
  ('dishub-timur',        'Suku Dinas Perhubungan - Jakarta Timur',                      'dinas_perhubungan',      -6.2140, 106.9447, true),
  ('kelurahan-pusat',     'Kelurahan Terdekat - Wilayah Jakarta Pusat',                  'kelurahan',              -6.1732, 106.8188, true),
  ('kelurahan-selatan',   'Kelurahan Terdekat - Wilayah Jakarta Selatan',               'kelurahan',              -6.2491, 106.8080, true),
  ('pertamanan-pusat',    'Dinas Pertamanan dan Hutan Kota - Jakarta Pusat',             'dinas_pertamanan_hutan', -6.1958, 106.8065, true),
  ('pertamanan-selatan',  'Suku Dinas Pertamanan dan Hutan Kota - Jakarta Selatan',      'dinas_pertamanan_hutan', -6.2491, 106.8080, true),
  ('sda-pusat',           'Dinas Sumber Daya Air - Jakarta Pusat',                       'dinas_sda',              -6.1823, 106.8113, true),
  ('sda-timur',           'Suku Dinas Sumber Daya Air - Jakarta Timur',                  'dinas_sda',              -6.2140, 106.9447, true),
  ('cipta-karya-pusat',   'Dinas Cipta Karya, Tata Ruang, dan Pertanahan - DKI Jakarta', 'dinas_cipta_karya',      -6.1823, 106.8113, true),
  ('bumd-pusat',          'Badan Pembinaan BUMD - DKI Jakarta',                          'badan_bumd',             -6.1813, 106.8286, true),
  ('review-manual',       'Unit Review Manual SmartCityApps',                            'instansi_lain',          -6.1813, 106.8286, false)
on conflict (id) do update set
  name        = excluded.name,
  category    = excluded.category,
  latitude    = excluded.latitude,
  longitude   = excluded.longitude,
  is_active   = excluded.is_active,
  updated_at  = timezone('utc', now());

-- ===================================================================
-- 2. Enforce the agency_id foreign key shown in the ERD
-- ===================================================================
-- Defensive: null out any orphan agency_id that has no matching registry row so
-- the constraint can be added cleanly (the denormalized agency_name/category on
-- the row are preserved). Then add the FK only if it does not already exist.

update public.report_assignments a
   set agency_id = null
 where a.agency_id is not null
   and not exists (select 1 from public.agencies g where g.id = a.agency_id);

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'report_assignments_agency_id_fkey'
      and conrelid = 'public.report_assignments'::regclass
  ) then
    alter table public.report_assignments
      add constraint report_assignments_agency_id_fkey
      foreign key (agency_id) references public.agencies(id) on delete set null;
  end if;
end$$;
