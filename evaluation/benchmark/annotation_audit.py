"""Token-free audit of human ground-truth collection overlap and policy."""

from __future__ import annotations

import argparse
import hashlib
import json
from itertools import combinations
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _contains_evidence(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(key == "_evidence" or _contains_evidence(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_evidence(item) for item in value)
    return False


def _resolve_values_path(value: Any, collection_path: Path) -> Path | None:
    """Resolve a declared value-GT path without inventing an annotation."""

    if not isinstance(value, str) or not value.strip():
        return None
    candidate = Path(value)
    candidates = [candidate]
    if not candidate.is_absolute():
        candidates.extend(
            [
                collection_path.parent / candidate,
                collection_path.parent / "values" / candidate.name,
            ]
        )
    for path in candidates:
        if path.is_file():
            return path
    return None


def _annotation_fingerprint(document: Mapping[str, Any], collection_path: Path) -> Dict[str, Any]:
    """Hash the reference values, not surrounding collection metadata.

    PETase collection entries may differ in legacy metadata while pointing to
    one canonical converted-values file.  Comparing the whole entry would
    incorrectly call that a value-annotation disagreement.
    """

    values_path = _resolve_values_path(document.get("ground_truth_values_path"), collection_path)
    if values_path is not None:
        return {
            "source": "ground_truth_values_path",
            "path": str(values_path),
            "sha256": hashlib.sha256(values_path.read_bytes()).hexdigest(),
        }
    if "ground_truth_fields" in document:
        return {
            "source": "ground_truth_fields",
            "path": None,
            "sha256": _canonical_hash(document.get("ground_truth_fields")),
        }
    if "ground_truth" in document:
        return {
            "source": "ground_truth",
            "path": None,
            "sha256": _canonical_hash(document.get("ground_truth")),
        }
    return {
        "source": "missing",
        "path": None,
        "sha256": None,
    }


def _load_collection(path: Path) -> Dict[str, Mapping[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    documents = value.get("documents") if isinstance(value, Mapping) else None
    if not isinstance(documents, list):
        raise ValueError("ground-truth collection must contain a documents list: %s" % path)
    result: Dict[str, Mapping[str, Any]] = {}
    for index, document in enumerate(documents):
        if not isinstance(document, Mapping) or not isinstance(document.get("document_id"), str):
            raise ValueError("invalid document %d in %s" % (index, path))
        document_id = str(document["document_id"])
        if document_id in result:
            raise ValueError("duplicate document_id in %s: %s" % (path, document_id))
        result[document_id] = document
    return result


def audit_collections(paths: Sequence[Path]) -> Dict[str, Any]:
    """Compare collection membership and converted annotation content."""

    if not paths:
        raise ValueError("at least one ground-truth collection is required")
    collections: Dict[str, Dict[str, Mapping[str, Any]]] = {
        str(path): _load_collection(path) for path in paths
    }
    annotation_fingerprints: Dict[str, Dict[str, Dict[str, Any]]] = {
        collection_path: {
            document_id: _annotation_fingerprint(document, Path(collection_path))
            for document_id, document in documents.items()
        }
        for collection_path, documents in collections.items()
    }
    pairwise: List[Dict[str, Any]] = []
    for left, right in combinations(collections, 2):
        left_docs = collections[left]
        right_docs = collections[right]
        shared = sorted(set(left_docs) & set(right_docs))
        identical: List[str] = []
        different: List[str] = []
        metadata_identical: List[str] = []
        metadata_different: List[str] = []
        for document_id in shared:
            if (
                annotation_fingerprints[left][document_id]["sha256"]
                == annotation_fingerprints[right][document_id]["sha256"]
                and annotation_fingerprints[left][document_id]["sha256"] is not None
            ):
                identical.append(document_id)
            else:
                different.append(document_id)
            if _canonical_hash(left_docs[document_id]) == _canonical_hash(right_docs[document_id]):
                metadata_identical.append(document_id)
            else:
                metadata_different.append(document_id)
        pairwise.append(
            {
                "left": left,
                "right": right,
                "shared_document_count": len(shared),
                "shared_document_ids": shared,
                "annotation_identical_ids": identical,
                "annotation_different_ids": different,
                "metadata_identical_ids": metadata_identical,
                "metadata_different_ids": metadata_different,
            }
        )
    document_rows = []
    for collection_path, documents in collections.items():
        for document_id, document in sorted(documents.items()):
            document_rows.append(
                {
                    "collection": collection_path,
                    "document_id": document_id,
                    "document_sha256": _canonical_hash(document),
                    "annotation_sha256": annotation_fingerprints[collection_path][document_id]["sha256"],
                    "annotation_source": annotation_fingerprints[collection_path][document_id]["source"],
                    "annotation_values_path": annotation_fingerprints[collection_path][document_id]["path"],
                    "contains_evidence_annotation": _contains_evidence(document),
                    "domain": ((document.get("metadata") or {}).get("domain") if isinstance(document.get("metadata"), Mapping) else None),
                }
            )
    return {
        "schema_version": "fairiagent.annotation_audit.v2",
        "collection_count": len(collections),
        "collections": {
            path: {"document_count": len(documents), "document_ids": sorted(documents)}
            for path, documents in collections.items()
        },
        "pairwise_overlap": pairwise,
        "documents": document_rows,
        "comparison_policy": {
            "annotation_comparison": "ground_truth_values_path_bytes_then_ground_truth_fields_then_ground_truth",
            "metadata_comparison": "complete_collection_entry",
            "field_level_merge": False,
        },
        "evidence_annotation_required": False,
        "model_or_api_calls_performed": False,
    }


def merge_non_overlapping_collections(
    paths: Sequence[Path],
    *,
    authoritative_overlaps: Mapping[str, str],
) -> Dict[str, Any]:
    """Materialize a non-overlapping collection from explicit source choices.

    A document appearing in one collection is copied as-is.  An overlapping
    document requires ``authoritative_overlaps[document_id]`` to name the exact
    collection path that supplies the reference answer.  No annotation is
    merged field-by-field and no evidence is added.
    """

    if not paths:
        raise ValueError("at least one ground-truth collection is required")
    collections = {str(path): _load_collection(path) for path in paths}
    owners: Dict[str, list[str]] = {}
    for collection_path, documents in collections.items():
        for document_id in documents:
            owners.setdefault(document_id, []).append(collection_path)

    selected_documents: Dict[str, Mapping[str, Any]] = {}
    selected_sources: Dict[str, str] = {}
    for document_id, candidates in sorted(owners.items()):
        if len(candidates) == 1:
            selected_path = candidates[0]
        else:
            selected_path = authoritative_overlaps.get(document_id)
            if selected_path not in candidates:
                raise ValueError(
                    "overlapping document requires an authoritative collection: %s (choose one of %s)"
                    % (document_id, candidates)
                )
        selected_document = dict(collections[selected_path][document_id])
        values_path = (
            Path(selected_path).parent
            / "values"
            / ("ground_truth_%s_values.json" % document_id)
        )
        if values_path.is_file() and "ground_truth_values_path" not in selected_document:
            selected_document["ground_truth_values_path"] = str(values_path)
        selected_documents[document_id] = selected_document
        selected_sources[document_id] = selected_path

    unknown_choices = sorted(set(authoritative_overlaps) - set(owners))
    if unknown_choices:
        raise ValueError(
            "authoritative choices reference documents absent from collections: "
            + ", ".join(unknown_choices)
        )

    return {
        "schema_version": "fairiagent.ground_truth_collection.v2",
        "documents": [selected_documents[key] for key in sorted(selected_documents)],
        "provenance": {
            "source_collections": sorted(collections),
            "selected_source_by_document": selected_sources,
            "authoritative_overlap_choices": dict(sorted(authoritative_overlaps.items())),
            "annotation_policy": "human_annotation_converted_without_evidence_requirement",
        },
        "evidence_annotation_required": False,
        "model_or_api_calls_performed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit ground-truth collection overlap without model access")
    parser.add_argument("--ground-truth", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--merged-output",
        type=Path,
        help="Write a merged collection after every overlap has an explicit source choice.",
    )
    parser.add_argument(
        "--authoritative-overlap",
        action="append",
        default=[],
        metavar="DOCUMENT_ID=COLLECTION_PATH",
        help="Explicit source for an overlapping document; repeat as needed.",
    )
    args = parser.parse_args()
    report = audit_collections(args.ground_truth)
    choices: Dict[str, str] = {}
    for value in args.authoritative_overlap:
        if "=" not in value:
            parser.error("--authoritative-overlap must use DOCUMENT_ID=COLLECTION_PATH")
        document_id, collection_path = value.split("=", 1)
        if not document_id or not collection_path:
            parser.error("--authoritative-overlap must use DOCUMENT_ID=COLLECTION_PATH")
        choices[document_id] = collection_path
    if choices and not args.merged_output:
        parser.error("--merged-output is required when --authoritative-overlap is supplied")
    if args.merged_output:
        merged = merge_non_overlapping_collections(
            args.ground_truth,
            authoritative_overlaps=choices,
        )
        args.merged_output.parent.mkdir(parents=True, exist_ok=True)
        args.merged_output.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
        report["merged_collection_path"] = str(args.merged_output)
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
