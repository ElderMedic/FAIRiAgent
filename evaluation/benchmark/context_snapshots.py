"""Materialize deterministic standards and retrieval context snapshots.

The publication baselines deliberately receive context as a versioned asset.
This module creates those assets from the manifest's FAIR-DS package and source
documents without reading ground-truth values and without initializing a model,
embedding service, or endpoint.  The retrieval implementation here is a
lexical control; semantic/hybrid retrieval must be materialized by a separate
explicit campaign with its model and index provenance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

from .assets import resolve_manifest_path, sha256_file
from .contracts import load_manifest
from evaluation.baselines.publication_runner import load_document


SCHEMA_VERSION = "fairiagent.context_snapshot.v1"
GENERATOR_VERSION = "lexical-package-context.v1"
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_./:-]{1,}")
_STOPWORDS = {
    "and",
    "are",
    "for",
    "from",
    "into",
    "that",
    "the",
    "this",
    "with",
    "your",
}


class ContextSnapshotError(ValueError):
    """Raised when a context snapshot cannot be created reproducibly."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _tokens(value: str) -> List[str]:
    result: List[str] = []
    for token in _TOKEN_RE.findall(value.casefold()):
        if token in _STOPWORDS or len(token) < 3:
            continue
        if token not in result:
            result.append(token)
    return result


def _package_queries(package: Mapping[str, Any]) -> List[Dict[str, str]]:
    metadata = package.get("metadata")
    if not isinstance(metadata, list):
        raise ContextSnapshotError("package metadata must be a list")
    queries: List[Dict[str, str]] = []
    for index, item in enumerate(metadata):
        if not isinstance(item, Mapping):
            continue
        term = item.get("term") if isinstance(item.get("term"), Mapping) else {}
        label = str(item.get("label") or term.get("label") or "").strip()
        definition = str(term.get("definition") or item.get("definition") or "").strip()
        query_tokens = _tokens(label)
        if not query_tokens:
            query_tokens = _tokens(definition)
        if not query_tokens:
            continue
        queries.append(
            {
                "query_id": str(index),
                "label": label or "unnamed field",
                "sheet_name": str(item.get("sheetName") or ""),
                "definition": definition,
                "query": " ".join(query_tokens),
            }
        )
    return queries


def _segments(source_id: str, text: str, *, max_chars: int) -> Iterable[Tuple[int, int, str]]:
    """Yield stable paragraph/window segments with source offsets."""

    if not text:
        return
    cursor = 0
    paragraphs = [part for part in re.split(r"\n\s*\n+", text) if part.strip()]
    for paragraph in paragraphs:
        start = text.find(paragraph, cursor)
        if start < 0:
            start = cursor
        end = start + len(paragraph)
        cursor = end
        if len(paragraph) <= max_chars:
            yield start, end, paragraph.strip()
            continue
        # Long PDF text blocks are split into overlapping fixed windows.  The
        # overlap preserves terms that happen to straddle a window boundary.
        step = max(1, max_chars - 120)
        for offset in range(0, len(paragraph), step):
            window = paragraph[offset : offset + max_chars].strip()
            if not window:
                continue
            yield start + offset, start + offset + len(window), window
            if offset + max_chars >= len(paragraph):
                break


def _lexical_hits(
    sources: Sequence[Mapping[str, Any]],
    query: Mapping[str, str],
    *,
    max_hits: int,
    segment_chars: int,
) -> List[Dict[str, Any]]:
    query_tokens = _tokens(str(query.get("query") or ""))
    if not query_tokens:
        return []
    candidates: List[Dict[str, Any]] = []
    for source in sources:
        source_id = str(source["source_id"])
        text = str(source["text"])
        for start, end, snippet in _segments(source_id, text, max_chars=segment_chars):
            lowered = snippet.casefold()
            matched = [token for token in query_tokens if token in lowered]
            if not matched:
                continue
            candidates.append(
                {
                    "source_id": source_id,
                    "source_path": str(source["path"]),
                    "char_start": start,
                    "char_end": end,
                    "lexical_score": len(matched),
                    "matched_terms": matched,
                    "text": snippet,
                }
            )
    candidates.sort(
        key=lambda item: (
            -int(item["lexical_score"]),
            str(item["source_id"]),
            int(item["char_start"]),
        )
    )
    selected: List[Dict[str, Any]] = []
    seen: set[Tuple[str, int, int]] = set()
    for candidate in candidates:
        key = (candidate["source_id"], candidate["char_start"], candidate["char_end"])
        if key in seen:
            continue
        seen.add(key)
        selected.append(candidate)
        if len(selected) >= max_hits:
            break
    return selected


