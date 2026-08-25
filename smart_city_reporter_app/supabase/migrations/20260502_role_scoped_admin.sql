-- Role-scoped agency admin migration.
--
-- Idempotent. Safe to apply multiple times. Adds:
--   * public.user_role enum (citizen / agency_admin / super_admin)
--   * profiles.role and profiles.assigned_agency columns
--   * helper rpcs current_role() and current_assigned_agency()
--   * scoped RLS policies on reports + report_history
--   * update_report_status() rpc that mutates a report and appends a
--     report_history row in one transaction

do $$
begin
  if not exists (select 1 from pg_type where typname = 'user_role') then
    create type public.user_role as enum (
      'citizen',
      'agency_admin',
      'super_admin'
    );
  end if;
end$$;

alter table public.profiles
  add column if not exists role public.user_role not null default 'citizen';

alter table public.profiles
  add column if not exists assigned_agency public.issue_category;

do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'profiles_role_agency_consistent'
  ) then
    alter table public.profiles
      add constraint profiles_role_agency_consistent
      check (
        (role = 'agency_admin' and assigned_agency is not null) or
        (role <> 'agency_admin' and assigned_agency is null)
      );
  end if;
end$$;

-- Promote existing moderators to super_admin.
update public.profiles
set role = 'super_admin'
where is_moderator = true and role = 'citizen';

create or replace function public.current_role() returns public.user_role
language sql stable security definer set search_path = public as $$
  select role from public.profiles where id = auth.uid()
$$;

create or replace function public.current_assigned_agency() returns public.issue_category
language sql stable security definer set search_path = public as $$
  select assigned_agency from public.profiles where id = auth.uid()
$$;

drop policy if exists "reports_update_self_or_moderator" on public.reports;
drop policy if exists "reports_update_scoped" on public.reports;
create policy "reports_update_scoped"
on public.reports
for update
to authenticated
using (
  auth.uid() = user_id
  or public.current_role() = 'super_admin'
  or (public.current_role() = 'agency_admin'
      and category = public.current_assigned_agency())
)
with check (
  auth.uid() = user_id
  or public.current_role() = 'super_admin'
  or (public.current_role() = 'agency_admin'
      and category = public.current_assigned_agency())
);

drop policy if exists "history_insert_self_or_moderator" on public.report_history;
drop policy if exists "history_insert_scoped" on public.report_history;
create policy "history_insert_scoped"
on public.report_history
for insert
to authenticated
with check (
  auth.uid() = updated_by
  and (
    public.current_role() in ('super_admin', 'agency_admin')
    or exists (
      select 1 from public.reports r
      where r.id = report_id and r.user_id = auth.uid()
    )
  )
);

create or replace function public.update_report_status(
  p_report_id uuid,
  p_new_status public.report_status,
  p_note text,
  p_new_category public.issue_category default null
)
returns public.reports
language plpgsql
security invoker
set search_path = public
as $$
declare
  v_actor uuid := auth.uid();
  v_actor_role public.user_role := public.current_role();
  v_actor_agency public.issue_category := public.current_assigned_agency();
  v_report public.reports;
  v_target_category public.issue_category;
begin
  if v_actor is null then
    raise exception 'not authenticated';
  end if;

  select * into v_report from public.reports where id = p_report_id;
  if not found then
    raise exception 'report % not found', p_report_id;
  end if;

  if v_actor_role = 'agency_admin'
     and v_report.category <> v_actor_agency then
    raise exception 'agency admin not authorised for this report';
  end if;

  v_target_category := coalesce(p_new_category, v_report.category);

  if p_new_category is not null
     and p_new_category <> v_report.category
     and v_actor_role <> 'super_admin' then
    raise exception 'only super_admin may reassign agency';
  end if;

  update public.reports
  set
    status = p_new_status,
    category = v_target_category,
    verified_by = case
      when p_new_status = 'verified' then v_actor
      else verified_by
    end,
    verified_at = case
      when p_new_status = 'verified' then timezone('utc', now())
      else verified_at
    end,
    rejection_reason = case
      when p_new_status = 'rejected' then nullif(p_note, '')
      else rejection_reason
    end
  where id = p_report_id
  returning * into v_report;

  insert into public.report_history (report_id, status, note, updated_by)
  values (p_report_id, p_new_status, coalesce(p_note, ''), v_actor);

  return v_report;
end;
$$;

grant execute on function public.update_report_status(
  uuid, public.report_status, text, public.issue_category
) to authenticated;
