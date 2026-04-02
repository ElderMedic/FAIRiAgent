#!/usr/bin/env python3
"""Launch script for FAIRifier services."""

import os
import subprocess
import sys
import time
from pathlib import Path

# LangSmith: controlled by config (apply_env_overrides). Do not set here.

PROJECT_ROOT = Path(__file__).resolve().parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"
FRONTEND_DIST = FRONTEND_DIR / "dist"


def run_api(port: int = 8000, reload: bool = True):
    """Run the FastAPI server."""
    cmd = [
        sys.executable, "-m", "uvicorn",
        "fairifier.apps.api.main:app",
        "--host", "0.0.0.0",
        "--port", str(port),
    ]
    if reload:
        cmd.append("--reload")
    return subprocess.Popen(cmd)


def run_frontend_dev(port: int = 5173):
    """Run the Vite dev server for frontend development."""
    if not (FRONTEND_DIR / "node_modules").is_dir():
        print("📦 Installing frontend dependencies...")
        subprocess.check_call(["npm", "install"], cwd=str(FRONTEND_DIR))
    cmd = ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", str(port)]
    return subprocess.Popen(cmd, cwd=str(FRONTEND_DIR))


def build_frontend():
    """Build the React frontend for production."""
    if not (FRONTEND_DIR / "node_modules").is_dir():
        print("📦 Installing frontend dependencies...")
        subprocess.check_call(["npm", "install"], cwd=str(FRONTEND_DIR))
    print("🔨 Building frontend...")
    subprocess.check_call(["npm", "run", "build"], cwd=str(FRONTEND_DIR))
    print(f"✅ Frontend built to {FRONTEND_DIST}")


def main():
    """Main launcher. Delegates to Click CLI for all commands except 'api'/'webui'."""
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

        elif mode == "webui":
            port = 8000
            args = sys.argv[2:]
            if args:
                if args[0] == "--port" and len(args) > 1:
                    try:
                        port = int(args[1])
                    except ValueError:
                        pass
                else:
                    try:
                        port = int(args[0])
                    except ValueError:
                        pass

            if not (FRONTEND_DIST / "index.html").is_file():
                build_frontend()

            print("🚀 Starting FAIRiAgent Web UI (production)...")
            processes.append(run_api(port=port, reload=False))
            print(f"🌐 Web UI available at http://localhost:{port}")
            print(f"📡 API docs at http://localhost:{port}/docs")
            import socket
            hostname = socket.gethostname()
            try:
                local_ip = socket.gethostbyname(hostname)
                print(f"🏠 LAN access: http://{local_ip}:{port}")
            except socket.gaierror:
                pass

        elif mode == "dev":
            print("🚀 Starting FAIRiAgent in development mode...")
            print("   Backend:  http://localhost:8000 (with hot-reload)")
            print("   Frontend: http://localhost:5173 (Vite dev server)")
            processes.append(run_api(port=8000, reload=True))
            processes.append(run_frontend_dev(port=5173))

        else:
            from fairifier.cli import cli
            cli()
            return

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
