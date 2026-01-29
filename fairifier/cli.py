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
from .utils.llm_helper import get_llm_helper, save_llm_responses, check_ollama_model_available

# LangSmith: config.apply_env_overrides() already set LANGCHAIN_TRACING_V2 and LANGCHAIN_PROJECT

# Use JSON logger
json_logger = get_logger("fairifier.cli")

# Registry path for tracking runs
RUNS_REGISTRY_PATH = Path(config.project_root) / "output" / ".runs.json"

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

# Suppress noisy third-party loggers (sqlite checkpoint, HTTP, LangSmith)
# They log every DB op / request at INFO and flood stdout + full_output.log
for _name in ("aiosqlite", "urllib3", "httpcore", "httpx", "langsmith", "langsmith.client"):
    logging.getLogger(_name).setLevel(logging.WARNING)


def _register_run(project_id: str, output_path: Path):
    """Register a run in the runs registry.
    
    Args:
        project_id: The project ID for this run
        output_path: The output directory path (absolute)
    """
    registry_path = RUNS_REGISTRY_PATH
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Load existing registry or create new
    if registry_path.exists():
        try:
            with open(registry_path, 'r', encoding='utf-8') as f:
                registry = json.load(f)
        except (json.JSONDecodeError, IOError):
            registry = {}
    else:
        registry = {}
    
    # Add/update entry (store relative path from output/ for portability)
    output_root = config.project_root / "output"
    try:
        rel_path = output_path.relative_to(output_root)
        registry[project_id] = str(rel_path)
    except ValueError:
        # output_path is not relative to output_root, use absolute
        registry[project_id] = str(output_path)
    
    # Save registry
    with open(registry_path, 'w', encoding='utf-8') as f:
        json.dump(registry, f, indent=2, ensure_ascii=False)


def _resolve_project_id(project_id: str) -> Optional[Path]:
    """Resolve a project_id to its output directory path.
    
    Uses registry first, then scans runtime_config.json files as fallback.
    
    Args:
        project_id: The project ID to resolve
        
    Returns:
        Path to the output directory, or None if not found
    """
    output_root = config.project_root / "output"
    
    # Try registry first
    registry_path = RUNS_REGISTRY_PATH
    if registry_path.exists():
        try:
            with open(registry_path, 'r', encoding='utf-8') as f:
                registry = json.load(f)
            
            if project_id in registry:
                run_dir_str = registry[project_id]
                # Try relative to output/ first
                if not run_dir_str.startswith('/'):
                    run_dir = output_root / run_dir_str
                else:
                    run_dir = Path(run_dir_str)
                
                if run_dir.exists():
                    return run_dir
        except (json.JSONDecodeError, IOError):
            pass
    
    # Fallback: scan output subdirectories for runtime_config.json
    if not output_root.exists():
        return None
    
    for subdir in output_root.iterdir():
        if not subdir.is_dir():
            continue
        
        runtime_config_file = subdir / "runtime_config.json"
        if runtime_config_file.exists():
            try:
                with open(runtime_config_file, 'r', encoding='utf-8') as f:
                    runtime_config = json.load(f)
                
                if runtime_config.get("runtime_info", {}).get("project_id") == project_id:
                    return subdir
            except (json.JSONDecodeError, IOError):
                continue
    
    return None


def _is_process_running(pid: int) -> bool:
    """Check if a process with given PID is running (Linux/Mac compatible).
    
    Args:
        pid: Process ID to check
        
    Returns:
        True if process is running, False otherwise
    """
    try:
        # Unix-like systems (Linux/Mac): sending signal 0 checks existence
        os.kill(pid, 0)
        return True
    except OSError:
        return False
    except Exception:
        return False


