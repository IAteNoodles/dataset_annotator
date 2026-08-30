#!/usr/bin/env python3
"""
Development startup script - runs both backend and frontend concurrently.
"""
import subprocess
import sys
import os
import signal
import time
import threading
from pathlib import Path


def run_backend():
    """Run the FastAPI backend server."""
    backend_dir = Path(__file__).parent
    env = os.environ.copy()
    env["DATASET_ANNOTATOR_CONFIG"] = str(backend_dir / "config" / "dataset_config.yaml")
    env["DATASET_ANNOTATOR_DB"] = str(backend_dir / "data" / "annotator.db")
    
    cmd = [sys.executable, "-m", "backend.cli", "serve", "--port", "8080"]
    return subprocess.Popen(cmd, cwd=backend_dir, env=env)


def run_frontend():
    """Run the Vite dev server for frontend."""
    frontend_dir = Path(__file__).parent / "frontend"
    cmd = ["npm", "run", "dev"]
    return subprocess.Popen(cmd, cwd=frontend_dir)


def main():
    print("=" * 60)
    print("Dataset Annotator - Development Server")
    print("=" * 60)
    print("Starting backend on http://localhost:8080")
    print("Starting frontend on http://localhost:3000")
    print("Press Ctrl+C to stop both servers")
    print("=" * 60)

    # Check if frontend dependencies are installed
    frontend_dir = Path(__file__).parent / "frontend"
    if not (frontend_dir / "node_modules").exists():
        print("Installing frontend dependencies...")
        subprocess.run(["npm", "install"], cwd=frontend_dir, check=True)

    # Start backend
    print("\n[Backend] Starting...")
    backend_proc = run_backend()
    
    # Wait a bit for backend to start
    time.sleep(3)
    
    # Start frontend
    print("[Frontend] Starting...")
    frontend_proc = run_frontend()

    # Wait for processes
    try:
        # Keep running until interrupted
        while True:
            # Check if processes are still alive
            if backend_proc.poll() is not None:
                print("[Backend] Process exited!")
                break
            if frontend_proc.poll() is not None:
                print("[Frontend] Process exited!")
                break
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\nShutting down...")
    finally:
        # Terminate both processes
        for proc, name in [(backend_proc, "Backend"), (frontend_proc, "Frontend")]:
            if proc.poll() is None:
                print(f"Stopping {name}...")
                if sys.platform == "win32":
                    proc.terminate()
                else:
                    proc.send_signal(signal.SIGTERM)
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()

    print("Done.")


if __name__ == "__main__":
    main()