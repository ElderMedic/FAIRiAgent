"""Minimal runner skeleton for private FAIRiAgent evaluation harnesses."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List


@dataclass
class HarnessCase:
    """Single evaluation case definition."""

    case_id: str
    document_path: str
    gold_path: str | None = None
    notes: str | None = None


def load_manifest(path: str | Path) -> List[HarnessCase]:
    """Load a simple case manifest."""
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    return [HarnessCase(**case) for case in manifest.get("cases", [])]


def summarize_cases(cases: List[HarnessCase]) -> Dict[str, Any]:
    """Return a lightweight manifest summary for local harness runs."""
    return {
        "case_count": len(cases),
        "case_ids": [case.case_id for case in cases],
    }


if __name__ == "__main__":
    manifest_path = Path(__file__).with_name("example_manifest.json")
    cases = load_manifest(manifest_path)
    print(json.dumps(summarize_cases(cases), indent=2))
