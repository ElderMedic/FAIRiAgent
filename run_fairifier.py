#!/usr/bin/env python3
"""Launch script for FAIRifier services."""

import subprocess
import sys
import time
import os

# LangSmith: controlled by config (apply_env_overrides). Do not set here.


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


def main():
    """Main launcher. Delegates to Click CLI for all commands except 'api'."""
    if len(sys.argv) < 2:
        from fairifier.cli import cli
        cli()
        return

    arg1 = sys.argv[1]
    if arg1 in ("-h", "--help", "help"):
        from fairifier.cli import cli
        cli()
        return

    mode = arg1.lower()
    processes = []

    try:
        if mode == "api":
            print("🚀 Starting FAIRifier API server...")
            processes.append(run_api())
            print("📡 API server running at http://localhost:8000")
        else:
            # Delegate all other commands to Click CLI (process, ui, status, config-info, etc.)
            from fairifier.cli import cli
            cli()
            return
        
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
