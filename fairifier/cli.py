"""Command-line interface for FAIRifier."""

import asyncio
import json
import sys
import logging
import os
from pathlib import Path
from typing import Optional
from datetime import datetime

import click

from .graph.langgraph_app import FAIRifierLangGraphApp
from .config import config
from .utils.json_logger import get_logger
from .utils.llm_helper import get_llm_helper, save_llm_responses

# Enable LangSmith tracing by default
os.environ["LANGCHAIN_TRACING_V2"] = "true"
os.environ["LANGCHAIN_PROJECT"] = os.getenv("LANGCHAIN_PROJECT", "fairifier")

# Use JSON logger
json_logger = get_logger("fairifier.cli")

# Also set up console logging for visibility
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_formatter = logging.Formatter(
    '%(asctime)s | %(name)s | %(message)s',
    datefmt='%H:%M:%S'
)
console_handler.setFormatter(console_formatter)

# Add to root logger
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
if not root_logger.handlers:
    root_logger.addHandler(console_handler)


@click.group()
def cli():
    """FAIRifier: Automated FAIR metadata generation."""
    pass


@cli.command()
@click.argument('document_path', type=click.Path(exists=True))
@click.option('--output-dir', '-o', type=click.Path(),
              help='Output directory for artifacts')
@click.option('--project-id', '-p',
              help='Project ID (auto-generated if not provided)')
@click.option('--env-file', '-e', type=click.Path(exists=True),
              help='Path to .env file with configuration (optional)')
@click.option('--json-log', is_flag=True, default=True,
              help='Use JSON line logging (default: True)')
@click.option('--verbose', '-v', is_flag=True,
              help='Show detailed processing steps')
def process(
    document_path: str,
    output_dir: Optional[str] = None,
    project_id: Optional[str] = None,
    env_file: Optional[str] = None,
    json_log: bool = True,
    verbose: bool = False
):
    """Process a document and generate FAIR metadata."""
    # Load custom .env file if provided (before importing config)
    if env_file:
        from .config import load_env_file, apply_env_overrides
        import fairifier.config as config_module
        env_path = Path(env_file)
        if load_env_file(env_path, verbose=verbose):
            click.echo(f"📋 Using configuration from: {env_path}")
            # Reload config after loading env file
            # This ensures each run uses independent configuration
            apply_env_overrides(config_module.config)
        else:
            click.echo(f"⚠️  Could not load .env file: {env_path}", err=True)
            sys.exit(1)
    
    # Import config after potentially loading custom env file
    from .config import config
    
    # JSON logging is now default
    if not json_log:
        click.echo("Warning: Non-JSON logging is deprecated", err=True)
    
    # Enable verbose logging if requested
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        click.echo("🔍 Verbose mode enabled\n")
    
    # Set up output directory with timestamp
    if output_dir:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
    else:
        # Create timestamped output directory under output folder
        # Include env file name in output dir if using custom env file
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        base_output_dir = config.project_root / "output"
        base_output_dir.mkdir(parents=True, exist_ok=True)
        
        if env_file:
            env_name = Path(env_file).stem  # Get filename without extension
            output_path = base_output_dir / f"{env_name}_{timestamp}"
        else:
            output_path = base_output_dir / timestamp
        output_path.mkdir(parents=True, exist_ok=True)
    
    click.echo("=" * 70)
    click.echo("🚀 FAIRifier - Automated FAIR Metadata Generation")
    click.echo("=" * 70)
    click.echo(f"📄 Document: {document_path}")
    click.echo(f"📁 Output: {output_path}")
    click.echo(f"🤖 LLM: {config.llm_model} ({config.llm_provider})")
    click.echo(f"🌐 FAIR-DS API: {config.fair_ds_api_url or 'http://localhost:8083 (default)'}")
    
    # LangSmith status - use unique project name if custom env file
    langsmith_project = config.langsmith_project
    if env_file:
        env_name = Path(env_file).stem
        langsmith_project = f"{config.langsmith_project}-{env_name}"
        # Set unique LangSmith project for this run
        os.environ["LANGCHAIN_PROJECT"] = langsmith_project
    
    if config.enable_langsmith and config.langsmith_api_key:
        click.echo(f"📊 LangSmith: ✅ Enabled "
                   f"(Project: {langsmith_project})")
    elif config.enable_langsmith:
        click.echo("📊 LangSmith: ⚠️  Enabled but no API key "
                   "(set LANGSMITH_API_KEY)")
    else:
        click.echo("📊 LangSmith: ❌ Disabled")
    
    click.echo("=" * 70)
    click.echo()
    
    # Run workflow
    asyncio.run(_run_workflow(document_path, output_path, project_id, verbose, langsmith_project))


