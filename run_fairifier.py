#!/usr/bin/env python3
"""Launch script for FAIRifier services."""

import subprocess
import sys
import time
import os
from pathlib import Path

# Enable LangSmith tracing by default
os.environ["LANGCHAIN_TRACING_V2"] = "true"
os.environ["LANGCHAIN_PROJECT"] = os.getenv("LANGCHAIN_PROJECT", "fairifier")


def run_api():
    """Run the FastAPI server."""
    cmd = [
        sys.executable, "-m", "uvicorn",
        "fairifier.apps.api.main:app",
        "--host", "0.0.0.0",
        "--port", "8000",
        "--reload"
    ]
    return subprocess.Popen(cmd)


def run_ui():
    """Run the Streamlit UI."""
    ui_path = Path(__file__).parent / "fairifier" / "apps" / "ui" / "streamlit_app.py"
    cmd = [
        sys.executable, "-m", "streamlit", "run",
        str(ui_path),
        "--server.port", "8501",
        "--server.address", "0.0.0.0"
    ]
    return subprocess.Popen(cmd)


def show_help():
    """Show help message."""
    print("Usage: python run_fairifier.py [mode] [options]")
    print("\nModes:")
    print("  api     - Run FastAPI server")
    print("  cli     - Run CLI interface (pass additional args after 'cli')")
    print("  process - Shortcut for CLI process command")
    print("\nExamples:")
    print("  python run_fairifier.py api")
    print("  python run_fairifier.py cli process document.pdf")
    print("  python run_fairifier.py process document.pdf  # shortcut")
    print("  python run_fairifier.py cli --help            # CLI help")


def main():
    """Main launcher."""
    if len(sys.argv) < 2 or sys.argv[1] in ['-h', '--help', 'help']:
        show_help()
        sys.exit(0)
    
    mode = sys.argv[1].lower()
    processes = []
    
    try:
        if mode == "api":
            print("🚀 Starting FAIRifier API server...")
            processes.append(run_api())
            print("📡 API server running at http://localhost:8000")
            
        elif mode == "cli":
            # Pass remaining arguments to CLI
            print("💻 Starting FAIRifier CLI...")
            sys.argv = [sys.argv[0]] + sys.argv[2:]  # Remove 'cli' from args
            from fairifier.cli import cli
            cli()
            return
            
        elif mode == "process":
            # Shortcut for CLI process command
            print("💻 Processing document...")
            sys.argv = [sys.argv[0], 'process'] + sys.argv[2:]
            from fairifier.cli import cli
            cli()
            return
            
        else:
            print(f"❌ Unknown mode: {mode}")
            print("\nRun 'python run_fairifier.py --help' for usage information")
            sys.exit(1)
        
        # Wait for processes
        if processes:
            print("\n🔄 Services running. Press Ctrl+C to stop.")
            try:
                for process in processes:
                    process.wait()
            except KeyboardInterrupt:
                print("\n🛑 Stopping services...")
                for process in processes:
                    process.terminate()
                time.sleep(2)
                for process in processes:
                    if process.poll() is None:
                        process.kill()
                print("✅ Services stopped.")
    
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        for process in processes:
            try:
                process.terminate()
            except Exception:
                pass
        sys.exit(1)


if __name__ == "__main__":
    main()
