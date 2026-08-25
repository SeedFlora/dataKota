-- Phase: normalize the report domain away from the single-table-heavy `reports`.
--
-- Motivation (thesis ERD review): `reports` carried six concerns in one row
-- (identity/location, AI prediction, assignment, status/verification, resolution
-- evidence, audit). That blocks multi-evidence, reassignment/escalation history,
-- duplicate linking, SLA, and public/private visibility.
--
-- Strategy (backward compatible): the multi-valued / historical concerns move to
-- dedicated child tables that become the durable system of record, while the flat
-- columns on `reports` stay as a denormalized READ PROJECTION so the Flutter
-- Realtime `.stream('reports')` client keeps working unchanged. Database triggers
-- fan each write on `reports` out into the child tables (SECURITY DEFINER so the
-- projection bypasses child-table RLS). Evidence is stored as bucket + object_path
-- (not a final URL) so production can mint short-lived signed URLs on demand.
--
-- Idempotent and additive: safe to re-run; existing rows are backfilled.

-- ===================================================================
-- 1. Enums
-- ===================================================================

do $$
begin
  if not exists (select 1 from pg_type where typname = 'evidence_kind') then
    create type public.evidence_kind as enum ('initial', 'resolution', 'additional');
  end if;
  if not exists (select 1 from pg_type where typname = 'assignment_status') then
    create type public.assignment_status as enum ('active', 'reassigned', 'escalated', 'superseded');
  end if;
  if not exists (select 1 from pg_type where typname = 'report_visibility') then
    create type public.report_visibility as enum ('public', 'private');
  end if;
end$$;

-- ===================================================================
-- 2. Agencies registry (replaces the denormalized assigned_agency_* text)
-- ===================================================================

