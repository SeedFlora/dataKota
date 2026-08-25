create extension if not exists "pgcrypto";

create type public.issue_category as enum (
  'dinas_bina_marga',
  'satpol_pp',
  'dinas_perhubungan',
  'kelurahan',
  'dinas_pertamanan_hutan',
  'dinas_sda',
  'dinas_cipta_karya',
  'badan_bumd',
  'instansi_lain'
);

create type public.report_status as enum (
  'submitted',
  'verified',
  'in_progress',
  'resolved',
  'rejected'
);

create type public.user_role as enum (
  'citizen',
  'agency_admin',
  'super_admin'
);

create type public.evidence_kind as enum (
  'initial',
  'resolution',
  'additional'
);

create type public.assignment_status as enum (
  'active',
  'reassigned',
  'escalated',
  'superseded'
);

create type public.report_visibility as enum (
  'public',
  'private'
);

-- Operator-controlled allowlist for inference artifacts that may be promoted
-- from an untrusted client claim to trusted routing evidence.  A release is
-- inserted by a database migration/operator after the export and class-map
-- digests have been independently checked; the service-role worker can read it
-- only through the SECURITY DEFINER attestation function below.
create table if not exists public.ai_model_releases (
  export_manifest_sha256 text primary key,
  class_map_sha256 text not null,
  model_name text not null,
  model_version text not null,
  inference_method text not null,
  ordered_class_labels jsonb not null,
  confidence_threshold numeric not null,
  uncertainty_method text,
  epistemic_uncertainty_threshold double precision,
  attestation_enabled boolean not null default false,
  registered_at timestamptz not null default timezone('utc', now()),
  constraint ai_model_releases_export_digest check (
    export_manifest_sha256 ~ '^[0-9a-f]{64}$'
  ),
  constraint ai_model_releases_class_map_digest check (
    class_map_sha256 ~ '^[0-9a-f]{64}$'
  ),
  constraint ai_model_releases_nonempty_identity check (
    nullif(btrim(model_name), '') is not null and
    nullif(btrim(model_version), '') is not null and
    nullif(btrim(inference_method), '') is not null and
    inference_method not in ('legacy_unspecified', 'client_unattested')
  ),
  constraint ai_model_releases_canonical_class_order check (
    ordered_class_labels = '["Dinas Bina Marga", "Satuan Polisi Pamong Praja", "Dinas Perhubungan", "Kelurahan", "Dinas Pertamanan dan Hutan", "Dinas Sumber Daya Air", "Dinas Cipta Karya, Tata Ruang, dan Pertanahan", "Badan Pembinaan Badan Usaha Milik Daerah", "Instansi lain"]'::jsonb
  ),
  constraint ai_model_releases_confidence_threshold check (
    confidence_threshold >= 0 and confidence_threshold <= 1
  ),
  constraint ai_model_releases_uncertainty_policy check (
    (uncertainty_method is null and epistemic_uncertainty_threshold is null) or
    (nullif(btrim(uncertainty_method), '') is not null and
      epistemic_uncertainty_threshold is not null and
      epistemic_uncertainty_threshold >= 0)
  )
);

alter table public.ai_model_releases enable row level security;
revoke all privileges on public.ai_model_releases
  from public, anon, authenticated, service_role;

create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  full_name text not null,
  email text not null unique,
  phone_number text not null,
  profile_photo_url text,
  is_moderator boolean not null default false,
  role public.user_role not null default 'citizen',
  assigned_agency public.issue_category,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now()),
  constraint profiles_role_agency_consistent check (
    (role = 'agency_admin' and assigned_agency is not null) or
    (role <> 'agency_admin' and assigned_agency is null)
  )
);

create table if not exists public.reports (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(id) on delete cascade,
  reporter_name text not null,
  reporter_email text not null,
  category public.issue_category not null,
  ai_prediction text not null,
  -- Keep the attested probability precision. numeric(5,4) silently rounded
  -- otherwise-valid model evidence and broke round-trip provenance checks.
  ai_confidence double precision not null default 0,
  ai_probabilities jsonb not null default '{}'::jsonb,
  ai_model_name text,
  ai_model_version text,
  ai_export_manifest_sha256 text,
  ai_class_map_sha256 text,
  ai_agency_registry_status text,
  ai_inference_method text not null default 'legacy_unspecified',
  ai_uncertainty_method text,
  ai_epistemic_uncertainty double precision,
  ai_predictive_entropy double precision,
  ai_expected_data_entropy double precision,
  ai_epistemic_uncertainty_threshold double precision,
  ai_review_required boolean not null default false,
  ai_review_reasons text[] not null default '{}'::text[],
  ai_prediction_overridden boolean not null default false,
  -- Client-supplied inference metadata is an audit claim, not trusted
  -- operational evidence. Only the service-role attestation RPC may set true.
  ai_evidence_trusted boolean not null default false,
  assigned_agency_id text,
  assigned_agency_name text,
  assigned_agency_category public.issue_category,
  assigned_distance_meters double precision,
  routing_method text,
  image_url text not null,
  description text not null,
  latitude double precision not null,
  longitude double precision not null,
  address text not null,
  status public.report_status not null default 'submitted',
  verified_by uuid references public.profiles(id),
  verified_at timestamptz,
  rejection_reason text,
  resolution_evidence_photo_url text,
  resolution_note text,
  resolved_by uuid references public.profiles(id),
  resolved_at timestamptz,
  -- Production extensions: per-report visibility and duplicate linking.
  visibility public.report_visibility not null default 'public',
  duplicate_of uuid references public.reports(id) on delete set null,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now()),
  constraint reports_ai_uncertainty_nonnegative check (
    (ai_epistemic_uncertainty is null or ai_epistemic_uncertainty >= 0) and
    (ai_predictive_entropy is null or ai_predictive_entropy >= 0) and
    (ai_expected_data_entropy is null or ai_expected_data_entropy >= 0) and
    (ai_epistemic_uncertainty_threshold is null or ai_epistemic_uncertainty_threshold >= 0)
  ),
  constraint reports_ai_confidence_probability check (
    ai_confidence >= 0 and ai_confidence <= 1
  ),
  constraint reports_ai_digest_format check (
    (ai_export_manifest_sha256 is null or
      ai_export_manifest_sha256 ~ '^[0-9a-f]{64}$') and
    (ai_class_map_sha256 is null or ai_class_map_sha256 ~ '^[0-9a-f]{64}$')
  ),
  constraint reports_coordinates_valid check (
    latitude >= -90 and latitude <= 90 and
    longitude >= -180 and longitude <= 180
  ),
  constraint reports_untrusted_ai_blocks_assignment check (
    ai_evidence_trusted or (
      assigned_agency_id is null and
      assigned_agency_name is null and
      assigned_agency_category is null and
      assigned_distance_meters is null and
      routing_method is null
    )
  ),
  constraint reports_trusted_ai_requires_provenance check (
    not ai_evidence_trusted or (
      nullif(btrim(ai_model_name), '') is not null and
      nullif(btrim(ai_model_version), '') is not null and
      nullif(btrim(ai_export_manifest_sha256), '') is not null and
      ai_export_manifest_sha256 ~ '^[0-9a-f]{64}$' and
      nullif(btrim(ai_class_map_sha256), '') is not null and
      ai_class_map_sha256 ~ '^[0-9a-f]{64}$' and
      nullif(btrim(ai_agency_registry_status), '') is not null and
      nullif(btrim(ai_inference_method), '') is not null and
      ai_inference_method not in ('legacy_unspecified', 'client_unattested')
    )
  ),
  constraint reports_assignment_fields_complete check (
    (
      assigned_agency_id is null and
      assigned_agency_name is null and
      assigned_agency_category is null and
      assigned_distance_meters is null and
      routing_method is null
    ) or (
      nullif(btrim(assigned_agency_id), '') is not null and
      nullif(btrim(assigned_agency_name), '') is not null and
      assigned_agency_category is not null and
      assigned_distance_meters is not null and
      assigned_distance_meters >= 0 and
      nullif(btrim(routing_method), '') is not null
    )
  ),
  constraint reports_assignment_requires_verified_registry check (
    assigned_agency_id is null or
    coalesce(ai_agency_registry_status = 'verified', false)
  ),
  constraint reports_catch_all_never_assigned check (
    assigned_agency_category is null or
    assigned_agency_category <> 'instansi_lain'
  ),
  constraint reports_review_blocks_automatic_assignment check (
    not ai_review_required or (
      assigned_agency_id is null and
      assigned_agency_name is null and
      assigned_agency_category is null and
      assigned_distance_meters is null and
      routing_method is null
    )
  )
);

