"""Analyze a refactor-eval run's processing_log.jsonl.

Summarizes:
- context_usage events (per-agent token cost over time)
- Critic decisions (per agent: ACCEPT / RETRY / ESCALATE counts, scores)
- Retry pattern (per-agent attempts)

Usage:
    python evaluation/scripts/analyze_refactor_run.py output/<run_dir>
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List


def load_events(log_path: Path) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    with log_path.open(encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return events


def summarize_context_usage(events: List[Dict[str, Any]]) -> None:
    """Per-agent context-usage trajectory."""
    print("\n=== Context usage at each agent boundary ===")
    print(f"{'agent':<24}{'attempt':>9}{'total':>10}  top fields")
    print("-" * 80)
    for ev in events:
        if ev.get("event") != "context_usage":
            continue
        agent = ev.get("agent", "?")
        attempt = ev.get("attempt", "")
        total = ev.get("total_tokens", 0)
        fields = ev.get("fields", {})
        top = sorted(fields.items(), key=lambda kv: kv[1], reverse=True)[:3]
        top_s = ", ".join(f"{k}={v}" for k, v in top)
        print(f"{agent:<24}{attempt:>9}{total:>10}  {top_s}")

    # Trajectory of total tokens by agent
    by_agent_total: Dict[str, List[int]] = defaultdict(list)
    for ev in events:
        if ev.get("event") != "context_usage":
            continue
        by_agent_total[ev.get("agent", "?")].append(ev.get("total_tokens", 0))
    print("\nPer-agent total-token trajectory:")
    for agent, totals in by_agent_total.items():
        if not totals:
            continue
        print(f"  {agent:<24}attempts={len(totals)}  min={min(totals)}  "
              f"max={max(totals)}  mean={mean(totals):.0f}")


def summarize_log_lines(log_path: Path) -> None:
    """Parse the human-readable log for Critic decisions."""
    full_log = log_path.parent / "full_output.log"
    if not full_log.exists():
        return

    decisions: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    current_agent = None
    print("\n=== Critic decisions per agent ===")
    for line in full_log.read_text(encoding="utf-8").splitlines():
        if "Step" in line and ":" in line:
            for marker in [
                "DocumentParser",
                "BioMetadataAgent",
                "Planning workflow strategy",
                "KnowledgeRetriever",
                "JSONGenerator",
                "ISAValueMapper",
            ]:
                if marker in line and "Step" in line:
                    current_agent = marker
                    break
        if "Critic decision" in line and "ACCEPT" in line or "RETRY" in line or "ESCALATE" in line:
            # Extract score if present
            pass
        if "Critic:" in line and "decision:" in line:
            # e.g.  "Critic: ✅ Critic decision: ACCEPT (score: 0.95)"
            for verdict in ("ACCEPT", "RETRY", "ESCALATE"):
                if verdict in line:
                    decisions[current_agent or "unknown"].append({"verdict": verdict})
                    break

    for agent, recs in decisions.items():
        verdicts = [r["verdict"] for r in recs]
        accept = verdicts.count("ACCEPT")
        retry = verdicts.count("RETRY")
        escalate = verdicts.count("ESCALATE")
        print(f"  {agent:<32}attempts={len(recs)}  ACCEPT={accept}  RETRY={retry}  ESCALATE={escalate}")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    run_dir = Path(sys.argv[1])
    log_path = run_dir / "processing_log.jsonl"
    if not log_path.exists():
        print(f"❌ {log_path} not found")
        return 1
    events = load_events(log_path)
    print(f"Loaded {len(events)} events from {log_path}")

    summarize_context_usage(events)
    summarize_log_lines(log_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
