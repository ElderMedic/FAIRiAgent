#!/usr/bin/env python3
"""Compare MinerU backends (vlm-http-client vs hybrid-http-client) on sample PDFs.

Writes a JSON report under ``evaluation/runs/mineru_backend_benchmark_<timestamp>/``.

Usage:
    mamba run -n FAIRiAgent python evaluation/scripts/benchmark_mineru_backends.py
    mamba run -n FAIRiAgent python evaluation/scripts/benchmark_mineru_backends.py \\
        --pdf examples/inputs/earthworm_4n_paper_bioRXiv.pdf --skip-run
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fairifier.config import config
from fairifier.services.mineru_client import MinerUClient, MinerUConversionError
from fairifier.services.mineru_health import summarize_mineru_health


DEFAULT_PDFS = [
    PROJECT_ROOT / "examples/inputs/earthworm_4n_paper_bioRXiv.pdf",
    PROJECT_ROOT
    / "evaluation/datasets/PETase_papers_json/10.1002_anie.202218390.pdf",
]


def _metrics_from_markdown(text: str) -> dict:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    headings = sum(1 for ln in lines if ln.lstrip().startswith("#"))
    tables = text.count("|") // 3
    return {
        "chars": len(text),
        "lines": len(lines),
        "headings": headings,
        "approx_table_rows": tables,
    }


def _run_backend(
    *,
    pdf: Path,
    backend: str,
    effort: str | None,
    out_root: Path,
) -> dict:
    client = MinerUClient(
        cli_path=config.mineru_cli_path,
        server_url=config.mineru_server_url or "",
        api_url=config.mineru_api_url,
        backend=backend,
        timeout_seconds=config.mineru_timeout_seconds,
        effort=effort,
        structured_output_enabled=True,
    )
    output_dir = out_root / backend.replace("-", "_")
    if effort:
        output_dir = output_dir / effort
    output_dir.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    try:
        result = client.convert_document(pdf, output_dir=output_dir)
        elapsed = time.perf_counter() - started
        return {
            "backend": backend,
            "effort": effort,
            "success": True,
            "elapsed_seconds": round(elapsed, 2),
            "markdown_path": str(result.markdown_path),
            "parse_dir": str(result.parse_dir) if result.parse_dir else None,
            "structured_block_count": len(result.structured_blocks),
            "metrics": _metrics_from_markdown(result.markdown_text),
            "error": None,
        }
    except MinerUConversionError as exc:
        elapsed = time.perf_counter() - started
        return {
            "backend": backend,
            "effort": effort,
            "success": False,
            "elapsed_seconds": round(elapsed, 2),
            "markdown_path": None,
            "parse_dir": None,
            "structured_block_count": 0,
            "metrics": {},
            "error": str(exc),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark MinerU backends")
    parser.add_argument(
        "--pdf",
        action="append",
        type=Path,
        help="PDF to convert (repeatable). Defaults to earthworm + PETase samples.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for benchmark artifacts and report JSON.",
    )
    parser.add_argument(
        "--skip-run",
        action="store_true",
        help="Only write environment probe (no conversion).",
    )
    args = parser.parse_args()

    pdfs = args.pdf or [p for p in DEFAULT_PDFS if p.is_file()]
    if not pdfs and not args.skip_run:
        print("No sample PDFs found. Pass --pdf or add files under examples/inputs/.")
        return 1

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = args.output_dir or (
        PROJECT_ROOT / "evaluation/runs" / f"mineru_backend_benchmark_{stamp}"
    )
    run_dir.mkdir(parents=True, exist_ok=True)

    health = summarize_mineru_health(
        cli_path=config.mineru_cli_path,
        vlm_url=config.mineru_server_url,
        api_url=config.mineru_api_url,
        backend=config.mineru_backend,
    )

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "mineru_cli_version": health.get("cli_version"),
            "mineru_api_url": config.mineru_api_url,
            "mineru_vlm_url": config.mineru_server_url,
            "health_ready": health.get("ready"),
        },
        "documents": [],
    }

    if args.skip_run or not health.get("ready"):
        report["note"] = (
            "Skipped conversions: services not ready or --skip-run set. "
            "Start mineru-api and VLM, then re-run."
        )
        report_path = run_dir / "benchmark_report.json"
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        print(f"\nReport: {report_path}")
        return 0 if args.skip_run else 2

    backends = [
        ("vlm-http-client", None),
        ("hybrid-http-client", "medium"),
        ("hybrid-http-client", "high"),
    ]

    for pdf in pdfs:
        doc_entry = {"pdf": str(pdf), "runs": []}
        doc_out = run_dir / pdf.stem
        for backend, effort in backends:
            print(f"Running {backend} effort={effort} on {pdf.name} ...")
            doc_entry["runs"].append(
                _run_backend(
                    pdf=pdf,
                    backend=backend,
                    effort=effort,
                    out_root=doc_out,
                )
            )
        report["documents"].append(doc_entry)

    report_path = run_dir / "benchmark_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"\nReport: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
