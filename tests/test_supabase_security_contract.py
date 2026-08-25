from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "smart_city_reporter_app" / "supabase" / "schema.sql"
MIGRATION = (
    ROOT
    / "smart_city_reporter_app"
    / "supabase"
    / "migrations"
    / "20260825_security_hardening.sql"
)
ROUTING_MIGRATION = (
    ROOT
    / "smart_city_reporter_app"
    / "supabase"
    / "migrations"
    / "20260825_enforce_review_queue_routing.sql"
)
AGENCY_SEED = ROOT / "agencies_seed.json"
REPORTS_REPOSITORY = (
    ROOT
    / "smart_city_reporter_app"
    / "lib"
    / "features"
    / "reports"
    / "reports_repository.dart"
)
AUTH_REPOSITORY = (
    ROOT
    / "smart_city_reporter_app"
    / "lib"
    / "features"
    / "auth"
    / "auth_repository.dart"
)
AGENCY_REPOSITORY = (
    ROOT
    / "smart_city_reporter_app"
    / "lib"
    / "features"
    / "admin"
    / "agency_registry_repository.dart"
)
ADMIN_SEED = ROOT / "smart_city_reporter_app" / "supabase" / "seed_admin_accounts.sql"
APP_CONFIG = (
    ROOT / "smart_city_reporter_app" / "lib" / "core" / "config" / "app_config.dart"
)
APP_ROUTER = (
    ROOT / "smart_city_reporter_app" / "lib" / "app" / "router" / "app_router.dart"
)
AI_SERVICE = (
    ROOT
    / "smart_city_reporter_app"
    / "lib"
    / "core"
    / "services"
    / "ai_classification_service.dart"
)
CLOUD_SERVICE = (
    ROOT
    / "smart_city_reporter_app"
    / "lib"
    / "core"
    / "services"
    / "cloud_classification_service.dart"
)


def _function(sql: str, name: str) -> str:
    start = sql.index(f"create or replace function public.{name}")
    end = sql.index("$$;", start) + 3
    return sql[start:end]


def _compact_sql(sql: str) -> str:
    return re.sub(r"\s+", " ", sql.strip().lower())


def _created_parameter_types(sql: str, name: str) -> tuple[str, ...]:
    compact = _compact_sql(sql)
    prefix = f"create or replace function public.{name}("
    start = compact.index(prefix) + len(prefix)
    end = compact.index(") returns", start)
    parameters = compact[start:end].split(",")
    types: list[str] = []
    for parameter in parameters:
        declaration = re.sub(r"\s+default\s+.*$", "", parameter.strip())
        _, parameter_type = declaration.split(" ", 1)
        types.append(parameter_type)
    return tuple(types)


SUBMIT_REPORT_TYPES = (
    "uuid",
    "public.issue_category",
    "text",
    "text",
    "double precision",
    "double precision",
    "text",
    "public.report_visibility",
    "text",
    "numeric",
    "jsonb",
    "text",
    "text",
    "text",
    "text",
    "text",
    "text",
    "text",
    "double precision",
    "double precision",
    "double precision",
    "double precision",
    "boolean",
    "text[]",
)

ATTEST_AI_TYPES = (
    "uuid",
    "text",
    "numeric",
    "jsonb",
    "text",
    "text",
    "text",
    "text",
    "text",
    "text",
    "text",
    "double precision",
    "double precision",
    "double precision",
    "double precision",
    "boolean",
    "text[]",
    "text",
    "text",
    "public.issue_category",
    "double precision",
    "text",
)

LEGACY_SUBMIT_REPORT_TYPES = SUBMIT_REPORT_TYPES[:15] + SUBMIT_REPORT_TYPES[18:]
LEGACY_ATTEST_AI_TYPES = ATTEST_AI_TYPES[:8] + ATTEST_AI_TYPES[11:]


def _assert_function_signature_contract(
    sql: str,
    name: str,
    expected_types: tuple[str, ...],
    grant_role: str,
) -> None:
    compact = _compact_sql(sql)
    signature = ", ".join(expected_types)
    assert _created_parameter_types(sql, name) == expected_types
    assert f"drop function if exists public.{name}( {signature} );" in compact
    assert f"revoke all on function public.{name}( {signature} )" in compact
    assert (
        f"grant execute on function public.{name}( {signature} ) to {grant_role};"
        in compact
    )


