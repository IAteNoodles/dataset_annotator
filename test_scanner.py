import asyncio
from backend.config import load_config
from backend.database import Database
from backend.services.scanner import scan_dataset
from backend.plugins import init_plugins
from pathlib import Path

async def test():
    config = load_config(Path('config/dataset_config.yaml'))
    init_plugins(config)
    db = Database(Path('data/annotator.db'), config)
    await db.initialize()
    print('Database initialized successfully')
    
    # Test scanner (will just check path exists)
    result = await scan_dataset(db, config)
    print(f'Scan result: {result}')

asyncio.run(test())