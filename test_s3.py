import requests
import json

# Test S3 test-connection
r = requests.post('http://localhost:8080/api/s3/test-connection', json={
    'config': {
        'enabled': True,
        'bucket': 'test-bucket',
        'region': 'us-east-1',
        'prefix': 'datasets/',
        'multipart_threshold_mb': 100,
        'multipart_chunksize_mb': 50,
        'fetch_on_startup': False,
        'fetch': {'exports': True, 'snapshots': True, 'cursor': True, 'verify_checksums': True},
        'push': {'exports': True, 'snapshots': True, 'cursor': True, 'overwrite': False},
        'max_bandwidth_mbps': 0,
        'access_key_id': 'test',
        'secret_access_key': 'test',
        'endpoint_url': 'http://localhost:9000'
    }
})
print('Test connection:', r.json())

# Test create bucket
r = requests.post('http://localhost:8080/api/s3/create-bucket', json={
    'config': {
        'enabled': True,
        'bucket': 'test-annotator-bucket',
        'region': 'us-east-1',
        'prefix': 'datasets/',
        'multipart_threshold_mb': 100,
        'multipart_chunksize_mb': 50,
        'fetch_on_startup': False,
        'fetch': {'exports': True, 'snapshots': True, 'cursor': True, 'verify_checksums': True},
        'push': {'exports': True, 'snapshots': True, 'cursor': True, 'overwrite': False},
        'max_bandwidth_mbps': 0,
        'access_key_id': 'test',
        'secret_access_key': 'test',
        'endpoint_url': 'http://localhost:9000'
    }
})
print('Create bucket:', r.json())