create index if not exists reports_user_id_idx on public.reports(user_id);
create index if not exists reports_status_idx on public.reports(status);
create index if not exists reports_category_idx on public.reports(category);
create index if not exists reports_created_at_idx on public.reports(created_at desc);
create index if not exists reports_status_created_idx on public.reports(status, created_at desc);
create index if not exists reports_assigned_agency_idx on public.reports(assigned_agency_category);
-- Backs the "My reports" stream: filter by user_id then sort newest-first.
create index if not exists reports_user_created_idx on public.reports(user_id, created_at desc);
create index if not exists reports_visibility_idx on public.reports(visibility);
create index if not exists reports_duplicate_of_idx on public.reports(duplicate_of);

create table if not exists public.report_history (
  id uuid primary key default gen_random_uuid(),
  report_id uuid not null references public.reports(id) on delete cascade,
  status public.report_status not null,
  note text not null,
  updated_by uuid references public.profiles(id),
  created_at timestamptz not null default timezone('utc', now())
);

create index if not exists report_history_report_id_idx on public.report_history(report_id);
create index if not exists report_history_created_at_idx on public.report_history(created_at);

create or replace function public.is_moderator(user_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from public.profiles
    where id = user_id
      and (role in ('agency_admin', 'super_admin') or is_moderator = true)
  );
$$;

create or replace function public.current_role() returns public.user_role
language sql stable security definer set search_path = '' as $$
  select coalesce(
    (select p.role from public.profiles p where p.id = auth.uid()),
    'citizen'::public.user_role
  )
$$;

create or replace function public.current_assigned_agency() returns public.issue_category
language sql stable security definer set search_path = '' as $$
  select p.assigned_agency from public.profiles p where p.id = auth.uid()
$$;

-- RLS helper used by every report child table and report-image object. It is
-- deliberately SECURITY DEFINER so the answer does not depend on nested RLS.
create or replace function public.can_access_report(p_report_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from public.reports r
    left join public.profiles p on p.id = auth.uid()
    where r.id = p_report_id
      and (
        r.user_id = auth.uid()
        or p.role = 'super_admin'
        or (p.role = 'agency_admin' and r.category = p.assigned_agency)
      )
  )
$$;

revoke all on function public.current_role() from public;
revoke all on function public.current_assigned_agency() from public;
revoke all on function public.can_access_report(uuid) from public;
revoke all on function public.is_moderator(uuid) from public, anon, authenticated;
grant execute on function public.current_role() to authenticated;
grant execute on function public.current_assigned_agency() to authenticated;
grant execute on function public.can_access_report(uuid) to anon, authenticated;

-- Citizens never UPDATE profiles directly. This narrow RPC can only change
-- the caller's display fields and validates that a private photo belongs to
-- the caller's storage prefix.
create or replace function public.update_own_profile(
  p_full_name text default null,
  p_phone_number text default null,
  p_profile_photo_url text default null
)
returns public.profiles
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_actor uuid := auth.uid();
  v_profile public.profiles;
begin
  if v_actor is null then
    raise exception using errcode = '42501', message = 'not authenticated';
  end if;
  if p_full_name is not null
     and (btrim(p_full_name) = '' or char_length(btrim(p_full_name)) > 160) then
    raise exception 'full name must contain 1..160 characters';
  end if;
  if p_phone_number is not null
     and (btrim(p_phone_number) = '' or char_length(btrim(p_phone_number)) > 40) then
    raise exception 'phone number must contain 1..40 characters';
  end if;
  if p_profile_photo_url is not null
     and (
       split_part(p_profile_photo_url, '/', 1) <> 'profile-photos'
       or split_part(p_profile_photo_url, '/', 2) <> v_actor::text
       or split_part(p_profile_photo_url, '/', 3) = ''
     ) then
    raise exception using errcode = '42501', message = 'profile photo path is not owned by caller';
  end if;

  update public.profiles p
  set
    full_name = coalesce(btrim(p_full_name), p.full_name),
    phone_number = coalesce(btrim(p_phone_number), p.phone_number),
    profile_photo_url = coalesce(p_profile_photo_url, p.profile_photo_url)
  where p.id = v_actor
  returning p.* into v_profile;

  if not found then
    raise exception 'profile not found';
  end if;
  return v_profile;
end;
$$;

revoke all on function public.update_own_profile(text, text, text)
  from public, anon, authenticated;
grant execute on function public.update_own_profile(text, text, text)
  to authenticated;

-- Privileged role changes are isolated from ordinary profile edits. Only an
-- already-provisioned super admin may call this function.
create or replace function public.admin_set_profile_role(
  p_profile_id uuid,
  p_role public.user_role,
  p_assigned_agency public.issue_category default null
)
returns public.profiles
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_profile public.profiles;
begin
  if auth.uid() is null or public.current_role() <> 'super_admin' then
    raise exception using errcode = '42501', message = 'super_admin role required';
  end if;
  if (p_role = 'agency_admin' and p_assigned_agency is null)
     or (p_role <> 'agency_admin' and p_assigned_agency is not null) then
    raise exception 'role and assigned agency are inconsistent';
  end if;

  update public.profiles p
  set
    role = p_role,
    assigned_agency = p_assigned_agency,
    is_moderator = p_role <> 'citizen'
  where p.id = p_profile_id
  returning p.* into v_profile;

  if not found then
    raise exception 'profile not found';
  end if;
  return v_profile;
end;
$$;

revoke all on function public.admin_set_profile_role(
  uuid, public.user_role, public.issue_category
) from public, anon, authenticated;
grant execute on function public.admin_set_profile_role(
  uuid, public.user_role, public.issue_category
) to authenticated;

-- Atomic citizen submission. Identity, initial status, history, trust, and
-- routing fields are controlled by the database rather than by the client.
-- Remove the legacy overload (before three provenance text parameters existed)
-- as well as the current overload so reapplying this file remains idempotent.
drop function if exists public.submit_report(
  uuid, public.issue_category, text, text, double precision,
  double precision, text, public.report_visibility, text, numeric, jsonb,
  text, text, text, text, double precision, double precision,
  double precision, double precision, boolean, text[]
);
drop function if exists public.submit_report(
  uuid, public.issue_category, text, text, double precision,
  double precision, text, public.report_visibility, text, numeric, jsonb,
  text, text, text, text, text, text, text, double precision, double precision,
  double precision, double precision, boolean, text[]
);

