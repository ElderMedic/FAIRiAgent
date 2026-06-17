#!/usr/bin/env python3
"""
G1 B1 — Zero-Shot Baseline Runner
===================================
Single-prompt LLM extraction of FAIR-DS metadata. No Planner, no Critic,
no retries, no FAIR-DS API calls. Produces artifacts compatible with the
FAIRiAgent evaluation pipeline.

Usage:
  python evaluation/paper_experiments_v1/run_baseline_b1.py \
    --doc earthworm --model qwen3.5-9b --repeats 1
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

PAPER_ROOT = PROJECT_ROOT / "evaluation" / "paper_experiments_v1"
CONFIG_DIR = PROJECT_ROOT / "evaluation" / "config" / "model_configs"
GT_VALUES_DIR = PROJECT_ROOT / "evaluation" / "datasets" / "annotated" / "values"

MODEL_CONFIGS = {
    "qwen3.5-9b":  CONFIG_DIR / "ollama_qwen3.5-9b_v1.4.0.env",
    "qwen3.6-27b": CONFIG_DIR / "ollama_qwen3.6-27b_v1.4.0.env",
    "qwen3.6-35b": CONFIG_DIR / "ollama_qwen3.6-35b_v1.4.0.env",
    "gemma4-31b":  CONFIG_DIR / "ollama_gemma4-31b_v1.4.0.env",
    "gpt-oss-20b": CONFIG_DIR / "ollama_gpt-oss-20b_v1.5.0.env",
    "deepseek-v4-pro": CONFIG_DIR / "deepseek_v4-pro_v1.4.0.env",
}

ALL_DOCS = [
    "aetherobacter_fasciculatus_genome", "arabidopsis_vacuolar_srna",
    "biorem", "biosensor", "earthworm", "human_gut_microbiome_temporal",
    "pea_cold_stress", "pomato", "pseudomonas_recombinase_screen",
    "sea_cucumber_gut_metagenome",
]

DOC_PATHS = {}  # Loaded from ground truth at runtime

def load_doc_paths() -> dict:
    """Load document paths from ground truth file."""
    gt_file = PROJECT_ROOT / "evaluation" / "datasets" / "annotated" / "ground_truth_filtered.json"
    with open(gt_file) as f:
        data = json.load(f)
    paths = {}
    for doc in data.get("documents", []):
        doc_id = doc["document_id"]
        doc_path = doc.get("document_path", "")
        if doc_path:
            full_path = PROJECT_ROOT / doc_path
            if full_path.exists():
                paths[doc_id] = str(full_path)
    return paths


def load_document_text(doc_id: str) -> str:
    """Load document text from MinerU markdown or study narrative."""
    paths = load_doc_paths()
    doc_path = paths.get(doc_id)
    if not doc_path:
        raise FileNotFoundError(f"No document path for '{doc_id}' in ground truth")
    text = Path(doc_path).read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"Empty document: {doc_path}")
    return text


def parse_args():
    p = argparse.ArgumentParser(description="G1 B1 Zero-Shot Baseline Runner")
    p.add_argument("--doc", required=True, choices=ALL_DOCS,
                   help="Document ID to evaluate")
    p.add_argument("--model", required=True, choices=sorted(MODEL_CONFIGS.keys()),
                   help="Local Ollama model preset")
    p.add_argument("--repeats", type=int, default=1,
                   help="Number of independent repeats")
    p.add_argument("--output-dir", type=Path,
                   default=PAPER_ROOT / "runs" / "baseline_b1",
                   help="Output directory under paper_experiments_v1")
    return p.parse_args()


def load_config(model_key: str) -> dict:
    """Load model config from env file, return dict of env overrides."""
    env_path = MODEL_CONFIGS[model_key]
    config = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            config[k.strip()] = v.strip().strip('"').strip("'")
    return config


def load_isa_schema_hints(doc_id: str) -> str:
    return """ISA Structure:
  **investigation**: Extract all investigation-level metadata.
  **study**: Extract all study-level metadata.
  **assay**: Extract all assay-level metadata.
  **sample**: Extract all sample-level metadata.
  **observationunit**: Extract all observation unit metadata."""


B1_PROMPT_TEMPLATE = """You are a FAIR metadata extraction system. Extract metadata from the following scientific document according to the ISA (Investigation-Study-Assay-Sample-ObservationUnit) model used by the FAIR Data Station.