def test_rpc_drop_create_revoke_and_grant_signatures_are_identical() -> None:
    for path in (SCHEMA, MIGRATION):
        sql = path.read_text(encoding="utf-8")
        compact = _compact_sql(sql)
        _assert_function_signature_contract(
            sql, "submit_report", SUBMIT_REPORT_TYPES, "authenticated"
        )
        _assert_function_signature_contract(
            sql, "attest_report_ai_evidence", ATTEST_AI_TYPES, "service_role"
        )
        legacy_submit = ", ".join(LEGACY_SUBMIT_REPORT_TYPES)
        legacy_attest = ", ".join(LEGACY_ATTEST_AI_TYPES)
        assert (
            "drop function if exists public.submit_report( "
            f"{legacy_submit} );" in compact
        )
        assert (
            "drop function if exists public.attest_report_ai_evidence( "
            f"{legacy_attest} );" in compact
        )


def test_schema_and_migration_fail_closed_ai_assignment_contract() -> None:
    for path in (SCHEMA, MIGRATION):
        sql = path.read_text(encoding="utf-8").lower()
        assert "ai_evidence_trusted boolean not null default false" in sql
        assert "reports_untrusted_ai_blocks_assignment" in sql
        assert "reports_assignment_fields_complete" in sql
        assert "reports_ai_confidence_probability" in sql
        if path == SCHEMA:
            assert "ai_confidence double precision not null default 0" in sql
        else:
            assert "alter column ai_confidence type double precision" in sql
        assert "reports_trusted_ai_requires_provenance" in sql
        assert "reports_ai_digest_format" in sql
        assert "reports_assignment_requires_verified_registry" in sql
        assert "ai_export_manifest_sha256" in sql
        assert "ai_class_map_sha256" in sql
        assert "ai_agency_registry_status" in sql

        attest = _function(sql, "attest_report_ai_evidence")
        assert "auth.role()" in attest and "service_role" in attest
        assert "ai_evidence_trusted = true" in attest
        assert (
            "v_prediction_overridden := v_predicted_slug <> v_report.category::text"
            in attest
        )
        assert "ai_prediction_overridden = v_prediction_overridden" in attest
        assert "assignment fields must be all-null or complete" in attest
        assert "p_agency_registry_status <> 'verified'" in attest
        assert "ai_export_manifest_sha256 = lower(p_export_manifest_sha256)" in attest
        assert "ai_class_map_sha256 = lower(p_class_map_sha256)" in attest


def test_trusted_ai_requires_an_allowlisted_mathematically_consistent_release() -> None:
    canonical_labels = (
        "dinas bina marga",
        "satuan polisi pamong praja",
        "dinas perhubungan",
        "kelurahan",
        "dinas pertamanan dan hutan",
        "dinas sumber daya air",
        "dinas cipta karya, tata ruang, dan pertanahan",
        "badan pembinaan badan usaha milik daerah",
        "instansi lain",
    )
    for path in (SCHEMA, MIGRATION):
        sql = path.read_text(encoding="utf-8").lower()
        assert "create table if not exists public.ai_model_releases" in sql
        assert "ai_model_releases_canonical_class_order" in sql
        assert "alter table public.ai_model_releases enable row level security" in sql
        assert (
            "revoke all privileges on public.ai_model_releases "
            "from public, anon, authenticated, service_role" in _compact_sql(sql)
        )
        for label in canonical_labels:
            assert label in sql

        attest = _function(sql, "attest_report_ai_evidence")
        for binding in (
            "release.export_manifest_sha256 = lower(p_export_manifest_sha256)",
            "release.class_map_sha256 = lower(p_class_map_sha256)",
            "release.model_name = btrim(p_model_name)",
            "release.model_version = btrim(p_model_version)",
            "release.inference_method = btrim(p_inference_method)",
            "release.attestation_enabled",
        ):
            assert binding in attest
        assert "exact canonical nine-label key set" in attest
        assert "abs(v_probability_sum - 1) > 0.000001" in attest
        assert "abs(p_confidence - v_max_probability) > 0.000001" in attest
        assert "v_predicted_slug := v_expected_slugs" in attest
        assert (
            "prediction slug must equal the deterministic probability argmax" in attest
        )
        assert "v_release.confidence_threshold" in attest
        assert "v_release.epistemic_uncertainty_threshold" in attest
        assert "agency_registry_unverified" in attest
        assert "or not v_has_complete_assignment" in attest
        assert "routing_assignment_unavailable" in attest
        assert "review-required evidence cannot include an agency assignment" in attest


