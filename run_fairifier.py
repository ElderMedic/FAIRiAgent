#!/usr/bin/env python3
"""Launch script for FAIRifier services."""

import subprocess
import sys
import time
import signal
from pathlib import Path

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

def main():
    """Main launcher."""
    if len(sys.argv) < 2:
        print("Usage: python run_fairifier.py [api|ui|both|cli]")
        print("  api  - Run FastAPI server only")
        print("  ui   - Run Streamlit UI only") 
        print("  both - Run both API and UI")
        print("  cli  - Run CLI interface")
        sys.exit(1)
    
    mode = sys.argv[1].lower()
    processes = []
    
    try:
        if mode == "api":
            print("🚀 Starting FAIRifier API server...")
            processes.append(run_api())
            print("📡 API server running at http://localhost:8000")
            
        elif mode == "ui":
            print("🎨 Starting FAIRifier UI...")
            processes.append(run_ui())
            print("🌐 UI running at http://localhost:8501")
            
        elif mode == "both":
            print("🚀 Starting FAIRifier API server...")
            processes.append(run_api())
            time.sleep(2)  # Give API time to start
            
            print("🎨 Starting FAIRifier UI...")
            processes.append(run_ui())
            
            print("\n✅ FAIRifier is running!")
            print("📡 API: http://localhost:8000")
            print("🌐 UI:  http://localhost:8501")
            print("📖 API Docs: http://localhost:8000/docs")
            
        elif mode == "cli":
            print("💻 Starting FAIRifier CLI...")
            from fairifier.cli import cli
            cli()
            return
            
        else:
            print(f"❌ Unknown mode: {mode}")
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
            except:
                pass
        sys.exit(1)

if __name__ == "__main__":
    main()
