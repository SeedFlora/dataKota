# Data access and redistribution boundary

The source dataset contains citizen reports submitted through Jakarta's CRM
ecosystem. Complaint narratives, images, precise locations, account fields,
and image metadata may contain personal or otherwise sensitive information.
Redistribution authorization has not been established for this public release.

Accordingly, this repository does not contain:

- raw or cleaned CRM records;
- complaint photographs or narrative text;
- coordinates, addresses, account identifiers, or EXIF metadata;
- image or text embeddings;
- historical checkpoints or per-sample predictions; or
- database dumps and private questionnaire records.

Access is not promised “on reasonable request.” Any future access must be
authorized in writing by the data owner and, where applicable, approved through
the relevant privacy, ethics, and data-use process. The public source therefore
supports inspection of the implementation and audit protocol, but it is not a
public data release or a complete reconstruction package for the historical
results.

The synthetic row in `data/schema.example.csv` demonstrates column structure
only and was not derived from a citizen report.
