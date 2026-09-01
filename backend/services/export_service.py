from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.config import AppConfig
from backend.database import Database
from backend.exporters.parquet_exporter import ParquetExporter
from backend.exporters.manifest import create_manifest, write_manifest
from backend.exporters.streaming_s3 import S3Exporter
from backend.ws.manager import broadcast_export_progress


_export_status: dict[str, dict[str, Any]] = {}


async def run_full_export(
    db: Database,
    config: AppConfig,
    dataset_id: int,
    push_s3: bool,
    formats: list[str],
    export_mode: str = "annotated",
    verify_images: bool = False,
) -> str:
    export_id = str(uuid.uuid4())[:8]
    _export_status[export_id] = {
        "export_id": export_id,
        "status": "running",
        "progress": 0.0,
        "current_step": "initializing",
        "records_processed": 0,
        "total_records": 0,
        "error": None,
        "output_paths": [],
        "push_s3": push_s3,
    }

    asyncio.create_task(_run_full_export_task(db, config, dataset_id, export_id, push_s3, formats, export_mode, verify_images))
    return export_id


async def _run_full_export_task(
    db: Database,
    config: AppConfig,
    dataset_id: int,
    export_id: str,
    push_s3: bool,
    formats: list[str],
    export_mode: str = "annotated",
    verify_images: bool = False,
):
    try:
        await _update_export_status(export_id, progress=0.1, current_step="fetching data")

        parquet_exporter = ParquetExporter(db, config)
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        dataset_name = config.dataset.name
        output_dir = Path(config.export.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        base_filename = f"{dataset_name}_{timestamp}"
        output_path = output_dir / base_filename

        await _update_export_status(export_id, progress=0.2, current_step="exporting to parquet")

        result = await parquet_exporter.export_full(dataset_id, output_path, formats, export_mode=export_mode, verify_images=verify_images)

        report_path = None
        if verify_images and "parquet" in result:
            report_path = await parquet_exporter.verify_exported_images(Path(result["parquet"]))

        await _update_export_status(export_id, progress=0.6, current_step="creating manifest")

        manifest = create_manifest(
            dataset_name=dataset_name,
            config=config.model_dump(mode="json"),
            config_hash=config.compute_hash(),
            parquet_path=Path(result["parquet"]),
            export_type="full",
        )
        manifest_path = Path(result["parquet"]).with_suffix(".manifest.json")
        write_manifest(manifest, manifest_path)

        if config.export.verify_after_write:
            await _update_export_status(export_id, progress=0.8, current_step="verifying export")
            from backend.recovery.integrity import verify_export
            await verify_export(result["parquet"])

        await db.execute(
            """INSERT INTO exports (dataset_id, format, output_path, record_count, config_snapshot_json, sha256, size_bytes)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                dataset_id,
                "parquet",
                result["parquet"],
                manifest["counts"]["total_rows"],
                manifest["config_json"],
                manifest["integrity"]["parquet_sha256"],
                manifest["integrity"]["parquet_size_bytes"],
            )
        )

        cursor = await db.fetchone(
            "SELECT MAX(a.id) as max_id FROM annotations a JOIN data_items di ON a.data_item_id = di.id WHERE di.dataset_id = ?",
            (dataset_id,)
        )
        max_ann_id = cursor["max_id"] if cursor else 0

        await db.execute(
            """INSERT INTO export_cursors (dataset_id, export_type, last_exported_annotation_id, s3_export_path, s3_manifest_path, status, records_exported)
               VALUES (?, 'full', ?, ?, ?, 'completed', ?)""",
            (dataset_id, max_ann_id, "", "", manifest["counts"]["total_rows"])
        )

        output_paths = list(result.values()) + [str(manifest_path)]
        if report_path:
            output_paths.append(str(report_path))

        if push_s3 and config.s3 and config.s3.enabled:
            await _update_export_status(export_id, progress=0.9, current_step="uploading to s3")
            s3_exporter = S3Exporter(config, db)

            for local_path_str in output_paths:
                local_path = Path(local_path_str)
                s3_key = f"{config.s3.prefix}{dataset_name}/exports/full/{local_path.name}"
                await s3_exporter.upload_file(local_path, s3_key)

                await db.execute(
                    """UPDATE export_cursors SET s3_export_path = ?, s3_manifest_path = ?
                       WHERE id = (
                           SELECT id FROM export_cursors
                           WHERE dataset_id = ? AND export_type = 'full'
                           ORDER BY created_at DESC LIMIT 1
                       )""",
                    (s3_key, f"{s3_key}.manifest.json", dataset_id)
                )

        await _update_export_status(
            export_id,
            progress=1.0,
            current_step="completed",
            status="completed",
            output_paths=output_paths,
        )

    except Exception as e:
        await _update_export_status(export_id, status="failed", error=str(e))
        raise


async def run_incremental_export(
    db: Database,
    config: AppConfig,
    dataset_id: int,
    push_s3: bool,
    formats: list[str],
    export_mode: str = "annotated",
    verify_images: bool = False,
) -> str:
    export_id = str(uuid.uuid4())[:8]
    _export_status[export_id] = {
        "export_id": export_id,
        "status": "running",
        "progress": 0.0,
        "current_step": "initializing",
        "records_processed": 0,
        "total_records": 0,
        "error": None,
        "output_paths": [],
        "push_s3": push_s3,
    }

    asyncio.create_task(_run_incremental_export_task(db, config, dataset_id, export_id, push_s3, formats, export_mode, verify_images))
    return export_id


async def _run_incremental_export_task(
    db: Database,
    config: AppConfig,
    dataset_id: int,
    export_id: str,
    push_s3: bool,
    formats: list[str],
    export_mode: str = "annotated",
    verify_images: bool = False,
):
    try:
        await _update_export_status(export_id, progress=0.1, current_step="fetching cursor")

        cursor = await db.fetchone(
            "SELECT last_exported_annotation_id FROM export_cursors WHERE dataset_id = ? AND export_type = 'incremental' ORDER BY created_at DESC LIMIT 1",
            (dataset_id,)
        )
        since_id = cursor["last_exported_annotation_id"] if cursor else 0

        await _update_export_status(export_id, progress=0.2, current_step="exporting incremental data")

        parquet_exporter = ParquetExporter(db, config)
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        dataset_name = config.dataset.name
        output_dir = Path(config.export.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        from_timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        base_filename = f"{dataset_name}_inc_{since_id}_{timestamp}"
        output_path = output_dir / base_filename

        result = await parquet_exporter.export_incremental(dataset_id, output_path, since_id, formats, export_mode=export_mode, verify_images=verify_images)

        report_path = None
        if verify_images and "parquet" in result:
            report_path = await parquet_exporter.verify_exported_images(Path(result["parquet"]))

        await _update_export_status(export_id, progress=0.6, current_step="creating manifest")

        manifest = create_manifest(
            dataset_name=dataset_name,
            config=config.model_dump(mode="json"),
            config_hash=config.compute_hash(),
            parquet_path=Path(result["parquet"]),
            export_type="incremental",
            since_timestamp=datetime.utcfromtimestamp(since_id / 1000).isoformat() if since_id else None,
        )
        manifest_path = Path(result["parquet"]).with_suffix(".manifest.json")
        write_manifest(manifest, manifest_path)

        if config.export.verify_after_write:
            await _update_export_status(export_id, progress=0.8, current_step="verifying export")
            from backend.recovery.integrity import verify_export
            await verify_export(result["parquet"])

        await db.execute(
            """INSERT INTO exports (dataset_id, format, output_path, record_count, config_snapshot_json, sha256, size_bytes)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                dataset_id,
                "parquet",
                result["parquet"],
                manifest["counts"]["total_rows"],
                manifest["config_json"],
                manifest["integrity"]["parquet_sha256"],
                manifest["integrity"]["parquet_size_bytes"],
            )
        )

        new_cursor = await db.fetchone(
            "SELECT MAX(id) as max_id FROM annotations a JOIN data_items di ON a.data_item_id = di.id WHERE di.dataset_id = ? AND a.id > ?",
            (dataset_id, since_id)
        )
        new_max_id = new_cursor["max_id"] if new_cursor else since_id

        await db.execute(
            """INSERT INTO export_cursors (dataset_id, export_type, last_exported_annotation_id, s3_export_path, s3_manifest_path, status, records_exported)
               VALUES (?, 'incremental', ?, ?, ?, 'completed', ?)""",
            (dataset_id, new_max_id, "", "", manifest["counts"]["total_rows"])
        )

        output_paths = list(result.values()) + [str(manifest_path)]
        if report_path:
            output_paths.append(str(report_path))

        if push_s3 and config.s3 and config.s3.enabled:
            await _update_export_status(export_id, progress=0.9, current_step="uploading to s3")
            s3_exporter = S3Exporter(config, db)

            for local_path_str in output_paths:
                local_path = Path(local_path_str)
                s3_key = f"{config.s3.prefix}{dataset_name}/exports/incremental/{local_path.name}"
                await s3_exporter.upload_file(local_path, s3_key)

        await _update_export_status(
            export_id,
            progress=1.0,
            current_step="completed",
            status="completed",
            output_paths=output_paths,
        )

    except Exception as e:
        await _update_export_status(export_id, status="failed", error=str(e))
        raise


async def get_export_status(export_id: str) -> dict[str, Any]:
    if export_id not in _export_status:
        return {
            "export_id": export_id,
            "status": "not_found",
            "progress": 0.0,
            "current_step": "",
            "records_processed": 0,
            "total_records": 0,
            "error": "Export not found",
            "output_paths": [],
        }
    return _export_status[export_id]


async def _update_export_status(
    export_id: str,
    progress: float | None = None,
    current_step: str | None = None,
    status: str | None = None,
    error: str | None = None,
    output_paths: list[str] | None = None,
):
    if export_id in _export_status:
        if progress is not None:
            _export_status[export_id]["progress"] = progress
        if current_step is not None:
            _export_status[export_id]["current_step"] = current_step
        if status is not None:
            _export_status[export_id]["status"] = status
        if error is not None:
            _export_status[export_id]["error"] = error
        if output_paths is not None:
            _export_status[export_id]["output_paths"] = output_paths

        await broadcast_export_progress(
            export_id,
            _export_status[export_id]["progress"],
            _export_status[export_id]["current_step"],
            _export_status[export_id]["records_processed"],
            _export_status[export_id]["total_records"],
        )