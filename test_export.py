import requests
import json

# Test export estimation
r = requests.post('http://localhost:8080/api/export/estimate', json={'dataset_id': 1, 'type': 'full'})
print('Export estimate:', r.json())

# Test full export
r = requests.post('http://localhost:8080/api/export/full', json={'dataset_id': 1, 'type': 'full', 'push_s3': False, 'formats': ['parquet']})
print('Export started:', r.json())
export_id = r.json()['export_id']

# Check export status
import time
for i in range(10):
    time.sleep(2)
    r = requests.get(f'http://localhost:8080/api/export/status/{export_id}')
    status = r.json()
    print(f'Export status: {status["status"]} - {status["progress"]*100:.0f}% - {status["current_step"]}')
    if status['status'] in ['completed', 'failed']:
        break

print('Final status:', status)