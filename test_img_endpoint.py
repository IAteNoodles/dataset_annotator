import requests
try:
    r = requests.get('http://localhost:8080/api/images/1', timeout=5)
    print(f'Status: {r.status_code}')
    print(f'Content-Type: {r.headers.get("Content-Type")}')
    print(f'Content-Length: {len(r.content)}')
except Exception as e:
    print(f'Error: {e}')