#!/usr/bin/env python3
"""
G1 B3 — Flat Agent Baseline Runner
=====================================
Full pipeline simulation WITHOUT ISA hierarchical constraints.
- Single-prompt extraction (like B1)
- But uses Critic-style self-evaluation (the LLM checks its own output)
- No entity_id grouping, no cross-sheet parent linkage
- Produces same isa_values format as B1

Usage:
  python evaluation/paper_experiments_v1/run_baseline_b3.py \
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

B3_EXTRACTION_PROMPT = """You are a FAIR metadata extraction system. Extract metadata from the following scientific document into ISA-Tab format. Extract fields FLAT (no entity_id grouping, no cross-sheet parent linkage).

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
1. Extract values ONLY from the document content. Do not invent values.
2. If a value is not found, omit the field — do NOT write "N/A".
3. Every row in a sheet must have the same set of columns.
4. The "columns" array must list ALL field names present in that sheet's rows.
5. Each row is INDEPENDENT — no entity_id grouping, no parent-child ISA links required.
6. Output valid JSON parseable by json.loads()."""

B3_CRITIC_PROMPT = """You are evaluating a metadata extraction output for a scientific document. Rate the output on:
1. Field presence: Are important fields present?
2. Value accuracy: Do values match the document?
3. Completeness: Are multi-row sheets adequately covered?

Output from the extractor:
{extracted_output}

Original document snippet (for verification):
{document_snippet}