create or replace function public.submit_report(
  p_report_id uuid,
  p_category public.issue_category,
  p_image_url text,
  p_description text,
  p_latitude double precision,
  p_longitude double precision,
  p_address text,
  p_visibility public.report_visibility default 'public',
  p_ai_prediction text default null,
  p_ai_confidence numeric default 0,
  p_ai_probabilities jsonb default '{}'::jsonb,
  p_ai_model_name text default null,
  p_ai_model_version text default null,
  p_ai_export_manifest_sha256 text default null,
  p_ai_class_map_sha256 text default null,
  p_ai_agency_registry_status text default null,
  p_ai_inference_method text default 'client_unattested',
  p_ai_uncertainty_method text default null,
  p_ai_epistemic_uncertainty double precision default null,
  p_ai_predictive_entropy double precision default null,
  p_ai_expected_data_entropy double precision default null,
  p_ai_epistemic_uncertainty_threshold double precision default null,
  p_ai_review_required boolean default false,
  p_ai_review_reasons text[] default '{}'::text[]
)
returns public.reports
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_actor uuid := auth.uid();
  v_profile public.profiles;
  v_report public.reports;
  v_prediction text := coalesce(nullif(btrim(p_ai_prediction), ''), p_category::text);
  v_overridden boolean;
  v_review_required boolean;
  v_review_reasons text[] := coalesce(p_ai_review_reasons, '{}'::text[]);
begin
  if v_actor is null then
    raise exception using errcode = '42501', message = 'not authenticated';
  end if;

  select p.* into v_profile
  from public.profiles p
  where p.id = v_actor
  for share;
  if not found then
    raise exception 'profile not found';
  end if;
  if v_profile.role <> 'citizen' then
    raise exception using errcode = '42501', message = 'citizen role required to submit a report';
  end if;

  if p_report_id is null then
    raise exception 'report id is required';
  end if;
  if split_part(p_image_url, '/', 1) <> 'report-images'
     or split_part(p_image_url, '/', 2) <> v_actor::text
     or split_part(p_image_url, '/', 3) = '' then
    raise exception using errcode = '42501', message = 'report image path is not owned by caller';
  end if;
  if char_length(btrim(p_description)) < 10
     or char_length(btrim(p_description)) > 4000 then
    raise exception 'description must contain 10..4000 characters';
  end if;
  if char_length(coalesce(p_address, '')) > 1000 then
    raise exception 'address is too long';
  end if;
  if not (p_latitude >= -90 and p_latitude <= 90
          and p_longitude >= -180 and p_longitude <= 180) then
    raise exception 'invalid coordinates';
  end if;
  if not (p_ai_confidence >= 0 and p_ai_confidence <= 1) then
    raise exception 'AI confidence must be between zero and one';
  end if;
  if jsonb_typeof(coalesce(p_ai_probabilities, '{}'::jsonb)) <> 'object' then
    raise exception 'AI probabilities must be a JSON object';
  end if;
  if char_length(v_prediction) > 160 then
    raise exception 'AI prediction is too long';
  end if;
  if (p_ai_export_manifest_sha256 is not null
      and lower(p_ai_export_manifest_sha256) !~ '^[0-9a-f]{64}$')
     or (p_ai_class_map_sha256 is not null
      and lower(p_ai_class_map_sha256) !~ '^[0-9a-f]{64}$') then
    raise exception 'AI manifest/class-map digests must be SHA-256';
  end if;
  if char_length(coalesce(p_ai_agency_registry_status, '')) > 80 then
    raise exception 'AI agency registry status is too long';
  end if;

  v_overridden := v_prediction <> p_category::text;
  v_review_required := coalesce(p_ai_review_required, false) or v_overridden;
  if v_overridden and not ('user_category_override' = any(v_review_reasons)) then
    v_review_reasons := array_append(v_review_reasons, 'user_category_override');
  elsif v_review_required and cardinality(v_review_reasons) = 0 then
    v_review_reasons := array_append(v_review_reasons, 'client_review_required');
  elsif not v_review_required then
    v_review_reasons := '{}'::text[];
  end if;

  insert into public.reports (
    id, user_id, reporter_name, reporter_email, category,
    ai_prediction, ai_confidence, ai_probabilities,
    ai_model_name, ai_model_version, ai_export_manifest_sha256,
    ai_class_map_sha256, ai_agency_registry_status, ai_inference_method,
    ai_uncertainty_method, ai_epistemic_uncertainty,
    ai_predictive_entropy, ai_expected_data_entropy,
    ai_epistemic_uncertainty_threshold, ai_review_required,
    ai_review_reasons, ai_prediction_overridden, ai_evidence_trusted,
    assigned_agency_id, assigned_agency_name, assigned_agency_category,
    assigned_distance_meters, routing_method,
    image_url, description, latitude, longitude, address, status, visibility
  ) values (
    p_report_id, v_actor, v_profile.full_name, v_profile.email, p_category,
    v_prediction, p_ai_confidence, coalesce(p_ai_probabilities, '{}'::jsonb),
    nullif(btrim(p_ai_model_name), ''), nullif(btrim(p_ai_model_version), ''),
    lower(nullif(btrim(p_ai_export_manifest_sha256), '')),
    lower(nullif(btrim(p_ai_class_map_sha256), '')),
    nullif(btrim(p_ai_agency_registry_status), ''),
    coalesce(nullif(btrim(p_ai_inference_method), ''), 'client_unattested'),
    nullif(btrim(p_ai_uncertainty_method), ''), p_ai_epistemic_uncertainty,
    p_ai_predictive_entropy, p_ai_expected_data_entropy,
    p_ai_epistemic_uncertainty_threshold, v_review_required,
    v_review_reasons, v_overridden, false,
    null, null, null, null, null,
    p_image_url, btrim(p_description), p_latitude, p_longitude,
    coalesce(p_address, ''), 'submitted', p_visibility
  )
  returning * into v_report;

  insert into public.report_history (report_id, status, note, updated_by)
  values (v_report.id, 'submitted', 'Report submitted from the app.', v_actor);

  return v_report;
end;
$$;

revoke all on function public.submit_report(
  uuid, public.issue_category, text, text, double precision,
  double precision, text, public.report_visibility, text, numeric, jsonb,
  text, text, text, text, text, text, text, double precision, double precision,
  double precision, double precision, boolean, text[]
) from public, anon, authenticated;
grant execute on function public.submit_report(
  uuid, public.issue_category, text, text, double precision,
  double precision, text, public.report_visibility, text, numeric, jsonb,
  text, text, text, text, text, text, text, double precision, double precision,
  double precision, double precision, boolean, text[]
) to authenticated;

create or replace function public.update_report_status(
  p_report_id uuid,
  p_new_status public.report_status,
  p_note text,
  p_new_category public.issue_category default null,
  p_resolution_photo_url text default null,
  p_resolution_note text default null
)
returns public.reports
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_actor uuid := auth.uid();
  v_actor_role public.user_role := public.current_role();
  v_actor_agency public.issue_category := public.current_assigned_agency();
  v_report public.reports;
  v_target_category public.issue_category;