# Document Content
{document_content}

# ISA Sheet Descriptions
{sheets_spec}

# Output Format
Respond with ONLY a valid JSON object — no markdown, no explanations.
The JSON must have this exact structure:
```json
{{
  "investigation": {{
    "columns": ["column1", "column2", ...],
    "rows": [
      {{"column1": "value", "column2": "value", ...}}
    ]
  }},
  "study": {{ "columns": [...], "rows": [...] }},
  "assay": {{ "columns": [...], "rows": [...] }},
  "sample": {{ "columns": [...], "rows": [...] }},
  "observationunit": {{ "columns": [...], "rows": [...] }}
}}
```

Rules:
1. Extract values ONLY from the document content. Do not invent values.
2. If a value is not found in the document, omit the field — do NOT write "N/A" or "unknown".
3. Determine field names from the document itself — use descriptive, lower-case names with spaces (e.g., "sample identifier", "geographic location").
4. Every row in a sheet must have the same set of columns.
5. The "columns" array must list ALL field names present in that sheet's rows.
6. Output valid JSON parseable by json.loads()."""

SHEET_SPECS = {
    "investigation": "Project-level administrative metadata: title, description, identifiers, and contact/affiliation information.",
    "study": "Experimental design metadata: study identifiers, design type, factors, and protocols.",
    "assay": "Measurement metadata: assay identifiers, measurement/technology type, platform, and instrument details.",
    "sample": "Biological source material metadata. Use one row per distinct sample if multiple exist.",
    "observationunit": "Observation unit metadata linking samples to studies. Use one row per distinct unit if multiple exist.",
}


def build_prompt(doc_text: str, doc_id: str) -> str:
    """Build the B1 zero-shot prompt."""
    sheets_spec = "\n".join(f"## {s}\n{spec}" for s, spec in SHEET_SPECS.items())

    # Truncate document if too long (Ollama context limits)
    max_chars = 30000
    if len(doc_text) > max_chars:
        doc_text = doc_text[:max_chars] + "\n\n[... document truncated ...]"

    return B1_PROMPT_TEMPLATE.format(
        document_content=doc_text,
        sheets_spec=sheets_spec,
    )


def call_llm(prompt: str, config: dict, timeout: int = 3600) -> dict:
    """Call LLM - routes to Ollama or DeepSeek API based on config's LLM_PROVIDER."""
    provider = config.get("LLM_PROVIDER", "ollama")
    if provider == "deepseek":
        return _call_deepseek(prompt, config, timeout)
    else:
        return _call_ollama(prompt, config, timeout)


def _call_ollama(prompt: str, config: dict, timeout: int = 3600) -> dict:
    """Make a single Ollama chat completion call."""
    import requests

    model_name = config.get("FAIRIFIER_LLM_MODEL", "")
    base_url = config.get("FAIRIFIER_LLM_BASE_URL", "http://localhost:11434")
    response = requests.post(
        f"{base_url}/api/chat",
        json={
            "model": model_name,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": 0.3},
        },
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    return {
        "raw_content": data["message"]["content"],
        "model": data.get("model", model_name),
        "total_tokens": data.get("eval_count", 0),
        "prompt_tokens": data.get("prompt_eval_count", 0),
        "duration_ns": data.get("total_duration", 0),
    }


def _call_deepseek(prompt: str, config: dict, timeout: int = 3600) -> dict:
    """Make a DeepSeek API chat completion call (OpenAI-compatible)."""
    import requests

    model_name = config.get("FAIRIFIER_LLM_MODEL", "deepseek-v4-pro")
    api_key = config.get("DEEPSEEK_API_KEY") or config.get("LLM_API_KEY", "")
    base_url = config.get("DEEPSEEK_API_BASE_URL", "https://api.deepseek.com")
    response = requests.post(
        f"{base_url}/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": 4096,
            "stream": False,
            "thinking": {"type": "disabled"},
        },
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    content = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})
    return {
        "raw_content": content,
        "model": data.get("model", model_name),
        "total_tokens": usage.get("total_tokens", 0),
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "duration_ns": 0,
    }


