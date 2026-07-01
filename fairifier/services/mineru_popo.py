"""Optional MinerU-Popo post-processing integration.

MinerU-Popo (https://github.com/opendatalab/MinerU-Popo) rebuilds document-level
structure from page-level MinerU outputs. This module shells out to the external
Popo repository when ``MINERU_POPO_ENABLED`` is set and ``MINERU_POPO_ROOT`` points
to a checkout with scripts installed.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import config


logger = logging.getLogger(__name__)


class MinerUPopoError(RuntimeError):
    """Raised when MinerU-Popo post-processing fails."""


@dataclass
class MinerUPopoResult:
    """Structured output from a Popo tree build."""

    tree_path: Optional[Path]
    tree_text_path: Optional[Path]
    inference_dir: Optional[Path]
    section_markdown: Optional[str] = None
    metadata: Dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.metadata is None:
            self.metadata = {}


def is_popo_available() -> bool:
    """Return True when Popo is enabled and the repo root exists."""
    if not config.mineru_popo_enabled:
        return False
    root = config.mineru_popo_root
    return bool(root and Path(root).is_dir())


def _run_script(script_name: str, *, cwd: Path, timeout: int = 3600) -> None:
    script = cwd / "scripts" / script_name
    if not script.is_file():
        raise MinerUPopoError(f"Popo script not found: {script}")
    completed = subprocess.run(
        ["bash", str(script)],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        raise MinerUPopoError(
            f"{script_name} failed ({completed.returncode}): "
            f"{(completed.stderr or completed.stdout or '').strip()[:800]}"
        )


def postprocess_mineru_output(
    mineru_parse_dir: Path,
    *,
    model_name: str = "mineru",
    work_dir: Optional[Path] = None,
) -> MinerUPopoResult:
    """Run label normalization → inference → tree build for one MinerU parse dir.

    Expects ``mineru_parse_dir`` to contain MinerU artifacts (middle.json, etc.).
    Copies or links into ``{popo_root}/post-process/{model_name}/`` before running
    the upstream shell scripts.
    """
    if not is_popo_available():
        raise MinerUPopoError("MinerU-Popo is not enabled or MINERU_POPO_ROOT is missing")

    popo_root = Path(config.mineru_popo_root).resolve()
    parse_dir = Path(mineru_parse_dir).resolve()
    if not parse_dir.is_dir():
        raise MinerUPopoError(f"MinerU parse directory not found: {parse_dir}")

    staging = popo_root / "post-process" / model_name
    staging.mkdir(parents=True, exist_ok=True)

    # Stage middle.json and siblings for Popo label normalization input.
    for artifact in parse_dir.iterdir():
        if artifact.is_file():
            dest = staging / artifact.name
            if not dest.exists():
                dest.write_bytes(artifact.read_bytes())

    if work_dir is None:
        work_dir = parse_dir.parent / "popo_work"
    work_dir = Path(work_dir).resolve()
    work_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Running MinerU-Popo pipeline in %s", popo_root)
    _run_script("run_label_normalization.sh", cwd=popo_root)
    _run_script("run_inference.sh", cwd=popo_root)
    _run_script("build_tree.sh", cwd=popo_root)

    tree_dir = popo_root / "outputs" / "build_tree" / model_name
    tree_txt_dir = popo_root / "outputs" / "build_tree_txt" / model_name
    inference_dir = popo_root / "outputs" / "inference" / model_name

    tree_files = sorted(tree_dir.glob("*.json")) if tree_dir.is_dir() else []
    tree_txt_files = sorted(tree_txt_dir.glob("*.txt")) if tree_txt_dir.is_dir() else []

    section_markdown: Optional[str] = None
    if tree_txt_files:
        section_markdown = tree_txt_files[0].read_text(encoding="utf-8", errors="ignore")

    return MinerUPopoResult(
        tree_path=tree_files[0] if tree_files else None,
        tree_text_path=tree_txt_files[0] if tree_txt_files else None,
        inference_dir=inference_dir if inference_dir.is_dir() else None,
        section_markdown=section_markdown,
        metadata={
            "popo_root": str(popo_root),
            "staging_dir": str(staging),
            "tree_count": len(tree_files),
        },
    )


def popo_metadata_for_conversion(conversion_info: Dict[str, Any]) -> Dict[str, Any]:
    """Attach Popo tree paths to conversion metadata when available."""
    meta: Dict[str, Any] = {}
    for key in ("popo_tree_path", "popo_tree_text_path", "popo_section_markdown"):
        if conversion_info.get(key):
            meta[key] = conversion_info[key]
    return meta


def try_enrich_conversion_with_popo(conversion_info: Dict[str, Any]) -> Dict[str, Any]:
    """Optionally run Popo and merge results into *conversion_info*."""
    if not is_popo_available():
        return conversion_info
    parse_dir = conversion_info.get("parse_dir")
    if not parse_dir:
        return conversion_info
    try:
        result = postprocess_mineru_output(Path(parse_dir))
    except MinerUPopoError as exc:
        logger.warning("MinerU-Popo skipped: %s", exc)
        conversion_info["popo_error"] = str(exc)
        return conversion_info

    if result.tree_path:
        conversion_info["popo_tree_path"] = str(result.tree_path)
    if result.tree_text_path:
        conversion_info["popo_tree_text_path"] = str(result.tree_text_path)
    if result.section_markdown:
        conversion_info["popo_section_markdown"] = result.section_markdown
    conversion_info["popo_metadata"] = result.metadata
    return conversion_info
