"""Report generator for workflow execution summary."""

import json
from typing import Dict, Any, List, Optional
from datetime import datetime
from pathlib import Path


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
        metadata_json_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generate comprehensive workflow execution report.
        
        Args:
            state: FAIRifierState dictionary
            metadata_json_path: Path to metadata_json.json file (optional)
            
        Returns:
            Dictionary containing report data
        """
        report = {
            "generated_at": datetime.now().isoformat(),
            "workflow_status": state.get("status", "unknown"),
            "execution_summary": self._generate_execution_summary(state),
            "quality_metrics": self._generate_quality_metrics(state),
            "field_analysis": self._analyze_fields(state, metadata_json_path),
            "duplicate_check": self._check_duplicates(state, metadata_json_path),
            "retry_analysis": self._analyze_retries(state),
            "timeline": self._generate_timeline(state)
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
        
        return {
            "total_steps": summary.get("total_steps", len(execution_history)),
            "successful_steps": summary.get("successful_steps", 0),
            "failed_steps": summary.get("failed_steps", 0),
            "steps_requiring_retry": summary.get("steps_requiring_retry", 0),
            "needs_human_review": summary.get("needs_human_review", False),
            "agents_executed": agents_executed,
            "processing_start": state.get("processing_start"),
            "processing_end": state.get("processing_end")
        }
    
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
        
        quality = {
            "overall_confidence": confidence_scores.get("overall", 0.0),
            "critic_confidence": confidence_scores.get("critic", 0.0),
            "structural_confidence": confidence_scores.get("structural", 0.0),
            "validation_confidence": confidence_scores.get("validation", 0.0),
            "needs_review": state.get("needs_human_review", False)
        }
        
        if metadata_data:
            quality.update({
                "metadata_overall_confidence": metadata_data.get("overall_confidence", 0.0),
                "packages_used": metadata_data.get("packages_used", []),
                "total_fields": metadata_data.get("statistics", {}).get("total_fields", 0),
                "confirmed_fields": metadata_data.get("statistics", {}).get("confirmed_fields", 0),
                "provisional_fields": metadata_data.get("statistics", {}).get("provisional_fields", 0)
            })
        
        return quality
    
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
                "sample_fields": [f.get("field_name", "") for f in fields[:5]]
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
                sample = stats.get("sample_fields", [])
                if sample:
                    lines.append(f"  Sample fields: {', '.join(sample[:3])}")
                    if len(sample) > 3:
                        lines.append(f"  ... and {len(sample) - 3} more")
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
            for entry in timeline[:10]:  # Show first 10 entries
                agent = entry.get("agent", "unknown")
                attempt = entry.get("attempt", 1)
                duration = entry.get("duration_seconds")
                success = "✅" if entry.get("success") else "❌"
                
                line = f"{success} {agent} (attempt {attempt})"
                if duration:
                    line += f" - {duration:.1f}s"
                lines.append(line)
            
            if len(timeline) > 10:
                lines.append(f"... and {len(timeline) - 10} more entries")
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

