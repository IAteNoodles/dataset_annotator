from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import click
import yaml

from backend.config import load_config, AppConfig
from backend.database import Database, create_snapshot, restore_snapshot
from backend.services.scanner import scan_dataset
from backend.recovery.recovery_engine import recover_from_export
from backend.recovery.s3_recovery import recover_from_s3
from backend.recovery.integrity import verify_export, verify_recovery
from backend.exporters.streaming_s3 import S3Exporter


CONFIG_PATH = Path(os.getenv("DATASET_ANNOTATOR_CONFIG", "config/dataset_config.yaml"))
DB_PATH = Path(os.getenv("DATASET_ANNOTATOR_DB", "data/annotator.db"))


@click.group()
def cli():
    """Dataset Annotator CLI"""
    pass


@cli.command()
@click.option("--config", "-c", default=str(CONFIG_PATH), help="Config file path")
def init(config: str):
    """Initialize dataset from config"""
    cfg = load_config(Path(config))
    click.echo(f"Initializing dataset: {cfg.dataset.name}")
    click.echo(f"Plugin: {cfg.dataset.plugin}")
    click.echo(f"Path: {cfg.dataset.path}")

    db = Database(DB_PATH, cfg)
    asyncio.run(db.initialize())
    click.echo("Database initialized")


@cli.command()
@click.option("--config", "-c", default=str(CONFIG_PATH), help="Config file path")
@click.option("--dataset", "-d", help="Dataset name")
def scan(config: str, dataset: str | None):
    """Scan dataset folder for images"""
    cfg = load_config(Path(config))
    if dataset:
        cfg.dataset.name = dataset

    db = Database(DB_PATH, cfg)
    asyncio.run(db.initialize())

    result = asyncio.run(scan_dataset(db, cfg))
    click.echo(f"Scanned: {result['scanned']} files")
    click.echo(f"Inserted: {result['inserted']}")
    click.echo(f"Updated: {result['updated']}")


@cli.command()
@click.option("--config", "-c", default=str(CONFIG_PATH), help="Config file path")
@click.option("--port", "-p", default=8080, help="Port to run on")
def serve(config: str, port: int):
    """Start the annotation server"""
    os.environ["DATASET_ANNOTATOR_CONFIG"] = config
    os.environ["DATASET_ANNOTATOR_DB"] = str(DB_PATH)

    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=port, reload=False)


@cli.group()
def export():
    """Export operations"""
    pass


@export.command("estimate")
@click.option("--config", "-c", default=str(CONFIG_PATH), help="Config file path")
@click.option("--dataset", "-d", help="Dataset name")
@click.option("--type", "-t", type=click.Choice(["full", "incremental"]), default="full")
def export_estimate(config: str, dataset: str | None, type: str):
    """Estimate export size and time"""
    cfg = load_config(Path(config))
    if dataset:
        cfg.dataset.name = dataset

    db = Database(DB_PATH, cfg)
    asyncio.run(db.initialize())

    from backend.services.estimation import estimate_export_size
    result = asyncio.run(estimate_export_size(db, cfg, 1, type))

    click.echo(f"Estimated size: {result.estimated_size_gb:.2f} GB")
    click.echo(f"Estimated time: {result.estimated_time_minutes} minutes")
    click.echo(f"Annotations: {result.annotation_count}")
    click.echo(f"Images: {result.image_count}")
    click.echo(f"Crops: {result.crop_count}")


