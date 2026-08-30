import requests
import json

# Test health
r = requests.get('http://localhost:8080/api/health')
print('Health:', r.json())

# Test dataset stats
r = requests.get('http://localhost:8080/api/datasets/1/stats')
print('Stats:', r.json())

# Test items
r = requests.get('http://localhost:8080/api/datasets/1/items?page=1&page_size=5')
data = r.json()
print(f'Total items: {data["total"]}')
for item in data['items'][:3]:
    print(f'  {item["id"]}: {item["rel_path"]} ({item["status"]})')

# Test annotations for first item
r = requests.get('http://localhost:8080/api/data-items/1/annotations')
print(f'Annotations for item 1: {len(r.json())}')