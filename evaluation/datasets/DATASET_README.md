# FAIRiAgent evaluation datasets

Last checked: 2026-10-16.

## Current collection

The canonical collection is
[`annotated/ground_truth_public_curated.json`](annotated/ground_truth_public_curated.json).
It contains **56 unique document records: 48 PETase papers and 8 other studies**.
All 56 `ground_truth_values_path` references resolve to local files. These are
inventory checks; source-level annotation review and evaluation results are
separate checks.

The eight other studies are `aetherobacter_fasciculatus_genome`,
`arabidopsis_vacuolar_srna`, `biosensor`, `earthworm`,
`human_gut_microbiome_temporal`, `pea_cold_stress`,
`pseudomonas_recombinase_screen`, and `sea_cucumber_gut_metagenome`.
`biorem`, `pomato`, and `compbiobench` remain outside this collection.

Use each record's `document_id` and `ground_truth_values_path` to select its
annotation. PETase records derive from expert annotation sources; conversion
into the evaluation format does not add evidence or certify semantic accuracy.

## File organization

```text
evaluation/datasets/
├── DATASET_README.md
├── annotated/
│   ├── ground_truth_public_curated.json   # current collection index
│   ├── values/                           # one values file per document
│   └── ground_truth_filtered.json        # legacy field-definition index
├── raw/                                  # source papers and supporting files
├── history/                              # retained earlier annotation versions
└── APPROVED_SPLIT_MAP_20260721.json       # frozen 27-document split
```

`annotated/ground_truth_phase4_ab.json` is an eight-document historical view.
The earlier PETase-only index is retained at
`history/petase_source_scoped_v1_20260930/evaluation/datasets/annotated/ground_truth_petase_only.json`.
These historical files retain their own scope and provenance. Use the current
canonical index to enumerate the expanded collection.

Source data and annotations stay gitignored. Evaluation code, schemas, shared
configuration and this README remain versioned. Run outputs belong in
`evaluation/runs/` or `output/`; presentation exports belong in
`docs/fairiagent-presentation/exports/`.

## Values contract

Per-document values use `fairiagent.ground_truth_values.v3`, defined in
[`ground_truth_values.schema.json`](../schemas/ground_truth_values.schema.json).
The evaluator reads rows from `isa_sheets[<sheet>].expected_rows`.

```json
{
  "document_id": "study_id",
  "schema_version": "fairiagent.ground_truth_values.v3",
  "publication": {},
  "source_assets": [],
  "isa_sheets": {
    "investigation": {
      "multi_row": true,
      "expected_rows": [{"investigation identifier": "study_id"}]
    }
  }
}
```

Populate investigation, study, observation-unit, sample and assay rows according
to the source study's entities and parent links. Keep publication details,
source assets and annotation provenance outside ISA rows. Preserve the source
annotation policy; PETase ground truth does not require invented `_evidence`
fields. Review entity counts, links, values and units against the source before
claiming a conversion is scientifically complete.

## Frozen July 2026 benchmark

[`APPROVED_SPLIT_MAP_20260721.json`](APPROVED_SPLIT_MAP_20260721.json) records
**27 documents: 7 development and 20 held-out**, including the then-current
19-paper PETase series. It pins a collection checksum and explicit document
IDs. The collection has since expanded to 56 records; the July split still
applies to its named 27 records.

For reproduction, use the campaign's approved IDs, pinned assets and protocol.
An evaluation of the expanded collection needs its own recorded split and run
manifest. Keep the July artifacts unchanged:

- [Release decision](RELEASE_DECISION_CHECKPOINT.md)
- [July split proposal](SPLIT_PROPOSAL_20260721.md)
- [July benchmark datasheet](BENCHMARK_DATASHEET_20260721.md)
- [Evaluation methodology](../../docs/en/EVALUATION_METHODOLOGY.md)

## Adding or updating a document

1. Retain its source paper, tables and expert annotation inputs under `raw/`.
2. Create or update its values file using `isa_sheets[*].expected_rows`; retain
   provenance and record any source-review limitations.
3. Update the canonical index with one unique `document_id` and a valid values
   path. Keep earlier, materially different annotations under `history/` with
   their provenance.
4. Check the index, schema, entity links and source-level values. Record a new
   campaign manifest when the evaluation scope changes.

A local inventory check, without model or API calls:

```bash
mamba run -n FAIRiAgent python -c '
import json
from pathlib import Path
p = Path("evaluation/datasets/annotated/ground_truth_public_curated.json")
docs = json.loads(p.read_text())["documents"]
assert len({d["document_id"] for d in docs}) == len(docs)
assert all(Path(d["ground_truth_values_path"]).is_file() for d in docs)
print({"documents": len(docs), "petase": sum(d["document_id"].startswith("petase_") for d in docs)})
'
```

The inventory check reports available records and paths. Evaluation methodology
and scientific annotation review remain documented separately.