@export.command("run")
@click.option("--config", "-c", default=str(CONFIG_PATH), help="Config file path")
@click.option("--dataset", "-d", help="Dataset name")
@click.option("--type", "-t", type=click.Choice(["full", "incremental"]), default="full")
@click.option("--push-s3", is_flag=True, help="Push to S3 after export")
@click.option("--formats", "-f", multiple=True, type=click.Choice(["parquet", "arrow"]), default=["parquet"])
def export_run(config: str, dataset: str | None, type: str, push_s3: bool, formats: list[str]):
    """Run export"""
    cfg = load_config(Path(config))
    if dataset:
        cfg.dataset.name = dataset

    db = Database(DB_PATH, cfg)
    asyncio.run(db.initialize())

    if type == "full":
        from backend.services.export_service import run_full_export
        export_id = asyncio.run(run_full_export(db, cfg, 1, push_s3, list(formats)))
    else:
        from backend.services.export_service import run_incremental_export
        export_id = asyncio.run(run_incremental_export(db, cfg, 1, push_s3, list(formats)))

    click.echo(f"Export started: {export_id}")
    click.echo("Check status with: dataset_annotator export status <export_id>")


@export.command("status")
@click.option("--config", "-c", default=str(CONFIG_PATH), help="Config file path")
@click.argument("export_id")
def export_status(config: str, export_id: str):
    """Check export status"""
    from backend.services.export_service import get_export_status
    status = asyncio.run(get_export_status(export_id))
    click.echo(f"Status: {status['status']}")
    click.echo(f"Progress: {status['progress']*100:.1f}%")
    click.echo(f"Step: {status['current_step']}")
    if status['error']:
        click.echo(f"Error: {status['error']}")
    if status['output_paths']:
        click.echo("Outputs:")
        for p in status['output_paths']:
            click.echo(f"  {p}")


@cli.group()
def s3():
    """S3 operations"""
    pass


@s3.command("sync")
@click.option("--config", "-c", default=str(CONFIG_PATH), help="Config file path")
@click.option("--dataset", "-d", help="Dataset name")
@click.option("--fetch/--no-fetch", default=True)
@click.option("--push/--no-push", default=False)
def s3_sync(config: str, dataset: str | None, fetch: bool, push: bool):
    """Sync with S3"""
    cfg = load_config(Path(config))
    if dataset:
        cfg.dataset.name = dataset

    db = Database(DB_PATH, cfg)
    asyncio.run(db.initialize())

    from backend.services.s3_service import S3Service
    s3_service = S3Service(cfg, db)
    result = asyncio.run(s3_service.sync(fetch, push))

    click.echo(f"Synced: {result['synced']}")
    click.echo(f"Fetched: {result['fetched']}")
    click.echo(f"Pushed: {result['pushed']}")
    if result['errors']:
        click.echo("Errors:")
        for e in result['errors']:
            click.echo(f"  {e}")


@s3.command("list")
@click.option("--config", "-c", default=str(CONFIG_PATH), help="Config file path")
@click.option("--dataset", "-d", help="Dataset name")
def s3_list(config: str, dataset: str | None):
    """List S3 objects"""
    cfg = load_config(Path(config))
    if dataset:
        cfg.dataset.name = dataset

    db = Database(DB_PATH, cfg)
    asyncio.run(db.initialize())

    from backend.services.s3_service import S3Service
    s3_service = S3Service(cfg, db)
    objects = asyncio.run(s3_service.list_objects(1))

    for obj in objects:
        click.echo(f"{obj['key']} ({obj['size']} bytes, {obj['last_modified']})")


@cli.group()
def recover():
    """Recovery operations"""
    pass


@recover.command("verify")
@click.option("--config", "-c", default=str(CONFIG_PATH), help="Config file path")
@click.argument("export_path")
def recover_verify(config: str, export_path: str):
    """Verify export integrity"""
    result = asyncio.run(verify_export(export_path))
    click.echo(f"Valid: {result['valid']}")
    if result['errors']:
        click.echo("Errors:")
        for e in result['errors']:
            click.echo(f"  {e}")
    if result['warnings']:
        click.echo("Warnings:")
        for w in result['warnings']:
            click.echo(f"  {w}")


