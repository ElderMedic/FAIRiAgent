#!/usr/bin/env python3
"""
G1 B2 — Pre-Meta-Style RAG Baseline Runner
============================================
Loads FAIR-DS packages as static ontology priors, selects relevant packages
via a Planner LLM call, then extracts metadata with FAIR-DS field guidance.
Single-pass extraction, no Critic loop, no dynamic API queries.

Usage:
  python evaluation/paper_experiments_v1/run_baseline_b2.py \
    --doc earthworm --model qwen3.6-27b --repeats 1
"""

from __future__ import annotations

import argparse
import json
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

FAIR_DS_API = "http://localhost:8083"

# Cache for static FAIR-DS data
_fairds_cache: dict | None = None


def load_config(model_key: str) -> dict:
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


def load_document_text(doc_id: str) -> str:
    gt_file = PROJECT_ROOT / "evaluation" / "datasets" / "annotated" / "ground_truth_filtered.json"
    with open(gt_file) as f:
        data = json.load(f)
    paths = {}
    for doc in data.get("documents", []):
        full_path = PROJECT_ROOT / doc.get("document_path", "")
        if full_path.exists():
            paths[doc["document_id"]] = str(full_path)
    doc_path = paths.get(doc_id)
    if not doc_path:
        raise FileNotFoundError(f"No document path for '{doc_id}'")
    text = Path(doc_path).read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"Empty document: {doc_path}")
    return text


def fetch_fairds_data() -> dict:
    """Fetch all FAIR-DS packages and their fields (static, one-time)."""
    global _fairds_cache
    if _fairds_cache is not None:
        return _fairds_cache

    import requests

    # Get package name list
    packages_resp = requests.get(f"{FAIR_DS_API}/api/package", timeout=30)
    packages_resp.raise_for_status()
    packages_data = packages_resp.json()
    package_names = [p for p in packages_data.get("packages", []) if isinstance(p, str)]

    # Fetch fields for each package via /api/package?name=<name>
    packages = {}
    for pkg_name in package_names:
        try:
            pkg_resp = requests.get(
                f"{FAIR_DS_API}/api/package",
                params={"name": pkg_name},
                timeout=30,
            )
            if pkg_resp.status_code == 200:
                pkg_data = pkg_resp.json()
                packages[pkg_name] = pkg_data
        except Exception:
            pass

    # Fetch terms
    try:
        terms_resp = requests.get(f"{FAIR_DS_API}/api/terms", timeout=30)
        terms = terms_resp.json() if terms_resp.status_code == 200 else []
    except Exception:
        terms = []

    _fairds_cache = {"packages": packages, "terms": terms}
    return _fairds_cache


def build_package_summary(packages: dict) -> str:
    """Build a compact summary of packages and their mandatory fields."""
    lines = []
    for pkg_name, pkg_data in sorted(packages.items()):
        metadata = pkg_data.get("metadata", [])
        # Group fields by level (ISA sheet)
        by_level: dict = {}
        for item in metadata:
            level = item.get("level", "unknown")
            by_level.setdefault(level, []).append(item)
        total_fields = len(metadata)
        lines.append(f"  **{pkg_name}** ({total_fields} fields)")
        for level, items in sorted(by_level.items()):
            mandatory = [
                it.get("label", "?")
                for it in items
                if it.get("requirement") == "MANDATORY"
            ]
            if mandatory:
                lines.append(f"    {level}: {', '.join(mandatory[:8])}")
    return "\n".join(lines)


PACKAGE_SELECTION_PROMPT = """You are selecting FAIR-DS metadata packages for a scientific document. Choose packages that match the document's methods and data types.

Document content (first portion):
{document_snippet}

Available FAIR-DS packages ({n_packages} total):
{package_list}

Select 5-8 packages most relevant to this document's methodology and data. Include both domain-specific packages (e.g., soil, water, host-associated) AND methodology packages (e.g., Genome, Illumina, Metabolomics, Proteomics). The "default" package should always be included.

Respond with ONLY a JSON array of package names:
["default", "package2", "package3", ...]"""