async def _run_workflow(
    document_path: str,
    output_path: Path,
    project_id: Optional[str] = None,
    verbose: bool = False,
    langsmith_project: Optional[str] = None
):
    """Run the FAIRifier workflow."""
    start_time = datetime.now()
    
    if not project_id:
        project_id = f"fairifier_{start_time.strftime('%Y%m%d_%H%M%S')}"
    
    # Set LangSmith project if provided (for isolation)
    if langsmith_project:
        os.environ["LANGCHAIN_PROJECT"] = langsmith_project
    
    # Set up log file redirection
    log_file = output_path / "full_output.log"
    log_handle = open(log_file, 'w', encoding='utf-8', buffering=1)  # Line buffered
    
    # Create a tee-like handler that writes to both console and file
    class TeeHandler(logging.Handler):
        def __init__(self, file_handle):
            super().__init__()
            self.file_handle = file_handle
        
        def emit(self, record):
            try:
                msg = self.format(record)
                self.file_handle.write(msg + '\n')
                self.file_handle.flush()
            except Exception:
                self.handleError(record)
    
    # Add file handler to root logger
    tee_handler = TeeHandler(log_handle)
    tee_handler.setFormatter(console_formatter)
    root_logger = logging.getLogger()
    root_logger.addHandler(tee_handler)
    
    try:
        workflow = FAIRifierLangGraphApp()
        
        json_logger.log_processing_start(document_path, project_id)
        click.echo(f"🔄 Starting processing (Project ID: {project_id})\n")
        
        # Run the workflow
        result = await workflow.run(document_path, project_id, output_dir=str(output_path))
        
        # Extract results
        status = result.get("status", "unknown")
        confidence_scores = result.get("confidence_scores", {})
        needs_review = result.get("needs_human_review", False)
        errors = result.get("errors", [])
        artifacts = result.get("artifacts", {})
        
        # Calculate duration
        duration = (datetime.now() - start_time).total_seconds()
        json_logger.log_processing_end(project_id, status, duration)
        
        click.echo("\n" + "=" * 70)
        click.echo("📊 Processing Results")
        click.echo("=" * 70)
        
        # Display confidence scores
        click.echo("\n🎯 Confidence Scores:")
        for component, score in confidence_scores.items():
            json_logger.log_confidence_score(component, score)
            emoji = "✅" if score >= 0.8 else "⚠️" if score >= 0.6 else "❌"
            click.echo(f"  {emoji} {component}: {score:.2%}")
        
        # Display status
        click.echo(f"\n📈 Status: {status.upper()}")
        click.echo(f"⏱️  Duration: {duration:.2f} seconds")
        
        # Check for critical output
        has_metadata_json = "metadata_json" in artifacts and artifacts["metadata_json"]
        if not has_metadata_json:
            click.echo("\n❌ CRITICAL: metadata_json.json was not generated!", err=True)
            click.echo("   The workflow did not complete successfully.", err=True)
        
        if needs_review:
            click.echo("⚠️  Human review recommended")
        
        if errors:
            click.echo(f"\n❌ Errors ({len(errors)}):")
            for error in errors[:5]:  # Show first 5 errors
                click.echo(f"  - {error}")
        
        # Save runtime configuration
        from fairifier.utils.config_saver import save_runtime_config
        config_file = save_runtime_config(document_path, project_id, output_path)
        click.echo(f"  ✓ runtime_config.json")
        
        # Save artifacts
        click.echo("\n💾 Saving artifacts...")
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

                    size_kb = len(content) / 1024
                    click.echo(f"  ✓ {filename} ({size_kb:.1f} KB)")
                    json_logger.info("artifact_saved", filename=filename,
                                     size_bytes=len(content))
        
        # Save processing log
        log_file = output_path / "processing_log.jsonl"
        with open(log_file, 'w', encoding='utf-8') as f:
            for log_entry in json_logger.get_logs():
                f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
        click.echo(f"  ✓ processing_log.jsonl")

        # Save LLM responses for inspection
        try:
            llm_helper = get_llm_helper()
            if llm_helper.llm_responses:
                save_llm_responses(output_path, llm_helper)
                click.echo(f"  ✓ llm_responses.json "
                           f"({len(llm_helper.llm_responses)} interactions)")
                click.echo(f"\n💡 Tip: Check llm_responses.json to see "
                           f"LLM's thinking process")
        except Exception as e:
            click.echo(f"  ⚠️  Could not save LLM responses: {e}", err=True)
        
        # Log completion
        json_logger.info(
            "processing_summary",
            status=status,
            needs_review=needs_review,
            error_count=len(errors),
            overall_confidence=confidence_scores.get("overall", 0.0),
            duration_seconds=round(duration, 2)
        )
        
        click.echo("\n" + "=" * 70)
        
        # Check if workflow actually succeeded
        if status == "failed":
            click.echo("❌ Processing FAILED!")
            click.echo(f"📁 Partial output saved to: {output_path}")
            click.echo(f"📝 Full log saved to: {log_file}")
            click.echo("=" * 70)
            sys.exit(1)
        else:
            click.echo("✨ Processing complete!")
            click.echo(f"📁 Output saved to: {output_path}")
            click.echo(f"📝 Full log saved to: {log_file}")
            click.echo("=" * 70)
        
    except Exception as e:
        click.echo(f"\n❌ Error: {str(e)}", err=True)
        json_logger.error("workflow_failed", error=str(e), project_id=project_id)
        sys.exit(1)
    finally:
        # Clean up log handler and close file
        root_logger.removeHandler(tee_handler)
        log_handle.close()


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
        click.echo(f"❌ File too large: "
                   f"{file_size / (1024*1024):.1f}MB "
                   f"(max: {config.max_document_size_mb}MB)")
        return
    
    # Check file type
    if file_path.suffix.lower() not in ['.pdf', '.txt', '.md']:
        click.echo(f"⚠️  File type {file_path.suffix} "
                   f"may not be fully supported")
    
    click.echo(f"✓ File size: {file_size / (1024*1024):.1f}MB")
    click.echo(f"✓ File type: {file_path.suffix}")
    click.echo("Document validation passed!")