begin
  if v_actor is null then
    raise exception using errcode = '42501', message = 'not authenticated';
  end if;

  if v_actor_role not in ('agency_admin', 'super_admin') then
    raise exception using errcode = '42501', message = 'agency_admin or super_admin role required';
  end if;

  select * into v_report
  from public.reports
  where id = p_report_id
  for update;
  if not found then
    raise exception 'report % not found', p_report_id;
  end if;

  if v_actor_role = 'agency_admin'
     and (v_actor_agency is null
          or v_report.category is distinct from v_actor_agency) then
    raise exception using errcode = '42501', message = 'agency admin not authorised for this report';
  end if;

  -- Enforce the same forward-only lifecycle exposed by the operator UI.  A
  -- super admin may reassign a submitted report while verifying it, or change
  -- the category of an already verified report without inventing a status
  -- transition.  Terminal reports cannot be reopened through this RPC.
  if not (
    (v_report.status = 'submitted' and p_new_status in ('verified', 'rejected'))
    or (v_report.status = 'verified' and p_new_status in ('in_progress', 'rejected'))
    or (v_report.status = 'verified' and p_new_status = 'verified'
        and p_new_category is not null
        and p_new_category is distinct from v_report.category)
    or (v_report.status = 'in_progress' and p_new_status = 'resolved')
  ) then
    raise exception 'illegal report status transition: % -> %',
      v_report.status, p_new_status;
  end if;

  v_target_category := coalesce(p_new_category, v_report.category);

  if p_new_category is not null
     and p_new_category <> v_report.category
     and v_actor_role <> 'super_admin' then
    raise exception using errcode = '42501', message = 'only super_admin may reassign agency';
  end if;

  if p_new_status = 'resolved'
     and nullif(p_resolution_photo_url, '') is null then
    raise exception 'resolution evidence photo is required';
  end if;
  if p_new_status = 'resolved'
     and (
       split_part(p_resolution_photo_url, '/', 1) <> 'report-images'
       or split_part(p_resolution_photo_url, '/', 2) <> v_actor::text
       or split_part(p_resolution_photo_url, '/', 3) = ''
     ) then
    raise exception using errcode = '42501', message = 'resolution image path is not owned by caller';
  end if;
  if p_new_status = 'rejected' and nullif(btrim(p_note), '') is null then
    raise exception 'a rejection reason is required';
  end if;

  update public.reports
  set
    status = p_new_status,
    category = v_target_category,
    ai_prediction_overridden = ai_prediction_overridden
      or v_target_category::text <> ai_prediction,
    ai_review_required = ai_review_required
      or v_target_category is distinct from category,
    ai_review_reasons = case
      when v_target_category is distinct from category
           and not ('manual_agency_reassignment' = any(ai_review_reasons))
        then array_append(ai_review_reasons, 'manual_agency_reassignment')
      else ai_review_reasons
    end,
    assigned_agency_id = case
      when v_target_category is distinct from category then null
      else assigned_agency_id
    end,
    assigned_agency_name = case
      when v_target_category is distinct from category then null
      else assigned_agency_name
    end,
    assigned_agency_category = case
      when v_target_category is distinct from category then null
      else assigned_agency_category
    end,
    assigned_distance_meters = case
      when v_target_category is distinct from category then null
      else assigned_distance_meters
    end,
    routing_method = case
      when v_target_category is distinct from category then null
      else routing_method
    end,
    verified_by = case when p_new_status = 'verified' then v_actor else verified_by end,
    verified_at = case when p_new_status = 'verified' then timezone('utc', now()) else verified_at end,
    rejection_reason = case when p_new_status = 'rejected' then nullif(p_note, '') else rejection_reason end,
    resolution_evidence_photo_url = case
      when p_new_status = 'resolved' then p_resolution_photo_url
      else resolution_evidence_photo_url
    end,
    resolution_note = case
      when p_new_status = 'resolved' then coalesce(p_resolution_note, p_note, '')
      else resolution_note
    end,
    resolved_by = case
      when p_new_status = 'resolved' then v_actor
      else resolved_by
    end,
    resolved_at = case
      when p_new_status = 'resolved' then timezone('utc', now())
      else resolved_at
    end
  where id = p_report_id
  returning * into v_report;

  insert into public.report_history (report_id, status, note, updated_by)
  values (
    p_report_id,
    p_new_status,
    coalesce(p_resolution_note, p_note, ''),
    v_actor
  );

  return v_report;
end;
$$;

grant execute on function public.update_report_status(
  uuid, public.report_status, text, public.issue_category, text, text
) to authenticated;

revoke all on function public.update_report_status(
  uuid, public.report_status, text, public.issue_category, text, text
) from public, anon;

-- Only a backend request authenticated with the Supabase service role can turn
-- a client claim into trusted inference evidence or create auto-routing data.
-- Remove the legacy overload and the current provenance-complete overload.
drop function if exists public.attest_report_ai_evidence(
  uuid, text, numeric, jsonb, text, text, text, text, double precision,
  double precision, double precision, double precision, boolean, text[],
  text, text, public.issue_category, double precision, text
);
drop function if exists public.attest_report_ai_evidence(
  uuid, text, numeric, jsonb, text, text, text, text, text, text, text, double precision,
  double precision, double precision, double precision, boolean, text[],
  text, text, public.issue_category, double precision, text
);

create or replace function public.attest_report_ai_evidence(
  p_report_id uuid,
  p_prediction text,
  p_confidence numeric,
  p_probabilities jsonb,
  p_model_name text,
  p_model_version text,
  p_export_manifest_sha256 text,
  p_class_map_sha256 text,
  p_agency_registry_status text,
  p_inference_method text,
  p_uncertainty_method text default null,
  p_epistemic_uncertainty double precision default null,
  p_predictive_entropy double precision default null,
  p_expected_data_entropy double precision default null,
  p_epistemic_uncertainty_threshold double precision default null,
  p_review_required boolean default false,
  p_review_reasons text[] default '{}'::text[],
  p_assigned_agency_id text default null,
  p_assigned_agency_name text default null,
  p_assigned_agency_category public.issue_category default null,
  p_assigned_distance_meters double precision default null,
  p_routing_method text default null
)
returns public.reports
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_report public.reports;
  v_release public.ai_model_releases;
  v_review_required boolean;
  v_prediction_overridden boolean;
  v_catch_all boolean;
  v_has_any_assignment boolean;
  v_has_complete_assignment boolean;
  v_review_reasons text[] := coalesce(p_review_reasons, '{}'::text[]);
  v_expected_labels constant text[] := array[
    'Dinas Bina Marga',
    'Satuan Polisi Pamong Praja',
    'Dinas Perhubungan',
    'Kelurahan',
    'Dinas Pertamanan dan Hutan',
    'Dinas Sumber Daya Air',
    'Dinas Cipta Karya, Tata Ruang, dan Pertanahan',
    'Badan Pembinaan Badan Usaha Milik Daerah',
    'Instansi lain'
  ];
  v_expected_slugs constant text[] := array[
    'dinas_bina_marga',
    'satpol_pp',
    'dinas_perhubungan',
    'kelurahan',
    'dinas_pertamanan_hutan',
    'dinas_sda',
    'dinas_cipta_karya',
    'badan_bumd',
    'instansi_lain'
  ];
  v_label text;
  v_label_index integer;
  v_probability numeric;
  v_probability_sum numeric := 0;
  v_max_probability numeric := -1;
  v_predicted_label text;
  v_predicted_slug text;
