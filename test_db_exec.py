import asyncio
from pathlib import Path
from backend.database import Database
from backend.config import load_config

cfg = load_config(Path('config/dataset_config.yaml'))
db = Database(Path('data/annotator.db'), cfg)

async def test():
    await db.initialize()
    
    # Test execute returning cursor
    cursor = await db.execute_returning('INSERT INTO test_table (name) VALUES (?)', ('test',))
    print(f'execute_returning cursor: {cursor}')
    if cursor:
        print(f'lastrowid: {cursor.lastrowid}')
    
    # Test regular execute
    result = await db.execute('INSERT INTO test_table (name) VALUES (?)', ('test2',))
    print(f'execute result: {result}')
    
    # Cleanup
    await db.execute('DELETE FROM test_table WHERE name = ?', ('test',))
    await db.execute('DELETE FROM test_table WHERE name = ?', ('test2',))
    
    await db.close()

asyncio.run(test())