def test_catch_all_is_forced_to_review_and_cannot_be_assigned() -> None:
    for path in (SCHEMA, MIGRATION):
        attest = _function(
            path.read_text(encoding="utf-8").lower(),
            "attest_report_ai_evidence",
        )
        assert "v_catch_all :=" in attest
        assert "or v_catch_all" in attest
        assert "'catch_all_class'" in attest
        assert "case when v_review_required then null" in attest

    schema = SCHEMA.read_text(encoding="utf-8").lower()
    routing_migration = ROUTING_MIGRATION.read_text(encoding="utf-8").lower()
    for sql in (schema, routing_migration):
        assert "agencies_catch_all_not_active" in sql
        assert "reports_catch_all_never_assigned" in sql
        assert "category <> 'instansi_lain' or not is_active" in sql
    seed = AGENCY_SEED.read_text(encoding="utf-8").lower()
    assert '"category_slug": "instansi_lain"' in seed
    assert '"is_active": false' in seed


def test_assignment_projection_supersedes_before_null_return() -> None:
    for path in (SCHEMA, MIGRATION):
        function = _function(
            path.read_text(encoding="utf-8").lower(),
            "project_report_assignment",
        )
        supersede = function.index("set status = 'superseded'")
        null_branch = function.index("if nullif(new.assigned_agency_id")
        assert supersede < null_branch
        assert "new.routing_method is distinct from old.routing_method" in function


def test_sensitive_tables_have_scoped_reads_and_no_client_dml() -> None:
    for path in (SCHEMA, MIGRATION):
        sql = path.read_text(encoding="utf-8").lower()
        assert "reports_select_authorized" in sql
        assert "using (public.can_access_report(id))" in sql
        for child in ("history", "report_evidence", "report_assignments", "report_sla"):
            assert f'{child}_select_authorized"' in sql
        assert "using (public.can_access_report(report_id))" in sql
        assert "revoke all privileges" in sql
        assert 'create policy "reports_select_authenticated"' not in sql
        assert 'create policy "history_select_authenticated"' not in sql
        assert (
            "on public.report_evidence for select to authenticated using (true)"
            not in sql
        )
        assert (
            "on public.report_assignments for select to authenticated using (true)"
            not in sql
        )
        assert (
            "on public.report_sla for select to authenticated using (true)" not in sql
        )
        assert "revoke all privileges on public.agencies" in sql
        assert "grant select, insert, update, delete on public.agencies" in sql
        assert 'create policy "report_images_delete_self"' in sql
        assert "not exists (\n    select 1 from public.report_evidence" in sql
        for guard in ("read", "insert", "update", "delete"):
            assert f'create policy "private_image_{guard}_guard"' in sql
        assert "on storage.objects as restrictive" in sql
        assert "'report-images'" in sql and "'profile-photos'" in sql
        assert "file_size_limit" in sql
        assert "allowed_mime_types" in sql
        assert "10485760" in sql
        assert "5242880" in sql
        assert "array['image/jpeg']::text[]" in sql


def test_controlled_rpcs_fix_identity_status_and_history() -> None:
    for path in (SCHEMA, MIGRATION):
        sql = path.read_text(encoding="utf-8").lower()
        submit = _function(sql, "submit_report")
        assert "v_actor uuid := auth.uid()" in submit
        assert "v_profile.full_name" in submit and "v_profile.email" in submit
        assert "'submitted'" in submit
        assert "v_overridden, false" in submit
        assert "null, null, null, null, null" in submit
        assert "insert into public.report_history" in submit

        status = _function(sql, "update_report_status")
        assert "security definer" in status
        assert "v_actor_role not in ('agency_admin', 'super_admin')" in status
        assert "only super_admin may reassign agency" in status
        assert "illegal report status transition" in status
        assert (
            "v_report.status = 'submitted' and p_new_status in ('verified', 'rejected')"
            in status
        )
        assert (
            "v_report.status = 'verified' and p_new_status in ('in_progress', 'rejected')"
            in status
        )
        assert "v_report.status = 'in_progress' and p_new_status = 'resolved'" in status
        assert "terminal reports cannot be reopened" in status