begin
  if coalesce(auth.role(), '') <> 'service_role' then
    raise exception using errcode = '42501', message = 'service_role required';
  end if;
  if nullif(btrim(p_prediction), '') is null
     or nullif(btrim(p_model_name), '') is null
     or nullif(btrim(p_model_version), '') is null
     or nullif(btrim(p_export_manifest_sha256), '') is null
     or lower(p_export_manifest_sha256) !~ '^[0-9a-f]{64}$'
     or nullif(btrim(p_class_map_sha256), '') is null
     or lower(p_class_map_sha256) !~ '^[0-9a-f]{64}$'
     or nullif(btrim(p_agency_registry_status), '') is null
     or nullif(btrim(p_inference_method), '') is null
     or btrim(p_inference_method) in ('legacy_unspecified', 'client_unattested') then
    raise exception 'prediction, model name, version, and inference method are required';
  end if;
  if not (p_confidence >= 0 and p_confidence <= 1) then
    raise exception 'AI confidence must be between zero and one';
  end if;
  if jsonb_typeof(coalesce(p_probabilities, '{}'::jsonb)) <> 'object' then
    raise exception 'AI probabilities must be a JSON object';
  end if;

  select release.* into v_release
  from public.ai_model_releases release
  where release.export_manifest_sha256 = lower(p_export_manifest_sha256)
    and release.class_map_sha256 = lower(p_class_map_sha256)
    and release.model_name = btrim(p_model_name)
    and release.model_version = btrim(p_model_version)
    and release.inference_method = btrim(p_inference_method)
    and release.attestation_enabled
  for share;
  if not found then
    raise exception 'inference evidence does not match an enabled model release';
  end if;

  if v_release.ordered_class_labels <> to_jsonb(v_expected_labels)
     or (select count(*) from jsonb_object_keys(p_probabilities))
        <> cardinality(v_expected_labels)
     or exists (
       select 1
       from unnest(v_expected_labels) as expected(label)
       where not (p_probabilities ? expected.label)
     )
     or exists (
       select 1
       from jsonb_object_keys(p_probabilities) as supplied(label)
       where not (supplied.label = any(v_expected_labels))
     ) then
    raise exception 'AI probabilities must contain the exact canonical nine-label key set';
  end if;

  for v_label_index in 1..cardinality(v_expected_labels) loop
    v_label := v_expected_labels[v_label_index];
    if jsonb_typeof(p_probabilities -> v_label) <> 'number' then
      raise exception 'AI probability for % must be numeric', v_label;
    end if;
    v_probability := (p_probabilities ->> v_label)::numeric;
    if v_probability < 0 or v_probability > 1 then
      raise exception 'AI probability for % must be between zero and one', v_label;
    end if;
    v_probability_sum := v_probability_sum + v_probability;
    if v_probability > v_max_probability then
      v_max_probability := v_probability;
      v_predicted_label := v_label;
    end if;
  end loop;
  if abs(v_probability_sum - 1) > 0.000001 then
    raise exception 'AI probabilities must sum to one within 1e-6';
  end if;
  if abs(p_confidence - v_max_probability) > 0.000001 then
    raise exception 'AI confidence must equal the maximum class probability';
  end if;
  v_predicted_slug := v_expected_slugs[
    array_position(v_expected_labels, v_predicted_label)
  ];
  if btrim(p_prediction) <> v_predicted_slug then
    raise exception 'AI prediction slug must equal the deterministic probability argmax';
  end if;

  if nullif(btrim(p_uncertainty_method), '')
       is distinct from v_release.uncertainty_method
     or (
       (p_epistemic_uncertainty_threshold is null)
         <> (v_release.epistemic_uncertainty_threshold is null)
     )
     or (
       p_epistemic_uncertainty_threshold is not null
       and abs(
         p_epistemic_uncertainty_threshold
         - v_release.epistemic_uncertainty_threshold
       ) > 0.000000000001
     ) then
    raise exception 'AI uncertainty policy differs from the enabled model release';
  end if;
  if v_release.uncertainty_method is null then
    if p_epistemic_uncertainty is not null
       or p_predictive_entropy is not null
       or p_expected_data_entropy is not null then
      raise exception 'point release must not claim ensemble uncertainty values';
    end if;
  elsif p_epistemic_uncertainty is null
        or p_predictive_entropy is null
        or p_expected_data_entropy is null
        or p_epistemic_uncertainty < 0
        or p_predictive_entropy < 0
        or p_expected_data_entropy < 0
        or abs(
          p_epistemic_uncertainty
          - (p_predictive_entropy - p_expected_data_entropy)
        ) > 0.000001 then
    raise exception 'ensemble uncertainty values are absent, negative, or inconsistent';
  end if;
  if btrim(p_agency_registry_status) not in (
    'verified', 'incomplete', 'untrusted_fallback', 'unavailable'
  ) then
    raise exception 'unknown agency registry status';
  end if;

  v_has_any_assignment := p_assigned_agency_id is not null
    or p_assigned_agency_name is not null
    or p_assigned_agency_category is not null
    or p_assigned_distance_meters is not null
    or p_routing_method is not null;
  v_has_complete_assignment := nullif(btrim(p_assigned_agency_id), '') is not null
    and nullif(btrim(p_assigned_agency_name), '') is not null
    and p_assigned_agency_category is not null
    and p_assigned_distance_meters is not null
    and p_assigned_distance_meters >= 0
    and nullif(btrim(p_routing_method), '') is not null;
  if v_has_any_assignment and not v_has_complete_assignment then
    raise exception 'assignment fields must be all-null or complete';
  end if;
  if v_has_complete_assignment and p_agency_registry_status <> 'verified' then
    raise exception 'assignment requires a verified agency registry';
  end if;

  select * into v_report
  from public.reports
  where id = p_report_id
  for update;
  if not found then
    raise exception 'report % not found', p_report_id;
  end if;

  v_prediction_overridden := v_predicted_slug <> v_report.category::text;
  v_catch_all := v_report.category = 'instansi_lain'
    or v_predicted_slug = 'instansi_lain';
  v_review_required := coalesce(p_review_required, false)
    or v_prediction_overridden
    or v_catch_all
    or p_confidence < v_release.confidence_threshold
    or btrim(p_agency_registry_status) <> 'verified'
    or not v_has_complete_assignment
    or (
      v_release.epistemic_uncertainty_threshold is not null
      and p_epistemic_uncertainty > v_release.epistemic_uncertainty_threshold
    );
  if not v_review_required and v_has_complete_assignment
     and not exists (
       select 1 from public.agencies a
       where a.id = p_assigned_agency_id
         and a.name = p_assigned_agency_name
         and a.category = p_assigned_agency_category
         and a.category = v_report.category
         and a.is_active
     ) then
    raise exception 'assignment does not match an active agency in the report category';
  end if;
  if v_catch_all
     and not ('catch_all_class' = any(v_review_reasons)) then
    v_review_reasons := array_append(v_review_reasons, 'catch_all_class');
  end if;
  if v_prediction_overridden
     and not ('user_category_override' = any(v_review_reasons)) then
    v_review_reasons := array_append(v_review_reasons, 'user_category_override');
  end if;
  if p_confidence < v_release.confidence_threshold
     and not ('low_confidence' = any(v_review_reasons)) then
    v_review_reasons := array_append(v_review_reasons, 'low_confidence');
  end if;
  if v_release.epistemic_uncertainty_threshold is not null
     and p_epistemic_uncertainty > v_release.epistemic_uncertainty_threshold
     and not ('high_epistemic_uncertainty' = any(v_review_reasons)) then
    v_review_reasons := array_append(v_review_reasons, 'high_epistemic_uncertainty');
  end if;
  if btrim(p_agency_registry_status) <> 'verified'
     and not ('agency_registry_unverified' = any(v_review_reasons)) then
    v_review_reasons := array_append(v_review_reasons, 'agency_registry_unverified');
  end if;
  if not v_has_complete_assignment
     and not ('routing_assignment_unavailable' = any(v_review_reasons)) then
    v_review_reasons := array_append(
      v_review_reasons, 'routing_assignment_unavailable'
    );
  end if;
  if v_review_required and v_has_any_assignment then
    raise exception 'review-required evidence cannot include an agency assignment';
  elsif v_review_required and cardinality(v_review_reasons) = 0 then
    v_review_reasons := array_append(v_review_reasons, 'service_review_required');
  elsif not v_review_required then
    v_review_reasons := '{}'::text[];
  end if;

  update public.reports
  set
    ai_prediction = v_predicted_slug,
    ai_confidence = p_confidence,
    ai_probabilities = coalesce(p_probabilities, '{}'::jsonb),
    ai_model_name = btrim(p_model_name),
    ai_model_version = btrim(p_model_version),
    ai_export_manifest_sha256 = lower(p_export_manifest_sha256),
    ai_class_map_sha256 = lower(p_class_map_sha256),
    ai_agency_registry_status = btrim(p_agency_registry_status),
    ai_inference_method = btrim(p_inference_method),
    ai_uncertainty_method = nullif(btrim(p_uncertainty_method), ''),
    ai_epistemic_uncertainty = p_epistemic_uncertainty,
    ai_predictive_entropy = p_predictive_entropy,
    ai_expected_data_entropy = p_expected_data_entropy,
    ai_epistemic_uncertainty_threshold = v_release.epistemic_uncertainty_threshold,
    ai_review_required = v_review_required,
    ai_review_reasons = v_review_reasons,
    ai_prediction_overridden = v_prediction_overridden,
    ai_evidence_trusted = true,
    assigned_agency_id = case when v_review_required then null else p_assigned_agency_id end,
    assigned_agency_name = case when v_review_required then null else p_assigned_agency_name end,
    assigned_agency_category = case when v_review_required then null else p_assigned_agency_category end,
    assigned_distance_meters = case when v_review_required then null else p_assigned_distance_meters end,
    routing_method = case when v_review_required then null else p_routing_method end
  where id = p_report_id
  returning * into v_report;

  return v_report;
