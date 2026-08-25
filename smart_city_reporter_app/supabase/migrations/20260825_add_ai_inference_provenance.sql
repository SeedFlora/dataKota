-- Preserve the exact inference and review contract used for each report.
-- Nullable uncertainty fields distinguish ONNX point inference from a genuine
-- parity-checked CatBoost virtual-ensemble run; zero must not mean "unavailable".

alter table public.reports
  add column if not exists ai_inference_method text not null default 'legacy_unspecified',
  add column if not exists ai_uncertainty_method text,
  add column if not exists ai_epistemic_uncertainty double precision,
  add column if not exists ai_predictive_entropy double precision,
  add column if not exists ai_expected_data_entropy double precision,
  add column if not exists ai_epistemic_uncertainty_threshold double precision,
  add column if not exists ai_review_required boolean not null default false,
  add column if not exists ai_review_reasons text[] not null default '{}'::text[],
  add column if not exists ai_prediction_overridden boolean not null default false;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'reports_ai_uncertainty_nonnegative'
      and conrelid = 'public.reports'::regclass
  ) then
    alter table public.reports
      add constraint reports_ai_uncertainty_nonnegative check (
        (ai_epistemic_uncertainty is null or ai_epistemic_uncertainty >= 0) and
        (ai_predictive_entropy is null or ai_predictive_entropy >= 0) and
        (ai_expected_data_entropy is null or ai_expected_data_entropy >= 0) and
        (ai_epistemic_uncertainty_threshold is null or ai_epistemic_uncertainty_threshold >= 0)
      );
  end if;
end$$;

comment on column public.reports.ai_inference_method is
  'onnx_equal_weight_seed_ensemble, catboost_virtual_ensemble_seed_ensemble, or legacy_unspecified';
comment on column public.reports.ai_uncertainty_method is
  'Null when unavailable; joint_training_seed_pgs_component_mutual_information_nats for the five-seed by virtual-component PGS contract';
