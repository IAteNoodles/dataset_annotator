import asyncio
from pathlib import Path
from backend.database import Database
from backend.config import load_config

cfg = load_config(Path('config/dataset_config.yaml'))
db = Database(Path('data/annotator.db'), cfg)

async def test():
    await db.initialize()
    print('DB initialized OK')
    version = await db.fetchval('SELECT version FROM schema_version')
    print(f'Schema version: {version}')
    
    # List tables
    tables = await db.fetchall('SELECT name FROM sqlite_master WHERE type="table"')
    print(f'Tables: {tables}')
    
    # Count data_items
    count = await db.fetchval('SELECT COUNT(*) FROM data_items')
    print(f'Data items: {count}')
    
    await db.close()

asyncio.run(test())