end;
$$;

revoke all on function public.attest_report_ai_evidence(
  uuid, text, numeric, jsonb, text, text, text, text, text, text, text, double precision,
  double precision, double precision, double precision, boolean, text[],
  text, text, public.issue_category, double precision, text
) from public, anon, authenticated;
grant execute on function public.attest_report_ai_evidence(
  uuid, text, numeric, jsonb, text, text, text, text, text, text, text, double precision,
  double precision, double precision, double precision, boolean, text[],
  text, text, public.issue_category, double precision, text
) to service_role;

-- Public discovery is an explicit redacted projection. It never exposes base
-- report PII, free text, evidence paths, exact coordinates, or model evidence.
create or replace function public.get_public_report_feed(p_limit integer default 200)
returns table (
  id uuid,
  user_id uuid,
  reporter_name text,
  reporter_email text,
  category public.issue_category,
  ai_prediction text,
  ai_confidence numeric,
  ai_probabilities jsonb,
  image_url text,
  description text,
  latitude double precision,
  longitude double precision,
  address text,
  status public.report_status,
  created_at timestamptz,
  updated_at timestamptz
)
language plpgsql
stable
security definer
set search_path = ''
rows 200
as $$
begin
  if auth.uid() is null then
    raise exception using errcode = '42501', message = 'not authenticated';
  end if;
  return query
    select
      r.id,
      '00000000-0000-0000-0000-000000000000'::uuid as user_id,
      'Warga'::text as reporter_name,
      ''::text as reporter_email,
      r.category,
      r.category::text as ai_prediction,
      0::numeric as ai_confidence,
      '{}'::jsonb as ai_probabilities,
      ''::text as image_url,
      'Detail laporan hanya tersedia bagi pelapor dan petugas berwenang.'::text as description,
      round(r.latitude::numeric, 2)::double precision as latitude,
      round(r.longitude::numeric, 2)::double precision as longitude,
      'Jakarta (lokasi diperkirakan)'::text as address,
      r.status,
      r.created_at,
      r.updated_at
    from public.reports r
    where r.visibility = 'public'
      and r.status <> 'rejected'
      and r.latitude >= -90 and r.latitude <= 90
      and r.longitude >= -180 and r.longitude <= 180
    order by r.created_at desc
    limit greatest(1, least(coalesce(p_limit, 200), 200));
end;
$$;

revoke all on function public.get_public_report_feed(integer)
  from public, anon, authenticated;
grant execute on function public.get_public_report_feed(integer)
  to authenticated;

-- Detail lookup returns the full row only to the owner/scoped operator. Other
-- authenticated users receive the same redacted projection as the public feed,
-- and private/rejected rows are indistinguishable from missing rows.
create or replace function public.get_report_detail(p_report_id uuid)
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
  v_report public.reports;
begin
  if auth.uid() is null then
    raise exception using errcode = '42501', message = 'not authenticated';
  end if;
  select r.* into v_report from public.reports r where r.id = p_report_id;
  if not found then
    return null;
  end if;
  if public.can_access_report(v_report.id) then
    return to_jsonb(v_report);
  end if;
  if v_report.visibility <> 'public'
     or v_report.status = 'rejected'
     or not (v_report.latitude >= -90 and v_report.latitude <= 90
             and v_report.longitude >= -180 and v_report.longitude <= 180) then
    return null;
  end if;
  return jsonb_build_object(
    'id', v_report.id,
    'user_id', '00000000-0000-0000-0000-000000000000'::uuid,
    'reporter_name', 'Warga',
    'reporter_email', '',
    'category', v_report.category,
    'ai_prediction', v_report.category::text,
    'ai_confidence', 0,
    'ai_probabilities', '{}'::jsonb,
    'image_url', '',
    'description', 'Detail laporan hanya tersedia bagi pelapor dan petugas berwenang.',
    'latitude', round(v_report.latitude::numeric, 2)::double precision,
    'longitude', round(v_report.longitude::numeric, 2)::double precision,
    'address', 'Jakarta (lokasi diperkirakan)',
    'status', v_report.status,
    'created_at', v_report.created_at,
    'updated_at', v_report.updated_at
  );
end;
$$;

revoke all on function public.get_report_detail(uuid)
  from public, anon, authenticated;
grant execute on function public.get_report_detail(uuid)
  to authenticated;

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles (
    id,
    full_name,
    email,
    phone_number
  )
  values (
    new.id,
    coalesce(new.raw_user_meta_data ->> 'full_name', ''),
    coalesce(new.email, ''),
    coalesce(new.raw_user_meta_data ->> 'phone_number', '')
  )
  on conflict (id) do nothing;

  return new;
end;
$$;

create or replace function public.touch_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = timezone('utc', now());
  return new;
end;
$$;

drop trigger if exists profiles_touch_updated_at on public.profiles;
create trigger profiles_touch_updated_at
before update on public.profiles
for each row
execute function public.touch_updated_at();

drop trigger if exists reports_touch_updated_at on public.reports;
create trigger reports_touch_updated_at
before update on public.reports
for each row
execute function public.touch_updated_at();

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
after insert on auth.users
for each row
execute function public.handle_new_user();

alter table public.profiles enable row level security;
alter table public.reports enable row level security;
alter table public.report_history enable row level security;

drop policy if exists "profiles_select_self_or_moderator" on public.profiles;
drop policy if exists "profiles_select_authorized" on public.profiles;
create policy "profiles_select_authorized"
on public.profiles
for select
to authenticated
using (auth.uid() = id or public.current_role() = 'super_admin');

drop policy if exists "profiles_insert_self" on public.profiles;
drop policy if exists "profiles_update_self_or_moderator" on public.profiles;
drop policy if exists "profiles_update_super_admin" on public.profiles;

drop policy if exists "reports_select_authenticated" on public.reports;
drop policy if exists "reports_select_authorized" on public.reports;
create policy "reports_select_authorized"
on public.reports
for select
to authenticated
using (public.can_access_report(id));

drop policy if exists "reports_insert_self" on public.reports;
drop policy if exists "reports_update_self_or_moderator" on public.reports;
drop policy if exists "reports_update_scoped" on public.reports;

drop policy if exists "history_select_authenticated" on public.report_history;
drop policy if exists "history_select_authorized" on public.report_history;
create policy "history_select_authorized"
on public.report_history
for select
to authenticated
using (public.can_access_report(report_id));

drop policy if exists "history_insert_self_or_moderator" on public.report_history;
drop policy if exists "history_insert_scoped" on public.report_history;

