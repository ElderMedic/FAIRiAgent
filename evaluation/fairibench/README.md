# FAIRiBench fact-level scoring (PETase)

## Why

The PETase expert annotation is a paper-level fact sheet: 5 sections, 24
fixed slots, values nested under context keys (assay, enzyme variant,
condition). It does not say how many observation units, samples or assays a
FAIR-DS record should have. The converted values-GT (`ground_truth_*_values.json`,
v3) adds that layout itself, so scoring against it rewards agreeing with the
converter:

- converted GT fields per expert fact: median 7.8x (range 4.4–23.8x);
- 67 % of substantive converted values repeat the same (field, value) in a paper,
  so one missed condition is penalised once per copied row;
- 44 % of converted values are converter-made identifiers, names, descriptions;
- 25 of 93 package fields never occur in any converted GT;
- 20 of 48 converted files were edited after conversion (expert re-approval pending).

## Three tasks, reported separately (`layered_scorer.py`)

No single number. In order of priority:

1. **Fields**: of the 24 slots the experts filled for a paper, how many have a
   real value in a package field meant for that slot (wide column, or the long
   layout `reported parameter name` + `measurement value`). Correctness is not
   checked here. `not specified` and similar placeholders count as empty.
   Slots the experts marked NA but the record fills are listed separately.
2. **Structure**: per expert material (enzyme variant, substrate), is it
   mentioned at all, does it get its own Sample/ObservationUnit row, is it named
   in a naming field (`enzyme type`, `sample name`, ...). A row is identified
   by its naming fields; descriptions are used only when no naming field
   identifies a material; a row listing more than two materials is nobody's own
   row. Name tokens shared by several materials (`LCC` in `LCC ICCG`) do not
   identify one. Also: package fields on their package sheet, samples linked to
   an observation unit (either direction), assays linked to a sample or unit,
   rows holding results linked to an expert material, row counts, duplicates.
3. **Values**: per expert value (material properties, conditions, results,
   method answers), found in a designated field, found anywhere, and for
   results tied to a material, on that material's row. For values reported
   with `± x`, whether `x` is kept is reported beside the score.

```bash
python evaluation/scripts/score_petase_layers.py --runs LABEL=RUN_DIR --expect-all --out layers.json --md layers.md
```

## Facts (`petase_facts.py`)

`petase_facts.py` turns each expert annotation into one fact per leaf value
(deterministic, no model calls). NA leaves are not facts. Explanations, values
cited from earlier work, fold changes ("approximately 3.4-fold higher activity",
a ratio rather than the slot's own quantity) and "not reported" statements are
kept in the file but not scored. Identical statements count once. Lists of materials are split into
members only when the text marks a list.

`fact_scorer.py` scores any ISA record (FAIRiAgent `metadata.json`, values-GT v3,
or `{sheet: rows}`), layout-agnostic:

| per fact | meaning |
|---|---|
| `structured` | value found in a field the package designates for the slot; wide (`enzyme melting temperature`) and long (`measurement value` + parameter) layouts are equivalent |
| `anywhere` | value found in any field (notes, names included) |
| `attached` | for values the expert tied to a material: the row holding the value is about that material (see below) |
| `strict` | `structured` × `attached` (the headline unit) |
| `uncertainty` | expert value has `± x` and was found: `x` is in the same cell or in the row's `measurement uncertainty value`; reported separately, never multiplied in |

Matching rules:

- **Units.** Numbers are unit-aware (`50 mg protein/L` = `0.05 g/L`, `48 h` =
  `2 days`). Equal numbers whose units both parse but differ in dimension
  (`1 µmol` vs `1 g/L`) do not match. Equal numbers without a predicted unit
  get half credit in a designated field.
- **Placement.** A wide result column belongs to one slot: a Km in the
  `catalytic rate constant kcat` column is not placed. A long-layout value is
  placed only when its parameter name (`reported parameter name`,
  `measurement quantity`; `measurement context` only when both are empty)
  names the slot. A row listing several kinetic parameters (`Km, Vmax, kcat`)
  designates none. Specific activity and initial rate share their fields for
  values (experts file activity outputs under either), not for the fields task.
- **Anywhere.** Outside designated fields a number counts only with a
  comparable unit, or with the slot's parameter name just before it
  (`kcat = 40.3`). A bare number in free text (`HiPrep 16/10`) is no evidence.
- **Changes.** A value stated as a change ("Ca2+ raised Tm by 6.4 °C") matches
  the change itself or the resulting absolute value (107.4 °C).
- **Attachment.** Each annotation key is resolved to one expert material
  (`Q132A_T101A`, `WT` -> the sole wild type). Starting at the value's row and
  walking up its parents (observation unit / sample / assay only), the first
  row that singles out one material decides. A row is read through its
  identity fields (`enzyme type`, `pet substrate type`, ...), then naming
  fields, then its remaining fields without `*notes`. Rows naming several
  materials decide nothing; study and investigation rows are never used.
  Keys that are not one expert material fall back to being named on the row
  or its material parents.

Building: a clause that defines a unit ("one unit is defined as 1 µmol ...
per min") is dropped from a result leaf; a leaf with nothing else becomes a
note (the unit is scored under `methods.activity_units`).

**Headline**: mean over papers of strict recall on materials, conditions and
results, with a paper-level bootstrap 95 % CI; missing outputs stay in the
denominator as 0. Method questions (actual PET vs proxy, HPLC, quantification,
endpoint vs time-resolved) are near binary and reported separately.

Reference-free checks, reported next to the headline:

- **source support**: share of predicted numeric condition/result cells whose
  numbers occur literally in the parsed source (precision proxy, lower bound);
- **NA conflicts**: values placed in slots the experts marked NA;
- **structure diagnostics**: rows per sheet, share of content-duplicate rows;
- **mismatched-paper control** (`--control`): each paper scored against another
  paper's record, i.e. the chance level the headline must beat.

## Validation

- `tests/test_fairibench_fact_scorer.py` (synthetic fixtures).
- Oracle: scoring the converted values-GT recovers 0.99 of expert facts anywhere,
  0.89 in designated fields (the gap is mostly condition series kept only in
  `reaction condition notes`); results 0.93 placed, 0.98 on the right material,
  error terms kept 1.0. Mismatched-paper control on the same records: 0.09.

## Run

```bash
python evaluation/scripts/build_petase_fact_gt.py          # writes annotated/facts/petase_facts_v1/
python evaluation/scripts/score_petase_facts.py --oracle --expect-all --control --out oracle.json
python evaluation/scripts/score_petase_facts.py --runs RUN_DIR --expect-all --control --out report.json
```

Decisions that belong to the experts are listed in
`evaluation/datasets/annotated/facts/petase_facts_v1/REVIEW_FOR_EXPERTS.md`
(local, gitignored with the data).