def test_public_feed_is_explicitly_redacted() -> None:
    for path in (SCHEMA, MIGRATION):
        sql = path.read_text(encoding="utf-8").lower()
        feed = _function(sql, "get_public_report_feed")
        assert "r.visibility = 'public'" in feed
        assert "r.status <> 'rejected'" in feed
        assert "'warga'::text" in feed
        assert "''::text as reporter_email" in feed or "''::text," in feed
        assert "round(r.latitude::numeric, 2)" in feed
        assert "r.reporter_email" not in feed
        assert "r.image_url" not in feed
        assert "r.description" not in feed
        assert "r.ai_probabilities" not in feed

        detail = _function(sql, "get_report_detail")
        assert "public.can_access_report(v_report.id)" in detail
        assert "return to_jsonb(v_report)" in detail
        assert "v_report.visibility <> 'public'" in detail
        assert "'reporter_email', ''" in detail
        assert "'image_url', ''" in detail
        assert "'ai_probabilities', '{}'::jsonb" in detail


def test_flutter_uses_rpc_boundaries_and_no_embedded_reload_secret_path() -> None:
    reports = REPORTS_REPOSITORY.read_text(encoding="utf-8")
    public_start = reports.index("Stream<List<CityReport>> watchPublicReports()")
    public_end = reports.index("Stream<CityReport?> watchReportById", public_start)
    public_method = reports[public_start:public_end]
    assert "_publicFeedRpc" in public_method
    assert ".from('reports')" not in public_method

    detail_start = reports.index("Stream<CityReport?> watchById")
    detail_end = reports.index(
        "Stream<List<ReportHistoryEntry>> watchHistory", detail_start
    )
    detail_method = reports[detail_start:detail_end]
    assert "_reportDetailRpc" in detail_method
    assert ".from('reports')" not in detail_method

    submit_start = reports.index("Future<CityReport> submitReport")
    submit_method = reports[submit_start:]
    assert "_submitReportRpc" in submit_method
    assert ".from('report_history').insert" not in submit_method
    assert ".from('reports')" not in submit_method
    assert "ai_evidence_trusted" not in submit_method
    assert "'p_ai_export_manifest_sha256'" in submit_method
    assert "'p_ai_class_map_sha256'" in submit_method
    assert "'p_ai_agency_registry_status'" in submit_method

    auth = AUTH_REPOSITORY.read_text(encoding="utf-8")
    assert "_updateOwnProfileRpc" in auth
    assert ".from('profiles')\n          .update" not in auth

    agency = AGENCY_REPOSITORY.read_text(encoding="utf-8")
    assert "http.post" not in agency
    assert "reloadInferenceServer" not in agency


def test_admin_template_contains_no_password_or_direct_auth_inserts() -> None:
    seed = ADMIN_SEED.read_text(encoding="utf-8").lower()
    assert "superadmin#" not in seed
    assert "agencyadmin#" not in seed
    assert "insert into auth.users" not in seed
    assert "insert into auth.identities" not in seed
    assert "example.invalid" in seed


def test_flutter_configuration_and_demo_path_fail_closed() -> None:
    config = APP_CONFIG.read_text(encoding="utf-8")
    assert "crmApiUrl: String.fromEnvironment('CRM_API_URL')," in config
    assert "allowInsecureHttp && uri.scheme == 'http'" in config
    assert "hasSupabaseConfig && hasInferenceConfig" in config

    router = APP_ROUTER.read_text(encoding="utf-8")
    assert "initialLocation: config.isConfigured ? '/splash' : '/setup'" in router
    assert "if (!config.isConfigured)" in router
    assert "return '/setup'" in router

    service = AI_SERVICE.read_text(encoding="utf-8")
    assert "if (config.enableTestingMode)" in service
    assert "'review_required': true" in service
    assert "'testing_mode_demo'" in service
    assert "'predicted_category_slug': response.predictedCategorySlug" in service
    assert "FallbackAiClassificationService" not in service

    cloud = CLOUD_SERVICE.read_text(encoding="utf-8")
    assert "predictedCategorySlug != matchingCategories.single.dbValue" in cloud
    assert "final policyRequiresReview" in cloud
    assert "if (policyRequiresReview && !reviewRequired)" in cloud
    assert "if (!reviewRequired && assignment == null)" in cloud
    assert "deterministicTop != matchingCategories.single" in cloud
