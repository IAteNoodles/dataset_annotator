from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from backend.config import AppConfig
from backend.database import Database
from backend.plugins import plugin_registry


class RecoveryEngine:
    def __init__(self, config: AppConfig):
        self.config = config
        self.plugin = plugin_registry.get_for_dataset(config)

    async def recover_from_export(self, export_path: Path, target_dir: Path) -> dict[str, Any]:
        target_dir = Path(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        await self._verify_export_integrity(export_path)

        db_path = target_dir / "annotator.db"
        await self._initialize_database(db_path)

        db = Database(db_path, self.config)
        await db.initialize()

        await self._restore_config(db, export_path, target_dir)
        await self._restore_data(db, export_path, target_dir)

        await db.close()

        return {
            "success": True,
            "target_dir": str(target_dir),
            "db_path": str(db_path),
        }

    async def _verify_export_integrity(self, export_path: Path) -> None:
        manifest_path = export_path.with_suffix(".manifest.json")
        if not manifest_path.exists():
            raise FileNotFoundError(f"Manifest not found: {manifest_path}")

        from backend.exporters.manifest import verify_manifest
        valid, errors = verify_manifest(manifest_path)
        if not valid:
            raise ValueError(f"Manifest verification failed: {errors}")

        pf = pq.ParquetFile(export_path)
        expected_rows = pf.metadata.num_rows

        actual_rows = 0
        for batch in pf.iter_batches(batch_size=10000):
            actual_rows += batch.num_rows

        if actual_rows != expected_rows:
            raise ValueError(f"Row count mismatch: expected {expected_rows}, got {actual_rows}")

    async def _initialize_database(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)

        import sqlite3
        conn = sqlite3.connect(str(db_path))
        from backend.database import SCHEMA
        conn.executescript(SCHEMA)
        conn.commit()
        conn.close()

    async def _restore_config(self, db: Database, export_path: Path, target_dir: Path) -> None:
        manifest_path = export_path.with_suffix(".manifest.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        config_json = manifest["config_json"]
        config_hash = manifest["config_hash"]

        cursor = await db.execute_returning(
            """INSERT OR REPLACE INTO datasets (id, name, plugin_type, config_hash, config_json)
               VALUES (?, ?, ?, ?, ?)""",
            (
                None,
                manifest["dataset_name"],
                manifest["plugin"]["type"],
                config_hash,
                config_json,
            )
        )
        dataset_id = cursor.lastrowid

        config_path = target_dir / "dataset_config.yaml"
        import yaml
        config_path.write_text(yaml.dump(json.loads(config_json), default_flow_style=False))

        return dataset_id

    async def _restore_data(self, db: Database, export_path: Path, target_dir: Path) -> None:
        dataset_id = await db.fetchval("SELECT id FROM datasets WHERE name = ?", (self.config.dataset.name,))

        pf = pq.ParquetFile(export_path)
        dataset_path = Path(self.config.dataset.path)

        for batch in pf.iter_batches(batch_size=5000):
            await self._restore_batch(db, dataset_id, batch, target_dir, dataset_path)

        await self._rebuild_field_categories(db, dataset_id)

    async def _restore_batch(
        self,
        db: Database,
        dataset_id: int,
        batch: pa.RecordBatch,
        target_dir: Path,
        dataset_path: Path,
    ) -> None:
        import asyncio

        items_to_insert = {}
        annotations_to_insert = {}
        fields_to_insert = {}

        for i in range(batch.num_rows):
            row = {col: batch[col][i].as_py() for col in batch.schema.names}

            item_key = row["item_id"]
            if item_key not in items_to_insert:
                items_to_insert[item_key] = {
                    "dataset_id": dataset_id,
                    "source_path": row["item_abs_path"],
                    "rel_path": row["item_rel_path"],
                    "mime_type": row["item_mime_type"],
                    "size_bytes": row["item_size_bytes"],
                    "sha256": row["item_sha256"],
                    "width": row["item_width"],
                    "height": row["item_height"],
                    "metadata_json": row["item_metadata_json"],
                    "status": "pending",
                    "sort_order": 0,
                }

                if row["source_image_base64"]:
                    await self._write_base64_image(row["source_image_base64"], dataset_path / row["item_rel_path"])

            ann_key = row["annotation_id"]
            if ann_key not in annotations_to_insert:
                annotations_to_insert[ann_key] = {
                    "data_item_id": row["item_id"],
                    "annotation_type": row["annotation_type"],
                    "geometry_json": row["geometry_json"],
                    "crop_path": row["crop_path"],
                    "parent_annotation_id": row["parent_annotation_id"],
                    "is_locked": row["is_locked"],
                    "annotation_order": row["annotation_order"],
                    "created_at": row["ann_created_at"],
                    "updated_at": row["ann_updated_at"],
                }

                if row["crop_image_base64"] and row["crop_path"]:
                    await self._write_base64_image(row["crop_image_base64"], dataset_path / row["crop_path"])

            for col in batch.schema.names:
                if col.startswith("field_") and row[col] is not None:
                    field_name = col[6:]
                    if ann_key not in fields_to_insert:
                        fields_to_insert[ann_key] = {}
                    fields_to_insert[ann_key][field_name] = {
                        "value": row[col],
                        "datatype": self._infer_datatype(row[col]),
                        "config": json.loads(row["field_configs_json"]).get(field_name, {}) if row["field_configs_json"] else {},
                    }

        for item_data in items_to_insert.values():
            await db.execute(
                """INSERT INTO data_items
                    (dataset_id, source_path, rel_path, mime_type, size_bytes, sha256,
                     width, height, duration_ms, metadata_json, status, sort_order)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item_data["dataset_id"],
                    item_data["source_path"],
                    item_data["rel_path"],
                    item_data["mime_type"],
                    item_data["size_bytes"],
                    item_data["sha256"],
                    item_data["width"],
                    item_data["height"],
                    None,
                    item_data["metadata_json"],
                    item_data["status"],
                    item_data["sort_order"],
                )
            )

        for ann_data in annotations_to_insert.values():
            await db.execute(
                """INSERT INTO annotations
                    (data_item_id, annotation_type, geometry_json, crop_path,
                     parent_annotation_id, is_locked, annotation_order, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    ann_data["data_item_id"],
                    ann_data["annotation_type"],
                    ann_data["geometry_json"],
                    ann_data["crop_path"],
                    ann_data["parent_annotation_id"],
                    ann_data["is_locked"],
                    ann_data["annotation_order"],
                    ann_data["ann_created_at"],
                    ann_data["ann_updated_at"],
                )
            )

        for ann_id, field_dict in fields_to_insert.items():
            for field_name, field_data in field_dict.items():
                await db.execute(
                    """INSERT INTO annotation_fields
                        (annotation_id, field_name, field_value, datatype, field_config_json)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        ann_id,
                        field_name,
                        field_data["value"],
                        field_data["datatype"],
                        json.dumps(field_data["config"]),
                    )
                )

    async def _write_base64_image(self, b64_data: str, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        img_data = base64.b64decode(b64_data)
        output_path.write_bytes(img_data)

    def _infer_datatype(self, value: Any) -> str:
        if isinstance(value, bool):
            return "boolean"
        elif isinstance(value, int):
            return "number"
        elif isinstance(value, float):
            return "number"
        elif isinstance(value, dict) or isinstance(value, list):
            return "json"
        return "string"

    async def _rebuild_field_categories(self, db: Database, dataset_id: int) -> None:
        rows = await db.fetchall(
            "SELECT field_name, field_value FROM annotation_fields af "
            "JOIN annotations a ON af.annotation_id = a.id "
            "JOIN data_items di ON a.data_item_id = di.id "
            "WHERE di.dataset_id = ? AND af.datatype = 'enum'",
            (dataset_id,)
        )

        for row in rows:
            value = row["field_value"]
            if value:
                normalized = value.lower()
                await db.execute(
                    """INSERT INTO field_categories (dataset_id, field_name, category_value, normalized_value, source)
                       VALUES (?, ?, ?, ?, 'recovered')
                       ON CONFLICT(dataset_id, field_name, normalized_value) DO UPDATE SET
                           count = count + 1""",
                    (dataset_id, row["field_name"], value, normalized)
                )


async def recover_from_export(config: AppConfig, export_path: str, target_dir: str) -> dict[str, Any]:
    engine = RecoveryEngine(config)
    return await engine.recover_from_export(Path(export_path), Path(target_dir))