create table if not exists public.agencies (
  id text primary key,
  name text not null,
  category public.issue_category not null,
  latitude double precision,
  longitude double precision,
  is_active boolean not null default true,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

create index if not exists agencies_category_idx on public.agencies(category);

-- ===================================================================
-- 3. Aggregate-root columns (additive, non-breaking)
-- ===================================================================
-- Defensively ensure the projection columns this migration reads exist, so it
-- runs even on a database where the earlier 20260523 migration was not applied.

alter table public.reports
  add column if not exists ai_probabilities jsonb not null default '{}'::jsonb,
  add column if not exists ai_model_name text,
  add column if not exists ai_model_version text,
  add column if not exists assigned_agency_id text,
  add column if not exists assigned_agency_name text,
  add column if not exists assigned_agency_category public.issue_category,
  add column if not exists assigned_distance_meters double precision,
  add column if not exists routing_method text,
  add column if not exists verified_by uuid references public.profiles(id),
  add column if not exists verified_at timestamptz,
  add column if not exists rejection_reason text,
  add column if not exists resolution_evidence_photo_url text,
  add column if not exists resolution_note text,
  add column if not exists resolved_by uuid references public.profiles(id),
  add column if not exists resolved_at timestamptz,
  add column if not exists visibility public.report_visibility not null default 'public',
  add column if not exists duplicate_of uuid references public.reports(id) on delete set null;

create index if not exists reports_visibility_idx on public.reports(visibility);
create index if not exists reports_duplicate_of_idx on public.reports(duplicate_of);

-- ===================================================================
-- 4. report_evidence (multi-evidence; bucket + object_path, not URL)
-- ===================================================================

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
-- One canonical row per (report, kind) for the projected initial/resolution photos.
create unique index if not exists report_evidence_report_kind_path_idx
  on public.report_evidence(report_id, kind, object_path);

-- ===================================================================
-- 5. report_assignments (assignment / reassignment / escalation history)
-- ===================================================================

create table if not exists public.report_assignments (
  id uuid primary key default gen_random_uuid(),
  report_id uuid not null references public.reports(id) on delete cascade,
  agency_id text,
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
-- At most one live assignment per report; history rows carry a non-active status.
create unique index if not exists report_assignments_one_active_idx
  on public.report_assignments(report_id)
  where status = 'active';

-- ===================================================================
-- 6. report_sla (per-report SLA clock; agency-level policy is future work)
-- ===================================================================

create table if not exists public.report_sla (
  report_id uuid primary key references public.reports(id) on delete cascade,
  first_response_due_at timestamptz,
  resolution_due_at timestamptz,
  first_response_at timestamptz,
  breached_at timestamptz,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

-- ===================================================================
-- 7. Helper: parse Supabase Storage URL -> (bucket, object_path)
-- ===================================================================

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
    -- Already a "bucket/path" reference.
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

-- ===================================================================
-- 8. Fan-out triggers: project flat reports.* writes into child tables
--    SECURITY DEFINER so the projection bypasses child-table RLS.
-- ===================================================================

create or replace function public.project_report_evidence()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  v_ref record;
begin
  -- Initial photo: present on insert, or newly set on update.
  if nullif(new.image_url, '') is not null
     and (tg_op = 'INSERT'
          or new.image_url is distinct from old.image_url) then
    for v_ref in select * from public.parse_storage_ref(new.image_url) loop
      insert into public.report_evidence (report_id, kind, bucket, object_path, uploaded_by)
      values (new.id, 'initial', v_ref.bucket, v_ref.object_path, new.user_id)
      on conflict (report_id, kind, object_path) do nothing;
    end loop;
  end if;

  -- Resolution photo: newly set when the report is resolved.
  if nullif(new.resolution_evidence_photo_url, '') is not null
     and (tg_op = 'INSERT'
          or new.resolution_evidence_photo_url is distinct from old.resolution_evidence_photo_url) then
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
set search_path = public
as $$
begin
  -- Only act when there is an actual routing assignment recorded.
  if nullif(new.assigned_agency_id, '') is null
     and nullif(new.assigned_agency_name, '') is null then
    return null;
  end if;

  -- On insert, or when the assigned agency changes, supersede the previous live
  -- row and append a new active assignment (so history/reassignment is preserved).
  if tg_op = 'INSERT'
     or new.assigned_agency_id is distinct from old.assigned_agency_id
     or new.assigned_agency_category is distinct from old.assigned_agency_category then

    update public.report_assignments
       set status = 'superseded'
     where report_id = new.id
       and status = 'active';

    insert into public.report_assignments (
      report_id, agency_id, agency_name, agency_category,
      distance_meters, routing_method, status, assigned_by
    )
    values (
      new.id, new.assigned_agency_id, new.assigned_agency_name, new.assigned_agency_category,
      new.assigned_distance_meters, new.routing_method, 'active',
      coalesce(new.verified_by, new.user_id)
    );
  end if;

  return null;
end;
$$;

drop trigger if exists reports_project_evidence on public.reports;
create trigger reports_project_evidence
after insert or update on public.reports
for each row
execute function public.project_report_evidence();

drop trigger if exists reports_project_assignment on public.reports;
create trigger reports_project_assignment
after insert or update on public.reports
for each row
execute function public.project_report_assignment();

-- ===================================================================
-- 9. Backfill child tables from existing rows
-- ===================================================================

insert into public.report_evidence (report_id, kind, bucket, object_path, uploaded_by, created_at)
select r.id, 'initial', ref.bucket, ref.object_path, r.user_id, r.created_at
from public.reports r
cross join lateral public.parse_storage_ref(r.image_url) ref
on conflict (report_id, kind, object_path) do nothing;

insert into public.report_evidence (report_id, kind, bucket, object_path, uploaded_by, created_at)
select r.id, 'resolution', ref.bucket, ref.object_path, coalesce(r.resolved_by, r.user_id), coalesce(r.resolved_at, r.updated_at)
from public.reports r
cross join lateral public.parse_storage_ref(r.resolution_evidence_photo_url) ref
on conflict (report_id, kind, object_path) do nothing;

insert into public.report_assignments (
  report_id, agency_id, agency_name, agency_category,
  distance_meters, routing_method, status, assigned_by, created_at
)
select
  r.id, r.assigned_agency_id, r.assigned_agency_name, r.assigned_agency_category,
  r.assigned_distance_meters, r.routing_method, 'active', coalesce(r.verified_by, r.user_id), r.created_at
from public.reports r
where (nullif(r.assigned_agency_id, '') is not null or nullif(r.assigned_agency_name, '') is not null)
  and not exists (
    select 1 from public.report_assignments a
    where a.report_id = r.id and a.status = 'active'
  );

-- Seed the agencies registry from whatever assignments already exist.
insert into public.agencies (id, name, category)
select distinct on (r.assigned_agency_id)
  r.assigned_agency_id, coalesce(r.assigned_agency_name, r.assigned_agency_id), r.assigned_agency_category
from public.reports r
where nullif(r.assigned_agency_id, '') is not null
  and r.assigned_agency_category is not null
on conflict (id) do nothing;

-- ===================================================================
-- 10. RLS for the new tables
--     Reads mirror reports (any authenticated user); writes happen only through
--     the SECURITY DEFINER projection triggers, so no INSERT policy is granted.
-- ===================================================================

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

drop policy if exists "report_evidence_select_authenticated" on public.report_evidence;
create policy "report_evidence_select_authenticated"
on public.report_evidence for select to authenticated using (true);

drop policy if exists "report_assignments_select_authenticated" on public.report_assignments;
create policy "report_assignments_select_authenticated"
on public.report_assignments for select to authenticated using (true);

drop policy if exists "report_sla_select_authenticated" on public.report_sla;
create policy "report_sla_select_authenticated"
on public.report_sla for select to authenticated using (true);

-- updated_at touch for agencies / report_sla
drop trigger if exists agencies_touch_updated_at on public.agencies;
create trigger agencies_touch_updated_at
before update on public.agencies
for each row execute function public.touch_updated_at();

drop trigger if exists report_sla_touch_updated_at on public.report_sla;
create trigger report_sla_touch_updated_at
before update on public.report_sla
for each row execute function public.touch_updated_at();

-- ===================================================================
-- 11. Make Storage buckets private (read via short-lived signed URLs)
--     The existing authenticated SELECT policies still allow signed-URL
--     creation; flipping `public` only disables anonymous public links.
-- ===================================================================

update storage.buckets set public = false
where id in ('report-images', 'profile-photos');
