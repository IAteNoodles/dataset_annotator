from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from backend.config import AppConfig
from backend.exporters.streaming_s3 import S3Exporter
from backend.recovery.recovery_engine import RecoveryEngine
from backend.ws.manager import broadcast_s3_sync_progress


async def recover_from_s3(
    config: AppConfig,
    dataset_name: str,
    bucket: str,
    target_dir: str,
    region: str | None = None,
) -> dict[str, Any]:
    target_path = Path(target_dir)
    target_path.mkdir(parents=True, exist_ok=True)

    exporter = S3Exporter(config, None)
    exporter.bucket = bucket
    if region:
        exporter.s3.meta.region_name = region

    await broadcast_s3_sync_progress(0, "recovery", 0.1, "Discovering exports in S3")

    exports = await exporter.list_objects(0, f"{dataset_name}/exports/")

    full_exports = [e for e in exports if "full" in e["key"] and e["key"].endswith(".parquet")]
    incremental_exports = [e for e in exports if "incremental" in e["key"] and e["key"].endswith(".parquet")]

    if not full_exports:
        raise ValueError("No full export found in S3")

    full_exports.sort(key=lambda x: x["last_modified"], reverse=True)
    latest_full = full_exports[0]

    incremental_exports.sort(key=lambda x: x["last_modified"])
    relevant_incrementals = [
        e for e in incremental_exports
        if e["last_modified"] > latest_full["last_modified"]
    ]

    await broadcast_s3_sync_progress(0, "recovery", 0.3, f"Downloading full export: {latest_full['key']}")

    full_local = target_path / "full_export.parquet"
    await exporter.download_file(latest_full["key"], full_local)

    await broadcast_s3_sync_progress(0, "recovery", 0.5, "Downloading incrementals")

    for inc in relevant_incrementals:
        inc_local = target_path / f"incremental_{inc['key'].split('/')[-1]}"
        await exporter.download_file(inc["key"], inc_local)

    await broadcast_s3_sync_progress(0, "recovery", 0.7, "Reconstructing database from full export")

    engine = RecoveryEngine(config)
    await engine.recover_from_export(full_local, target_path)

    await broadcast_s3_sync_progress(0, "recovery", 0.85, "Applying incremental exports")

    for inc in relevant_incrementals:
        inc_local = target_path / f"incremental_{inc['key'].split('/')[-1]}"
        await _apply_incremental(config, target_path, inc_local)

    await broadcast_s3_sync_progress(0, "recovery", 0.95, "Verifying recovery")

    from backend.recovery.integrity import verify_recovery
    await verify_recovery(target_dir)

    await broadcast_s3_sync_progress(0, "recovery", 1.0, "Recovery complete")

    return {
        "success": True,
        "target_dir": target_dir,
        "full_export": latest_full["key"],
        "incrementals_applied": len(relevant_incrementals),
    }


async def _apply_incremental(config: AppConfig, target_dir: Path, incremental_path: Path) -> None:
    import pyarrow.parquet as pq
    from backend.database import Database

    db_path = target_dir / "annotator.db"
    db = Database(db_path, config)
    await db.initialize()

    pf = pq.ParquetFile(incremental_path)

    for batch in pf.iter_batches(batch_size=5000):
        await _restore_incremental_batch(db, batch, target_dir)

    await db.close()


async def _restore_incremental_batch(db: Database, batch, target_dir: Path) -> None:
    for i in range(batch.num_rows):
        row = {col: batch[col][i].as_py() for col in batch.schema.names}

        ann_id = row["annotation_id"]
        existing = await db.fetchone("SELECT id FROM annotations WHERE id = ?", (ann_id,))

        if existing:
            await db.execute(
                """UPDATE annotations SET
                    annotation_type = ?, geometry_json = ?, crop_path = ?,
                    parent_annotation_id = ?, is_locked = ?, annotation_order = ?,
                    updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (
                    row["annotation_type"],
                    row["geometry_json"],
                    row["crop_path"],
                    row["parent_annotation_id"],
                    row["is_locked"],
                    row["annotation_order"],
                    ann_id,
                )
            )
        else:
            await db.execute(
                """INSERT INTO annotations
                    (id, data_item_id, annotation_type, geometry_json, crop_path,
                     parent_annotation_id, is_locked, annotation_order, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    ann_id,
                    row["item_id"],
                    row["annotation_type"],
                    row["geometry_json"],
                    row["crop_path"],
                    row["parent_annotation_id"],
                    row["is_locked"],
                    row["annotation_order"],
                    row["ann_created_at"],
                    row["ann_updated_at"],
                )
            )

        for col in batch.schema.names:
            if col.startswith("field_") and row[col] is not None:
                field_name = col[6:]
                await db.execute(
                    """INSERT INTO annotation_fields (annotation_id, field_name, field_value, datatype, field_config_json)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(annotation_id, field_name) DO UPDATE SET
                           field_value = excluded.field_value,
                           datatype = excluded.datatype,
                           field_config_json = excluded.field_config_json,
                           updated_at = CURRENT_TIMESTAMP""",
                    (
                        ann_id,
                        field_name,
                        row[col],
                        "string",
                        row["field_configs_json"] or "{}",
                    )
                )

        if row["crop_image_base64"] and row["crop_path"]:
            import base64
            dataset_path = Path(config.dataset.path)
            crop_full = dataset_path / row["crop_path"]
            crop_full.parent.mkdir(parents=True, exist_ok=True)
            crop_full.write_bytes(base64.b64decode(row["crop_image_base64"]))