@click.group(
    context_settings={"help_option_names": ["-h", "--help"]},
    invoke_without_command=True,
)
@click.pass_context
def cli(ctx: click.Context):
    """FAIRiAgent CLI – FAIR metadata generation from research documents."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())
        return


@cli.command()
@click.argument("document_path", type=click.Path(exists=True))
@click.option(
    "--output-dir",
    "-o",
    type=click.Path(),
    help="Output directory for generated artifacts (default: output/<timestamp>).",
)
@click.option(
    "--project-id",
    "-p",
    help="Project ID for this run (default: auto-generated).",
)
@click.option(
    "--env-file",
    "-e",
    type=click.Path(exists=True),
    help="Path to .env file to use for this run (optional).",
)
@click.option(
    "--json-log",
    is_flag=True,
    default=True,
    help="Write JSONL processing log (default: True).",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Print detailed processing steps.",
)
def process(
    document_path: str,
    output_dir: Optional[str] = None,
    project_id: Optional[str] = None,
    env_file: Optional[str] = None,
    json_log: bool = True,
    verbose: bool = False
):
    """Process a document and generate FAIR-DS compatible metadata."""
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
    # Verify Ollama model exists before running (avoid silent fallback to default)
    if config.llm_provider.lower() == "ollama" and config.llm_base_url:
        model_ok, model_msg = check_ollama_model_available(config.llm_base_url, config.llm_model)
        if not model_ok:
            click.echo(f"❌ LLM model check failed: {model_msg}", err=True)
            if not os.getenv("FAIRIFIER_LLM_SKIP_MODEL_CHECK", "").strip().lower() in ("1", "true", "yes"):
                click.echo("   Set FAIRIFIER_LLM_SKIP_MODEL_CHECK=1 to skip this check.", err=True)
                sys.exit(1)
            click.echo("   ⚠️  Proceeding anyway (FAIRIFIER_LLM_SKIP_MODEL_CHECK is set).", err=True)
        else:
            if model_msg != config.llm_model:
                click.echo(f"   ✓ Model resolved: {config.llm_model} → {model_msg}")
    click.echo(f"🌐 FAIR-DS API: {config.fair_ds_api_url or 'http://localhost:8083 (default)'}")
    
    # LangSmith status - only set project name when tracing is enabled
    langsmith_project = None
    if config.enable_langsmith:
        if config.langsmith_use_fair_naming:
            from fairifier.utils.langsmith_helper import generate_fair_langsmith_project_name
            env_suffix = Path(env_file).stem if env_file else None
            langsmith_project = generate_fair_langsmith_project_name(
                environment="cli",
                model_provider=config.llm_provider,
                model_name=config.llm_model,
                project_id=None,
                custom_suffix=env_suffix
            )
        else:
            langsmith_project = config.langsmith_project
            if env_file:
                langsmith_project = f"{config.langsmith_project}-{Path(env_file).stem}"
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
    
    # Register this run in the runs registry
    _register_run(project_id, output_path)
    
    # Write .running file with PID for status tracking
    running_file = output_path / ".running"
    running_file.write_text(str(os.getpid()))
    
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
        # Clean up .running file
        running_file = output_path / ".running"
        if running_file.exists():
            running_file.unlink()
        
        # Clean up log handler and close file
        root_logger.removeHandler(tee_handler)
        log_handle.close()


@cli.command()
@click.option("--gradio", is_flag=True, help="Launch Gradio UI (default: Streamlit).")
@click.option(
    "--port",
    type=int,
    default=None,
    help="Port for Streamlit (default: 8501) or Gradio (default: 7860).",
)
def ui(gradio: bool, port: Optional[int]):
    """Launch the Web UI (Streamlit or Gradio)."""
    import subprocess

    if gradio:
        port = port or 7860
        click.echo("🚀 Starting Gradio Web UI...")
        click.echo(f"   Interface: http://localhost:{port}")
        click.echo("   API docs:  http://localhost:{port}/docs")
        subprocess.run(
            [sys.executable, "fairifier/apps/ui/gradio_app.py"],
            cwd=Path(__file__).resolve().parents[2],
        )
    else:
        port = port or 8501
        click.echo("🚀 Starting Streamlit Web UI...")
        click.echo(f"   Interface: http://localhost:{port}")
        subprocess.run(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                "fairifier/apps/ui/streamlit_app.py",
                "--server.port",
                str(port),
                "--server.address",
                "0.0.0.0",
                "--browser.gatherUsageStats",
                "false",
            ],
            cwd=Path(__file__).resolve().parents[2],
        )


@cli.command()
@click.argument("project_id")
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Show detailed checkpoint information (if available).",
)
def status(project_id: str, verbose: bool):
    """Show status for a run by project ID."""
    # Resolve project_id to output directory
    run_dir = _resolve_project_id(project_id)
    
    if not run_dir:
        click.echo(f"❌ No run found for project ID: {project_id}", err=True)
        click.echo("\nTip: Check available runs in output/ directory", err=True)
        sys.exit(1)
    
    section = "=" * 70
    click.echo(section)
    click.echo(f"Status for: {project_id}")
    click.echo(section)
    
    # Load runtime_config.json if available
    runtime_config_file = run_dir / "runtime_config.json"
    runtime_info = {}
    if runtime_config_file.exists():
        try:
            with open(runtime_config_file, 'r', encoding='utf-8') as f:
                runtime_config = json.load(f)
            runtime_info = runtime_config.get("runtime_info", {})
            
            click.echo(f"\n📄 Document:   {runtime_info.get('document_name', 'unknown')}")
            click.echo(f"   Path:       {runtime_info.get('document_path', 'unknown')}")
            click.echo(f"📁 Output:     {run_dir}")
            click.echo(f"🕐 Started:    {runtime_info.get('timestamp', 'unknown')}")
        except (json.JSONDecodeError, IOError) as e:
            click.echo(f"⚠️  Could not load runtime_config.json: {e}")
    else:
        click.echo(f"\n📁 Output:     {run_dir}")
        click.echo("⚠️  No runtime_config.json found (run may have been interrupted early)")
    
    # Check if running
    running_file = run_dir / ".running"
    is_running = False
    if running_file.exists():
        try:
            pid = int(running_file.read_text().strip())
            is_running = _is_process_running(pid)
            if is_running:
                click.echo(f"\n🔄 Status:     RUNNING (PID: {pid})")
            else:
                click.echo(f"\n⚠️  Status:     INTERRUPTED (process {pid} not found)")
                # Clean up stale .running file
                running_file.unlink()
        except (ValueError, IOError):
            pass
    
    # Load processing_log.jsonl if available
    processing_log_file = run_dir / "processing_log.jsonl"
    status_from_log = None
    duration_from_log = None
    confidence_from_log = {}
    
    if processing_log_file.exists() and not is_running:
        try:
            with open(processing_log_file, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        log_entry = json.loads(line.strip())
                        event = log_entry.get("event")
                        
                        if event == "processing_completed":
                            status_from_log = log_entry.get("status", "unknown")
                            duration_from_log = log_entry.get("duration_seconds")
                        
                        elif event == "confidence_score":
                            component = log_entry.get("component", "unknown")
                            score = log_entry.get("score", 0.0)
                            confidence_from_log[component] = score
                    except json.JSONDecodeError:
                        continue
            
            if status_from_log:
                status_emoji = "✅" if status_from_log == "completed" else "❌"
                click.echo(f"\n{status_emoji} Status:     {status_from_log.upper()}")
                if duration_from_log:
                    click.echo(f"⏱️  Duration:   {duration_from_log:.1f} seconds")
            
            if confidence_from_log:
                overall_conf = confidence_from_log.get("overall")
                if overall_conf is not None:
                    conf_emoji = "🟢" if overall_conf >= 0.8 else "🟡" if overall_conf >= 0.5 else "🔴"
                    click.echo(f"\n{conf_emoji} Confidence: {overall_conf:.2%}")
                    
                    if verbose:
                        click.echo("   Components:")
                        for component, score in sorted(confidence_from_log.items()):
                            if component != "overall":
                                click.echo(f"     - {component}: {score:.2%}")
        except IOError as e:
            click.echo(f"⚠️  Could not load processing_log.jsonl: {e}")
    
    # Infer status from files if not in log
    if not is_running and status_from_log is None:
        metadata_json_file = run_dir / "metadata_json.json"
        if metadata_json_file.exists():
            click.echo(f"\n✅ Status:     COMPLETED (inferred from metadata_json.json)")
        else:
            click.echo(f"\n❓ Status:     UNKNOWN (no processing_log.jsonl or metadata_json.json)")
    
    # Check for errors in logs (optional, simple implementation)
    error_count = 0
    if processing_log_file.exists():
        try:
            with open(processing_log_file, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        log_entry = json.loads(line.strip())
                        if log_entry.get("level") == "error":
                            error_count += 1
                    except json.JSONDecodeError:
                        continue
        except IOError:
            pass
    
    if error_count > 0:
        click.echo(f"\n⚠️  Errors:     {error_count} error(s) in processing_log.jsonl")
    
    # Optionally show checkpoint info if verbose and checkpointer is sqlite
    if verbose and config.checkpointer_backend == "sqlite" and not is_running:
        try:
            from .graph.langgraph_app import FAIRifierLangGraphApp
            
            app = FAIRifierLangGraphApp()
            if app.checkpointer:
                checkpoint_config = {"configurable": {"thread_id": project_id}}
                state_snapshot = app.workflow.get_state(checkpoint_config)
                
                if state_snapshot and state_snapshot.values:
                    click.echo(f"\n🔍 Checkpoint: Available")
                    click.echo(f"   Next nodes: {state_snapshot.next or 'none (completed)'}")
                    if state_snapshot.metadata:
                        step = state_snapshot.metadata.get("step", "unknown")
                        click.echo(f"   Last step:  {step}")
                else:
                    click.echo(f"\n🔍 Checkpoint: None found for this thread_id")
        except Exception as e:
            click.echo(f"\n⚠️  Could not load checkpoint info: {e}")
    
    click.echo("\n" + section)


@cli.command()
@click.argument("project_id")
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Show detailed processing steps.",
)
def resume(project_id: str, verbose: bool):
    """Resume an interrupted run from its last checkpoint.
    
    Requires persistent checkpointer (CHECKPOINTER_BACKEND=sqlite).
    """
    # Check checkpointer backend
    if config.checkpointer_backend != "sqlite":
        click.echo(
            f"❌ Resume requires persistent checkpointer (sqlite).", err=True
        )
        click.echo(
            f"   Current backend: {config.checkpointer_backend}", err=True
        )
        click.echo(
            f"   Set CHECKPOINTER_BACKEND=sqlite in .env to enable resume.", err=True
        )
        sys.exit(1)
    
    # Resolve project_id to output directory
    run_dir = _resolve_project_id(project_id)
    
    if not run_dir:
        click.echo(f"❌ No run found for project ID: {project_id}", err=True)
        sys.exit(1)
    
    # Check if already running
    running_file = run_dir / ".running"
    if running_file.exists():
        try:
            pid = int(running_file.read_text().strip())
            if _is_process_running(pid):
                click.echo(f"❌ Run is already in progress (PID: {pid})", err=True)
                sys.exit(1)
            else:
                # Stale .running file, clean up
                running_file.unlink()
        except (ValueError, IOError):
            pass
    
    # Load runtime_config to get document_path
    runtime_config_file = run_dir / "runtime_config.json"
    document_path = None
    if runtime_config_file.exists():
        try:
            with open(runtime_config_file, 'r', encoding='utf-8') as f:
                runtime_config = json.load(f)
            runtime_info = runtime_config.get("runtime_info", {})
            document_path = runtime_info.get("document_path")
        except (json.JSONDecodeError, IOError):
            pass
    
    if not document_path:
        click.echo(f"❌ Could not find document_path in runtime_config.json", err=True)
        sys.exit(1)
    
    # Enable verbose logging if requested
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    click.echo("=" * 70)
    click.echo("🔄 Resuming FAIRifier run")
    click.echo("=" * 70)
    click.echo(f"📄 Project ID: {project_id}")
    click.echo(f"📁 Output:     {run_dir}")
    click.echo(f"📄 Document:   {document_path}")
    click.echo(f"🤖 LLM:        {config.llm_model} ({config.llm_provider})")
    click.echo("=" * 70)
    click.echo()
    
    # Run workflow (will resume from checkpoint with same thread_id)
    asyncio.run(_resume_workflow(document_path, run_dir, project_id, verbose))


async def _resume_workflow(
    document_path: str,
    output_path: Path,
    project_id: str,
    verbose: bool = False
):
    """Resume a workflow from its last checkpoint."""
    start_time = datetime.now()
    
    # Write .running file
    running_file = output_path / ".running"
    running_file.write_text(str(os.getpid()))
    
    # Set up log file (append mode for resume)
    log_file = output_path / "full_output.log"
    log_handle = open(log_file, 'a', encoding='utf-8', buffering=1)
    log_handle.write(f"\n\n{'='*70}\n")
    log_handle.write(f"Resume started at: {start_time.isoformat()}\n")
    log_handle.write(f"{'='*70}\n\n")
    
    # Reuse same TeeHandler setup from _run_workflow
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
    
    tee_handler = TeeHandler(log_handle)
    tee_handler.setFormatter(console_formatter)
    root_logger = logging.getLogger()
    root_logger.addHandler(tee_handler)
    
    try:
        workflow = FAIRifierLangGraphApp()
        
        click.echo(f"🔄 Resuming from last checkpoint (Project ID: {project_id})\n")
        
        # Resume: invoke with None (or minimal state) and same thread_id
        # LangGraph will load last checkpoint and continue from there
        result = await workflow.run(document_path, project_id, output_dir=str(output_path))
        
        # Extract results (same as _run_workflow)
        status = result.get("status", "unknown")
        confidence_scores = result.get("confidence_scores", {})
        needs_review = result.get("needs_human_review", False)
        errors = result.get("errors", [])
        artifacts = result.get("artifacts", {})
        
        # Calculate duration of this resume session
        duration = (datetime.now() - start_time).total_seconds()
        
        click.echo("\n" + "=" * 70)
        click.echo("📊 Resume Results")
        click.echo("=" * 70)
        
        # Display confidence scores
        click.echo("\n🎯 Confidence Scores:")
        for component, score in confidence_scores.items():
            emoji = "✅" if score >= 0.8 else "⚠️" if score >= 0.6 else "❌"
            click.echo(f"  {emoji} {component}: {score:.2%}")
        
        # Display status
        click.echo(f"\n📈 Status: {status.upper()}")
        click.echo(f"⏱️  Resume duration: {duration:.2f} seconds")
        
        if needs_review:
            click.echo("⚠️  Human review recommended")
        
        if errors:
            click.echo(f"\n❌ Errors ({len(errors)}):")
            for error in errors[:5]:
                click.echo(f"  - {error}")
        
        # Save artifacts (same logic as _run_workflow)
        click.echo("\n💾 Saving artifacts...")
        if artifacts:
            for artifact_name, content in artifacts.items():
                if content:
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
        
        # Save processing log (append mode)
        processing_log_file = output_path / "processing_log.jsonl"
        with open(processing_log_file, 'a', encoding='utf-8') as f:
            for log_entry in json_logger.get_logs():
                f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
        click.echo(f"  ✓ processing_log.jsonl (appended)")
        
        # Save LLM responses
        try:
            llm_helper = get_llm_helper()
            if llm_helper.llm_responses:
                save_llm_responses(output_path, llm_helper)
                click.echo(f"  ✓ llm_responses.json ({len(llm_helper.llm_responses)} interactions)")
        except Exception as e:
            click.echo(f"  ⚠️  Could not save LLM responses: {e}", err=True)
        
        click.echo("\n" + "=" * 70)
        
        if status == "failed":
            click.echo("❌ Resume FAILED!")
            click.echo(f"📁 Output: {output_path}")
            click.echo("=" * 70)
            sys.exit(1)
        else:
            click.echo("✨ Resume complete!")
            click.echo(f"📁 Output: {output_path}")
            click.echo("=" * 70)
    
    except Exception as e:
        click.echo(f"\n❌ Resume error: {str(e)}", err=True)
        sys.exit(1)
    finally:
        # Clean up .running file
        if running_file.exists():
            running_file.unlink()
        
        # Clean up log handler and close file
        root_logger.removeHandler(tee_handler)
        log_handle.close()


@cli.command("config-info")
def config_info():
    """Show current FAIRiAgent configuration."""
    click.echo("FAIRiAgent Configuration:")
    click.echo(f"  Project root: {config.project_root}")
    click.echo(f"  Knowledge base: {config.kb_path}")
    click.echo(f"  Output path: {config.output_path}")
    click.echo(f"  LLM model: {config.llm_model}")
    click.echo(f"  LLM base URL: {config.llm_base_url}")
    click.echo(f"  Min confidence: {config.min_confidence_threshold}")
    click.echo(f"  Default MIxS package: {config.default_mixs_package}")
    click.echo(f"\n  External Services:")
    click.echo(f"    • FAIR-DS API: {config.fair_ds_api_url or 'Not configured'}")
    click.echo(f"    • MinerU: {'Enabled' if config.mineru_enabled else 'Disabled'}")
    click.echo(f"  Tools Layer:")
    click.echo(f"    • LangChain Tools: Enabled (v1.0+)")
    click.echo(f"    • FAIR-DS Tools: 5 tools (get_available_packages, get_package, get_terms, search_terms_for_fields, search_fields_in_packages)")
    click.echo(f"    • MinerU Tool: 1 tool (convert_document)")
    click.echo(f"    • Observability: Full LangSmith tracing")


def _check_mineru_preflight() -> tuple[bool, str]:
    """Quick MinerU pre-flight: server reachable if enabled. Returns (ok, message)."""
    import socket
    from urllib.parse import urlparse

    if not config.mineru_enabled:
        return True, "disabled (optional)"
    if not config.mineru_server_url:
        return False, "enabled but MINERU_SERVER_URL not set"
    try:
        parsed = urlparse(config.mineru_server_url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 30000
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        result = sock.connect_ex((host, port))
        sock.close()
        if result == 0:
            return True, "reachable"
        return False, f"port {port} not accessible"
    except Exception as e:
        return False, str(e)


def _check_fair_ds_preflight() -> tuple[bool, str]:
    """Quick FAIR-DS API pre-flight. Returns (ok, message)."""
    if not config.fair_ds_api_url:
        return True, "not configured (optional)"
    try:
        from .services.fair_data_station import FAIRDataStationClient

        client = FAIRDataStationClient(config.fair_ds_api_url, timeout=5)
        if client.is_available():
            return True, "reachable"
        return False, "no response"
    except Exception as e:
        return False, str(e)


def _check_llm_preflight() -> tuple[bool, str]:
    """Quick LLM pre-flight: config present; for Ollama, ping base URL and verify model exists. Returns (ok, message)."""
    try:
        import requests
    except ImportError:
        return True, f"{config.llm_provider} / {config.llm_model} (requests not installed, skip ping)"
    if not config.llm_base_url and config.llm_provider.lower() == "ollama":
        return False, "Ollama selected but LLM base URL not set"
    if config.llm_provider.lower() == "ollama" and config.llm_base_url:
        model_ok, model_msg = check_ollama_model_available(config.llm_base_url, config.llm_model, timeout=3)
        if not model_ok:
            return False, model_msg
        if model_msg != config.llm_model:
            return True, f"{config.llm_model} → {model_msg}"
        return True, f"{config.llm_model} (ok)"
    return True, f"{config.llm_provider} / {config.llm_model} (config ok)"


@cli.command("validate-document")
@click.argument("input_file", type=click.Path(exists=True), required=False)
@click.option(
    "--env-only",
    is_flag=True,
    help="Only run environment checks (MinerU, FAIR-DS, LLM); skip document validation.",
)
def validate_document(input_file: Optional[str], env_only: bool):
    """Pre-flight check: document (size/format) and environment (MinerU, FAIR-DS, LLM).

    Run before 'process' to ensure the document and services are ready.
    Use --env-only to check only environment (no document path needed).
    """
    if not input_file and not env_only:
        click.echo("Error: INPUT_FILE required unless --env-only.", err=True)
        sys.exit(2)

    section = "=" * 60
    click.echo(section)
    click.echo("Pre-flight check")
    click.echo(section)

    doc_ok = True  # skip document checks when --env-only
    if not env_only and input_file:
        file_path = Path(input_file)
        click.echo("\n📄 Document")
        click.echo(f"   Path: {file_path}")
        file_size = file_path.stat().st_size
        max_size = config.max_document_size_mb * 1024 * 1024
        if file_size > max_size:
            size_mb = file_size / (1024 * 1024)
            click.echo(f"   ❌ File too large: {size_mb:.2f} MB (max: {config.max_document_size_mb} MB)")
            doc_ok = False
        else:
            if file_size < 1024 * 1024:
                size_str = f"{file_size / 1024:.1f} KB"
            else:
                size_str = f"{file_size / (1024 * 1024):.2f} MB"
            click.echo(f"   ✓ Size: {size_str}")
        if file_path.suffix.lower() not in (".pdf", ".txt", ".md"):
            click.echo(f"   ⚠️  Type {file_path.suffix} may not be fully supported")
        else:
            click.echo(f"   ✓ Type: {file_path.suffix}")
        if doc_ok:
            click.echo("   Document validation passed.")

    click.echo("\n🔧 Environment")
    mineru_ok, mineru_msg = _check_mineru_preflight()
    click.echo(f"   MinerU:      {'✅ ' + mineru_msg if mineru_ok else '❌ ' + mineru_msg}")
    fair_ok, fair_msg = _check_fair_ds_preflight()
    click.echo(f"   FAIR-DS API: {'✅ ' + fair_msg if fair_ok else '❌ ' + fair_msg}")
    llm_ok, llm_msg = _check_llm_preflight()
    click.echo(f"   LLM:         {'✅ ' + llm_msg if llm_ok else '❌ ' + llm_msg}")

    click.echo("\n" + section)
    all_ok = doc_ok and mineru_ok and fair_ok and llm_ok
    if all_ok:
        click.echo("Pre-flight passed. You can run 'process'.")
    else:
        click.echo("Pre-flight had failures. Fix issues above before running 'process'.")
        sys.exit(1)


@cli.command("check-mineru")
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Show detailed diagnostic information.",
)
def check_mineru(verbose: bool):
    """Check MinerU service availability and configuration.

    Verifies MinerU CLI and HTTP server are configured and available
    for document conversion.
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


