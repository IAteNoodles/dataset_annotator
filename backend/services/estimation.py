from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from backend.config import AppConfig
from backend.database import Database
from backend.models import ExportEstimateResponse


async def estimate_export_size(
    db: Database,
    config: AppConfig,
    dataset_id: int,
    export_type: str,
    export_mode: str = "annotated",
) -> ExportEstimateResponse:
    # count annotations (and crops) for the selected export window
    if export_type == "full":
        annotation_count = await db.fetchval(
            """SELECT COUNT(*) FROM annotations a
               JOIN data_items di ON a.data_item_id = di.id
               WHERE di.dataset_id = ?""", (dataset_id,)
        )
        crop_count = await db.fetchval(
            """SELECT COUNT(*) FROM annotations a
               JOIN data_items di ON a.data_item_id = di.id
               WHERE di.dataset_id = ? AND a.crop_path IS NOT NULL""", (dataset_id,)
        )
    else:
        cursor = await db.fetchone(
            "SELECT last_exported_annotation_id FROM export_cursors WHERE dataset_id = ? ORDER BY created_at DESC LIMIT 1",
            (dataset_id,)
        )
        last_id = cursor["last_exported_annotation_id"] if cursor else 0
        annotation_count = await db.fetchval(
            """SELECT COUNT(*) FROM annotations a
               JOIN data_items di ON a.data_item_id = di.id
               WHERE di.dataset_id = ? AND a.id > ?""", (dataset_id, last_id)
        )
        crop_count = await db.fetchval(
            """SELECT COUNT(*) FROM annotations a
               JOIN data_items di ON a.data_item_id = di.id
               WHERE di.dataset_id = ? AND a.id > ? AND a.crop_path IS NOT NULL""", (dataset_id, last_id)
        )

    # number of images to include
    if export_mode == "full":
        # full mode: every data item, annotated or not
        image_count = await db.fetchval(
            "SELECT COUNT(*) FROM data_items WHERE dataset_id = ?", (dataset_id,)
        )
    else:
        # annotated mode: only items that have at least one annotation
        image_count = await db.fetchval(
            """SELECT COUNT(DISTINCT di.id) FROM data_items di
               WHERE di.dataset_id = ? AND EXISTS (
                   SELECT 1 FROM annotations a WHERE a.data_item_id = di.id
               )""", (dataset_id,)
        )
        if export_type != "full":
            cursor = await db.fetchone(
                "SELECT last_exported_annotation_id FROM export_cursors WHERE dataset_id = ? ORDER BY created_at DESC LIMIT 1",
                (dataset_id,)
            )
            last_id = cursor["last_exported_annotation_id"] if cursor else 0
            image_count = await db.fetchval(
                """SELECT COUNT(DISTINCT di.id) FROM data_items di
                   JOIN annotations a ON a.data_item_id = di.id
                   WHERE di.dataset_id = ? AND a.id > ?""", (dataset_id, last_id)
            )

    if annotation_count is None:
        annotation_count = 0
    if image_count is None:
        image_count = 0
    if crop_count is None:
        crop_count = 0

    sample_rows = config.export.estimation.sample_rows
    include_images = config.export.estimation.include_images_in_estimate

    avg_annotation_size = await _estimate_avg_annotation_size(db, dataset_id, sample_rows)
    avg_image_size = await _estimate_avg_image_size(db, dataset_id, sample_rows) if include_images else 0
    avg_crop_size = await _estimate_avg_crop_size(db, dataset_id, sample_rows)

    estimated_bytes = (
        annotation_count * avg_annotation_size +
        (image_count * avg_image_size if include_images else 0) +
        crop_count * avg_crop_size
    )

    estimated_size_gb = estimated_bytes / (1024 ** 3)

    throughput_mbps = 100
    estimated_time_seconds = (estimated_bytes / (1024 ** 2)) / throughput_mbps
    estimated_time_minutes = max(1, int(estimated_time_seconds / 60) + 1)

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(config.export.output_dir).resolve()
    primary = output_dir / f"{config.dataset.name}_{timestamp}.parquet"

    return ExportEstimateResponse(
        estimated_size_gb=round(estimated_size_gb, 2),
        estimated_time_minutes=estimated_time_minutes,
        annotation_count=annotation_count,
        image_count=image_count,
        crop_count=crop_count,
        output_path=str(primary),
    )


async def _estimate_avg_annotation_size(db: Database, dataset_id: int, sample_size: int) -> int:
    rows = await db.fetchall(
        """SELECT a.geometry_json, af.field_name, af.field_value, af.datatype
           FROM annotations a
           JOIN data_items di ON a.data_item_id = di.id
           LEFT JOIN annotation_fields af ON af.annotation_id = a.id
           WHERE di.dataset_id = ?
           ORDER BY RANDOM() LIMIT ?""",
        (dataset_id, sample_size)
    )

    if not rows:
        return 500

    import json
    total_size = 0
    for row in rows:
        geom_size = len(row["geometry_json"])
        field_size = len(row["field_name"] or "") + len(row["field_value"] or "") + len(row["datatype"] or "")
        total_size += geom_size + field_size + 100

    return total_size // len(rows)


async def _estimate_avg_image_size(db: Database, dataset_id: int, sample_size: int) -> int:
    if not sample_size:
        return 0

    rows = await db.fetchall(
        "SELECT size_bytes FROM data_items WHERE dataset_id = ? ORDER BY RANDOM() LIMIT ?",
        (dataset_id, sample_size)
    )

    if not rows:
        return 0

    return sum(row["size_bytes"] for row in rows) // len(rows)


async def _estimate_avg_crop_size(db: Database, dataset_id: int, sample_size: int) -> int:
    rows = await db.fetchall(
        """SELECT a.crop_path FROM annotations a
           JOIN data_items di ON a.data_item_id = di.id
           WHERE di.dataset_id = ? AND a.crop_path IS NOT NULL
           ORDER BY RANDOM() LIMIT ?""",
        (dataset_id, sample_size)
    )

    if not rows:
        return 0

    import os
    total = 0
    count = 0
    for row in rows:
        try:
            total += os.path.getsize(row["crop_path"])
            count += 1
        except Exception:
            pass

    return total // count if count else 0