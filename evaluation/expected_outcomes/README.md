# FAIR-DS expected outcomes

These fixtures are external evaluation contracts for curated development
cases. Case JSON files are local-only (`evaluation/expected_outcomes/*.json`
is gitignored) because they can contain collaborator identifiers and
study-specific expectations. Production agents and materialisers must not
import or inspect this directory.

Each fixture is validated by
`evaluation/schemas/fairds_expected_outcome.schema.json` and evaluated with:

```bash
mamba run -n FAIRiAgent python \
  evaluation/scripts/evaluate_fairds_expected_outcome.py \
  <run_dir> evaluation/expected_outcomes/<case>.json \
  --output <run_dir>/reports/expected_outcome_evaluation.json
```

The source checksum prevents a changed input from silently inheriting stale
expectations. Version 2 fixtures can pin every source asset, declare the focal,
contextual, and result-data boundaries, record an evidence-backed coverage
ledger, require acceptable package alternatives, and compare source-table
values to output rows by stable keys (including numeric checks with tolerances).
This prevents a correct row count from hiding substituted, missing, invented,
or row-shifted values.

Expected outcomes are acceptance contracts, not prompts and not allowlists for
production extraction. A fixture should include source-supported metadata at
the appropriate ISA level, explicitly record source-absent review fields, and
classify bulky result matrices rather than omitting them silently. Production
agents must never import these case-specific files. Passing a fixture is
stricter than workflow completion, but it does not waive source-dependent
mandatory-field review warnings.

Do not require a derived value column merely because an identifier encodes the
same concept. When the source has no standalone column and acceptable packages
do not share a value-field contract, assert the authoritative identifiers and
entity cardinality instead. This keeps a fixture from forcing inference or
silently preferring one otherwise acceptable package.
