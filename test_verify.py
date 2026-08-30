import asyncio
from backend.config import load_config
from backend.database import Database
from backend.plugins import init_plugins
from pathlib import Path

async def test():
    config = load_config(Path('config/dataset_config.yaml'))
    init_plugins(config)
    db = Database(Path('data/annotator.db'), config)
    await db.initialize()
    
    items = await db.fetchall('SELECT id, rel_path, status FROM data_items LIMIT 5')
    for item in items:
        print(f'  {item["id"]}: {item["rel_path"]} ({item["status"]})')
    
    count = await db.fetchval('SELECT COUNT(*) FROM data_items')
    print(f'Total items: {count}')

asyncio.run(test())