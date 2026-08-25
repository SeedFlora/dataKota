# Supabase provisioning and migrations

For a new isolated project, apply `schema.sql` once. For an existing project,
apply every file in `migrations/` in filename order and record the checksum in
the deployment log. Take a database backup before production migration.

The current terminal migration is `20260825_security_hardening.sql`. It is a
release blocker: it revokes direct client writes to sensitive tables, moves
report submission/profile edits/status changes behind narrow RPCs, replaces the
public base-table feed with a redacted RPC, scopes child rows and Storage reads,
and marks all pre-existing client AI evidence untrusted. Historic automatic
assignments are cleared and must be re-attested by a service-role backend.

After applying it:

1. Regenerate PostgREST's schema cache if the project does not do so
   automatically.
2. Deploy the matching Flutter client; older clients that insert directly into
   `reports` will correctly fail closed.
3. Run every role-negative and positive check in
   `SECURITY_TEST_PROTOCOL.md` against a non-production project.
4. Re-attest eligible historical AI rows from a controlled backend only after
   validating their model/version/evidence receipts, exact export-manifest and
   class-map SHA-256 anchors, and routing-registry status.
5. Reload the inference server's agency registry through a trusted deployment
   job or Edge Function. Never distribute the reload credential in the app.

The database-runtime gate has not been executed in this repository environment
because `psql` and a disposable Supabase instance were unavailable. Static
contract tests live in `tests/test_supabase_security_contract.py`; they are not
a substitute for the role/JWT integration protocol.