@cli.group()
def memory():
    """Manage mem0 persistent memory for workflow sessions."""
    pass


@memory.command("list")
@click.argument("session_id", required=False)
@click.option(
    "--agent",
    "-a",
    help="Filter by agent name (e.g., DocumentParser, JSONGenerator).",
)
@click.option(
    "--limit",
    "-n",
    type=int,
    default=50,
    help="Maximum number of memories to display (default: 50).",
)
def memory_list(session_id: Optional[str], agent: Optional[str], limit: int):
    """List memories for a session (project ID).
    
    If no session_id is provided, shows memory service status.
    
    Examples:
    
        fairifier memory list                    # Show status
        fairifier memory list fairifier_20260129_120000  # List all memories
        fairifier memory list fairifier_20260129_120000 -a JSONGenerator  # Filter by agent
    """
    # Check if mem0 is enabled
    if not config.mem0_enabled:
        click.echo("❌ Mem0 is disabled in configuration.")
        click.echo("   Set MEM0_ENABLED=true in .env to enable.")
        return
    
    # Try to get mem0 service
    try:
        from .services.mem0_service import get_mem0_service
        mem0_service = get_mem0_service()
    except ImportError:
        click.echo("❌ mem0ai package not installed.")
        click.echo("   Install with: pip install mem0ai")
        return
    
    if not mem0_service or not mem0_service.is_available():
        click.echo("❌ Mem0 service not available.")
        click.echo("   Check Qdrant connection at: "
                   f"{config.mem0_qdrant_host}:{config.mem0_qdrant_port}")
        return
    
    if not session_id:
        # Show status only
        click.echo("=" * 60)
        click.echo("Mem0 Memory Service Status")
        click.echo("=" * 60)
        click.echo(f"✅ Status:     Available")
        click.echo(f"📦 Qdrant:     {config.mem0_qdrant_host}:{config.mem0_qdrant_port}")
        click.echo(f"📁 Collection: {config.mem0_collection_name}")
        click.echo(f"🧠 Embedding:  {config.mem0_embedding_model}")
        click.echo("\nUsage: fairifier memory list <session_id>")
        return
    
    # List memories for the session
    click.echo("=" * 60)
    click.echo(f"Memories for session: {session_id}")
    click.echo("=" * 60)
    
    memories = mem0_service.list_memories(session_id, agent_id=agent)
    
    if not memories:
        click.echo("\n(No memories found)")
        return
    
    # Display memories
    displayed = 0
    for m in memories[:limit]:
        if displayed > 0:
            click.echo("-" * 40)
        
        memory_id = m.get("id", "unknown")[:12]
        memory_text = m.get("memory", "")
        agent_id = m.get("agent_id", "unknown")
        metadata = m.get("metadata", {})
        score = metadata.get("score", "N/A")
        timestamp = metadata.get("timestamp", "")[:19] if metadata.get("timestamp") else ""
        
        click.echo(f"\n🆔 {memory_id}...")
        click.echo(f"🤖 Agent: {agent_id}")
        if score != "N/A":
            click.echo(f"📊 Score: {score}")
        if timestamp:
            click.echo(f"⏰ Time:  {timestamp}")
        click.echo(f"💭 {memory_text[:200]}{'...' if len(memory_text) > 200 else ''}")
        
        displayed += 1
    
    if len(memories) > limit:
        click.echo(f"\n... and {len(memories) - limit} more (use -n to show more)")
    
    click.echo("\n" + "=" * 60)
    click.echo(f"Total: {len(memories)} memories")


