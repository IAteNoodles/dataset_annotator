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

# Test health
r = requests.get("http://localhost:8000/api/health", timeout=5)
print(f"Health: {r.json()}")

# Test datasets
r = requests.get("http://localhost:8000/api/datasets", timeout=5)
print(f"Datasets: status={r.status_code}, body={r.text[:200]}")

# Test fields
r = requests.get("http://localhost:8000/api/fields", timeout=5)
print(f"Fields: status={r.status_code}, body={r.text[:200]}")

# Test annotations list (GET)
r = requests.get("http://localhost:8000/api/annotations", timeout=5)
print(f"Annotations list GET: status={r.status_code}, body={r.text[:200]}")

# Test create annotation (POST)
try:
    r = requests.post("http://localhost:8000/api/annotations", 
                      json={"data_item_id": 1, "annotation_type": "text", "geometry": {"x": 0, "y": 0, "width": 100, "height": 100}}, 
                      timeout=5)
    print(f"Create annotation: status={r.status_code}, body={r.text[:200]}")
except Exception as e:
    print(f"Create annotation error: {e}")

# Test list annotations for item 1
r = requests.get("http://localhost:8000/api/data-items/1/annotations", timeout=5)
print(f"Item 1 annotations: status={r.status_code}, body={r.text[:200]}")

print("\nDone testing")