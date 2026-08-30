from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pyarrow.compute as pc

from backend.config import AppConfig
from backend.database import Database
from backend.plugins import plugin_registry


class ParquetExporter:
    def __init__(self, db: Database, config: AppConfig):
        self.db = db
        self.config = config
        self.plugin = plugin_registry.get_for_dataset(config)

    async def export_full(
        self,
        dataset_id: int,
        output_path: Path,
        formats: list[str],
    ) -> dict[str, Any]:
        rows = await self._fetch_export_rows(dataset_id)
        table = self._rows_to_arrow_table(rows, dataset_id)

        results = {}
        if "parquet" in formats:
            parquet_path = output_path.with_suffix(".parquet")
            await self._write_parquet(table, parquet_path)
            results["parquet"] = str(parquet_path)

        if "arrow" in formats:
            arrow_path = output_path.with_suffix(".arrow")
            await self._write_arrow(table, arrow_path)
            results["arrow"] = str(arrow_path)

        return results

    async def export_incremental(
        self,
        dataset_id: int,
        output_path: Path,
        since_annotation_id: int,
        formats: list[str],
    ) -> dict[str, Any]:
        rows = await self._fetch_incremental_rows(dataset_id, since_annotation_id)
        table = self._rows_to_arrow_table(rows, dataset_id)

        results = {}
        if "parquet" in formats:
            parquet_path = output_path.with_suffix(".parquet")
            await self._write_parquet(table, parquet_path)
            results["parquet"] = str(parquet_path)

        if "arrow" in formats:
            arrow_path = output_path.with_suffix(".arrow")
            await self._write_arrow(table, arrow_path)
            results["arrow"] = str(arrow_path)

        return results

    async def _fetch_export_rows(self, dataset_id: int) -> list[dict]:
        query = """
            SELECT 
                d.name as dataset_name,
                d.config_hash as dataset_config_hash,
                di.id as item_id,
                di.rel_path as item_rel_path,
                di.source_path as item_abs_path,
                di.mime_type as item_mime_type,
                di.size_bytes as item_size_bytes,
                di.sha256 as item_sha256,
                di.width as item_width,
                di.height as item_height,
                di.metadata_json as item_metadata_json,
                a.id as annotation_id,
                a.annotation_type,
                a.geometry_json,
                a.crop_path,
                a.parent_annotation_id,
                a.is_locked,
                a.annotation_order,
                a.created_at as ann_created_at,
                a.updated_at as ann_updated_at,
                af.field_name,
                af.field_value,
                af.datatype,
                af.field_config_json
            FROM datasets d
            JOIN data_items di ON di.dataset_id = d.id
            LEFT JOIN annotations a ON a.data_item_id = di.id
            LEFT JOIN annotation_fields af ON af.annotation_id = a.id
            WHERE d.id = ?
            ORDER BY di.sort_order, a.id, af.field_name
        """
        return await self.db.fetchall(query, (dataset_id,))

    async def _fetch_incremental_rows(self, dataset_id: int, since_annotation_id: int) -> list[dict]:
        query = """
            SELECT 
                d.name as dataset_name,
                d.config_hash as dataset_config_hash,
                di.id as item_id,
                di.rel_path as item_rel_path,
                di.source_path as item_abs_path,
                di.mime_type as item_mime_type,
                di.size_bytes as item_size_bytes,
                di.sha256 as item_sha256,
                di.width as item_width,
                di.height as item_height,
                di.metadata_json as item_metadata_json,
                a.id as annotation_id,
                a.annotation_type,
                a.geometry_json,
                a.crop_path,
                a.parent_annotation_id,
                a.is_locked,
                a.annotation_order,
                a.created_at as ann_created_at,
                a.updated_at as ann_updated_at,
                af.field_name,
                af.field_value,
                af.datatype,
                af.field_config_json
            FROM datasets d
            JOIN data_items di ON di.dataset_id = d.id
            LEFT JOIN annotations a ON a.data_item_id = di.id
            LEFT JOIN annotation_fields af ON af.annotation_id = a.id
            WHERE d.id = ? AND a.id > ?
            ORDER BY di.sort_order, a.id, af.field_name
        """
        return await self.db.fetchall(query, (dataset_id, since_annotation_id))

    def _rows_to_arrow_table(self, rows: list[dict], dataset_id: int) -> pa.Table:
        if not rows:
            return pa.Table.from_pydict({})

        from collections import defaultdict
        annotations = defaultdict(lambda: {
            "dataset_name": None,
            "dataset_config_hash": None,
            "item_id": None,
            "item_rel_path": None,
            "item_abs_path": None,
            "item_mime_type": None,
            "item_size_bytes": None,
            "item_sha256": None,
            "item_width": None,
            "item_height": None,
            "item_metadata_json": None,
            "annotation_id": None,
            "annotation_type": None,
            "geometry_json": None,
            "crop_path": None,
            "parent_annotation_id": None,
            "is_locked": False,
            "annotation_order": 0,
            "ann_created_at": None,
            "ann_updated_at": None,
            "fields": {},
            "field_configs": {},
        })

        for row in rows:
            ann_id = row["annotation_id"]
            ann = annotations[ann_id]
            ann["dataset_name"] = row["dataset_name"]
            ann["dataset_config_hash"] = row["dataset_config_hash"]
            ann["item_id"] = row["item_id"]
            ann["item_rel_path"] = row["item_rel_path"]
            ann["item_abs_path"] = row["item_abs_path"]
            ann["item_mime_type"] = row["item_mime_type"]
            ann["item_size_bytes"] = row["item_size_bytes"]
            ann["item_sha256"] = row["item_sha256"]
            ann["item_width"] = row["item_width"]
            ann["item_height"] = row["item_height"]
            ann["item_metadata_json"] = row["item_metadata_json"]
            ann["annotation_id"] = row["annotation_id"]
            ann["annotation_type"] = row["annotation_type"]
            ann["geometry_json"] = row["geometry_json"]
            ann["crop_path"] = row["crop_path"]
            ann["parent_annotation_id"] = row["parent_annotation_id"]
            ann["is_locked"] = row["is_locked"]
            ann["annotation_order"] = row["annotation_order"]
            ann["ann_created_at"] = row["ann_created_at"]
            ann["ann_updated_at"] = row["ann_updated_at"]

            if row["field_name"]:
                ann["fields"][row["field_name"]] = row["field_value"]
                if row["field_config_json"]:
                    ann["field_configs"][row["field_name"]] = row["field_config_json"]

        all_field_names = set()
        for ann in annotations.values():
            all_field_names.update(ann["fields"].keys())

        sorted_field_names = sorted(all_field_names)

        columns = {
            "dataset_name": [],
            "dataset_config_hash": [],
            "export_timestamp": [],
            "export_version": [],
            "item_id": [],
            "item_rel_path": [],
            "item_abs_path": [],
            "item_mime_type": [],
            "item_size_bytes": [],
            "item_sha256": [],
            "item_width": [],
            "item_height": [],
            "item_metadata_json": [],
            "annotation_id": [],
            "annotation_type": [],
            "geometry_json": [],
            "crop_path": [],
            "parent_annotation_id": [],
            "is_locked": [],
            "annotation_order": [],
            "ann_created_at": [],
            "ann_updated_at": [],
            "source_image_base64": [],
            "crop_image_base64": [],
            "crop_format": [],
            "crop_sha256": [],
            "field_configs_json": [],
        }

        for fname in sorted_field_names:
            columns[f"field_{fname}"] = []

        export_timestamp = datetime.utcnow().isoformat()
        export_version = "1.0"

        dataset_path = Path(self.config.dataset.path)

        for ann in annotations.values():
            columns["dataset_name"].append(ann["dataset_name"])
            columns["dataset_config_hash"].append(ann["dataset_config_hash"])
            columns["export_timestamp"].append(export_timestamp)
            columns["export_version"].append(export_version)
            columns["item_id"].append(ann["item_id"])
            columns["item_rel_path"].append(ann["item_rel_path"])
            columns["item_abs_path"].append(ann["item_abs_path"])
            columns["item_mime_type"].append(ann["item_mime_type"])
            columns["item_size_bytes"].append(ann["item_size_bytes"])
            columns["item_sha256"].append(ann["item_sha256"])
            columns["item_width"].append(ann["item_width"])
            columns["item_height"].append(ann["item_height"])
            columns["item_metadata_json"].append(ann["item_metadata_json"])
            columns["annotation_id"].append(ann["annotation_id"])
            columns["annotation_type"].append(ann["annotation_type"])
            columns["geometry_json"].append(ann["geometry_json"])
            columns["crop_path"].append(ann["crop_path"])
            columns["parent_annotation_id"].append(ann["parent_annotation_id"])
            columns["is_locked"].append(ann["is_locked"])
            columns["annotation_order"].append(ann["annotation_order"])
            columns["ann_created_at"].append(ann["ann_created_at"])
            columns["ann_updated_at"].append(ann["ann_updated_at"])

            source_img_b64 = None
            if self.config.export.embed_source_images and ann["item_abs_path"]:
                source_img_b64 = self._encode_image_base64(Path(ann["item_abs_path"]))
            columns["source_image_base64"].append(source_img_b64)

            crop_img_b64 = None
            crop_fmt = None
            crop_sha = None
            if self.config.export.embed_crops and ann["crop_path"]:
                crop_full = dataset_path / ann["crop_path"]
                if crop_full.exists():
                    crop_img_b64 = self._encode_image_base64(crop_full)
                    crop_fmt = self.config.export.image_encoding.format
                    crop_sha = self._compute_sha256(crop_full)
            columns["crop_image_base64"].append(crop_img_b64)
            columns["crop_format"].append(crop_fmt)
            columns["crop_sha256"].append(crop_sha)

            field_configs_json = json.dumps(ann["field_configs"])
            columns["field_configs_json"].append(field_configs_json)

            for fname in sorted_field_names:
                columns[f"field_{fname}"].append(ann["fields"].get(fname))

        return pa.Table.from_pydict(columns)

    def _encode_image_base64(self, image_path: Path) -> str | None:
        try:
            from PIL import Image
            with Image.open(image_path) as img:
                max_dim = self.config.export.image_encoding.max_dimension
                if max_dim > 0:
                    img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)

                buffer = io.BytesIO()
                img.save(buffer, format="PNG")
                return base64.b64encode(buffer.getvalue()).decode()
        except Exception:
            return None

    def _compute_sha256(self, file_path: Path) -> str:
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest()

    async def _write_parquet(self, table: pa.Table, output_path: Path):
        pq.write_table(
            table,
            output_path,
            compression=self.config.export.parquet.compression,
            compression_level=self.config.export.parquet.compression_level,
            row_group_size=self.config.export.parquet.row_group_size,
            data_page_size=self.config.export.parquet.data_page_size,
            write_statistics=self.config.export.parquet.write_statistics,
            use_dictionary=self.config.export.parquet.use_dictionary,
            dictionary_pagesize_limit=self.config.export.parquet.dictionary_pagesize_limit,
        )

    async def _write_arrow(self, table: pa.Table, output_path: Path):
        with pa.ipc.new_file(output_path, table.schema) as writer:
            writer.write_table(table)