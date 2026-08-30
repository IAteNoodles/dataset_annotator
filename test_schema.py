import asyncio
from pathlib import Path
from backend.database import Database
from backend.config import load_config

cfg = load_config(Path('config/dataset_config.yaml'))
db = Database(Path('data/annotator.db'), cfg)

async def test():
    await db.initialize()
    
    # Check datasets table schema
    schema = await db.fetchall('SELECT sql FROM sqlite_master WHERE type="table" AND name="datasets"')
    print(f'Datasets schema: {schema}')
    
    # Check if dataset already exists
    existing = await db.fetchone('SELECT * FROM datasets WHERE name = ?', ('Prescription_Dataset(600)',))
    print(f'Existing dataset: {existing}')
    
    await db.close()

asyncio.run(test())