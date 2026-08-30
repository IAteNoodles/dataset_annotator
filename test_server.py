import asyncio
import uvicorn
import threading
import time

def run_server():
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=False, log_level="warning")

# Start server in background thread
t = threading.Thread(target=run_server, daemon=True)
t.start()
time.sleep(2)

import requests

try:
    r = requests.get("http://localhost:8000/api/health", timeout=5)
    print(f"Health: {r.json()}")
except Exception as e:
    print(f"Health check failed: {e}")

# Test annotations endpoint
try:
    r = requests.get("http://localhost:8000/api/annotations", timeout=5)
    print(f"Annotations list: status={r.status_code}, body={r.text[:200]}")
except Exception as e:
    print(f"Annotations list failed: {e}")

# Test datasets endpoint
try:
    r = requests.get("http://localhost:8000/api/datasets", timeout=5)
    print(f"Datasets: status={r.status_code}, body={r.text[:200]}")
except Exception as e:
    print(f"Datasets failed: {e}")

# Test fields endpoint
try:
    r = requests.get("http://localhost:8000/api/fields", timeout=5)
    print(f"Fields: status={r.status_code}, body={r.text[:200]}")
except Exception as e:
    print(f"Fields failed: {e}")

print("Done testing")