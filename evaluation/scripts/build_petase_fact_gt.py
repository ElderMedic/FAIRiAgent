#!/usr/bin/env python3
"""Build fact-level PETase references from the expert annotations.

Reads the original expert JSON files (never the converted ISA values) and
writes one ``fairibench.petase_facts.v1`` file per paper plus a manifest
with checksums. Deterministic; no model calls; existing values-GT files are
not touched.

    python evaluation/scripts/build_petase_fact_gt.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from evaluation.fairibench.petase_facts import PRIMARY_KINDS, SCHEMA_VERSION, build_facts  # noqa: E402

DEFAULT_ANNOTATIONS = (ROOT / "evaluation/datasets/PETase_papers_json/manu_package_review_20261007"
                       / "expert_reference/original_annotations")
# One annotation per paper that Manu annotated in more than one batch; read first.
DEFAULT_HARMONIZED = DEFAULT_ANNOTATIONS.parent / "harmonized"
DEFAULT_VALUES = ROOT / "evaluation/datasets/annotated/values"
DEFAULT_OUT = ROOT / "evaluation/datasets/annotated/facts/petase_facts_v1"


def _doi_key(doi: str) -> str:
    return re.sub(r"[^0-9a-z]", "", str(doi).lower())


def document_ids_from_values(values_dir: Path) -> dict:
    """Map DOI -> existing document_id so the two references line up."""
    out = {}
    for path in sorted(values_dir.glob("ground_truth_petase_*_values.json")):
        doc = json.loads(path.read_text())
        out[_doi_key(doc.get("document_source", ""))] = doc["document_id"]
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotations", type=Path, default=DEFAULT_ANNOTATIONS)
    parser.add_argument("--harmonized", type=Path, default=DEFAULT_HARMONIZED)
    parser.add_argument("--values-dir", type=Path, default=DEFAULT_VALUES)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    ids = document_ids_from_values(args.values_dir)
    args.out.mkdir(parents=True, exist_ok=True)
    manifest = {"schema_version": SCHEMA_VERSION + ".manifest", "built_on": date.today().isoformat(),
                "annotation_root": str(args.annotations.relative_to(ROOT)), "documents": []}
    seen = set()
    paths = sorted(args.harmonized.glob("*.json")) + sorted(args.annotations.glob("*/*.json"))
    for path in paths:
        annotation = json.loads(path.read_text())
        key = _doi_key(annotation.get("doi", path.stem))
        doc_id = ids.get(key) or "petase_" + re.sub(r"[./]", "_", annotation.get("doi", path.stem))
        if doc_id in seen:
            print(f"duplicate annotation for {doc_id}: {path}", file=sys.stderr)
            continue
        seen.add(doc_id)
        facts = build_facts(annotation, doc_id, source_path=str(path))
        facts["source_annotation"]["path"] = str(path.relative_to(ROOT))
        target = args.out / f"{doc_id}.facts.json"
        target.write_text(json.dumps(facts, indent=1, ensure_ascii=False) + "\n")
        primary = [f for f in facts["facts"] if f["kind"] in PRIMARY_KINDS]
        manifest["documents"].append({
            "document_id": doc_id,
            "doi": annotation.get("doi"),
            "batch": path.parent.name,
            "has_values_gt": (args.values_dir / f"ground_truth_{doc_id}_values.json").exists(),
            "n_facts": len(primary),
            "n_excluded": {k: sum(1 for f in facts["facts"] if f["kind"] == k)
                           for k in ("note", "cited", "not_reported")},
            "by_group": {g: sum(1 for f in primary if f["group"] == g)
                         for g in ("materials", "conditions", "results", "methods")},
            "annotation_sha256": facts["source_annotation"]["sha256"],
            "facts_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        })
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n")
    n = len(manifest["documents"])
    print(f"wrote {n} fact files to {args.out}")
    print(f"facts total: {sum(d['n_facts'] for d in manifest['documents'])}; "
          f"without values-GT match: {[d['document_id'] for d in manifest['documents'] if not d['has_values_gt']]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
