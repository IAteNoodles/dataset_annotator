import asyncio
from pathlib import Path
from backend.database import Database
from backend.config import load_config

cfg = load_config(Path('config/dataset_config.yaml'))
db = Database(Path('data/annotator.db'), cfg)

async def test():
    await db.initialize()
    anns = await db.fetchall('SELECT * FROM annotations WHERE data_item_id = 1')
    for ann in anns:
        fields = await db.fetchall('SELECT * FROM annotation_fields WHERE annotation_id = ?', (ann['id'],))
        print(f'Annotation {ann["id"]}: type={ann["annotation_type"]}, fields={len(fields)}')
        for f in fields:
            print(f'  Field: {f}')
    await db.close()

asyncio.run(test())