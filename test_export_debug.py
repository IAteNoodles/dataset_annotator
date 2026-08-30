import asyncio
from backend.config import load_config
from backend.database import Database
from backend.plugins import init_plugins
from backend.exporters.parquet_exporter import ParquetExporter
from backend.recovery.integrity import verify_export
from pathlib import Path

async def test():
    config = load_config(Path('config/dataset_config.yaml'))
    init_plugins(config)
    db = Database(Path('data/annotator.db'), config)
    await db.initialize()
    
    # Test parquet export
    exporter = ParquetExporter(db, config)
    output_dir = Path(config.export.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"test_export_{int(asyncio.get_event_loop().time())}"
    
    print("Exporting...")
    result = await exporter.export_full(1, output_path, ['parquet'])
    print(f"Export result: {result}")
    
    print("Verifying...")
    try:
        await verify_export(result["parquet"])
        print("Verification passed!")
    except Exception as e:
        print(f"Verification failed: {e}")
        import traceback
        traceback.print_exc()

asyncio.run(test())