-- The authenticated role gets read access subject to RLS. All writes are
-- mediated by narrow SECURITY DEFINER RPCs above; direct DML is denied.
revoke all privileges on public.profiles from public, anon, authenticated;
revoke all privileges on public.reports from public, anon, authenticated;
revoke all privileges on public.report_history from public, anon, authenticated;
grant select on public.profiles, public.reports, public.report_history to authenticated;

-- Private buckets: durable references are stored as bucket + object_path and
-- read through short-lived signed URLs, so a leaked/expired link cannot expose
-- citizen photos (which may contain faces, plates, or other PII).
insert into storage.buckets (
  id, name, public, file_size_limit, allowed_mime_types
)
values
  ('report-images', 'report-images', false, 10485760, array['image/jpeg']::text[]),
  ('profile-photos', 'profile-photos', false, 5242880, array['image/jpeg']::text[])
on conflict (id) do update set
  public = excluded.public,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists "report_images_select_authenticated" on storage.objects;
drop policy if exists "report_images_select_authorized" on storage.objects;
create policy "report_images_select_authorized"
on storage.objects
for select
to authenticated
using (
  bucket_id = 'report-images'
  and split_part(name, '/', 1) = auth.uid()::text
);

drop policy if exists "report_images_insert_self" on storage.objects;
create policy "report_images_insert_self"
on storage.objects
for insert
to authenticated
with check (
  bucket_id = 'report-images'
  and split_part(name, '/', 1) = auth.uid()::text
);

drop policy if exists "profile_photos_select_authenticated" on storage.objects;
drop policy if exists "profile_photos_select_self" on storage.objects;
create policy "profile_photos_select_self"
on storage.objects
for select
to authenticated
using (
  bucket_id = 'profile-photos'
  and split_part(name, '/', 1) = auth.uid()::text
);

drop policy if exists "profile_photos_insert_self" on storage.objects;
create policy "profile_photos_insert_self"
on storage.objects
for insert
to authenticated
with check (
  bucket_id = 'profile-photos'
  and split_part(name, '/', 1) = auth.uid()::text
);

drop policy if exists "profile_photos_update_self" on storage.objects;
create policy "profile_photos_update_self"
on storage.objects
for update
to authenticated
using (
  bucket_id = 'profile-photos'
  and split_part(name, '/', 1) = auth.uid()::text
)
with check (
  bucket_id = 'profile-photos'
  and split_part(name, '/', 1) = auth.uid()::text
);

drop policy if exists "profile_photos_delete_self" on storage.objects;
create policy "profile_photos_delete_self"
on storage.objects
for delete
to authenticated
using (
  bucket_id = 'profile-photos'
  and split_part(name, '/', 1) = auth.uid()::text
);

-- ===================================================================
-- Normalized report domain
-- ===================================================================
-- The flat columns above on `reports` are kept as a denormalized READ PROJECTION
-- for owner/admin Flutter Realtime streams. Public discovery uses the redacted
-- `get_public_report_feed` RPC and never subscribes to this base PII table. The
-- tables below are the durable system of record for multi-valued / historical
-- concerns; SECURITY DEFINER projection triggers fan writes out into them.

-- Agency registry (replaces the denormalized assigned_agency_* text fields).
create table if not exists public.agencies (
  id text primary key,
  name text not null,
  category public.issue_category not null,
  latitude double precision,
  longitude double precision,
  is_active boolean not null default true,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now()),
  constraint agencies_catch_all_not_active check (
    category <> 'instansi_lain' or not is_active
  )
);
create index if not exists agencies_category_idx on public.agencies(category);

-- Multi-evidence: stores bucket + object_path (not a final URL).
create table if not exists public.report_evidence (
  id uuid primary key default gen_random_uuid(),
  report_id uuid not null references public.reports(id) on delete cascade,
  kind public.evidence_kind not null,
  bucket text not null,
  object_path text not null,
  content_type text,
  uploaded_by uuid references public.profiles(id),
  created_at timestamptz not null default timezone('utc', now())
);
create index if not exists report_evidence_report_id_idx on public.report_evidence(report_id);
create unique index if not exists report_evidence_report_kind_path_idx
  on public.report_evidence(report_id, kind, object_path);

-- Assignment / reassignment / escalation history.
create table if not exists public.report_assignments (
  id uuid primary key default gen_random_uuid(),
  report_id uuid not null references public.reports(id) on delete cascade,
  agency_id text references public.agencies(id) on delete set null,
  agency_name text,
  agency_category public.issue_category,
  distance_meters double precision,
  routing_method text,
  status public.assignment_status not null default 'active',
  reason text,
  assigned_by uuid references public.profiles(id),
  created_at timestamptz not null default timezone('utc', now())
);
create index if not exists report_assignments_report_id_idx on public.report_assignments(report_id);
create unique index if not exists report_assignments_one_active_idx
  on public.report_assignments(report_id) where status = 'active';