@memory.command("clear")
@click.argument("session_id")
@click.option(
    "--force",
    "-f",
    is_flag=True,
    help="Skip confirmation prompt.",
)
def memory_clear(session_id: str, force: bool):
    """Clear all memories for a session (project ID).
    
    This is useful for re-running a workflow with fresh context.
    
    Example:
    
        fairifier memory clear fairifier_20260129_120000
    """
    # Check if mem0 is enabled
    if not config.mem0_enabled:
        click.echo("❌ Mem0 is disabled in configuration.")
        click.echo("   Set MEM0_ENABLED=true in .env to enable.")
        return
    
    # Try to get mem0 service
    try:
        from .services.mem0_service import get_mem0_service
        mem0_service = get_mem0_service()
    except ImportError:
        click.echo("❌ mem0ai package not installed.")
        click.echo("   Install with: pip install mem0ai")
        return
    
    if not mem0_service or not mem0_service.is_available():
        click.echo("❌ Mem0 service not available.")
        return
    
    # Count memories first
    memories = mem0_service.list_memories(session_id)
    count = len(memories)
    
    if count == 0:
        click.echo(f"No memories found for session: {session_id}")
        return
    
    # Confirm deletion
    if not force:
        click.echo(f"⚠️  About to delete {count} memories for session: {session_id}")
        if not click.confirm("Are you sure?"):
            click.echo("Cancelled.")
            return
    
    # Delete memories
    deleted = mem0_service.delete_session_memories(session_id)
    
    if deleted > 0:
        click.echo(f"✅ Deleted {deleted} memories for session: {session_id}")
    else:
        click.echo(f"⚠️  No memories were deleted (may have been already cleared)")


