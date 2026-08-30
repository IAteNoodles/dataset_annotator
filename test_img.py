import asyncio
from pathlib import Path
from backend.database import Database
from backend.config import load_config

cfg = load_config(Path('config/dataset_config.yaml'))
db = Database(Path('data/annotator.db'), cfg)

async def test():
    await db.initialize()
    item = await db.fetchone('SELECT * FROM data_items WHERE id = 1')
    print(f'Item: {item}')
    if item:
        import os
        print(f'rel_path: {item["rel_path"]}')
        print(f'source_path: {item["source_path"]}')
        print(f'Exists (rel): {Path(item["rel_path"]).exists()}')
        print(f'Exists (source): {Path(item["source_path"]).exists()}')
        
        # Check config path
        base = Path(cfg.dataset.path)
        full = base / item["rel_path"]
        print(f'Full path: {full}')
        print(f'Exists full: {full.exists()}')
    
    await db.close()

asyncio.run(test())