def _load_source_records(
    instance: Mapping[str, Any],
    *,
    manifest_path: Path,
    project_root: Path,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    paths: List[Tuple[str, str]] = [("primary", str(instance["source_path"]))]
    paths.extend(
        ("supplementary_%d" % index, str(value))
        for index, value in enumerate(instance.get("supplementary_paths") or [])
    )
    records: List[Dict[str, Any]] = []
    assets: List[Dict[str, str]] = []
    for source_id, raw_path in paths:
        path = resolve_manifest_path(raw_path, manifest_path, project_root)
        if not path.is_file():
            raise ContextSnapshotError("source asset does not exist: %s" % path)
        text = load_document(path)
        records.append({"source_id": source_id, "path": str(path), "text": text})
        assets.append({"source_id": source_id, "path": str(path), "sha256": sha256_file(path)})
    return records, assets


def _standards_snapshot(package: Mapping[str, Any], package_bytes: bytes) -> str:
    # Keep the package payload lossless apart from a trailing newline.  The
    # baseline prompt supplies the output contract separately.
    payload = package_bytes.decode("utf-8")
    return payload.rstrip() + "\n"


def materialize_context_snapshots(
    manifest: Mapping[str, Any],
    manifest_path: Path,
    *,
    project_root: Path,
    output_dir: Path,
    retrieval_method: str = "lexical",
    max_hits_per_field: int = 2,
    segment_chars: int = 1_200,
    max_retrieved_chars: int = 24_000,
) -> Dict[str, Any]:
    """Create context assets and return a manifest patch without model calls."""

    if retrieval_method != "lexical":
        raise ContextSnapshotError(
            "only retrieval_method=lexical is token-free; semantic/hybrid snapshots require an explicit index campaign"
        )
    if max_hits_per_field < 1 or segment_chars < 200 or max_retrieved_chars < 1:
        raise ContextSnapshotError("context limits are invalid")
    output_dir.mkdir(parents=True, exist_ok=True)
    instance_patches: Dict[str, Dict[str, str]] = {}
    instance_reports: List[Dict[str, Any]] = []
    for instance in manifest.get("instances", []):
        if not isinstance(instance, Mapping) or not instance.get("instance_id"):
            raise ContextSnapshotError("every manifest instance needs an instance_id")
        instance_id = str(instance["instance_id"])
        raw_package = instance.get("package_path")
        if not isinstance(raw_package, str) or not raw_package:
            raise ContextSnapshotError("%s.package_path is required" % instance_id)
        package_path = resolve_manifest_path(raw_package, manifest_path, project_root)
        if not package_path.is_file():
            raise ContextSnapshotError("package asset does not exist: %s" % package_path)
        try:
            package = json.loads(package_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ContextSnapshotError("invalid package JSON: %s" % package_path) from exc
        if not isinstance(package, Mapping):
            raise ContextSnapshotError("package root must be an object: %s" % package_path)
        package_bytes = package_path.read_bytes()
        queries = _package_queries(package)
        sources, source_assets = _load_source_records(
            instance,
            manifest_path=manifest_path,
            project_root=project_root,
        )

        instance_dir = output_dir / instance_id
        instance_dir.mkdir(parents=True, exist_ok=True)
        standards_path = instance_dir / "standards_context.json"
        standards_path.write_text(_standards_snapshot(package, package_bytes), encoding="utf-8")

        retrieval_sections: List[str] = [
            "# Deterministic lexical retrieval context",
            "",
            "This snapshot was generated from the declared source assets using",
            "package field labels and definitions as lexical queries. It contains",
            "no ground-truth values and no model-generated evidence.",
            "",
            "- generator: %s" % GENERATOR_VERSION,
            "- retrieval_method: lexical",
            "- package_sha256: %s" % sha256_file(package_path),
            "",
        ]
        selected_hit_count = 0
        retrieved_chars = 0
        for query in queries:
            hits = _lexical_hits(
                sources,
                query,
                max_hits=max_hits_per_field,
                segment_chars=segment_chars,
            )
            retrieval_sections.extend(
                ["## %s (%s)" % (query["label"], query["sheet_name"] or "unspecified sheet"), ""]
            )
            if not hits:
                retrieval_sections.append("No lexical match was found in the declared source assets.")
                retrieval_sections.append("")
                continue
            for hit in hits:
                rendered = (
                    "- source_id: {source_id}\n"
                    "- source_path: {source_path}\n"
                    "- character_range: {char_start}-{char_end}\n"
                    "- lexical_score: {lexical_score}\n"
                    "\n{text}\n"
                ).format(**hit)
                if retrieved_chars + len(rendered) > max_retrieved_chars:
                    break
                retrieval_sections.append(rendered)
                retrieved_chars += len(rendered)
                selected_hit_count += 1
            if retrieved_chars >= max_retrieved_chars:
                break
        retrieval_path = instance_dir / "lexical_retrieved_context.md"
        retrieval_path.write_text("\n".join(retrieval_sections).rstrip() + "\n", encoding="utf-8")

        instance_patches[instance_id] = {
            "standards_context_path": str(standards_path),
            "retrieved_context_path": str(retrieval_path),
        }
        instance_reports.append(
            {
                "instance_id": instance_id,
                "package": {"path": str(package_path), "sha256": sha256_file(package_path)},
                "source_assets": source_assets,
                "standards_context": {
                    "path": str(standards_path),
                    "sha256": sha256_file(standards_path),
                },
                "retrieved_context": {
                    "path": str(retrieval_path),
                    "sha256": sha256_file(retrieval_path),
                    "retrieval_method": retrieval_method,
                    "query_count": len(queries),
                    "selected_hit_count": selected_hit_count,
                    "characters": retrieved_chars,
                },
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "generator_version": GENERATOR_VERSION,
        "retrieval_method": retrieval_method,
        "configuration": {
            "max_hits_per_field": max_hits_per_field,
            "segment_chars": segment_chars,
            "max_retrieved_chars": max_retrieved_chars,
        },
        "model_or_api_calls_performed": False,
        "token_calls_performed": False,
        "instance_context_paths": instance_patches,
        "instances": instance_reports,
    }


def manifest_with_context_paths(
    manifest: Mapping[str, Any],
    report: Mapping[str, Any],
) -> Dict[str, Any]:
    """Return a copied manifest with explicit snapshot paths applied.

    The input object is never modified.  The caller is responsible for giving
    the resulting manifest a new benchmark-release/provenance decision; this
    helper only wires already-checksummed context assets into a candidate copy.
    """

    paths = report.get("instance_context_paths")
    if not isinstance(paths, Mapping):
        raise ContextSnapshotError("context report lacks instance_context_paths")
    copied = dict(manifest)
    copied_instances: List[Dict[str, Any]] = []
    for instance in manifest.get("instances", []):
        if not isinstance(instance, Mapping):
            raise ContextSnapshotError("manifest instance must be an object")
        instance_id = str(instance.get("instance_id") or "")
        patch = paths.get(instance_id)
        if not isinstance(patch, Mapping):
            raise ContextSnapshotError("context report lacks instance: %s" % instance_id)
        updated = dict(instance)
        for key in ("standards_context_path", "retrieved_context_path"):
            value = patch.get(key)
            if not isinstance(value, str) or not value:
                raise ContextSnapshotError("context report lacks %s for %s" % (key, instance_id))
            updated[key] = value
        copied_instances.append(updated)
    copied["instances"] = copied_instances
    provenance = dict(manifest.get("provenance") or {})
    provenance["context_snapshot_schema_version"] = report.get("schema_version")
    provenance["context_snapshot_generator"] = report.get("generator_version")
    provenance["context_snapshot_retrieval_method"] = report.get("retrieval_method")
    copied["provenance"] = provenance
    return copied


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize deterministic benchmark context snapshots")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--manifest-output",
        type=Path,
        help="Write a candidate manifest copy with the generated context paths; never overwrites --manifest",
    )
    parser.add_argument("--max-hits-per-field", type=int, default=2)
    parser.add_argument("--segment-chars", type=int, default=1_200)
    parser.add_argument("--max-retrieved-chars", type=int, default=24_000)
    args = parser.parse_args()
    manifest = load_manifest(args.manifest)
    report = materialize_context_snapshots(
        manifest,
        args.manifest,
        project_root=args.project_root,
        output_dir=args.output_dir,
        max_hits_per_field=args.max_hits_per_field,
        segment_chars=args.segment_chars,
        max_retrieved_chars=args.max_retrieved_chars,
    )
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    if args.manifest_output:
        candidate = manifest_with_context_paths(manifest, report)
        args.manifest_output.parent.mkdir(parents=True, exist_ok=True)
        args.manifest_output.write_text(
            json.dumps(candidate, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
