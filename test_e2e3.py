import asyncio
import uvicorn
import threading
import time
import requests
import json
from pathlib import Path

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

# Test create annotation
r = requests.post('http://localhost:8000/api/annotations', 
                  json={'data_item_id': 1, 'annotation_type': 'rectangle', 'geometry': {'type': 'rectangle', 'coordinates': [[0, 0], [100, 100]]}}, 
                  timeout=5)
print(f'Create annotation: status={r.status_code}')

# Test list annotations for item 1
r = requests.get('http://localhost:8000/api/data-items/1/annotations', timeout=5)
print(f'Item 1 annotations: status={r.status_code}, count={len(r.json()) if r.status_code == 200 else "N/A"}')

# Test export full
r = requests.post('http://localhost:8000/api/export/full', 
                  json={'dataset_id': 1, 'type': 'full', 'formats': ['parquet']}, 
                  timeout=10)
print(f'Export full: status={r.status_code}')
if r.status_code == 200:
    result = r.json()
    export_id = result.get("export_id")
    print(f'Export: export_id={export_id}')

# Test export status
export_id = r.json().get("export_id") if r.status_code == 200 else None
if export_id:
    r = requests.get(f'http://localhost:8000/api/export/status/{export_id}', timeout=5)
    print(f'Export status: status={r.status_code}, progress={r.json().get("progress")}')

# Test snapshot
r = requests.post('http://localhost:8000/api/snapshots', 
                  json={'dataset_id': 1, 'trigger': 'manual'}, 
                  timeout=10)
print(f'Snapshot: status={r.status_code}')
if r.status_code == 200:
    result = r.json()
    print(f'Snapshot: ann_count={result.get("annotation_count")}')

# Test recover from export - need export file path and target dir
# Find the export parquet file
exports_dir = Path('exports')
parquet_files = list(exports_dir.glob('*.parquet'))
if parquet_files:
    export_path = str(parquet_files[0])
    print(f'Using export path: {export_path}')
    
    # Test recover from export
    r = requests.post('http://localhost:8000/api/recover/from-export', 
                      json={'export_path': export_path, 'target_dir': 'recovered_test'}, 
                      timeout=10)
    print(f'Recover from export: status={r.status_code}')
    if r.status_code == 200:
        result = r.json()
        print(f'Recover: success={result.get("success")}, dataset_id={result.get("dataset_id")}')
    
    # Test verify recovery
    r = requests.post('http://localhost:8000/api/recover/verify-recovery', 
                      json={'target_dir': 'recovered_test'}, 
                      timeout=10)
    print(f'Verify recovery: status={r.status_code}')
    if r.status_code == 200:
        result = r.json()
        print(f'Verify: valid={result.get("valid")}')

print("\n=== All tests done ===")