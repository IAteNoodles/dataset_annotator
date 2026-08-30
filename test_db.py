import asyncio
from backend.config import load_config
from backend.database import Database
from pathlib import Path

async def test():
    config = load_config(Path('config/dataset_config.yaml'))
    db = Database(Path('data/annotator.db'), config)
    await db.initialize()
    print('Database initialized successfully')
    
    # Check tables
    tables = await db.fetchall("SELECT name FROM sqlite_master WHERE type='table'")
    for t in tables:
        print(f'  Table: {t["name"]}')

asyncio.run(test())