def extract_json(content: str) -> dict:
    """Extract and parse JSON from LLM response text."""
    from fairifier.utils.llm_helper import _parse_json_with_fallback
    parsed = _parse_json_with_fallback(content)
    if parsed is not None:
        return parsed
    raise ValueError("Failed to extract valid JSON from LLM response.")


def normalize_to_metadata_json(parsed: dict, doc_id: str) -> dict:
    """Convert raw B1 LLM output to FAIRiAgent-compatible metadata.json shape."""
    isa_values = {}
    total_fields = 0

    for sheet in ["investigation", "study", "assay", "sample", "observationunit"]:
        sheet_data = parsed.get(sheet, {})
        if isinstance(sheet_data, list):
            # Handle list-of-dicts format
            if sheet_data and isinstance(sheet_data[0], dict):
                columns = list(sheet_data[0].keys())
                rows = sheet_data
            else:
                columns, rows = [], []
        elif isinstance(sheet_data, dict):
            columns = sheet_data.get("columns", [])
            rows = sheet_data.get("rows", [])
        else:
            columns, rows = [], []

        isa_values[sheet] = {"columns": columns, "rows": rows}
        total_fields += sum(len(r) for r in rows if isinstance(r, dict))

    # Convert isa_values rows to evaluator-compatible metadata list
    metadata_list = []
    for sheet in ["investigation", "study", "assay", "sample", "observationunit"]:
        sheet_data = isa_values.get(sheet, {})
        for row in sheet_data.get("rows", []):
            if not isinstance(row, dict):
                continue
            entity_id = row.get("entity_id", row.get("identifier", ""))
            for key, val in row.items():
                if key in ("entity_id",):
                    continue
                metadata_list.append({
                    "field_name": key,
                    "value": str(val) if val is not None else "",
                    "isa_sheet": sheet,
                    "entity_id": entity_id,
                    "evidence": "",
                    "confidence": 0.5,
                    "origin": "baseline",
                    "package_source": "default",
                    "status": "provisional"
                })

    return {
        "fairifier_version": "baseline-b1-v1.0.0",
        "metadata": metadata_list,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "document_source": doc_id,
        "overall_confidence": 0.5,
        "needs_review": True,
        "packages_used": [],
        "isa_values": isa_values,
        "isa_structure": {},
        "document_info": {},
        "statistics": {
            "total_fields": total_fields,
            "confirmed_fields": total_fields,
            "provisional_fields": 0,
            "source_grounding_summary": {
                "source_grounded_fields": 0,
                "ungrounded_high_confidence_fields": 0,
                "table_backed_fields": 0,
            },
        },
        "confidence_scores": {
            "document_parsing": 1.0,
            "knowledge_retrieval": 0.5,
            "json_generation": 0.5,
        },
        "errors": [],
        "warnings": ["Baseline B1: zero-shot single-prompt, no FAIR-DS API, no Critic"],
    }


