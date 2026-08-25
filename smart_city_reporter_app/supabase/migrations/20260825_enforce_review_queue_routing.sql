-- A model flag that requests human review must prevent automatic dispatch.
-- Preserve prediction/review provenance, supersede any previously projected
-- active assignment, and reject future rows that combine an unresolved review
-- flag with denormalized routing fields.

-- The heterogeneous classifier catch-all is a review queue, not an agency.
-- Deactivate any historical seed row before adding the fail-closed registry
-- constraint so upgraded databases cannot route to it.
update public.agencies
set is_active = false,
    updated_at = timezone('utc', now())
where category = 'instansi_lain'
  and is_active;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'agencies_catch_all_not_active'
      and conrelid = 'public.agencies'::regclass
  ) then
    alter table public.agencies
      add constraint agencies_catch_all_not_active check (
        category <> 'instansi_lain' or not is_active
      );
  end if;
end$$;

update public.reports
set ai_review_required = true,
    ai_review_reasons = case
      when 'catch_all_class' = any(ai_review_reasons) then ai_review_reasons
      else array_append(ai_review_reasons, 'catch_all_class')
    end
where category = 'instansi_lain'
   or assigned_agency_category = 'instansi_lain'
   or lower(btrim(coalesce(ai_prediction, ''))) in ('instansi lain', 'instansi_lain');

update public.report_assignments as assignment
set status = 'superseded'
from public.reports as report
where assignment.report_id = report.id
  and assignment.status = 'active'
  and report.ai_review_required;

update public.reports
set assigned_agency_id = null,
    assigned_agency_name = null,
    assigned_agency_category = null,
    assigned_distance_meters = null,
    routing_method = null
where ai_review_required;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'reports_review_blocks_automatic_assignment'
      and conrelid = 'public.reports'::regclass
  ) then
    alter table public.reports
      add constraint reports_review_blocks_automatic_assignment check (
        not ai_review_required or (
          assigned_agency_id is null and
          assigned_agency_name is null and
          assigned_agency_category is null and
          assigned_distance_meters is null and
          routing_method is null
        )
      );
  end if;
end$$;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'reports_catch_all_never_assigned'
      and conrelid = 'public.reports'::regclass
  ) then
    alter table public.reports
      add constraint reports_catch_all_never_assigned check (
        assigned_agency_category is null or
        assigned_agency_category <> 'instansi_lain'
      );
  end if;
end$$;

comment on constraint reports_review_blocks_automatic_assignment
  on public.reports is
  'Unresolved model-review flags cannot coexist with an automatic agency assignment.';
