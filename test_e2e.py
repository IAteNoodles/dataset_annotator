import asyncio
import uvicorn
import threading
import time
import requests
import json

def run_server():
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=False, log_level="warning")

# Start server in background thread
t = threading.Thread(target=run_server, daemon=True)
t.start()
time.sleep(2)

# Test 1: Create annotation
print("=== Test 1: Create annotation ===")
r = requests.post('http://localhost:8000/api/annotations', 
                  json={'data_item_id': 1, 'annotation_type': 'rectangle', 'geometry': {'type': 'rectangle', 'coordinates': [[0, 0], [100, 100]]}}, 
                  timeout=5)
print(f'Create annotation: status={r.status_code}')

# Test 2: List annotations for item 1
print("\n=== Test 2: List annotations ===")
r = requests.get('http://localhost:8000/api/data-items/1/annotations', timeout=5)
print(f'Item 1 annotations: status={r.status_code}, count={len(r.json()) if r.status_code == 200 else "N/A"}')

# Test 3: Export dataset
print("\n=== Test 3: Export dataset ===")
r = requests.post('http://localhost:8000/api/export', 
                  json={'dataset_id': 1, 'export_type': 'full', 'format': 'parquet'}, 
                  timeout=10)
print(f'Export: status={r.status_code}')
if r.status_code == 200:
    result = r.json()
    print(f'Export result: {json.dumps(result, indent=2)[:500]}')
    
    # Check if export file exists
    import os
    export_dir = Path('exports')
    if export_dir.exists():
        files = list(export_dir.glob('*.parquet'))
        print(f'Export files: {files}')

# Test 4: Snapshot
print("\n=== Test 4: Create snapshot ===")
r = requests.post('http://localhost:8000/api/snapshots', 
                  json={'dataset_id': 1, 'trigger': 'manual'}, 
                  timeout=10)
print(f'Snapshot: status={r.status_code}')
if r.status_code == 200:
    result = r.json()
    print(f'Snapshot result: {json.dumps(result, indent=2)[:500]}')

# Test 5: Recovery
print("\n=== Test 5: Recovery ===")
r = requests.post('http://localhost:8000/api/recovery', 
                  json={'dataset_id': 1}, 
                  timeout=10)
print(f'Recovery: status={r.status_code}')
if r.status_code == 200:
    result = r.json()
    print(f'Recovery result: {json.dumps(result, indent=2)[:500]}')

print("\n=== All tests done ===")