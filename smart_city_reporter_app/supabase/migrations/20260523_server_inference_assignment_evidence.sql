-- Phase 2: server-side inference metadata, nearest agency assignment, and
-- mandatory resolution evidence for reports marked selesai/resolved.

do $$
begin
  alter type public.issue_category add value if not exists 'dinas_bina_marga';
  alter type public.issue_category add value if not exists 'satpol_pp';
  alter type public.issue_category add value if not exists 'dinas_perhubungan';
  alter type public.issue_category add value if not exists 'kelurahan';
  alter type public.issue_category add value if not exists 'dinas_pertamanan_hutan';
  alter type public.issue_category add value if not exists 'dinas_sda';
  alter type public.issue_category add value if not exists 'dinas_cipta_karya';
  alter type public.issue_category add value if not exists 'badan_bumd';
  alter type public.issue_category add value if not exists 'instansi_lain';
end$$;

alter table public.reports
  add column if not exists ai_probabilities jsonb not null default '{}'::jsonb,
  add column if not exists ai_model_name text,
  add column if not exists ai_model_version text,
  add column if not exists assigned_agency_id text,
  add column if not exists assigned_agency_name text,
  add column if not exists assigned_agency_category public.issue_category,
  add column if not exists assigned_distance_meters double precision,
  add column if not exists routing_method text,
  add column if not exists resolution_evidence_photo_url text,
  add column if not exists resolution_note text,
  add column if not exists resolved_by uuid references public.profiles(id),
  add column if not exists resolved_at timestamptz;

create index if not exists reports_assigned_agency_idx
on public.reports(assigned_agency_category);

drop function if exists public.update_report_status(
  uuid, public.report_status, text, public.issue_category
);

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

  if p_new_status = 'resolved'
     and nullif(p_resolution_photo_url, '') is null then
    raise exception 'resolution evidence photo is required';
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
    end,
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
