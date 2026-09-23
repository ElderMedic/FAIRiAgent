"""Immutable asset checksums for benchmark manifests and run indexes."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, List, Mapping


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Return the SHA-256 digest of one file without loading it all in memory."""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def resolve_manifest_path(value: str, manifest_path: Path, project_root: Path) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate
    from_manifest = manifest_path.parent / candidate
    if from_manifest.exists():
        return from_manifest
    return project_root / candidate


def collect_asset_checksums(
    manifest: Mapping[str, Any],
    manifest_path: Path,
    *,
    project_root: Path,
    require_ground_truth: bool = True,
) -> Dict[str, Any]:
    """Resolve and hash all source/GT/package files used by a manifest.

    Missing paths are returned as errors rather than silently omitted. A
    manifest can be inspected without assets only by explicitly setting
    ``require_ground_truth=False``; execution should always use the strict mode.
    """

    assets: Dict[str, Any] = {}
    errors: List[str] = []
    for instance in manifest.get("instances", []):
        instance_id = str(instance["instance_id"])
        paths = {"source": instance.get("source_path")}
        if require_ground_truth:
            paths["ground_truth"] = instance.get("ground_truth_path")
        for manifest_key, asset_key in (
            ("package_path", "package"),
            ("ground_truth_values_path", "ground_truth_values"),
            ("standards_context_path", "standards_context"),
            ("retrieved_context_path", "retrieved_context"),
        ):
            if instance.get(manifest_key):
                paths[asset_key] = instance.get(manifest_key)
        instance_assets: Dict[str, Any] = {}
        for kind, value in paths.items():
            if not isinstance(value, str) or not value:
                errors.append("%s.%s path is missing" % (instance_id, kind))
                continue
            path = resolve_manifest_path(value, manifest_path, project_root)
            if not path.is_file():
                errors.append("%s.%s file does not exist: %s" % (instance_id, kind, path))
                continue
            instance_assets[kind] = {"path": str(path), "sha256": sha256_file(path)}
        supplementary = instance.get("supplementary_paths")
        if supplementary is not None:
            if not isinstance(supplementary, list):
                errors.append("%s.supplementary_paths must be a list" % instance_id)
            else:
                supplementary_assets = []
                for index, value in enumerate(supplementary):
                    if not isinstance(value, str) or not value:
                        errors.append(
                            "%s.supplementary_paths[%d] path is missing" % (instance_id, index)
                        )
                        continue
                    path = resolve_manifest_path(value, manifest_path, project_root)
                    if not path.is_file():
                        errors.append(
                            "%s.supplementary_paths[%d] file does not exist: %s"
                            % (instance_id, index, path)
                        )
                        continue
                    supplementary_assets.append(
                        {"path": str(path), "sha256": sha256_file(path)}
                    )
                instance_assets["supplementary"] = supplementary_assets
        assets[instance_id] = instance_assets
    if errors:
        raise FileNotFoundError("Benchmark asset validation failed:\n- " + "\n- ".join(errors))
    return assets
