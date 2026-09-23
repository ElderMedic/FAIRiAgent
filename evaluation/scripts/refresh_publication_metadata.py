#!/usr/bin/env python3
"""Refresh a reproducible Crossref cache for public GT publications."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
VALUES_DIR = PROJECT_ROOT / "evaluation/datasets/annotated/values"
OUTPUT = PROJECT_ROOT / "evaluation/config/publication_metadata_cache.json"


def _date_parts(message: dict[str, Any]) -> str | None:
    for key in ("published", "published-print", "published-online", "issued", "posted"):
        parts = message.get(key, {}).get("date-parts", [[]])[0]
        if parts:
            return "-".join(f"{part:02d}" for part in parts)
    return None


def fetch_crossref(doi: str) -> dict[str, Any]:
    url = f"https://api.crossref.org/works/{urllib.parse.quote(doi, safe='')}"
    request = urllib.request.Request(url, headers={"User-Agent": "FAIRiAgent-GT-curation/1.0 (mailto:fairiagent@wur.nl)"})
    with urllib.request.urlopen(request, timeout=30) as response:
        message = json.load(response)["message"]
    authors = [
        " ".join(part for part in (author.get("given"), author.get("family")) if part)
        for author in message.get("author", [])
    ]
    result = {
        "title": (message.get("title") or [None])[0],
        "doi": message.get("DOI", doi),
        "url": message.get("URL", f"https://doi.org/{doi}"),
        "type": message.get("subtype") or message.get("type"),
        "publisher": message.get("publisher"),
        "journal": (message.get("container-title") or [None])[0],
        "published": _date_parts(message),
        "authors": [author for author in authors if author],
        "source_url": url,
        "retrieved_at": date.today().isoformat(),
    }
    licenses = message.get("license", [])
    if licenses:
        result["license_url"] = licenses[0].get("URL")
    return {key: value for key, value in result.items() if value not in (None, [], "")}


def main() -> None:
    dois = set()
    for path in VALUES_DIR.glob("ground_truth_*_values.json"):
        if any(name in path.name for name in ("biorem", "pomato", "compbiobench")):
            continue
        document = json.loads(path.read_text(encoding="utf-8"))
        doi = str(document.get("paper_doi") or "").strip()
        if doi and not doi.startswith("unknown/"):
            dois.add(doi)
    dois.add("10.1101/2025.06.16.660036")

    existing = json.loads(OUTPUT.read_text(encoding="utf-8")) if OUTPUT.exists() else {}
    failures = []
    for doi in sorted(dois):
        try:
            existing[doi.lower()] = fetch_crossref(doi)
            print(f"verified {doi}: {existing[doi.lower()].get('title')}")
        except Exception as exc:  # retain prior verified cache on transient failure
            failures.append(f"{doi}: {exc}")
    OUTPUT.write_text(json.dumps(existing, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(PROJECT_ROOT)} ({len(existing)} DOI records)")
    if failures:
        raise SystemExit("Crossref failures:\n- " + "\n- ".join(failures))


if __name__ == "__main__":
    main()