@recover.command("from-export")
@click.option("--config", "-c", default=str(CONFIG_PATH), help="Config file path")
@click.argument("export_path")
@click.argument("target_dir")
def recover_from_export_cmd(config: str, export_path: str, target_dir: str):
    """Recover from local export file"""
    cfg = load_config(Path(config))
    result = asyncio.run(recover_from_export(cfg, export_path, target_dir))
    click.echo(f"Success: {result['success']}")
    click.echo(f"Target: {result['target_dir']}")
    if result['errors']:
        for e in result['errors']:
            click.echo(f"Error: {e}")


@recover.command("from-s3")
@click.option("--config", "-c", default=str(CONFIG_PATH), help="Config file path")
@click.option("--dataset", "-d", help="Dataset name")
@click.option("--bucket", "-b", required=True, help="S3 bucket")
@click.option("--target", "-t", required=True, help="Target directory")
@click.option("--region", "-r", help="S3 region")
def recover_from_s3_cmd(config: str, dataset: str | None, bucket: str, target: str, region: str | None):
    """Recover from S3"""
    cfg = load_config(Path(config))
    if dataset:
        cfg.dataset.name = dataset

    result = asyncio.run(recover_from_s3(cfg, cfg.dataset.name, bucket, target, region))
    click.echo(f"Success: {result['success']}")
    click.echo(f"Target: {result['target_dir']}")
    click.echo(f"Full export: {result['full_export']}")
    click.echo(f"Incrementals applied: {result['incrementals_applied']}")
    if result.get('errors'):
        for e in result['errors']:
            click.echo(f"Error: {e}")


@recover.command("verify-recovery")
@click.option("--config", "-c", default=str(CONFIG_PATH), help="Config file path")
@click.argument("target_dir")
def recover_verify_recovery(config: str, target_dir: str):
    """Verify recovered dataset"""
    result = asyncio.run(verify_recovery(target_dir))
    click.echo(f"Valid: {result['valid']}")
    click.echo(f"Datasets: {result['counts']['datasets']}")
    click.echo(f"Items: {result['counts']['data_items']}")
    click.echo(f"Annotations: {result['counts']['annotations']}")
    click.echo(f"Fields: {result['counts']['fields']}")
    if result['errors']:
        click.echo("Errors:")
        for e in result['errors']:
            click.echo(f"  {e}")
    if result['warnings']:
        click.echo("Warnings:")
        for w in result['warnings']:
            click.echo(f"  {w}")


@cli.group()
def snapshot():
    """Snapshot operations"""
    pass


@snapshot.command("create")
@click.option("--config", "-c", default=str(CONFIG_PATH), help="Config file path")
@click.option("--dataset", "-d", help="Dataset name")
@click.option("--trigger", default="manual", help="Trigger type")
def snapshot_create(config: str, dataset: str | None, trigger: str):
    """Create snapshot"""
    cfg = load_config(Path(config))
    if dataset:
        cfg.dataset.name = dataset

    db = Database(DB_PATH, cfg)
    asyncio.run(db.initialize())

    snap_path = asyncio.run(create_snapshot(db, 1, Path(cfg.snapshot.path), trigger))
    click.echo(f"Snapshot created: {snap_path}")


@snapshot.command("list")
@click.option("--config", "-c", default=str(CONFIG_PATH), help="Config file path")
@click.option("--dataset", "-d", help="Dataset name")
def snapshot_list(config: str, dataset: str | None):
    """List snapshots"""
    cfg = load_config(Path(config))
    if dataset:
        cfg.dataset.name = dataset

    db = Database(DB_PATH, cfg)
    asyncio.run(db.initialize())

    snaps = asyncio.run(db.fetchall(
        "SELECT * FROM snapshots WHERE dataset_id = ? ORDER BY created_at DESC",
        (1,)
    ))

    for snap in snaps:
        click.echo(f"{snap['id']}: {snap['snapshot_path']} ({snap['annotation_count']} ann, {snap['trigger']}, {snap['created_at']})")


