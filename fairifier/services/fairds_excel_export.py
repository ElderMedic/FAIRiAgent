"""FAIR Data Station Excel export via POST /api/isa from workflow metadata.json."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def try_export_fairds_metadata_excel(
    output_dir: Path,
    *,
    fair_ds_api_url: Optional[str] = None,
) -> Optional[Path]:
    """Write ``metadata_fairds.xlsx`` when ``metadata.json`` has fillable ISA data.

    Calls FAIR-DS ``/api/isa``. Skips when the API URL is unset, the service is
    unreachable, or ``isa_structure`` has no fields. Logs on failure.

    Returns:
        Path to the ``.xlsx`` file, or ``None`` if export did not run or failed.
    """
    from ..config import config
    from ..output_paths import (
        FAIRDS_METADATA_EXCEL_FILENAME,
        resolve_metadata_output_read_path,
    )
    from .fair_data_station import FAIRDataStationClient

    url = (
        config.fair_ds_api_url
        if fair_ds_api_url is None
        else fair_ds_api_url
    )
    if not url or not str(url).strip():
        logger.debug("FAIR-DS Excel export skipped: no API URL")
        return None

    meta_path = resolve_metadata_output_read_path(Path(output_dir))
    if not meta_path:
        logger.debug(
            "FAIR-DS Excel export skipped: no metadata.json in %s",
            output_dir,
        )
        return None

    try:
        with open(meta_path, encoding="utf-8") as fh:
            data: Dict[str, Any] = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(
            "FAIR-DS Excel export skipped: cannot read %s: %s",
            meta_path,
            exc,
        )
        return None

    isa_structure = data.get("isa_structure")
    if not isinstance(isa_structure, dict) or not isa_structure:
        logger.debug(
            "FAIR-DS Excel export skipped: missing or empty isa_structure"
        )
        return None

    has_fields = False
    for _level, block in isa_structure.items():
        if isinstance(block, dict) and block.get("fields"):
            has_fields = True
            break
    if not has_fields:
        logger.debug(
            "FAIR-DS Excel export skipped: no fields under isa_structure"
        )
        return None

    base = str(url).strip().rstrip("/")
    client = FAIRDataStationClient(base)
    if not client.is_available():
        logger.warning(
            "FAIR-DS Excel export skipped: API not reachable at %s",
            base,
        )
        return None

    try:
        xlsx_bytes = client.generate_excel_from_isa_structure(isa_structure)
    except Exception as exc:
        logger.warning("FAIR-DS Excel export failed: %s", exc)
        return None

    out = Path(output_dir) / FAIRDS_METADATA_EXCEL_FILENAME
    try:
        out.write_bytes(xlsx_bytes)
    except OSError as exc:
        logger.warning(
            "FAIR-DS Excel export could not write %s: %s",
            out,
            exc,
        )
        return None

    logger.info(
        "FAIR-DS metadata Excel written: %s (%s bytes)",
        out.name,
        len(xlsx_bytes),
    )
    return out


__all__ = ["try_export_fairds_metadata_excel"]
