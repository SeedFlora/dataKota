# Supabase authorization test protocol

This protocol is a release gate for the migration
`20260825_security_hardening.sql`. Run it against an isolated Supabase project,
never production. The repository environment used for this revision did not
contain `psql`, so these database-runtime checks remain pending.

## Fixtures

Create five authenticated test users through Supabase Auth, then provision:

| Principal | Role/scope | Owned report |
|---|---|---|
| `citizen_a` | citizen | `report_a` (public) |
| `citizen_b` | citizen | `report_b` (private) |
| `agency_bm` | agency_admin / `dinas_bina_marga` | none |
| `agency_sda` | agency_admin / `dinas_sda` | none |
| `super_admin` | super_admin | none |

For each client test, use that user's access token through PostgREST or set the
equivalent local JWT claims. Never run negative tests with the service key.

## Required negative checks

Every operation below must return no rows or an authorization error:

1. `citizen_a` selects `report_b`, even if it guesses the UUID.
2. `citizen_a` selects any `report_history`, `report_evidence`,
   `report_assignments`, or `report_sla` row belonging to `report_b`.
3. `citizen_a` selects/downloads `report-images/<citizen_b UUID>/...` or
   `profile-photos/<citizen_b UUID>/...`.
4. `citizen_a` directly inserts, updates, or deletes `reports`, including an
   attempted `status='resolved'`, `ai_evidence_trusted=true`, or populated
   assignment fields.
5. `citizen_a` directly inserts history or assignment rows.
6. `citizen_a` updates its `profiles.role`, `is_moderator`,
   `assigned_agency`, email, or another user's profile.
7. `citizen_a` calls `update_report_status`, `admin_set_profile_role`, or
   `attest_report_ai_evidence`.
8. `agency_bm` reads or changes `report_b` when its category is not
   `dinas_bina_marga`; repeat symmetrically for `agency_sda`.
9. `agency_bm` attempts to recategorize a report through
   `update_report_status`; only a super admin may return it to triage.
10. Any authenticated client calls `attest_report_ai_evidence`; only a trusted
    service-role backend may execute it.
11. Submit an incomplete assignment (only agency ID, or negative distance) and
    confirm the database rejects it.
12. Call attestation with missing/malformed `export_manifest_sha256` or
    `class_map_sha256`, and with an assignment whose registry status is not
    exactly `verified`; each call must fail without mutating the report.
13. Call attestation with a well-formed but unregistered digest, a disabled
    release, or any model name/version/method that differs from its allowlist
    row; every call must be rejected.
14. Mutate, omit, or add a probability key; use a nonnumeric/out-of-range value;
    make the values sum away from one; mismatch confidence, argmax slug, or the
    release uncertainty policy. Every call must be rejected.
15. Supply `review_required=false` below the registered confidence threshold,
    above the registered epistemic threshold, for the catch-all, or with an
    unverified registry. Also omit every assignment field from an otherwise
    routable trusted result. The database must force review in each case.
    Supplying an assignment while any other review gate is active must be
    rejected.
16. Transition a trusted assigned report into review/unassigned state and
    confirm its prior active `report_assignments` row becomes `superseded`.
17. Attempt every illegal lifecycle jump, including `submitted -> resolved`,
    `verified -> resolved`, regressions, and any transition out of `resolved`
    or `rejected`; each call must fail without adding a history row.
18. Attempt a same-status update without a super-admin category change and a
    recategorization after work has started; both calls must fail.

## Required positive checks

1. `submit_report` derives reporter identity from `auth.uid()`, creates exactly
   one `submitted` history row in the same transaction, sets
   `ai_evidence_trusted=false`, and leaves every assignment field null.
2. A user category different from the client AI prediction sets
   `ai_prediction_overridden=true`, `ai_review_required=true`, and includes the
   `user_category_override` reason.
3. `citizen_a` can read only `report_a` and its child rows; `citizen_b` can read
   only `report_b` and its child rows.
4. Scoped agency admins can read/update reports only for their agency through
   `update_report_status`; `super_admin` can access all reports.
5. `update_own_profile` changes only the caller's name, phone, and owned private
   photo reference. Role fields remain unchanged.
