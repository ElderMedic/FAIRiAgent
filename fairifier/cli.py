"""Command-line interface for FAIRifier."""

import asyncio
import json
import sys
from pathlib import Path
from typing import Optional
from datetime import datetime

import click

from .graph.workflow import FAIRifierWorkflow
from .config import config
from .utils.json_logger import get_logger

# Use JSON logger
json_logger = get_logger("fairifier.cli")


@click.group()
def cli():
    """FAIRifier: Automated FAIR metadata generation."""
    pass


@cli.command()
@click.argument('document_path', type=click.Path(exists=True))
@click.option('--output-dir', '-o', type=click.Path(), help='Output directory for artifacts')
@click.option('--project-id', '-p', help='Project ID (auto-generated if not provided)')
@click.option('--json-log', is_flag=True, default=True, help='Use JSON line logging (default: True)')
def process(document_path: str, output_dir: Optional[str] = None, project_id: Optional[str] = None, json_log: bool = True):
    """Process a document and generate FAIR metadata."""
    # JSON logging is now default
    if not json_log:
        click.echo("Warning: Non-JSON logging is deprecated", err=True)
    
    # Set up output directory
    if output_dir:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
    else:
        output_path = config.output_path
    
    click.echo(f"Processing document: {document_path}")
    click.echo(f"Output directory: {output_path}")
    
    # Run workflow
    asyncio.run(_run_workflow(document_path, output_path, project_id))


async def _run_workflow(document_path: str, output_path: Path, project_id: Optional[str] = None):
    """Run the FAIRifier workflow."""
    start_time = datetime.now()
    
    if not project_id:
        project_id = f"fairifier_{start_time.strftime('%Y%m%d_%H%M%S')}"
    
    try:
        workflow = FAIRifierWorkflow()
        
        json_logger.log_processing_start(document_path, project_id)
        
        # Run the workflow
        result = await workflow.run(document_path, project_id)
        
        # Extract results
        status = result.get("status", "unknown")
        confidence_scores = result.get("confidence_scores", {})
        needs_review = result.get("needs_human_review", False)
        errors = result.get("errors", [])
        artifacts = result.get("artifacts", {})
        
        # Calculate duration
        duration = (datetime.now() - start_time).total_seconds()
        json_logger.log_processing_end(project_id, status, duration)
        
        # Log confidence scores
        for component, score in confidence_scores.items():
            json_logger.log_confidence_score(component, score)
        
        # Save artifacts (JSON only)
        if artifacts:
            json_logger.info("saving_artifacts", output_path=str(output_path), artifact_count=len(artifacts))
            
            for artifact_name, content in artifacts.items():
                if content:
                    # Determine file extension
                    extensions = {
                        "metadata_json": ".json",
                        "validation_report": ".txt",
                        "processing_log": ".jsonl"
                    }
                    
                    ext = extensions.get(artifact_name, ".json")
                    filename = f"{artifact_name}{ext}"
                    filepath = output_path / filename
                    
                    with open(filepath, 'w', encoding='utf-8') as f:
                        f.write(content)
                    
                    json_logger.info("artifact_saved", filename=filename, size_bytes=len(content))
        
        # Save processing log
        log_file = output_path / "processing_log.jsonl"
        with open(log_file, 'w', encoding='utf-8') as f:
            for log_entry in json_logger.get_logs():
                f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
        
        # Log completion
        json_logger.info(
            "processing_summary",
            status=status,
            needs_review=needs_review,
            error_count=len(errors),
            overall_confidence=confidence_scores.get("overall", 0.0),
            duration_seconds=round(duration, 2)
        )
        
    except Exception as e:
        json_logger.error("workflow_failed", error=str(e), project_id=project_id)
        sys.exit(1)


@cli.command()
@click.argument('project_id')
def status(project_id: str):
    """Get status of a project."""
    click.echo(f"Getting status for project: {project_id}")
    # This would query the workflow checkpointer in a full implementation
    click.echo("Status checking not implemented in CLI mode")


@cli.command()
def config_info():
    """Show current configuration."""
    click.echo("FAIRifier Configuration:")
    click.echo(f"  Project root: {config.project_root}")
    click.echo(f"  Knowledge base: {config.kb_path}")
    click.echo(f"  Output path: {config.output_path}")
    click.echo(f"  LLM model: {config.llm_model}")
    click.echo(f"  LLM base URL: {config.llm_base_url}")
    click.echo(f"  Min confidence: {config.min_confidence_threshold}")
    click.echo(f"  Default MIxS package: {config.default_mixs_package}")


@cli.command()
@click.argument('input_file', type=click.Path(exists=True))
def validate_document(input_file: str):
    """Validate a document can be processed."""
    file_path = Path(input_file)
    
    click.echo(f"Validating document: {file_path}")
    
    # Check file size
    file_size = file_path.stat().st_size
    max_size = config.max_document_size_mb * 1024 * 1024
    
    if file_size > max_size:
        click.echo(f"❌ File too large: {file_size / (1024*1024):.1f}MB (max: {config.max_document_size_mb}MB)")
        return
    
    # Check file type
    if file_path.suffix.lower() not in ['.pdf', '.txt', '.md']:
        click.echo(f"⚠️  File type {file_path.suffix} may not be fully supported")
    
    click.echo(f"✓ File size: {file_size / (1024*1024):.1f}MB")
    click.echo(f"✓ File type: {file_path.suffix}")
    click.echo("Document validation passed!")


if __name__ == "__main__":
    cli()