Provide a CRITIQUE and SCORE (0.0-1.0). Then output IMPROVED metadata in the same JSON format.
Respond with ONLY a JSON object:
{{{{
  "score": 0.X,
  "critique": "Brief assessment",
  "improved_output": {{{{... same format as input ...}}}}
}}}}"""


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


def load_isa_schema_hints(doc_id: str) -> str:
    return """ISA Structure:
  **investigation**: Extract all investigation-level metadata.
  **study**: Extract all study-level metadata.
  **assay**: Extract all assay-level metadata.
  **sample**: Extract all sample-level metadata.
  **observationunit**: Extract all observation unit metadata."""


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


def normalize_to_metadata_json(parsed: dict, doc_id: str, critic_score: float = 0.0) -> dict:
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
        "fairifier_version": "baseline-b3-v1.0.0",
        "metadata": metadata_list,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "document_source": doc_id,
        "overall_confidence": critic_score if critic_score > 0 else 0.55,
        "needs_review": critic_score < 0.65,
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
            "json_generation": max(critic_score, 0.55),
        },
        "errors": [],
        "warnings": ["Baseline B3: flat agent, self-critique, no ISA constraint, no FAIR-DS API"],
    }


def parse_args():
    p = argparse.ArgumentParser(description="G1 B3 Flat Agent Baseline Runner")
    p.add_argument("--doc", required=True, choices=ALL_DOCS, help="Document ID")
    p.add_argument("--model", required=True, choices=sorted(MODEL_CONFIGS.keys()),
                   help="Local Ollama model preset")
    p.add_argument("--repeats", type=int, default=1, help="Number of repeats")
    p.add_argument("--output-dir", type=Path,
                   default=PAPER_ROOT / "runs" / "baseline_b3",
                   help="Output directory")
    return p.parse_args()


def main():
    args = parse_args()
    config = load_config(args.model)
    model_name = config.get("FAIRIFIER_LLM_MODEL", args.model)

    print(f"=== G1 B3 Flat Agent Baseline ===")
    print(f"  Document: {args.doc}")
    print(f"  Model: {model_name}")

    doc_text = load_document_text(args.doc)
    print(f"  Loaded {len(doc_text)} characters")

    for run_idx in range(1, args.repeats + 1):
        config_name = MODEL_CONFIGS[args.model].stem
        run_dir = args.output_dir / config_name / args.doc / f"run_{run_idx}"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / ".running").touch()

        print(f"\n--- Run {run_idx}/{args.repeats} ---")
        start_time = time.time()
        llm_responses = []

        try:
            # Step 1: Flat extraction
            print(f"  Step 1: Flat extraction...")
            max_chars = 25000
            doc_truncated = doc_text[:max_chars]
            if len(doc_text) > max_chars:
                doc_truncated += "\n\n[... document truncated ...]"

            ext_prompt = B3_EXTRACTION_PROMPT.format(
                document_content=doc_truncated,
            )
            ext_result = call_llm(ext_prompt, config)
            ext_elapsed = time.time() - start_time
            print(f"    Extraction: {ext_elapsed:.1f}s, {ext_result['total_tokens']} tokens")
            llm_responses.append({
                "agent": "B3_Extractor",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "model": ext_result["model"],
                "total_tokens": ext_result["total_tokens"],
                "response": ext_result["raw_content"],
            })

            parsed = extract_json(ext_result["raw_content"])
            print(f"    Sheets: {[s for s in ['investigation','study','assay','sample','observationunit'] if s in parsed]}")

            # Step 2: Self-critique (like Critic but without ISA constraints)
            print(f"  Step 2: Self-critique...")
            critic_prompt = B3_CRITIC_PROMPT.format(
                extracted_output=json.dumps(parsed, indent=2)[:3000],
                document_snippet=doc_text[:1500],
            )
            critic_result = call_llm(critic_prompt, config)
            critic_elapsed = time.time() - start_time - ext_elapsed
            print(f"    Critique: {critic_elapsed:.1f}s, {critic_result['total_tokens']} tokens")
            llm_responses.append({
                "agent": "B3_Critic",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "model": critic_result["model"],
                "total_tokens": critic_result["total_tokens"],
                "response": critic_result["raw_content"],
            })

            # Parse critic output
            try:
                critic_data = extract_json(critic_result["raw_content"])
                critic_score = float(critic_data.get("score", 0.5))
                improved = critic_data.get("improved_output", parsed)
                print(f"    Critic score: {critic_score:.2f}")
            except Exception:
                critic_score = 0.5
                improved = parsed
                print(f"    Could not parse critic output, using original")

            # Use improved output
            metadata = normalize_to_metadata_json(improved, args.doc, critic_score)
            total_fields = metadata["statistics"]["total_fields"]
            elapsed = time.time() - start_time

            # Write artifacts (same format as B1)
            with open(run_dir / "metadata.json", "w") as f:
                json.dump(metadata, f, indent=2)

            eval_result = {
                "success": total_fields > 0,
                "project_id": f"baseline_b3_{args.model}_{args.doc}_run{run_idx}",
                "document_id": args.doc,
                "config_name": config_name,
                "run_idx": run_idx,
                "runtime_seconds": elapsed,
                "start_time": datetime.now(timezone.utc).isoformat(),
                "end_time": datetime.now(timezone.utc).isoformat(),
                "output_dir": str(run_dir),
                "metadata_json_path": str(run_dir / "metadata.json"),
                "n_fields_extracted": total_fields,
                "confidence_scores": {
                    "baseline_b3_flat_agent": critic_score,
                    "critic_score": critic_score,
                },
                "error": None,
            }
            with open(run_dir / "eval_result.json", "w") as f:
                json.dump(eval_result, f, indent=2)

            with open(run_dir / "llm_responses.json", "w") as f:
                json.dump(llm_responses, f, indent=2)

            runtime_config = {
                "baseline": "B3_flat_agent",
                "model": model_name,
                "provider": "ollama",
                "document": args.doc,
                "critic_score": critic_score,
                "has_self_critique": True,
            }
            with open(run_dir / "runtime_config.json", "w") as f:
                json.dump(runtime_config, f, indent=2)

            with open(run_dir / "processing_log.jsonl", "w") as f:
                f.write(json.dumps({
                    "event": "baseline_b3_complete",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "document": args.doc,
                    "n_fields": total_fields,
                    "runtime_s": elapsed,
                    "critic_score": critic_score,
                    "tokens_extraction": ext_result["total_tokens"],
                    "tokens_critic": critic_result["total_tokens"],
                }) + "\n")

            print(f"  [OK] Fields: {total_fields}, Critic: {critic_score:.2f}, Time: {elapsed:.0f}s")

        except Exception as e:
            elapsed = time.time() - start_time
            print(f"  [FAIL] {e}")
            eval_result = {
                "success": False,
                "project_id": f"baseline_b3_{args.model}_{args.doc}_run{run_idx}",
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