B2_EXTRACTION_PROMPT = """You are a FAIR metadata extraction system. Extract metadata from the following scientific document according to the ISA (Investigation-Study-Assay-Sample-ObservationUnit) model.

# FAIR-DS Ontology Guidance
The following field names are from FAIR-DS packages. Use these EXACT field names where possible:

{package_fields}

# Document Content
{document_content}

# Output Format
Respond with ONLY a valid JSON object — no markdown, no explanations:
{{{{
  "investigation": {{{{"columns": ["col1", "col2", ...], "rows": [{{"col1": "value", ...}}]}}}},
  "study": {{{{"columns": [...], "rows": [...]}}}},
  "assay": {{{{"columns": [...], "rows": [...]}}}},
  "sample": {{{{"columns": [...], "rows": [...]}}}},
  "observationunit": {{{{"columns": [...], "rows": [...]}}}}
}}}}

Rules:
1. Use EXACT field names from the FAIR-DS ontology guidance where applicable.
2. Extract values ONLY from the document content. Do not invent values.
3. If a value is not found, omit the field — do NOT write "N/A".
4. Every row must have the same columns.
5. The "columns" array must list ALL field names in that sheet.
6. Output valid JSON parseable by json.loads()."""


def call_llm(prompt: str, config: dict, timeout: int = 1800) -> dict:
    """Call LLM - routes to Ollama or DeepSeek API based on config's LLM_PROVIDER."""
    provider = config.get("LLM_PROVIDER", "ollama")
    if provider == "deepseek":
        return _call_deepseek(prompt, config, timeout)
    else:
        return _call_ollama(prompt, config, timeout)


def _call_ollama(prompt: str, config: dict, timeout: int = 1800) -> dict:
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
    content = data["message"]["content"]
    return {
        "raw_content": content,
        "model": data.get("model", model_name),
        "total_tokens": data.get("eval_count", 0),
        "prompt_tokens": data.get("prompt_eval_count", 0),
        "duration_ns": data.get("total_duration", 0),
    }


def _call_deepseek(prompt: str, config: dict, timeout: int = 1800) -> dict:
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
    content = content.strip()
    if content.startswith("{"):
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass
    json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", content, re.DOTALL)
    if json_match:
        content = json_match.group(1).strip()
        if content.startswith("{"):
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                pass
    obj_match = re.search(r"\{.*\}", content, re.DOTALL)
    if obj_match:
        content = obj_match.group(0)
    return json.loads(content)


def normalize_to_metadata_json(parsed: dict, doc_id: str, packages_used: list) -> dict:
    """Convert raw LLM output to FAIRiAgent-compatible metadata.json shape."""
    isa_values = {}
    total_fields = 0
    for sheet in ["investigation", "study", "assay", "sample", "observationunit"]:
        sheet_data = parsed.get(sheet, {})
        if isinstance(sheet_data, dict):
            columns = sheet_data.get("columns", [])
            rows = sheet_data.get("rows", [])
        else:
            columns, rows = [], []
        isa_values[sheet] = {"columns": columns, "rows": rows}
        total_fields += sum(len(r) for r in rows if isinstance(r, dict))

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
        "fairifier_version": "baseline-b2-v1.0.0",
        "metadata": metadata_list,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "document_source": doc_id,
        "overall_confidence": 0.6,
        "needs_review": True,
        "packages_used": packages_used,
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
            "knowledge_retrieval": 0.7,
            "json_generation": 0.6,
        },
        "errors": [],
        "warnings": ["Baseline B2: Pre-Meta RAG, static FAIR-DS context, no dynamic API, no Critic"],
    }


