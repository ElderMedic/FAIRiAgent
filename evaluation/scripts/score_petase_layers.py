#!/usr/bin/env python3
"""Score PETase records on three separate tasks: fields, structure, values.

Each ``--runs LABEL=DIR`` is searched for ``metadata.json`` under a
``petase_10_*`` directory. Papers listed in the facts manifest without an
output stay in the denominator (``--expect-all``).

    python evaluation/scripts/score_petase_layers.py \\
        --runs complete_1020=output/reeval_20261020_all56/deepseek_v4.1-flash \\
        --runs B2_1102=output/seminar_baselines_20261102/baseline_b2_fairds_guided_deepseek_v4.1-flash \\
        --expect-all --out layers.json --md layers.md
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from evaluation.fairibench.layered_scorer import score_layers, summarize  # noqa: E402

DEFAULT_FACTS = ROOT / "evaluation/datasets/annotated/facts/petase_facts_v1"


def find_records(run_dir: Path) -> dict:
    found: dict = {}
    for path in sorted(run_dir.rglob("metadata.json")):
        if "_failed" in path.parts:
            continue
        doc = next((p for p in reversed(path.parts) if p.startswith("petase_10_")), None)
        if doc and doc not in found:
            found[doc] = path
    return found


def source_text(record_path: Path):
    """The parsed paper (main text and SI) the run kept next to its deliverables, if it is there."""
    for parent in (record_path.parent, record_path.parent.parent):
        parsed = sorted(parent.glob("mineru_*/**/*.md")) or sorted(parent.glob("extracted_document_content.txt"))
        if parsed:
            return "\n".join(path.read_text(errors="ignore") for path in parsed)
    return None


def pct(v) -> str:
    return "–" if v is None else f"{100 * v:.0f}%"


def render(label: str, s: dict) -> str:
    f, st, v = s["fields"], s["structure"], s["values"]
    lines = [f"### {label}",
             f"{s['n_outputs_present']}/{s['n_documents']} papers with output; "
             f"PETase package selected in {s['petase_package_selected']}", "",
             "**1. Fields** (expert-filled slots that have a real value in a designated field)", "",
             "| all slots | materials | conditions | results | methods | NA slots filled / paper |",
             "|---|---|---|---|---|---|",
             f"| {pct(f['slot_recall'])} | {pct(f['materials_recall'])} | {pct(f['conditions_recall'])} | "
             f"{pct(f['results_recall'])} | {pct(f['methods_recall'])} | {f['na_slots_filled_per_paper']} |", "",
             "**2. Structure**", "",
             "| | mentioned | own row | named in field |", "|---|---|---|---|",
             f"| enzymes | {pct(st['enzyme_mentioned'])} | {pct(st['enzyme_own_row'])} | {pct(st['enzyme_named_in_field'])} |",
             f"| substrates | {pct(st['substrate_mentioned'])} | {pct(st['substrate_own_row'])} | {pct(st['substrate_named_in_field'])} |",
             "",
             f"fields on package sheet {pct(st['field_on_package_sheet'])}; samples linked to OU "
             f"{pct(st['sample_to_ou_link'])}; assays linked {pct(st['assay_to_sample_link'])}; "
             f"papers with result rows {st['papers_with_result_rows']}; result rows linked to a material "
             f"{pct(st['result_rows_linked_to_material'])}; median rows {st['median_rows']}; "
             f"assay duplicate rows {pct(st['assay_duplicate_row_share'])}", "",
             "**3. Values** (expert values; in designated field / anywhere / on the right material when found /"
             " ± error term kept when found; share of values in the parsed text at all / in field among those."
             " Values only drawn in figures are not in the text)", "",
             "| | in field | anywhere | right material | error term kept | in parsed text | in field, text values |",
             "|---|---|---|---|---|---|---|"]
    for g, m in v.items():
        lines.append(f"| {g} | {pct(m['in_field'])} | {pct(m['anywhere'])} | {pct(m['attached_of_found'])} "
                     f"| {pct(m['uncertainty_kept_of_found'])} | {pct(m.get('in_source_text'))} "
                     f"| {pct(m.get('in_field_of_source_text'))} |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--facts", type=Path, default=DEFAULT_FACTS)
    parser.add_argument("--runs", action="append", default=[], help="LABEL=DIR")
    parser.add_argument("--expect-all", action="store_true")
    parser.add_argument("--only-present", action="store_true", help="score papers that have an output only")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--md", type=Path)
    args = parser.parse_args()

    manifest = json.loads((args.facts / "manifest.json").read_text())
    all_docs = [d["document_id"] for d in manifest["documents"]]
    report = {"schema_version": "fairibench.petase_layers.v1", "facts_root": str(args.facts), "runs": {}}
    md = []
    for item in args.runs:
        label, run_dir = item.split("=", 1)
        records = find_records(Path(run_dir))
        docs = all_docs if args.expect_all and not args.only_present else sorted(d for d in records if d in all_docs)
        results = []
        for doc in docs:
            facts = json.loads((args.facts / f"{doc}.facts.json").read_text())
            record = json.loads(records[doc].read_text()) if doc in records else None
            result = score_layers(facts, record, source_text(records[doc]) if doc in records else None)
            result["record_path"] = str(records.get(doc, ""))
            results.append(result)
        summary = summarize(results)
        report["runs"][label] = {"run_dir": run_dir, "summary": summary, "documents": results}
        md.append(render(label, summary))
        print(md[-1])
    args.out.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    if args.md:
        args.md.write_text("\n".join(md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
