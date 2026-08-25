# Public data boundary

No real Jakarta CRM records are distributed in this repository. This directory
contains one synthetic schema row and three non-sensitive aggregate tables:

- `schema.example.csv` illustrates fields expected by the locked experiment;
- `author_reported_class_metrics.csv` transcribes the author-reported historical
  four-decimal class report used by the integer-reconstruction audit;
- `reconstructed_class_counts.csv` is the deterministic output of that audit;
- `author_reported_encoder_matrix.csv` preserves the exploratory 4x4 macro-F1
  matrix discussed in the paper.

These tables contain no row-level complaint text, media, locations, identifiers,
predictions, or confusion-matrix cells. They reproduce only arithmetic on
historical aggregate records and are not suitable for training or confirmatory
performance evaluation. Authorized data must be processed in a controlled
environment and must satisfy the schema, class-map, temporal, leakage-group,
and hash-receipt checks implemented by the repository.
