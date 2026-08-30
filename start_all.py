#!/usr/bin/env python3
"""
Start backend + frontend with health check.
Usage: python start_all.py
This script:
1. Starts the FastAPI backend on port 8080
2. Serves a simple embedded frontend HTML page
3. Prints the frontend URL
"""
import subprocess
import sys
import os
import time
import webbrowser
import threading
from pathlib import Path


def run_backend():
    """Run the FastAPI backend server."""
    backend_dir = Path(__file__).parent
    env = os.environ.copy()
    env["DATASET_ANNOTATOR_CONFIG"] = str(backend_dir / "config" / "dataset_config.yaml")
    env["DATASET_ANNOTATOR_DB"] = str(backend_dir / "data" / "annotator.db")
    
    cmd = [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8080"]
    return subprocess.Popen(cmd, cwd=backend_dir, env=env)


def wait_for_backend(timeout=30):
    """Wait for backend to be healthy."""
    print("Waiting for backend to be ready...", end=" ", flush=True)
    start = time.time()
    while time.time() - start < timeout:
        try:
            import requests
            r = requests.get("http://localhost:8080/api/health", timeout=2)
            if r.status_code == 200:
                print("Backend ready!")
                return True
        except Exception:
            pass
        time.sleep(0.5)
        print(".", end=" ", flush=True)
    print("Backend failed to start")
    return False


def open_frontend_browser(url):
    """Open the frontend in the default browser."""
    webbrowser.open(url)


def main():
    print("=" * 60)
    print("Dataset Annotator - Starting All Services")
    print("=" * 60)

    # Start backend
    print("\nStarting backend...")
    backend = run_backend()

    # Stream backend logs a bit then wait for health
    time.sleep(2)

    if not wait_for_backend():
        backend.terminate()
        sys.exit(1)

    # Frontend: serve a simple embedded HTML page
    # We'll just use the backend to serve static files if dist exists,
    # otherwise we print the URL for the user to open manually
    frontend_url = "http://localhost:8080"

    print("\n" + "=" * 60)
    print("All services running!")
    print(f"   Backend:  http://localhost:8080")
    print(f"   Frontend: {frontend_url}")
    print(f"   API Docs: http://localhost:8080/docs")
    print("=" * 60)
    print("\nFrontend URL: {frontend_url}")
    print("Open your browser to: {frontend_url}")
    print("\nPress Ctrl+C to stop the backend server\n")

    # Open browser after a short delay
    def delayed_open():
        time.sleep(3)
        webbrowser.open(frontend_url)

    browser_thread = threading.Thread(target=delayed_open, daemon=True)
    browser_thread.start()

    # Keep alive
    try:
        while True:
            if backend.poll() is not None:
                print("\nBackend crashed!")
                break
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        print("\nShutting down...")
        if backend.poll() is None:
            backend.terminate()
            try:
                backend.wait(timeout=5)
            except subprocess.TimeoutExpired:
                backend.kill()
        print("Done.")


if __name__ == "__main__":
    main()