6. `get_public_report_feed` exposes only non-rejected public rows and returns
   `Warga`, blank email/image, generic free text/address, rounded coordinates,
   and no model provenance or assignment data.
   Repeat with `get_report_detail`: the owner/scoped operator gets the full row,
   another authenticated user gets only the redacted public projection, and a
   private or rejected foreign report returns null.
7. After an operator registers and enables the reviewed release, service-role
   attestation records its exact 64-hex export-manifest and class-map hashes,
   model name/version, inference method, canonical probability vector, and
   registry status. Include a non-four-decimal score such as `0.823456`, read
   the row back, require exact equality for digests/identifiers/JSON keys, and
   require confidence to equal the stored winning probability within `1e-12`.
   This guards against storage-layer rounding. When review is required
   (including a citizen override), assignment fields stay null.
8. A fully specified, non-review trusted assignment creates one active child
   assignment and satisfies the completeness constraint.
9. The legal lifecycle succeeds only in order: `submitted -> verified ->
   in_progress -> resolved`; rejection succeeds only from `submitted` or
   `verified`, and a verified super admin may change category while remaining
   `verified`.

## Transaction and leakage checks

Force the history insert inside `submit_report` to fail in the isolated test
(for example with a temporary rejecting trigger) and verify no report row is
committed. Verify the app removes the already-uploaded image after the RPC
error. Also inspect PostgREST/OpenAPI metadata: authenticated users should have
`SELECT` only on sensitive tables and execute only on the explicitly granted
RPCs; `attest_report_ai_evidence` must not be callable with an authenticated
JWT.

The `/reload-agencies` inference endpoint is not called by the Flutter app.
Registry reload must be performed by a trusted deployment job or Supabase Edge
Function that holds the server credential; the credential must never be placed
in an APK, web bundle, or mobile configuration.

## Client image-sanitization checks

Run these on each supported Android/iOS release target and inspect the actual
private Storage object, not only the local preview:

1. Upload JPEG fixtures containing EXIF orientation, GPS coordinates, camera
   make/model, comment/text data, ICC data, and an embedded thumbnail through
   report submission, resolution evidence, and profile-photo flows. Each stored
   object must be a `.jpg` whose signature and Storage content type are exactly
   JPEG; no source metadata or filename may remain, and displayed orientation
   must match the source orientation tag.
2. Repeat with valid PNG and WebP content carrying misleading `.jpg`, `.heic`,
   or extensionless names. Acceptance must follow content bytes, and the stored
   result must still be the sanitizer-produced JPEG.
3. Try empty, truncated, malformed, GIF, HEIC, animated PNG/WebP, over-20-MiB,
   over-8,192-axis, over-24-megapixel, over-10-MiB sanitized report evidence,
   and over-5-MiB sanitized profile-photo fixtures.
   Each attempt must fail before a Storage object is created and before the
   associated report/profile RPC runs.
4. Confirm transparent pixels are flattened onto white, the sanitizer reports
   the post-orientation dimensions, and retry/orphan cleanup behavior remains
   correct for an RPC failure after a successful sanitized upload. Exercise
   both `submit_report` and `update_own_profile`; neither may leave an orphaned
   object after the corresponding RPC fails.
5. Using an authenticated REST/Storage client rather than the Flutter app,
   attempt to upload arbitrary non-image bytes to that user's own prefix. The
   current ownership-only policy permits this, demonstrating that the client
   sanitizer is bypassable. Production acceptance requires a trusted
   backend/Edge ingestion boundary to reject or quarantine this object,
   decode/re-encode accepted images independently, record their SHA-256, and
   allow RPC binding only to the verified digest/object.
6. Compare the bytes sent to `/predict` with the object ultimately stored. In
   the current client they differ because prediction uses the original picker
   file and Storage receives a later JPEG re-encode. Treat that prediction as
   untrusted. Before enabling AI attestation, require the trusted worker to
   re-run inference from the exact verified stored bytes and bind the stored
   object digest to the attested model/export provenance. A test must mutate
   one stored byte/digest and confirm attestation fails.

The constants and implementation under test are in
`lib/core/security/image_upload_sanitizer.dart`; Dart unit tests cover content
sniffing, malformed/size rejection, orientation, and metadata removal. These
device checks remain mandatory because codec behavior and picker streams can
vary by platform.