@snapshot.command("restore")
@click.option("--config", "-c", default=str(CONFIG_PATH), help="Config file path")
@click.option("--dataset", "-d", help="Dataset name")
@click.option("--id", "-i", "snap_id", required=True, type=int, help="Snapshot ID")
def snapshot_restore(config: str, dataset: str | None, snap_id: int):
    """Restore from snapshot"""
    cfg = load_config(Path(config))
    if dataset:
        cfg.dataset.name = dataset

    db = Database(DB_PATH, cfg)
    asyncio.run(db.initialize())

    asyncio.run(restore_snapshot(db, 1, snap_id))
    click.echo("Snapshot restored")


@snapshot.command("verify")
@click.option("--config", "-c", default=str(CONFIG_PATH), help="Config file path")
@click.option("--dataset", "-d", help="Dataset name")
def snapshot_verify(config: str, dataset: str | None):
    """Verify all snapshots"""
    cfg = load_config(Path(config))
    if dataset:
        cfg.dataset.name = dataset

    db = Database(DB_PATH, cfg)
    asyncio.run(db.initialize())

    snaps = asyncio.run(db.fetchall(
        "SELECT * FROM snapshots WHERE dataset_id = ? ORDER BY created_at DESC",
        (1,)
    ))

    for snap in snaps:
        snap_path = Path(snap['snapshot_path'])
        if snap_path.exists():
            import hashlib
            sha256_hash = hashlib.sha256()
            with open(snap_path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    sha256_hash.update(chunk)
            actual = sha256_hash.hexdigest()
            expected = snap['sha256']
            match = "✓" if actual == expected else "✗"
            click.echo(f"{match} {snap['id']}: {snap_path.name} (expected: {expected[:16]}..., actual: {actual[:16]}...)")
        else:
            click.echo(f"✗ {snap['id']}: {snap_path.name} (FILE MISSING)")


@cli.group()
def import_cmd():
    """Import operations"""
    pass


@import_cmd.command("preview")
@click.option("--config", "-c", default=str(CONFIG_PATH), help="Config file path")
@click.option("--format", "-f", type=click.Choice(["coco", "yolo", "labelme", "custom"]), required=True)
@click.argument("file")
def import_preview(config: str, format: str, file: str):
    """Preview import"""
    file_content = Path(file).read_text()
    from backend.services.import_service import preview_import
    result = asyncio.run(preview_import(format, file_content))

    click.echo(f"Annotations: {result['annotation_count']}")
    click.echo(f"Fields found: {', '.join(result['fields_found'])}")
    if result['warnings']:
        click.echo("Warnings:")
        for w in result['warnings']:
            click.echo(f"  {w}")


@import_cmd.command("run")
@click.option("--config", "-c", default=str(CONFIG_PATH), help="Config file path")
@click.option("--dataset", "-d", help="Dataset name")
@click.option("--format", "-f", type=click.Choice(["coco", "yolo", "labelme", "custom"]), required=True)
@click.option("--mapping", "-m", multiple=True, help="Field mapping: source=target")
@click.argument("file")
def import_run(config: str, dataset: str | None, format: str, mapping: list[str], file: str):
    """Execute import"""
    cfg = load_config(Path(config))
    if dataset:
        cfg.dataset.name = dataset

    db = Database(DB_PATH, cfg)
    asyncio.run(db.initialize())

    field_mapping = {}
    for m in mapping:
        if "=" in m:
            src, dst = m.split("=", 1)
            field_mapping[src] = dst

    file_content = Path(file).read_text()
    from backend.services.import_service import execute_import
    result = asyncio.run(execute_import(db, cfg, 1, format, file_content, field_mapping))

    click.echo(f"Imported: {result['imported']}")
    click.echo(f"Skipped: {result['skipped']}")
    if result['errors']:
        click.echo("Errors:")
        for e in result['errors']:
            click.echo(f"  {e}")


if __name__ == "__main__":
    cli()