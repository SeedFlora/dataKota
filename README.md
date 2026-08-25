# dataKota

Research software and non-sensitive reproducibility materials for the paper
**"An Evidence Audit of Multimodal Citizen-Complaint Triage on Jakarta CRM
Data."** The project combines image and Indonesian complaint-text features,
an evidence-bound evaluation protocol, a FastAPI inference contract, and the
core Flutter/Supabase client implementation.

## Scope and scientific status

This repository is a curated public snapshot for inspection of the software,
tests, and audit protocol. It does **not** publish the underlying Jakarta CRM
records and does not convert the historical exploratory scores into held-out or
production-performance claims. The confirmatory protocol in
`configs/q2_experiment.yaml` has to be executed on an authorized, hash-bound
dataset before such claims can be made.

## Repository layout

```text
configs/                    Locked experiment and preprocessing examples
data/                       Public schema and aggregate paper-audit tables
docs/                       Data/model cards and evidence protocols
figures/                    Reproducible aggregate paper figure
notebooks/                  Output-cleared historical workflow notebooks
src/crm/                    Multimodal and evaluation-contract implementation
tools/                      Split, experiment, privacy, parity, and export tools
tests/                      Automated contract and implementation tests
smart_city_reporter_app/    Core Flutter client and Supabase contracts
serve_model.py              FastAPI inference service
```

Generated embeddings, model weights, checkpoints, prediction files, database
dumps, real environment files, and credentials are deliberately excluded.

The paper's exact arithmetic audit is independently reproducible from public
aggregate values:

```bash
python tools/reconstruct_rounded_metrics.py \
  --csv-out data/reconstructed_class_counts.csv
pip install -r requirements-analysis.txt
python tools/build_paper_figures.py
```

The reconstruction exhaustively enumerates integer class margins compatible
with the printed four-decimal precision, recall, F1, and supports. It does not
recover off-diagonal confusion cells or any sample identity.

## Quick start

The experiment-contract environment is CPU-capable after image and text
embeddings have been prepared:

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements-experiment.txt
pytest -q
```

Inspect the available commands before supplying any controlled artifacts:

```bash
python tools/build_q2_splits.py --help
python tools/run_q2_experiment.py --help
python tools/q2_readiness.py --help
```

The curated snapshot was validated on Python 3.13.5 on 26 August 2026:
`143 passed`. The test outcome is not evidence that the historical study is
reproducible or that a deployment release exists.

For the inference service, install `requirements-serve.txt`, copy
`.env.example` to `.env`, and replace every placeholder locally. The real
`.env` is ignored by Git.

## Data and privacy

No real complaint image, narrative, coordinate, account field, embedding,
checkpoint, or per-sample prediction is included. See [DATA_ACCESS.md](DATA_ACCESS.md)
and [data/README.md](data/README.md) for the access boundary and public schema.
Do not open a GitHub issue containing citizen data or credentials.

## Citation

Use the metadata in [CITATION.cff](CITATION.cff). The versioned release tag and
full commit identifier should be reported in publications; do not cite the
moving `main` branch alone.

## License

No reuse license has yet been granted. The source is public for academic
inspection; reuse or redistribution requires permission from the copyright
holders until an explicit license is added.