def load_isa_schema_hints(doc_id: str) -> str:
    return """ISA Structure:
  **investigation**: Extract all investigation-level metadata.
  **study**: Extract all study-level metadata.
  **assay**: Extract all assay-level metadata.
  **sample**: Extract all sample-level metadata.
  **observationunit**: Extract all observation unit metadata."""


def parse_args():
    p = argparse.ArgumentParser(description="G1 B2 Pre-Meta RAG Baseline Runner")
    p.add_argument("--doc", required=True, choices=ALL_DOCS, help="Document ID")
    p.add_argument("--model", required=True, choices=sorted(MODEL_CONFIGS.keys()),
                   help="Local Ollama model preset")
    p.add_argument("--repeats", type=int, default=1, help="Number of repeats")
    p.add_argument("--output-dir", type=Path,
                   default=PAPER_ROOT / "runs" / "baseline_b2",
                   help="Output directory")
    return p.parse_args()


def main():
    args = parse_args()
    config = load_config(args.model)
    model_name = config.get("FAIRIFIER_LLM_MODEL", args.model)

    print(f"=== G1 B2 Pre-Meta RAG Baseline ===")
    print(f"  Document: {args.doc}")
    print(f"  Model: {model_name}")
    print(f"  Output: {args.output_dir}")

    # Load document
    print(f"\nLoading document '{args.doc}'...")
    doc_text = load_document_text(args.doc)
    print(f"  Loaded {len(doc_text)} characters")

    # Load FAIR-DS data (static, one-time)
    print(f"\nLoading FAIR-DS ontology data...")
    fairds = fetch_fairds_data()
    packages = fairds["packages"]
    print(f"  Loaded {len(packages)} packages, {len(fairds['terms'])} terms")

    # Build package list for selection
    package_list = []
    for pkg_name, pkg_data in sorted(packages.items()):
        metadata = pkg_data.get("metadata", [])
        n_fields = len(metadata)
        package_list.append(f"  - {pkg_name} ({n_fields} fields)")
    package_list_str = "\n".join(package_list[:60])  # Truncate for prompt

    for run_idx in range(1, args.repeats + 1):
        config_name = MODEL_CONFIGS[args.model].stem
        run_dir = args.output_dir / config_name / args.doc / f"run_{run_idx}"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / ".running").touch()

        print(f"\n--- Run {run_idx}/{args.repeats} ---")
        start_time = time.time()
        llm_responses = []

        try:
            # Step 1: Package selection via Planner LLM call
            print(f"  Step 1: Selecting packages...")
            doc_snippet = doc_text[:2000].strip()
            sel_prompt = PACKAGE_SELECTION_PROMPT.format(
                document_snippet=doc_snippet,
                n_packages=len(packages),
                package_list=package_list_str,
            )
            sel_result = call_llm(sel_prompt, config)
            sel_elapsed = time.time() - start_time
            print(f"    Package selection: {sel_elapsed:.1f}s")
            llm_responses.append({
                "agent": "B2_Planner",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "model": sel_result["model"],
                "total_tokens": sel_result["total_tokens"],
                "response": sel_result["raw_content"],
            })

            # Parse selected packages
            try:
                selected_packages = extract_json(sel_result["raw_content"])
                if not isinstance(selected_packages, list):
                    selected_packages = []
            except Exception:
                # Fallback: use default packages
                selected_packages = ["Genome", "soil", "default", "Illumina"]

            # Filter to known packages
            selected_packages = [p for p in selected_packages if p in packages]
            if not selected_packages:
                selected_packages = ["default", "Genome"]
            print(f"    Selected: {selected_packages}")

            # Step 2: Build FAIR-DS field guidance from selected packages
            field_lines = []
            for pkg_name in selected_packages:
                pkg_data = packages[pkg_name]
                metadata = pkg_data.get("metadata", [])
                # Group by level (ISA sheet)
                by_level: dict = {}
                for item in metadata:
                    level = item.get("level", "unknown")
                    by_level.setdefault(level, []).append(item)
                for level, items in sorted(by_level.items()):
                    field_names = [it.get("label", "?") for it in items]
                    if field_names:
                        field_lines.append(f"  [{pkg_name}/{level}]: {', '.join(field_names[:20])}")

            if not field_lines:
                field_lines = ["  (no specific field guidance available)"]
            field_guidance = "\n".join(field_lines[:80])

            # Step 3: Extraction with FAIR-DS guidance
            print(f"  Step 2: Extracting metadata with FAIR-DS guidance...")
            # Truncate document
            max_chars = 25000
            doc_truncated = doc_text[:max_chars]
            if len(doc_text) > max_chars:
                doc_truncated += "\n\n[... document truncated ...]"

            ext_prompt = B2_EXTRACTION_PROMPT.format(
                package_fields=field_guidance,
                document_content=doc_truncated,
            )
            ext_result = call_llm(ext_prompt, config)
            ext_elapsed = time.time() - start_time - sel_elapsed
            print(f"    Extraction: {ext_elapsed:.1f}s")
            print(f"    Tokens: {ext_result['total_tokens']}")
            llm_responses.append({
                "agent": "B2_JSONGenerator",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "model": ext_result["model"],
                "total_tokens": ext_result["total_tokens"],
                "response": ext_result["raw_content"],
            })

            # Parse output
            parsed = extract_json(ext_result["raw_content"])
            print(f"    Parsed sheets: {[s for s in ['investigation','study','assay','sample','observationunit'] if s in parsed]}")

            # Convert to metadata.json format
            metadata = normalize_to_metadata_json(parsed, args.doc, selected_packages)
            total_fields = metadata["statistics"]["total_fields"]
            print(f"    Fields extracted: {total_fields}")

            elapsed = time.time() - start_time

            # Write artifacts
            with open(run_dir / "metadata.json", "w") as f:
                json.dump(metadata, f, indent=2)

            eval_result = {
                "success": total_fields > 0,
                "project_id": f"baseline_b2_{args.model}_{args.doc}_run{run_idx}",
                "document_id": args.doc,
                "config_name": config_name,
                "run_idx": run_idx,
                "runtime_seconds": elapsed,
                "start_time": datetime.now(timezone.utc).isoformat(),
                "end_time": datetime.now(timezone.utc).isoformat(),
                "output_dir": str(run_dir),
                "metadata_json_path": str(run_dir / "metadata.json"),
                "n_fields_extracted": total_fields,
                "confidence_scores": {"baseline_b2_rag": 0.6},
                "error": None,
            }
            with open(run_dir / "eval_result.json", "w") as f:
                json.dump(eval_result, f, indent=2)

            with open(run_dir / "llm_responses.json", "w") as f:
                json.dump(llm_responses, f, indent=2)

            runtime_config = {
                "baseline": "B2_pre_meta_rag",
                "model": model_name,
                "provider": "ollama",
                "document": args.doc,
                "selected_packages": selected_packages,
                "fairds_packages_loaded": len(packages),
            }
            with open(run_dir / "runtime_config.json", "w") as f:
                json.dump(runtime_config, f, indent=2)

            with open(run_dir / "processing_log.jsonl", "w") as f:
                f.write(json.dumps({
                    "event": "baseline_b2_complete",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "document": args.doc,
                    "n_fields": total_fields,
                    "runtime_s": elapsed,
                    "packages": selected_packages,
                    "tokens_planner": sel_result["total_tokens"],
                    "tokens_generator": ext_result["total_tokens"],
                }) + "\n")

            print(f"  [OK] Artifacts written to {run_dir}")

        except Exception as e:
            elapsed = time.time() - start_time
            print(f"  [FAIL] {e}")
            eval_result = {
                "success": False,
                "project_id": f"baseline_b2_{args.model}_{args.doc}_run{run_idx}",
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