@cli.command()
@click.option('--verbose', '-v', is_flag=True, help='Show detailed diagnostic information')
def check_mineru(verbose: bool):
    """Check MinerU service availability and configuration.
    
    This command verifies that MinerU CLI and HTTP server are properly
    configured and available for document conversion.
    """
    import subprocess
    import socket
    import requests
    from urllib.parse import urlparse
    
    click.echo("=" * 60)
    click.echo("MinerU Service Check")
    click.echo("=" * 60)
    
    # Show configuration
    click.echo("\n📋 Configuration:")
    click.echo(f"   MINERU_ENABLED: {config.mineru_enabled}")
    click.echo(f"   MINERU_CLI_PATH: {config.mineru_cli_path}")
    click.echo(f"   MINERU_SERVER_URL: {config.mineru_server_url}")
    click.echo(f"   MINERU_BACKEND: {config.mineru_backend}")
    click.echo(f"   MINERU_TIMEOUT_SECONDS: {config.mineru_timeout_seconds}")
    
    if not config.mineru_enabled:
        click.echo("\n⚠️  Warning: MinerU is disabled in configuration")
        click.echo("   Set MINERU_ENABLED=true in .env to enable")
        return
    
    results = []
    
    # Test 1: CLI availability
    click.echo("\n🔍 Test 1: MinerU CLI")
    cli_ok = False
    try:
        result = subprocess.run(
            [config.mineru_cli_path, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            version_info = result.stdout.strip()
            click.echo(f"   ✅ CLI available: {version_info}")
            cli_ok = True
        else:
            click.echo(f"   ❌ CLI returned error code: {result.returncode}")
    except FileNotFoundError:
        click.echo(f"   ❌ CLI not found: {config.mineru_cli_path}")
        click.echo("   Install MinerU: pip install mineru or conda install mineru")
    except Exception as e:
        click.echo(f"   ❌ Error checking CLI: {e}")
    results.append(("CLI", cli_ok))
    
    # Test 2: Server availability
    click.echo("\n🔍 Test 2: MinerU HTTP Server")
    server_ok = False
    if config.mineru_server_url:
        parsed = urlparse(config.mineru_server_url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 30000
        
        # Check port connectivity
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex((host, port))
            sock.close()
            
            if result == 0:
                click.echo(f"   ✅ Port {port} accessible")
                # Try health check
                try:
                    health_url = f"{config.mineru_server_url.rstrip('/')}/health"
                    response = requests.get(health_url, timeout=5)
                    if response.status_code == 200:
                        click.echo(f"   ✅ Health check passed")
                        server_ok = True
                    else:
                        click.echo(f"   ⚠️  Health check returned: {response.status_code}")
                        server_ok = True  # Server is running even if health endpoint is different
                except requests.exceptions.RequestException as e:
                    click.echo(f"   ⚠️  Health check failed: {e}")
                    server_ok = True  # Port is open, assume server is running
            else:
                click.echo(f"   ❌ Port {port} not accessible")
                click.echo(f"   Start server: {config.mineru_cli_path} server start")
        except Exception as e:
            click.echo(f"   ❌ Connection test failed: {e}")
    else:
        click.echo("   ❌ Server URL not configured")
    results.append(("Server", server_ok))
    
    # Test 3: Client initialization
    click.echo("\n🔍 Test 3: MinerUClient")
    client_ok = False
    try:
        from .services.mineru_client import MinerUClient
        
        client = MinerUClient(
            cli_path=config.mineru_cli_path,
            server_url=config.mineru_server_url,
            backend=config.mineru_backend,
            timeout_seconds=config.mineru_timeout_seconds,
        )
        
        if client.is_available():
            click.echo("   ✅ MinerUClient initialized and available")
            client_ok = True
        else:
            click.echo("   ❌ MinerUClient not available")
    except Exception as e:
        click.echo(f"   ❌ Client initialization failed: {e}")
    results.append(("Client", client_ok))
    
    # Summary
    click.echo("\n" + "=" * 60)
    click.echo("Summary")
    click.echo("=" * 60)
    
    all_passed = all(result for _, result in results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        click.echo(f"   {name}: {status}")
    
    if all_passed:
        click.echo("\n🎉 All checks passed! MinerU is ready to use.")
        if verbose:
            click.echo("\n💡 Tip: Run 'pytest tests/test_mineru_client.py -v' for detailed tests")
    else:
        click.echo("\n⚠️  Some checks failed. MinerU may not be fully functional.")
        click.echo("\n💡 Troubleshooting:")
        if not results[0][1]:  # CLI failed
            click.echo("   - Install MinerU: pip install mineru")
        if not results[1][1]:  # Server failed
            click.echo(f"   - Start server: {config.mineru_cli_path} server start")
        click.echo("   - Check configuration in .env file")
        click.echo("   - Run with --verbose for more details")


if __name__ == "__main__":
    cli()