def main():
    args = parse_args()
    config = load_config(args.model)
    model_name = config.get("FAIRIFIER_LLM_MODEL", args.model)

    print(f"=== G1 B1 Zero-Shot Baseline ===")
    print(f"  Document: {args.doc}")
    print(f"  Model: {model_name}")
    print(f"  Repeats: {args.repeats}")
    print(f"  Output: {args.output_dir}")

    # Load document text from ground-truth-registered path
    print(f"\nLoading document '{args.doc}'...")
    try:
        doc_text = load_document_text(args.doc)
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)
    print(f"  Loaded {len(doc_text)} characters")

    # Build prompt
    prompt = build_prompt(doc_text, args.doc)
    print(f"  Prompt length: {len(prompt)} characters")

    for run_idx in range(1, args.repeats + 1):
        config_name = MODEL_CONFIGS[args.model].stem
        run_dir = args.output_dir / config_name / args.doc / f"run_{run_idx}"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / ".running").touch()

        print(f"\n--- Run {run_idx}/{args.repeats} ---")
        start_time = time.time()

        try:
            # Call Ollama
            print(f"  Calling Ollama ({model_name})...")
            result = call_llm(prompt, config)
            elapsed = time.time() - start_time
            print(f"  Response received in {elapsed:.1f}s")
            print(f"  Tokens: {result['total_tokens']}")

            parsed = extract_json(result["raw_content"])
            print(f"  Parsed sheets: {[s for s in ['investigation','study','assay','sample','observationunit'] if s in parsed]}")

            # Convert to metadata.json format
            metadata = normalize_to_metadata_json(parsed, args.doc)
            total_fields = metadata["statistics"]["total_fields"]
            print(f"  Total fields extracted: {total_fields}")

            # Write metadata.json
            with open(run_dir / "metadata.json", "w") as f:
                json.dump(metadata, f, indent=2)

            # Write eval_result.json
            eval_result = {
                "success": total_fields > 0,
                "project_id": f"baseline_b1_{args.model}_{args.doc}_run{run_idx}",
                "document_id": args.doc,
                "config_name": config_name,
                "run_idx": run_idx,
                "runtime_seconds": elapsed,
                "start_time": datetime.now(timezone.utc).isoformat(),
                "end_time": datetime.now(timezone.utc).isoformat(),
                "output_dir": str(run_dir),
                "metadata_json_path": str(run_dir / "metadata.json"),
                "n_fields_extracted": total_fields,
                "confidence_scores": {"baseline_b1_zeroshot": 0.5},
                "error": None,
            }
            with open(run_dir / "eval_result.json", "w") as f:
                json.dump(eval_result, f, indent=2)

            # Write llm_responses.json
            llm_responses = [{
                "agent": "BaselineB1",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "model": result["model"],
                "prompt_tokens": result["prompt_tokens"],
                "completion_tokens": result["total_tokens"] - result["prompt_tokens"],
                "total_tokens": result["total_tokens"],
                "response": result["raw_content"],
                "parsed_output": parsed,
            }]
            with open(run_dir / "llm_responses.json", "w") as f:
                json.dump(llm_responses, f, indent=2)

            # Write runtime_config.json
            runtime_config = {
                "baseline": "B1_zero_shot",
                "model": model_name,
                "provider": "ollama",
                "document": args.doc,
                "prompt_length": len(prompt),
                "extracted_chars": len(doc_text),
                "temperature": 0.7,
            }
            with open(run_dir / "runtime_config.json", "w") as f:
                json.dump(runtime_config, f, indent=2)

            # Write minimal processing_log.jsonl
            with open(run_dir / "processing_log.jsonl", "w") as f:
                f.write(json.dumps({
                    "event": "baseline_b1_complete",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "document": args.doc,
                    "n_fields": total_fields,
                    "runtime_s": elapsed,
                    "tokens": result["total_tokens"],
                }) + "\n")

            print(f"  [OK] Artifacts written to {run_dir}")

        except Exception as e:
            elapsed = time.time() - start_time
            print(f"  [FAIL] {e}")
            eval_result = {
                "success": False,
                "project_id": f"baseline_b1_{args.model}_{args.doc}_run{run_idx}",
                "document_id": args.doc,
                "config_name": config_name,
                "run_idx": run_idx,
                "runtime_seconds": elapsed,
                "error": str(e),
            }
            with open(run_dir / "eval_result.json", "w") as f:
                json.dump(eval_result, f, indent=2)

        finally:
            (run_dir / ".running").unlink(missing_ok=True)

    print(f"\nDone. Output: {args.output_dir}")


if __name__ == "__main__":
    main()
