#!/usr/bin/env python3
"""Score metadata records against expert PETase facts.

Inputs are pairs of (document_id, metadata.json). They can be given as a
directory that is searched for ``deliverables/metadata.json`` (the document
id is read from the path), as explicit ``DOC_ID=path`` pairs, or as values-GT
files (``--oracle``) to check how much of the expert content the converted
ISA reference itself keeps.

Documents listed with ``--expect`` that have no record stay in the
denominator with score 0.

    python evaluation/scripts/score_petase_facts.py --runs RUN_DIR --out report.json
    python evaluation/scripts/score_petase_facts.py --oracle --out oracle.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from evaluation.fairibench.fact_scorer import aggregate, score_record  # noqa: E402

DEFAULT_FACTS = ROOT / "evaluation/datasets/annotated/facts/petase_facts_v1"
DEFAULT_VALUES = ROOT / "evaluation/datasets/annotated/values"
_DOC_RE = re.compile(r"(petase_10_[0-9A-Za-z_\-]+?)(?:/|$)")


def _find_records(run_dir: Path):
    for path in sorted(run_dir.rglob("metadata.json")):
        match = None
        for part in reversed(path.parts):
            if part.startswith("petase_10_"):
                match = part
                break
        if match:
            yield match, path


def _source_text(metadata_path: Path) -> str | None:
    run_dir = metadata_path.parent.parent
    mds = sorted(run_dir.glob("mineru_*/**/*.md"))
    if not mds:
        return None
    return "\n".join(p.read_text(errors="ignore") for p in mds)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--facts", type=Path, default=DEFAULT_FACTS)
    parser.add_argument("--runs", type=Path, action="append", default=[],
                        help="directory searched for */deliverables/metadata.json")
    parser.add_argument("--record", action="append", default=[], help="DOC_ID=path/to/metadata.json")
    parser.add_argument("--oracle", action="store_true",
                        help="score the converted values-GT files instead of system outputs")
    parser.add_argument("--values-dir", type=Path, default=DEFAULT_VALUES)
    parser.add_argument("--expect", nargs="*", default=None,
                        help="document ids in the denominator (default: those with a record)")
    parser.add_argument("--expect-all", action="store_true",
                        help="every paper in the facts manifest is in the denominator")
    parser.add_argument("--control", action="store_true",
                        help="also score each paper against the next paper's record (chance level)")
    parser.add_argument("--label", default="")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    records: dict = {}
    sources: dict = {}
    if args.oracle:
        for path in sorted(args.values_dir.glob("ground_truth_petase_*_values.json")):
            doc = json.loads(path.read_text())
            records[doc["document_id"]] = path
    for run_dir in args.runs:
        for doc_id, path in _find_records(run_dir):
            if doc_id in records:
                print(f"warning: several records for {doc_id}; keeping {records[doc_id]}", file=sys.stderr)
                continue
            records[doc_id] = path
            sources[doc_id] = _source_text(path)
    for item in args.record:
        doc_id, path = item.split("=", 1)
        records[doc_id] = Path(path)
        sources[doc_id] = _source_text(Path(path))

    if args.expect_all:
        manifest = json.loads((args.facts / "manifest.json").read_text())
        expected = [d["document_id"] for d in manifest["documents"]]
    elif args.expect is not None:
        expected = args.expect
    else:
        expected = sorted(records)
    results = []
    for doc_id in expected:
        facts_path = args.facts / f"{doc_id}.facts.json"
        if not facts_path.exists():
            print(f"no expert facts for {doc_id}; skipped", file=sys.stderr)
            continue
        facts_doc = json.loads(facts_path.read_text())
        record = json.loads(records[doc_id].read_text()) if doc_id in records else None
        result = score_record(facts_doc, record, source_text=sources.get(doc_id))
        result["record_path"] = str(records.get(doc_id, ""))
        results.append(result)

    if args.control:
        # Chance level: each paper's facts scored against another paper's record.
        ids = [r["document_id"] for r in results]
        control = []
        for i, doc_id in enumerate(ids):
            other = ids[(i + 1) % len(ids)]
            if other in records:
                control.append(score_record(json.loads((args.facts / f"{doc_id}.facts.json").read_text()),
                                            json.loads(records[other].read_text())))
        control_summary = aggregate(control)
    report = {"schema_version": "fairibench.fact_score.v1", "label": args.label,
              "facts_root": str(args.facts), "summary": aggregate(results), "documents": results}
    if args.control:
        report["mismatched_paper_control"] = control_summary
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")

    s = report["summary"]
    print(f"{args.label or 'report'}: {s['n_outputs_present']}/{s['n_documents']} outputs, {s['n_facts']} facts "
          f"(headline = {', '.join(s['headline_groups'])})")
    for metric in ("strict", "structured", "anywhere"):
        m = s[metric]
        print(f"  {metric:10s} macro {m['macro']}  ci95 {m['macro_ci95']}  micro {m['micro']}")
    print("  by group (micro strict / structured / anywhere):")
    for g, v in s["by_group_micro"].items():
        print(f"    {g:11s} n={v['n']:4d}  {v['strict']:.3f} / {v['structured']:.3f} / {v['anywhere']:.3f}")
    print(f"  entity attachment {s['entity_attachment_rate']}  error term kept {s.get('uncertainty_kept_rate')}"
          f"  source support {s.get('source_support_rate')}"
          f"  NA conflicts {s['na_conflicts']}")
    if args.control:
        c = report["mismatched_paper_control"]
        print(f"  chance level (mismatched paper): strict macro {c['strict']['macro']} "
              f"ci95 {c['strict']['macro_ci95']}; methods {c['by_group_micro'].get('methods', {}).get('strict')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
