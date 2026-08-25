-- Role-provisioning template. NOT a migration.
--
-- Create users through Supabase Auth using unique credentials held outside the
-- repository. Replace the two example.invalid addresses below immediately
-- before running this file in a controlled SQL session. No password or direct
-- auth.users insertion belongs in source control.
--
-- Constraint reminder (profiles_role_agency_consistent):
--   * super_admin / citizen  -> assigned_agency MUST be NULL
--   * agency_admin           -> assigned_agency MUST be a valid issue_category
--
-- ===================================================================
-- Provision users through Dashboard -> Authentication -> Users, with email
-- confirmation and MFA policy appropriate to the environment. The
-- handle_new_user trigger creates citizen profiles; then elevate by email.
-- ===================================================================
update public.profiles p
   set role = 'super_admin', assigned_agency = null, is_moderator = true
  from auth.users u
 where u.id = p.id
   and u.email = 'replace-super-admin@example.invalid';

update public.profiles p
   set role = 'agency_admin', assigned_agency = 'dinas_bina_marga', is_moderator = true
  from auth.users u
 where u.id = p.id
   and u.email = 'replace-agency-admin@example.invalid';

-- Verify the result:
-- select u.email, p.role, p.assigned_agency
--   from public.profiles p
--   join auth.users u on u.id = p.id
--  where u.email in (
--    'replace-super-admin@example.invalid',
--    'replace-agency-admin@example.invalid'
--  );