-- Per-report SLA clock (agency-level policy is future work).
create table if not exists public.report_sla (
  report_id uuid primary key references public.reports(id) on delete cascade,
  first_response_due_at timestamptz,
  resolution_due_at timestamptz,
  first_response_at timestamptz,
  breached_at timestamptz,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

-- Parse a Supabase Storage public/signed URL (or a bucket/path string) into parts.
create or replace function public.parse_storage_ref(p_url text)
returns table(bucket text, object_path text)
language plpgsql
immutable
as $$
declare
  rest text;
begin
  if p_url is null or btrim(p_url) = '' then
    return;
  end if;
  if position('/object/public/' in p_url) > 0 then
    rest := split_part(p_url, '/object/public/', 2);
  elsif position('/object/sign/' in p_url) > 0 then
    rest := split_part(split_part(p_url, '/object/sign/', 2), '?', 1);
  else
    rest := p_url;
  end if;
  bucket := split_part(rest, '/', 1);
  object_path := substr(rest, length(bucket) + 2);
  if object_path = '' then
    return;
  end if;
  return next;
end;
$$;

create or replace function public.project_report_evidence()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_ref record;
begin
  if nullif(new.image_url, '') is not null
     and (tg_op = 'INSERT' or new.image_url is distinct from old.image_url) then
    for v_ref in select * from public.parse_storage_ref(new.image_url) loop
      insert into public.report_evidence (report_id, kind, bucket, object_path, uploaded_by)
      values (new.id, 'initial', v_ref.bucket, v_ref.object_path, new.user_id)
      on conflict (report_id, kind, object_path) do nothing;
    end loop;
  end if;
  if nullif(new.resolution_evidence_photo_url, '') is not null
     and (tg_op = 'INSERT' or new.resolution_evidence_photo_url is distinct from old.resolution_evidence_photo_url) then
    for v_ref in select * from public.parse_storage_ref(new.resolution_evidence_photo_url) loop
      insert into public.report_evidence (report_id, kind, bucket, object_path, uploaded_by)
      values (new.id, 'resolution', v_ref.bucket, v_ref.object_path, coalesce(new.resolved_by, new.user_id))
      on conflict (report_id, kind, object_path) do nothing;
    end loop;
  end if;
  return null;
end;
$$;

create or replace function public.project_report_assignment()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if tg_op = 'INSERT'
     or new.assigned_agency_id is distinct from old.assigned_agency_id
     or new.assigned_agency_name is distinct from old.assigned_agency_name
     or new.assigned_agency_category is distinct from old.assigned_agency_category
     or new.assigned_distance_meters is distinct from old.assigned_distance_meters
     or new.routing_method is distinct from old.routing_method then
    update public.report_assignments
       set status = 'superseded'
     where report_id = new.id and status = 'active';

    -- Clearing an assignment (for example when review becomes required) must
    -- still supersede the prior active child record before returning.
    if nullif(new.assigned_agency_id, '') is null
       and nullif(new.assigned_agency_name, '') is null then
      return null;
    end if;

    insert into public.report_assignments (
      report_id, agency_id, agency_name, agency_category,
      distance_meters, routing_method, status, assigned_by
    )
    values (
      new.id, new.assigned_agency_id, new.assigned_agency_name, new.assigned_agency_category,
      new.assigned_distance_meters, new.routing_method, 'active',
      new.verified_by
    );
  end if;
  return null;
end;
$$;

drop trigger if exists reports_project_evidence on public.reports;
create trigger reports_project_evidence
after insert or update on public.reports
for each row execute function public.project_report_evidence();

drop trigger if exists reports_project_assignment on public.reports;
create trigger reports_project_assignment
after insert or update on public.reports
for each row execute function public.project_report_assignment();

drop trigger if exists agencies_touch_updated_at on public.agencies;
create trigger agencies_touch_updated_at
before update on public.agencies
for each row execute function public.touch_updated_at();

drop trigger if exists report_sla_touch_updated_at on public.report_sla;
create trigger report_sla_touch_updated_at
before update on public.report_sla
for each row execute function public.touch_updated_at();

alter table public.agencies enable row level security;
alter table public.report_evidence enable row level security;
alter table public.report_assignments enable row level security;
alter table public.report_sla enable row level security;

drop policy if exists "agencies_select_authenticated" on public.agencies;
create policy "agencies_select_authenticated"
on public.agencies for select to authenticated using (true);

drop policy if exists "agencies_write_super_admin" on public.agencies;
create policy "agencies_write_super_admin"
on public.agencies for all to authenticated
using (public.current_role() = 'super_admin')
with check (public.current_role() = 'super_admin');

-- Supabase projects may inherit broad platform default privileges. Keep the
-- registry boundary explicit: all authenticated users may read, while write
-- statements remain restricted by the super-admin RLS policy above.
revoke all privileges on public.agencies from public, anon, authenticated;
grant select, insert, update, delete on public.agencies to authenticated;

drop policy if exists "report_evidence_select_authenticated" on public.report_evidence;
drop policy if exists "report_evidence_select_authorized" on public.report_evidence;
create policy "report_evidence_select_authorized"
on public.report_evidence for select to authenticated
using (public.can_access_report(report_id));

drop policy if exists "report_assignments_select_authenticated" on public.report_assignments;
drop policy if exists "report_assignments_select_authorized" on public.report_assignments;
create policy "report_assignments_select_authorized"
on public.report_assignments for select to authenticated
using (public.can_access_report(report_id));

drop policy if exists "report_sla_select_authenticated" on public.report_sla;
drop policy if exists "report_sla_select_authorized" on public.report_sla;
create policy "report_sla_select_authorized"
on public.report_sla for select to authenticated
using (public.can_access_report(report_id));

revoke all privileges on public.report_evidence
  from public, anon, authenticated;
revoke all privileges on public.report_assignments
  from public, anon, authenticated;
revoke all privileges on public.report_sla
  from public, anon, authenticated;
grant select on public.report_evidence, public.report_assignments, public.report_sla
  to authenticated;

-- Now that report_evidence exists, expand the earlier owner-only object read
-- policy to also permit an administrator who is authorised for the report.
drop policy if exists "report_images_select_authorized" on storage.objects;
create policy "report_images_select_authorized"
on storage.objects
for select
to authenticated
using (
  bucket_id = 'report-images'
  and (
    split_part(name, '/', 1) = auth.uid()::text
    or exists (
      select 1
      from public.report_evidence e
      where e.bucket = bucket_id
        and e.object_path = name
        and public.can_access_report(e.report_id)
    )
  )
);

-- Owners may replace/remove only orphaned uploads (for example after a failed
-- transactional submission). Once projected as report evidence, the object is
-- immutable to mobile clients.
drop policy if exists "report_images_update_self" on storage.objects;
create policy "report_images_update_self"
on storage.objects
for update
to authenticated
using (
  bucket_id = 'report-images'
  and split_part(name, '/', 1) = auth.uid()::text
  and not exists (
    select 1 from public.report_evidence e
    where e.bucket = bucket_id and e.object_path = name
  )
)
with check (
  bucket_id = 'report-images'
  and split_part(name, '/', 1) = auth.uid()::text
  and not exists (
    select 1 from public.report_evidence e
    where e.bucket = bucket_id and e.object_path = name
  )
);

drop policy if exists "report_images_delete_self" on storage.objects;
create policy "report_images_delete_self"
on storage.objects
for delete
to authenticated
using (
  bucket_id = 'report-images'
  and split_part(name, '/', 1) = auth.uid()::text
  and not exists (
    select 1 from public.report_evidence e
    where e.bucket = bucket_id and e.object_path = name
  )
);

-- Restrictive guards keep these two private buckets safe even if another
-- migration later adds a broad permissive policy to storage.objects.
drop policy if exists "private_image_read_guard" on storage.objects;
create policy "private_image_read_guard"
on storage.objects as restrictive
for select to public
using (
  bucket_id not in ('report-images', 'profile-photos')
  or (
    bucket_id = 'profile-photos'
    and split_part(name, '/', 1) = auth.uid()::text
  )
  or (
    bucket_id = 'report-images'
    and (
      split_part(name, '/', 1) = auth.uid()::text
      or exists (
        select 1 from public.report_evidence e
        where e.bucket = bucket_id
          and e.object_path = name
          and public.can_access_report(e.report_id)
      )
    )
  )
);

drop policy if exists "private_image_insert_guard" on storage.objects;
create policy "private_image_insert_guard"
on storage.objects as restrictive
for insert to public
with check (
  bucket_id not in ('report-images', 'profile-photos')
  or (
    bucket_id in ('report-images', 'profile-photos')
    and split_part(name, '/', 1) = auth.uid()::text
  )
);

drop policy if exists "private_image_update_guard" on storage.objects;
create policy "private_image_update_guard"
on storage.objects as restrictive
for update to public
using (
  bucket_id not in ('report-images', 'profile-photos')
  or (
    bucket_id = 'profile-photos'
    and split_part(name, '/', 1) = auth.uid()::text
  )
  or (
    bucket_id = 'report-images'
    and split_part(name, '/', 1) = auth.uid()::text
    and not exists (
      select 1 from public.report_evidence e
      where e.bucket = bucket_id and e.object_path = name
    )
  )
)
with check (
  bucket_id not in ('report-images', 'profile-photos')
  or (
    bucket_id = 'profile-photos'
    and split_part(name, '/', 1) = auth.uid()::text
  )
  or (
    bucket_id = 'report-images'
    and split_part(name, '/', 1) = auth.uid()::text
    and not exists (
      select 1 from public.report_evidence e
      where e.bucket = bucket_id and e.object_path = name
    )
  )
);

drop policy if exists "private_image_delete_guard" on storage.objects;
create policy "private_image_delete_guard"
on storage.objects as restrictive
for delete to public
using (
  bucket_id not in ('report-images', 'profile-photos')
  or (
    bucket_id = 'profile-photos'
    and split_part(name, '/', 1) = auth.uid()::text
  )
  or (
    bucket_id = 'report-images'
    and split_part(name, '/', 1) = auth.uid()::text
    and not exists (
      select 1 from public.report_evidence e
      where e.bucket = bucket_id and e.object_path = name
    )
  )
);

-- ===================================================================
-- Seed: agency registry (master data)
-- ===================================================================
-- Single source of truth is `smartCityReport/agencies_seed.json`, which the
-- FastAPI inference server (serve_model.py) also loads at startup. Keep these
-- rows in sync with that file. Coordinates are geocoded (OpenStreetMap Nominatim)
-- from official office addresses; suku dinas are proxied to their kotamadya
-- walikota complex. Full provenance is documented in agencies_seed.json.
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
