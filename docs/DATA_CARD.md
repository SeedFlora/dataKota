# Jakarta CRM Multimodal Dataset - Data Card (Draft)

**Release status:** restricted and unavailable in this repository. The figures
below are manuscript claims and must be regenerated from the frozen source
snapshot before publication.

## Intended use

Research on decision-support classification of Jakarta citizen reports from an
image and Indonesian free-text description into eight broad agency groups plus
one heterogeneous catch-all. It is not a registry of administrative authority
and must not be used to automatically dispatch emergency or enforcement work.

## Claimed composition

- Raw collection: 88,302 reports and 487 operational SKPD strings.
- Post exact-text filtering: 61,773 reports.
- Inputs: complaint narrative and supporting image.
- Target: the historical operational handler mapped to eight agency groups plus
  `Instansi lain`.

These counts are not currently reproducible because the raw metadata, mapping
snapshot, image archive, and preprocessing receipts are absent from the repo.
Required future receipts follow docs/PREPROCESSING_PROVENANCE.md; the presence
of that validation schema is not evidence that extraction has been rerun.

## Required fields in the restricted master table

`report_id`, `embedding_index`, collection/creation timestamp, source channel,
latitude/longitude when available, original SKPD label, mapped label, narrative,
image path and content hash, mapping version, and collection snapshot id.

## Sensitive content

Narratives and images may contain names, email addresses, telephone numbers,
addresses, faces, people, documents, house numbers, vehicle plates, device EXIF,
or GPS metadata. Public visibility on the source website does not by itself make
unrestricted redistribution appropriate. Run the aggregate privacy audit, obtain
the applicable legal/ethical determination, and document redaction, access,
retention, and deletion controls before sharing any derivative.

## Label quality

Historical assignment is silver-standard operational ground truth. It may encode
operator practice, policy changes, workload, and multiple valid destinations.
The 487-to-9 mapping is many-to-one, and `Instansi lain` is not a coherent semantic
class. A two-annotator domain-expert audit and adjudication report are required.

## Split policy

The previous exact-text-deduplicated random row split is deprecated. Journal
experiments must use the group-temporal builder and preserve its manifest. Near
text/image duplicates and explicit incident identifiers are connected before
partitioning. Boundary-spanning groups are quarantined or handled according to
the recorded policy; they must not cross partitions.

## Known limitations

- Single city/platform and collection period.
- Operational labels may change with policy and organisational structure.
- Reports without images or with inaccessible images may be underrepresented.
- Citizen access and reporting behaviour introduce demographic and geographic
  selection bias.
- The catch-all class obscures open-set and multi-agency cases.
- No verified external-city or prospective evaluation is currently available.

## Version receipt required for publication

The final data card must add the collection dates, collection/legal basis,
snapshot SHA-256, preprocessing code commit, mapping version and complete table,
privacy audit summary, expert-label audit, split manifest, exclusion flow, class
distribution, missingness, and the exact access procedure.
