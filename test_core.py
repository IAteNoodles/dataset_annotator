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
    
    # Test config hash
    print(f'Config hash: {config.compute_hash()[:16]}...')
    
    # Test plugin registry
    from backend.plugins import plugin_registry
    plugin = plugin_registry.get_for_dataset(config)
    print(f'Plugin: {plugin.name}')
    
    # Test schema version
    version = await db.fetchval("SELECT version FROM schema_version")
    print(f'Schema version: {version}')

asyncio.run(test())