# Source Workspace and Multi-file Inputs

FAIRiAgent preserves input files in a source workspace instead of treating context
limits as permission to discard information. Prompts receive compact inventories
and evidence snippets; the original source text and table rows remain available in
the run output directory.

## Artifacts

When `FAIRIFIER_SOURCE_WORKSPACE_ENABLED=true`, each run writes:

- `source_workspace/source_manifest.json`: source ids, paths, methods, roles, sizes, and table references.
- `source_workspace/source_workspace.md`: compact inventory for agents and reports.
- `source_workspace/sources/source_*.md`: full source text or MinerU markdown.
- `source_workspace/tables/*.jsonl`: full table rows for CSV/TSV/Excel inputs.

Single-file runs use the same structure with one source. Directory and zip inputs
create one source per supported file.

## Multi-file Stability

Before applying the input-file cap, FAIRiAgent prioritizes likely research files:
main manuscripts, supplements, metadata/sample files, tables, and protocol/method
files. Generic notes or administrative files are downweighted so they are less
likely to consume the limited input budget.

The current merge path still records field conflicts after per-source parsing.
The source workspace is the base for stricter field-level source weighting and
outlier handling in later extraction passes.

## Metadata Evidence Search

During JSON metadata generation, FAIRiAgent builds field-specific evidence
context from the preserved workspace. For each FAIR-DS field, it searches source
text with literal queries from the field name and description. For table inputs,
it searches the full JSONL table rows by column name and cell value, so values
outside the table preview can still be surfaced to the LLM.

When evidence is found, prompts ask the model to cite source references such as
`source_001:123-145` or `source_002 table samples row 4` in the generated
metadata evidence field.

## Configuration

Use `.env` or shell variables:

```bash
FAIRIFIER_SOURCE_WORKSPACE_ENABLED=true
FAIRIFIER_SOURCE_WORKSPACE_DIR_NAME=source_workspace
FAIRIFIER_SOURCE_MAX_SELECTED_INPUTS=8
FAIRIFIER_SOURCE_INVENTORY_MAX_CHARS_PER_SOURCE=4000
FAIRIFIER_SOURCE_READ_MAX_CHARS=8000
FAIRIFIER_SOURCE_GREP_CONTEXT_CHARS=600
FAIRIFIER_SOURCE_MAX_SEARCH_RESULTS=20
FAIRIFIER_SOURCE_ROLE_DETECTION_ENABLED=true
FAIRIFIER_SOURCE_MIN_RELEVANCE_SCORE=0.35
FAIRIFIER_SOURCE_OUTLIER_POLICY=downweight
FAIRIFIER_METADATA_CONTEXT_MODE=agentic_search
FAIRIFIER_METADATA_MAX_CONTEXT_CHARS_PER_FIELD=12000
FAIRIFIER_TABLE_FULL_SCAN_ENABLED=true
FAIRIFIER_TABLE_SEARCH_MAX_ROWS=5000
FAIRIFIER_TABLE_SEARCH_MAX_MATCHES=50
```

The `*_MAX_CONTEXT_*`, grep, and table-search limits control how much is exposed
to an agent in one step. They do not remove content from the workspace.
