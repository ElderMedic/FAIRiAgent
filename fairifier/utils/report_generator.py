"""Report generator for workflow execution summary."""

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ..config import config
from .performance_metrics import build_performance_metrics


class WorkflowReportGenerator:
    """Generate comprehensive workflow execution reports."""
    
    def __init__(self, output_dir: Optional[str] = None):
        """
        Initialize report generator.
        
        Args:
            output_dir: Directory to save reports (optional)
        """
        self.output_dir = Path(output_dir) if output_dir else None
    
    def generate_report(
        self,
        state: Dict[str, Any],
        metadata_json_path: Optional[str] = None,
        *,
        llm_responses: Optional[Sequence[Mapping[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Generate comprehensive workflow execution report.
        
        Args:
            state: FAIRifierState dictionary
            metadata_json_path: Path to metadata.json on disk (optional)
            
        Returns:
            Dictionary containing report data
        """
        if llm_responses is None:
            # Avoid initializing a provider connection during report generation,
            # while still including telemetry from the workflow's shared helper.
            from .llm_helper import get_existing_llm_helper

            existing_llm_helper = get_existing_llm_helper()
            llm_responses = (
                existing_llm_helper.llm_responses
                if existing_llm_helper is not None
                else []
            )

        report = {
            "generated_at": datetime.now().isoformat(),
            "workflow_status": state.get("status", "unknown"),
            "execution_summary": self._generate_execution_summary(state),
            "quality_metrics": self._generate_quality_metrics(state),
            "retrieval_metrics": self._generate_retrieval_metrics(state),
            "section_coverage": state.get("section_coverage", {}),
            "auto_repair_trace": state.get("auto_repair_trace", {}),
            "field_analysis": self._analyze_fields(state, metadata_json_path),
            "duplicate_check": self._check_duplicates(state, metadata_json_path),
            "retry_analysis": self._analyze_retries(state),
            "timeline": self._generate_timeline(state),
            "performance": build_performance_metrics(
                state,
                llm_responses,
                config,
            ),
        }
        
        return report
    
    def _generate_execution_summary(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Generate execution summary statistics."""
        execution_history = state.get("execution_history", [])
        summary = state.get("execution_summary", {})
        
        # Count agents executed
        agents_executed = {}
        for record in execution_history:
            agent_name = record.get("agent_name", "unknown")
            if agent_name not in agents_executed:
                agents_executed[agent_name] = {
                    "total_attempts": 0,
                    "successful": 0,
                    "failed": 0
                }
            agents_executed[agent_name]["total_attempts"] += 1
            if record.get("success"):
                agents_executed[agent_name]["successful"] += 1
            else:
                agents_executed[agent_name]["failed"] += 1
        
        exec_summary = {
            "total_steps": summary.get("total_steps", len(execution_history)),
            "successful_steps": summary.get("successful_steps", 0),
            "failed_steps": summary.get("failed_steps", 0),
            "steps_requiring_retry": summary.get("steps_requiring_retry", 0),
            "needs_human_review": summary.get("needs_human_review", False),
            "agents_executed": agents_executed,
            "processing_start": state.get("processing_start"),
            "processing_end": state.get("processing_end"),
        }
        for key in (
            "total_retries",
            "retries_by_agent",
            "retry_trajectory",
            "agent_handoff",
            "overall_confidence",
            "average_confidence",
        ):
            if key in summary:
                exec_summary[key] = summary[key]
        return exec_summary
    
    def _generate_quality_metrics(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Generate quality metrics summary."""
        confidence_scores = state.get("confidence_scores", {})
        metadata_json = state.get("artifacts", {}).get("metadata_json")
        
        # Parse metadata_json if available
        metadata_data = None
        if metadata_json:
            try:
                metadata_data = json.loads(metadata_json)
            except (json.JSONDecodeError, TypeError):
                pass
        
        # Aggregate confidence is stored nested under "_aggregate" by the
        # finalize node; fall back to top-level keys for backward compatibility.
        aggregate = confidence_scores.get("_aggregate", {}) or {}
        quality = {
            "overall_confidence": aggregate.get("overall", confidence_scores.get("overall", 0.0)),
            "critic_confidence": aggregate.get("critic", confidence_scores.get("critic", 0.0)),
            "structural_confidence": aggregate.get("structural", confidence_scores.get("structural", 0.0)),
            "validation_confidence": aggregate.get("validation", confidence_scores.get("validation", 0.0)),
            "needs_review": state.get("needs_human_review", False)
        }
        
        if metadata_data:
            quality.update({
                "metadata_overall_confidence": metadata_data.get("overall_confidence", 0.0),
                "packages_used": metadata_data.get("packages_used", []),
                "total_fields": metadata_data.get("statistics", {}).get("total_fields", 0),
                "confirmed_fields": metadata_data.get("statistics", {}).get("confirmed_fields", 0),
                "provisional_fields": metadata_data.get("statistics", {}).get("provisional_fields", 0),
            })
            source_grounding = metadata_data.get("statistics", {}).get("source_grounding_summary", {})
            if source_grounding:
                quality["source_grounding"] = {
                    "source_grounded_fields": source_grounding.get("source_grounded_fields", 0),
                    "ungrounded_high_confidence_fields": source_grounding.get(
                        "ungrounded_high_confidence_fields", 0
                    ),
                    "table_backed_fields": source_grounding.get("table_backed_fields", 0),
                }

        return quality

    def _generate_retrieval_metrics(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Summarize hybrid retrieval telemetry and semantic index status."""
        semantic_index = state.get("semantic_index") or {}
        retrieval_telemetry = state.get("retrieval_telemetry") or {}
        field_stats = []
        hybrid_fields = 0
        legacy_only_fields = 0
        semantic_only_fields = 0
        rerank_skipped = 0
        rerank_applied = 0
        retrieval_mode_counts: Counter[str] = Counter()
        prompt_mode_counts: Counter[str] = Counter()
        auto_repair_scores: List[float] = []
        auto_repair_reason_counts: Counter[str] = Counter()

        for field_name, stats in retrieval_telemetry.items():
            if not isinstance(stats, dict):
                continue
            lexical_hits = int(stats.get("lexical_hit_count") or 0)
            semantic_hits = int(stats.get("semantic_hit_count") or 0)
            hybrid_hits = int(stats.get("hybrid_hit_count") or 0)
            rerank_status = stats.get("rerank_status")
            if rerank_status == "skipped":
                rerank_skipped += 1
            elif rerank_status == "applied":
                rerank_applied += 1
            if hybrid_hits > lexical_hits:
                hybrid_fields += 1
            if lexical_hits > 0 and semantic_hits == 0:
                legacy_only_fields += 1
            if semantic_hits > 0 and lexical_hits == 0:
                semantic_only_fields += 1

            retrieval_mode = stats.get("retrieval_mode")
            if retrieval_mode:
                retrieval_mode_counts[str(retrieval_mode)] += 1
            prompt_mode = stats.get("prompt_mode")
            if prompt_mode:
                prompt_mode_counts[str(prompt_mode)] += 1
            try:
                auto_repair_scores.append(float(stats.get("auto_repair_score") or 0.0))
            except (TypeError, ValueError):
                pass
            reasons = stats.get("auto_repair_reasons") or []
            if isinstance(reasons, list):
                auto_repair_reason_counts.update(str(reason) for reason in reasons)

            field_stats.append(
                {
                    "field": field_name,
                    "lexical_hit_count": lexical_hits,
                    "semantic_hit_count": semantic_hits,
                    "hybrid_hit_count": hybrid_hits,
                    "rerank_status": rerank_status,
                    "shadow_mode": stats.get("shadow_mode"),
                    "retrieval_mode": stats.get("retrieval_mode"),
                    "prompt_mode": stats.get("prompt_mode"),
                    "auto_repair_score": stats.get("auto_repair_score"),
                    "auto_repair_reasons": stats.get("auto_repair_reasons", []),
                    "hybrid_candidate_ids": stats.get("hybrid_candidate_ids", []),
                }
            )

        semantic_status = semantic_index.get("status", "unknown")
        qdrant_fallback_used = not bool(semantic_index.get("available", False))
        rerank_total = rerank_skipped + rerank_applied
        rerank_timeout_rate = (
            rerank_skipped / rerank_total if rerank_total > 0 else 0.0
        )
        auto_repair_score_summary: Dict[str, Any] = {
            "count": len(auto_repair_scores),
            "min": 0.0,
            "max": 0.0,
            "avg": 0.0,
        }
        if auto_repair_scores:
            auto_repair_score_summary.update(
                {
                    "min": round(min(auto_repair_scores), 4),
                    "max": round(max(auto_repair_scores), 4),
                    "avg": round(
                        sum(auto_repair_scores) / len(auto_repair_scores),
                        4,
                    ),
                }
            )

        return {
            "semantic_index_status": semantic_status,
            "semantic_index_available": semantic_index.get("available", False),
            "indexed_chunk_count": semantic_index.get("indexed_chunk_count", 0),
            "chunk_count": semantic_index.get("chunk_count", len(state.get("source_chunks") or [])),
            "section_count": semantic_index.get("section_count", len(state.get("source_sections") or [])),
            "evidence_items": int((state.get("evidence_store") or {}).get("record_count", 0)),
            "hybrid_fields": hybrid_fields,
            "legacy_only_fields": legacy_only_fields,
            "semantic_only_fields": semantic_only_fields,
            "rerank_status": "skipped" if rerank_skipped and not rerank_applied else "ok",
            "rerank_timeout_rate": round(rerank_timeout_rate, 4),
            "qdrant_fallback_used": qdrant_fallback_used,
            "fields_with_retrieval_telemetry": len(field_stats),
            "retrieval_mode_counts": dict(retrieval_mode_counts),
            "prompt_mode_counts": dict(prompt_mode_counts),
            "auto_repair_score_summary": auto_repair_score_summary,
            "auto_repair_reason_counts": dict(auto_repair_reason_counts),
            "field_retrieval_stats": field_stats,
            "evidence_store": state.get("evidence_store", {}),
        }
    
    def _analyze_fields(
        self,
        state: Dict[str, Any],
        metadata_json_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """Analyze field distribution and statistics."""
        metadata_json = state.get("artifacts", {}).get("metadata_json")
        metadata_data = None
        
        # Try to load from state first
        if metadata_json:
            try:
                metadata_data = json.loads(metadata_json)
            except (json.JSONDecodeError, TypeError):
                pass
        
        # Fallback to file path
        if not metadata_data and metadata_json_path:
            try:
                with open(metadata_json_path, 'r', encoding='utf-8') as f:
                    metadata_data = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                pass
        
        if not metadata_data:
            return {
                "error": "Metadata JSON not available",
                "fields_by_isa": {},
                "total_fields": 0
            }
        
        isa_structure = metadata_data.get("isa_structure", {})
        fields_by_isa = {}
        
        for sheet_name, sheet_data in isa_structure.items():
            fields = sheet_data.get("fields", [])
            confirmed = sum(1 for f in fields if f.get("status") == "confirmed")
            provisional = sum(1 for f in fields if f.get("status") == "provisional")
            
            fields_by_isa[sheet_name] = {
                "total": len(fields),
                "confirmed": confirmed,
                "provisional": provisional,
            }
        
        return {
            "fields_by_isa": fields_by_isa,
            "total_fields": metadata_data.get("statistics", {}).get("total_fields", 0),
            "packages_used": metadata_data.get("packages_used", [])
        }
    
    def _check_duplicates(
        self,
        state: Dict[str, Any],
        metadata_json_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """Check for duplicate field names in each ISA sheet."""
        metadata_json = state.get("artifacts", {}).get("metadata_json")
        metadata_data = None
        
        # Try to load from state first
        if metadata_json:
            try:
                metadata_data = json.loads(metadata_json)
            except (json.JSONDecodeError, TypeError):
                pass
        
        # Fallback to file path
        if not metadata_data and metadata_json_path:
            try:
                with open(metadata_json_path, 'r', encoding='utf-8') as f:
                    metadata_data = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                pass
        
        if not metadata_data:
            return {
                "error": "Metadata JSON not available",
                "duplicates_found": False,
                "duplicate_details": {}
            }
        
        isa_structure = metadata_data.get("isa_structure", {})
        duplicate_details = {}
        total_duplicates = 0
        
        for sheet_name, sheet_data in isa_structure.items():
            fields = sheet_data.get("fields", [])
            field_names = [f.get("field_name", "").lower().strip() for f in fields]
            
            seen = {}
            duplicates = []
            for i, name in enumerate(field_names):
                if name in seen:
                    duplicates.append({
                        "field_name": fields[i].get("field_name", ""),
                        "first_occurrence": seen[name],
                        "duplicate_occurrence": i
                    })
                    total_duplicates += 1
                else:
                    seen[name] = i
            
            duplicate_details[sheet_name] = {
                "total_fields": len(fields),
                "duplicates_found": len(duplicates),
                "duplicate_list": duplicates
            }
        
        return {
            "duplicates_found": total_duplicates > 0,
            "total_duplicates": total_duplicates,
            "duplicate_details": duplicate_details
        }
    
    def _analyze_retries(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze retry patterns."""
        execution_history = state.get("execution_history", [])
        context = state.get("context", {})
        
        # Try to get global retry info from state (if stored)
        global_retries_used = state.get("global_retries_used", 0)
        max_global_retries = state.get("max_global_retries", 10)
        
        retry_analysis = {
            "global_retries_used": global_retries_used,
            "max_global_retries": max_global_retries,
            "agents_with_retries": [],
            "retry_details": {}
        }
        
        # Group by agent
        agent_retries = {}
        for record in execution_history:
            agent_name = record.get("agent_name", "unknown")
            attempt = record.get("attempt", 1)
            
            if agent_name not in agent_retries:
                agent_retries[agent_name] = {
                    "total_attempts": 0,
                    "max_attempt": 0,
                    "retries": 0
                }
            
            agent_retries[agent_name]["total_attempts"] += 1
            agent_retries[agent_name]["max_attempt"] = max(
                agent_retries[agent_name]["max_attempt"],
                attempt
            )
            if attempt > 1:
                agent_retries[agent_name]["retries"] += 1
        
        for agent_name, stats in agent_retries.items():
            if stats["retries"] > 0:
                retry_analysis["agents_with_retries"].append(agent_name)
                retry_analysis["retry_details"][agent_name] = stats
        
        return retry_analysis
    
    def _generate_timeline(self, state: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate execution timeline."""
        execution_history = state.get("execution_history", [])
        timeline = []
        
        processing_start = state.get("processing_start")
        if processing_start:
            try:
                start_time = datetime.fromisoformat(processing_start.replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                start_time = None
        else:
            start_time = None
        
        for record in execution_history:
            agent_name = record.get("agent_name", "unknown")
            attempt = record.get("attempt", 1)
            start = record.get("start_time")
            end = record.get("end_time")
            success = record.get("success", False)
            
            # Calculate duration if both times available
            duration = None
            if start and end:
                try:
                    start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
                    end_dt = datetime.fromisoformat(end.replace('Z', '+00:00'))
                    duration = (end_dt - start_dt).total_seconds()
                except (ValueError, AttributeError):
                    pass
            
            timeline.append({
                "agent": agent_name,
                "attempt": attempt,
                "start_time": start,
                "end_time": end,
                "duration_seconds": duration,
                "success": success
            })
        
        return timeline
    
    def save_report(
        self,
        report: Dict[str, Any],
        filename: str = "workflow_report.json"
    ) -> Optional[Path]:
        """
        Save report to file.
        
        Args:
            report: Report dictionary
            filename: Output filename
            
        Returns:
            Path to saved file, or None if output_dir not set
        """
        if not self.output_dir:
            return None
        
        self.output_dir.mkdir(parents=True, exist_ok=True)
        report_path = self.output_dir / filename
        
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        
        return report_path
    
    def generate_text_report(
        self,
        report: Dict[str, Any]
    ) -> str:
        """
        Generate human-readable text report.
        
        Args:
            report: Report dictionary
            
        Returns:
            Formatted text report
        """
        lines = []
        lines.append("=" * 80)
        lines.append("WORKFLOW EXECUTION REPORT")
        lines.append("=" * 80)
        lines.append(f"Generated at: {report.get('generated_at', 'unknown')}")
        lines.append(f"Workflow Status: {report.get('workflow_status', 'unknown').upper()}")
        lines.append("")
        
        # Execution Summary
        exec_summary = report.get("execution_summary", {})
        lines.append("EXECUTION SUMMARY")
        lines.append("-" * 80)
        lines.append(f"Total Steps: {exec_summary.get('total_steps', 0)}")
        lines.append(f"Successful Steps: {exec_summary.get('successful_steps', 0)}")
        lines.append(f"Failed Steps: {exec_summary.get('failed_steps', 0)}")
        lines.append(f"Steps Requiring Retry: {exec_summary.get('steps_requiring_retry', 0)}")
        lines.append(f"Needs Human Review: {exec_summary.get('needs_human_review', False)}")
        lines.append("")
        
        # Quality Metrics
        quality = report.get("quality_metrics", {})
        lines.append("QUALITY METRICS")
        lines.append("-" * 80)
        lines.append(f"Overall Confidence: {quality.get('overall_confidence', 0.0):.2%}")
        if quality.get("metadata_overall_confidence"):
            lines.append(f"Metadata Overall Confidence: {quality.get('metadata_overall_confidence', 0.0):.2%}")
        lines.append(f"Total Fields: {quality.get('total_fields', 0)}")
        lines.append(f"Confirmed Fields: {quality.get('confirmed_fields', 0)}")
        lines.append(f"Provisional Fields: {quality.get('provisional_fields', 0)}")
        lines.append(f"Packages Used: {', '.join(quality.get('packages_used', []))}")
        lines.append("")

        # Source grounding
        sg = quality.get("source_grounding")
        if sg:
            lines.append("SOURCE GROUNDING")
            lines.append("-" * 80)
            lines.append(f"Source-grounded fields:          {sg.get('source_grounded_fields', 0)}")
            lines.append(f"Table-backed fields:             {sg.get('table_backed_fields', 0)}")
            ungrounded = sg.get('ungrounded_high_confidence_fields', 0)
            flag = "⚠️ " if ungrounded > 0 else "✅ "
            lines.append(f"Ungrounded high-confidence fields:{flag}{ungrounded}")
            lines.append("")

        retrieval = report.get("retrieval_metrics") or {}
        if retrieval:
            lines.append("RETRIEVAL AND AUTO PROMPTING")
            lines.append("-" * 80)
            lines.append(
                f"Semantic index status:           {retrieval.get('semantic_index_status', 'unknown')}"
            )
            lines.append(
                f"Telemetry fields:                {retrieval.get('fields_with_retrieval_telemetry', 0)}"
            )
            retrieval_modes = retrieval.get("retrieval_mode_counts") or {}
            if retrieval_modes:
                mode_text = ", ".join(
                    f"{mode}={count}" for mode, count in sorted(retrieval_modes.items())
                )
                lines.append(f"Retrieval modes:                 {mode_text}")
            prompt_modes = retrieval.get("prompt_mode_counts") or {}
            if prompt_modes:
                prompt_text = ", ".join(
                    f"{mode}={count}" for mode, count in sorted(prompt_modes.items())
                )
                lines.append(f"Prompt modes:                    {prompt_text}")
            score_summary = retrieval.get("auto_repair_score_summary") or {}
            if score_summary.get("count"):
                lines.append(
                    "Auto repair score avg/max:       "
                    f"{score_summary.get('avg', 0.0):.2f}/"
                    f"{score_summary.get('max', 0.0):.2f}"
                )
            reason_counts = retrieval.get("auto_repair_reason_counts") or {}
            if reason_counts:
                reason_text = ", ".join(
                    f"{reason}={count}" for reason, count in sorted(reason_counts.items())
                )
                lines.append(f"Auto repair reasons:             {reason_text}")
            lines.append("")

        auto_repair = report.get("auto_repair_trace") or {}
        auto_summary = auto_repair.get("summary") or {}
        if auto_summary:
            lines.append("AUTO REPAIR TRACE")
            lines.append("-" * 80)
            lines.append(f"Mode:                            {auto_repair.get('mode', 'unknown')}")
            lines.append(f"Apply patches:                   {auto_summary.get('apply_patches', False)}")
            lines.append(f"Candidate fields:                {auto_summary.get('candidate_count', 0)}")
            lines.append(f"Skipped gap fields:              {auto_summary.get('skipped_gap_count', 0)}")
            lines.append(f"Accepted patches:                {auto_summary.get('accepted_patch_count', 0)}")
            lines.append(f"Rejected patches:                {auto_summary.get('rejected_patch_count', 0)}")
            lines.append(
                "Classifier shadow predictions:   "
                f"{auto_summary.get('classifier_shadow_prediction_count', 0)}"
            )
            lines.append(f"Metadata mutated:                {auto_summary.get('metadata_mutated', False)}")
            lines.append("")
        # Field Analysis
        field_analysis = report.get("field_analysis", {})
        if "error" not in field_analysis:
            lines.append("FIELD DISTRIBUTION")
            lines.append("-" * 80)
            fields_by_isa = field_analysis.get("fields_by_isa", {})
            for sheet_name, stats in fields_by_isa.items():
                lines.append(f"{sheet_name.upper()}:")
                lines.append(f"  Total: {stats.get('total', 0)} fields")
                lines.append(f"  Confirmed: {stats.get('confirmed', 0)}, Provisional: {stats.get('provisional', 0)}")
            lines.append("")
        
        # Duplicate Check
        dup_check = report.get("duplicate_check", {})
        lines.append("DUPLICATE FIELD CHECK")
        lines.append("-" * 80)
        if dup_check.get("duplicates_found"):
            lines.append(f"❌ Found {dup_check.get('total_duplicates', 0)} duplicate(s)")
            dup_details = dup_check.get("duplicate_details", {})
            for sheet_name, details in dup_details.items():
                if details.get("duplicates_found", 0) > 0:
                    lines.append(f"  {sheet_name}: {details.get('duplicates_found', 0)} duplicate(s)")
        else:
            lines.append("✅ No duplicates found")
        lines.append("")
        
        # Retry Analysis
        retry_analysis = report.get("retry_analysis", {})
        lines.append("RETRY ANALYSIS")
        lines.append("-" * 80)
        lines.append(f"Global Retries Used: {retry_analysis.get('global_retries_used', 0)}/{retry_analysis.get('max_global_retries', 10)}")
        agents_with_retries = retry_analysis.get("agents_with_retries", [])
        if agents_with_retries:
            lines.append(f"Agents with Retries: {', '.join(agents_with_retries)}")
            retry_details = retry_analysis.get("retry_details", {})
            for agent, details in retry_details.items():
                lines.append(f"  {agent}: {details.get('retries', 0)} retry(ies), max attempt {details.get('max_attempt', 1)}")
        else:
            lines.append("No retries required")
        lines.append("")
        
        # Timeline
        timeline = report.get("timeline", [])
        if timeline:
            lines.append("EXECUTION TIMELINE")
            lines.append("-" * 80)
            for entry in timeline:
                agent = entry.get("agent", "unknown")
                attempt = entry.get("attempt", 1)
                duration = entry.get("duration_seconds")
                success = "✅" if entry.get("success") else "❌"
                
                line = f"{success} {agent} (attempt {attempt})"
                if duration:
                    line += f" - {duration:.1f}s"
                lines.append(line)
        lines.append("")

        performance = report.get("performance", {})
        if performance:
            workflow = performance.get("workflow", {})
            usage = performance.get("llm_usage", {})
            cost = performance.get("cost", {})
            gates = performance.get("gates", {})
            lines.append("PERFORMANCE AND COST")
            lines.append("-" * 80)
            lines.append(
                f"Workflow wall time:              {workflow.get('wall_time_seconds')} s"
            )
            lines.append(
                f"LLM calls with usage:            {usage.get('calls_with_token_usage', 0)}/{usage.get('calls', 0)}"
            )
            lines.append(
                f"Observed tokens (in/out/total):  {usage.get('input_tokens', 0)}/"
                f"{usage.get('output_tokens', 0)}/{usage.get('total_tokens', 0)}"
            )
            lines.append(
                f"Observed LLM latency:            {usage.get('latency_seconds', 0)} s"
            )
            lines.append(
                f"Estimated cost:                  {cost.get('estimated_total_cost')} USD "
                f"({cost.get('estimate_status', 'unknown')})"
            )
            lines.append(
                f"Performance gate:                {gates.get('overall_status', 'unknown')}"
            )
            for check in gates.get("checks", []):
                lines.append(
                    f"  {check.get('name')}: {check.get('status')} "
                    f"({check.get('value')} / {check.get('limit')} {check.get('unit')})"
                )
            for phase, phase_checks in gates.get("per_phase", {}).items():
                summary = ", ".join(
                    f"{check.get('name')}={check.get('status')}"
                    for check in phase_checks
                )
                lines.append(f"  phase {phase}: {summary}")
            lines.append("")
        
        lines.append("=" * 80)
        
        return "\n".join(lines)
    
    def save_text_report(
        self,
        report: Dict[str, Any],
        filename: str = "workflow_report.txt"
    ) -> Optional[Path]:
        """
        Save text report to file.
        
        Args:
            report: Report dictionary
            filename: Output filename
            
        Returns:
            Path to saved file, or None if output_dir not set
        """
        if not self.output_dir:
            return None
        
        text_report = self.generate_text_report(report)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        report_path = self.output_dir / filename
        
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(text_report)
        
        return report_path
