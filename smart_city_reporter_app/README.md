# SmartCityApps

Flutter client for authenticated citizen reporting, human review of multimodal
classification, private evidence upload, map/location capture, and scoped
operator workflows. The active classifier is the repository FastAPI service;
production builds do not run or silently substitute an ONNX model on-device.

## Active architecture

- Supabase Auth manages identity and sessions.
- Private Supabase Storage buckets hold profile photos and report evidence.
- Narrow PostgreSQL RPCs perform report submission, profile updates, status
  transitions, redacted public reads, and backend-only AI attestation.
- FastAPI receives image, Indonesian report text, and optional coordinates. A
  valid response must carry the human label, explicit database category slug,
  complete nine-class score vector, model and immutable export provenance,
  review decision, and routing-registry status.
- Flutter rejects incomplete or inconsistent inference responses. The
  deterministic demo classifier is available only when
  `ENABLE_TESTING_MODE=true`; it always requests human review and never creates
  an assignment.

Client-supplied inference evidence is stored with
`ai_evidence_trusted=false`. Only a trusted service-role backend can call
`attest_report_ai_evidence`, bind the exact export/class-map hashes, and create
an assignment. The exact reviewed release must first be added to the
operator-only allowlist described in
[`supabase/AI_MODEL_RELEASE_REGISTRATION.md`](supabase/AI_MODEL_RELEASE_REGISTRATION.md).
The RPC independently revalidates the nine-class probability simplex,
argmax/enum slug, confidence, uncertainty policy, and review gates. That backend
integration and its runtime authorization test are release gates, not
capabilities proven by this repository alone.

## Configuration

Copy `env/dev.example.json` to the gitignored `env/dev.json`, then set:

| Define | Requirement |
|---|---|
| `SUPABASE_URL` | HTTPS Supabase project URL. |
| `SUPABASE_ANON_KEY` | Publishable/anon client key; never use a service key. |
| `CRM_API_URL` | HTTPS FastAPI base URL. There is no production default. |
| `AUTH_REDIRECT_URL` | Auth callback registered in Supabase and Android. |
| `ENABLE_TESTING_MODE` | `true` only for explicit demo/testing builds. |
| `ALLOW_INSECURE_HTTP` | `true` only for local emulator/USB development. |

Run:

```bash
flutter pub get
flutter run --dart-define-from-file=env/dev.json
```

If required values are absent or placeholders, the app opens `/setup` and does
not initialize Supabase. For a local Android emulator use
`CRM_API_URL=http://10.0.2.2:8000` together with
`ALLOW_INSECURE_HTTP=true`. For a USB device, `adb reverse tcp:8000 tcp:8000`
allows `http://127.0.0.1:8000`. Release configurations must use HTTPS.

## Supabase provisioning

- Fresh isolated project: apply `supabase/schema.sql`.
- Existing project: follow `supabase/MIGRATION_PLAN.md` and apply migrations in
  filename order after a backup.
- Configure email confirmation, redirects, and SMTP deliberately for the target
  environment; do not weaken production authentication for convenience.
- Run every JWT/RLS/Storage/RPC check in
  `supabase/SECURITY_TEST_PROTOCOL.md` against a disposable project.
- Enable Realtime only for the tables needed by the authenticated scoped views.

The static schema tests prove source-level invariants only. They do not replace
PostgreSQL/PostgREST runtime tests with citizen, scoped agency-admin,
super-admin, and service-role tokens.

## Upload sanitization

Every report image, resolution-evidence image, and profile photo uploaded by
the shipped Flutter client passes through one fail-closed sanitizer before
Supabase Storage. It does not trust the filename extension or picker MIME type.
Content must decode as a single-frame JPEG, PNG, or WebP; HEIC and other formats
remain rejected until an audited cross-platform decoder is available.

The production limits are 20 MiB of input bytes, 8,192 pixels on either axis,
24 megapixels of decoded canvas, and—matching the configured private Storage
buckets—10 MiB after sanitization for report/resolution evidence or 5 MiB for a
profile photo. The sanitizer checks the decoder header before allocating the
raster, applies EXIF
orientation, flattens transparency onto white, copies pixels into a fresh RGB
canvas, and re-encodes JPEG at fixed quality 88 with 4:2:0 chroma subsampling.
The fresh raster has no EXIF/GPS, ICC profile, text chunks, animation, embedded
thumbnail, or source filename; Storage receives only `.jpg` bytes with
`image/jpeg` content type. These source-level controls still require the
device/object inspection cases in `supabase/SECURITY_TEST_PROTOCOL.md` before
release.

This is client hygiene, not a server-enforced trust invariant. A modified
client can currently call Supabase Storage directly and upload arbitrary bytes
to its own allowed prefix; the RPCs validate ownership/path but do not decode
the object or bind its digest. Production release therefore remains blocked on
a trusted backend/Edge ingestion step that independently decodes and
re-encodes the object, records a SHA-256 digest, and permits a report/profile
reference only to that verified object. The current classification request also
precedes Storage sanitization, so its input bytes are not identical to the
stored JPEG. Client inference remains untrusted; an attestation worker must
re-run inference from the exact verified stored bytes and bind that object
digest before it can attest provenance or routing.

## Submission and trust flow

1. An authenticated citizen captures/selects an image and enters a report.
2. FastAPI returns a fail-closed prediction contract; the citizen may correct
   the category.
3. The app sanitizes the evidence and uploads the re-encoded JPEG to the
   caller-owned private Storage prefix.
4. `submit_report` atomically derives identity from `auth.uid()`, fixes the
   initial status, stores client provenance as untrusted, clears assignment,
   and inserts the first history row.
5. On RPC failure the app attempts to remove the orphaned upload.
6. A separate trusted backend may reproduce/verify inference and attest the row.
   Review, override, catch-all, low-score, uncertainty, or registry-gap cases
   remain unassigned.

Legal status transitions are forward-only:
`submitted -> verified|rejected`, `verified -> in_progress|rejected`, and
`in_progress -> resolved`. Resolution requires evidence. Terminal reports are
not reopened by the client RPC.

## Tests

```bash
flutter test
```

The suite includes model mapping, classification/routing logic, fail-closed
cloud response parsing, validators, and screenshot/render fixtures. Flutter and
an Android SDK are required; when they are unavailable, the Python/SQL static
contract tests in the repository root remain useful but are not a substitute.

## Known release gates

- Apply migrations and execute the full authorization protocol on an isolated
  Supabase deployment.
- Integrate and test the service-role attestation worker without distributing
  its secret to the app; it must infer from the verified stored object, not the
  original client classification request.
- Enforce image sanitization at the trusted backend/Edge boundary, bind the
  sanitized-object SHA-256 to report/profile references, and reject direct raw
  own-prefix uploads. The Flutter sanitizer alone is bypassable.
- Validate the implemented evidence-file sanitizer, including EXIF removal,
  orientation, malformed/oversized rejection, and stored-object MIME bytes, on
  actual Android/iOS devices.
- Complete the receipt-bound model export, raw-input parity, latency/memory
  benchmark, and locked external evaluation described in the repository Q2
  protocol.
- Configure production SMTP, crash reporting, privacy/retention controls, and
  incident/rollback procedures before real public use.

The client is a research prototype until those gates pass.