@memory.command("status")
def memory_status():
    """Show mem0 memory service status and configuration."""
    click.echo("=" * 60)
    click.echo("Mem0 Memory Service Status")
    click.echo("=" * 60)
    
    click.echo("\n📋 Configuration:")
    click.echo(f"   MEM0_ENABLED:          {config.mem0_enabled}")
    click.echo(f"   MEM0_QDRANT_HOST:      {config.mem0_qdrant_host}")
    click.echo(f"   MEM0_QDRANT_PORT:      {config.mem0_qdrant_port}")
    click.echo(f"   MEM0_COLLECTION_NAME:  {config.mem0_collection_name}")
    click.echo(f"   MEM0_EMBEDDING_MODEL:  {config.mem0_embedding_model}")
    click.echo(f"   MEM0_LLM_MODEL:        {config.mem0_llm_model or '(uses main LLM)'}")
    click.echo(f"   MEM0_OLLAMA_BASE_URL:  {config.mem0_ollama_base_url or '(uses main LLM base URL)'}")
    
    if not config.mem0_enabled:
        click.echo("\n⚠️  Mem0 is DISABLED")
        click.echo("   Set MEM0_ENABLED=true in .env to enable.")
        return
    
    # Try to connect
    click.echo("\n🔍 Connection Test:")
    try:
        from .services.mem0_service import get_mem0_service
        mem0_service = get_mem0_service()
        
        if mem0_service and mem0_service.is_available():
            click.echo("   ✅ Mem0 service is available")
            click.echo("   ✅ Qdrant connection OK")
        else:
            click.echo("   ❌ Mem0 service not available")
            click.echo(f"   Check Qdrant at: {config.mem0_qdrant_host}:{config.mem0_qdrant_port}")
    except ImportError:
        click.echo("   ❌ mem0ai package not installed")
        click.echo("   Install with: pip install mem0ai")
    except Exception as e:
        click.echo(f"   ❌ Connection failed: {e}")
    
    click.echo("\n" + "=" * 60)


if __name__ == "__main__":
    cli()
