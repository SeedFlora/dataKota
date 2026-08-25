# Embedding preprocessing provenance contract

Q2 evidence must reproduce the bytes-to-embedding path, not merely identify a
model repository. Framework defaults, processor files, tokenizer files, Pillow
behavior, and upstream text cleaning can all change embeddings while leaving the
model name unchanged.

Embedding extraction receipts therefore use schema version 2 and contain a
preprocessing object with schema version 1. Complete illustrative Hugging Face
image, TIMM image, and Hugging Face text profiles are in
configs/preprocessing_contracts.example.yaml. They intentionally contain
REPLACE_* values and are not valid evidence.

## Common binding rules

- Pin the encoder and any separate processor/tokenizer repository to immutable
  40--64 hexadecimal commits. A branch, tag, latest, or model name alone fails.
- Record exact installed library versions and the resolved processor/tokenizer
  class. A configuration dump without code/library identity is insufficient.
- List every processor/tokenizer asset as a safe relative path plus lowercase
  SHA-256. During export, every non-model file must be declared and every declared
  hash must equal the staged runtime file.
- Compute preprocessing_sha256 over UTF-8 JSON using sorted keys, compact
  separators, and ensure_ascii=false. The runner, readiness gate, parity gate,
  exporter, and downloaded-bundle validator recompute it independently.
- The top-level receipt pooling, prefix, max_length, and embedding dtype must equal
  the nested contract. This duplication catches runtime reinterpretation.
- Unknown fields fail. Extend the versioned schema rather than hiding another
  transform in a free-form note.

## Image requirements

The image contract declares:

- implementation framework, exact version, processor class, configuration source,
  immutable processor revision when repository-backed, and asset hashes;
- decoder/backend version, EXIF-orientation behavior, target color mode, alpha
  handling, animated-image policy, and fail-closed missing/decode policy;
- resize mode and dimensions, aspect-ratio behavior, interpolation, antialiasing,
  deterministic crop mode and crop size;
- channel order, rescaling factor, pixel mean/std normalization, tensor layout,
  and tensor dtype; and
- output pooling, embedding L2 normalization, and output dtype.

Random augmentation is intentionally unsupported for prespecified Phase-A
extraction. A future schema would need to bind the RNG, seed schedule, and draw
receipt.

For Hugging Face processors, use repository_assets and hash the exact resolved
processor files. For TIMM/torchvision transforms derived in code, use
explicit_parameters, set processor repository/revision to null, spell out the
resolved transform values, and still hash any config consumed by deployment.

## Text requirements

The text contract declares:

- tokenizer framework/library version, resolved class, repository, immutable
  revision, and every tokenizer/special-token asset;
- UTF-8 decoding, Unicode normalization, trimming, whitespace collapsing,
  lowercasing, newline, HTML, URL, mention, control-character, and empty-text
  policies;
- exact prefix, special-token behavior, truncation flag/side, maximum length,
  padding rule/side/multiple, attention-mask behavior, and token-type-ID behavior;
  and
- pooling semantics, embedding L2 normalization, and output dtype.

e5_avg and mean both mean attention-mask-weighted pooling in the current schema;
cls means the first token. The exporter may reject a scientifically valid
extraction contract if serve_model.py cannot reproduce that runtime path.

## Receipt workflow

1. Resolve the real model, processor/tokenizer, code, and package versions.
2. Inspect the actual transform/tokenizer configuration after all overrides.
3. Fill a modality template and hash every referenced asset.
4. Compute and store preprocessing_sha256; never use an example value.
5. Generate embeddings and record their file hash, row order, dimensions, dtype,
   source snapshot, and extraction-code commit in the schema-version-2 receipt.
6. Let experiment selection validate the receipt before reading an embedding.
7. Reuse the same contract in tensor-boundary parity evidence. The parity
   contract must name and hash the selected embedding cache and its extraction
   receipt. The parity tool postprocesses the native tensor with the contracted
   pooling/L2 rule and verifies it against every locked-test cache row selected
   by `embedding_index`; a caller-authored native reference cannot validate
   itself.
8. Export only the declared assets. The bundle validator repeats semantic and
   file-hash checks after download. Readiness additionally requires the image
   and text parity contracts to match the exact encoders of the selected
   candidate and every ONNX graph/external-data hash to match the export.

Classifier parity uses a schema-version-2 fused-feature receipt. It identifies
the selected candidate, both exact source embedding files/extraction receipts,
their preprocessing digests and dimensions, the ordered locked-test embedding
indices, modality order, per-modality L2 rule (`epsilon=1e-9`), concatenation
axis, and output dtype. The parity tool reconstructs the fused matrix from those
sources and requires exact equality before comparing classifier runtimes.

The repository contains no real extraction receipts or embedding artifacts at
present. These instructions define the gate; they do not attest evidence exists.
