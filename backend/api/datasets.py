from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from backend.deps import get_config, get_db
from backend.models import (
    DatasetResponse, DataItemResponse, DataItemListResponse,
    ConfigValidationRequest, ConfigValidationResponse,
    DatasetListResponse,
)


router = APIRouter(tags=["datasets"])


@router.post("/datasets/init", response_model=DatasetResponse)
async def init_dataset() -> DatasetResponse:
    db = get_db()
    config = get_config()

    dataset_row = await db.fetchone("SELECT * FROM datasets WHERE name = ?", (config.dataset.name,))
    if not dataset_row:
        config_hash = config.compute_hash()
        config_json = json.dumps(config.model_dump(mode="json"))
        cursor = await db.execute(
            """INSERT INTO datasets (name, plugin_type, config_hash, config_json)
               VALUES (?, ?, ?, ?)""",
            (config.dataset.name, config.dataset.plugin, config_hash, config_json)
        )
        dataset_row = await db.fetchone("SELECT * FROM datasets WHERE id = ?", (cursor.lastrowid,))
    return DatasetResponse(**dataset_row)


@router.get("/datasets", response_model=DatasetListResponse)
async def list_datasets() -> DatasetListResponse:
    db = get_db()
    datasets = await db.fetchall("SELECT * FROM datasets ORDER BY created_at DESC")
    return DatasetListResponse(datasets=[DatasetResponse(**d) for d in datasets], total=len(datasets))


@router.post("/datasets/scan")
async def scan_dataset_endpoint() -> dict[str, int]:
    db = get_db()
    config = get_config()
    from backend.services.scanner import scan_dataset
    return await scan_dataset(db, config)


@router.get("/datasets/{dataset_id}/items", response_model=DataItemListResponse)
async def list_items(
    dataset_id: int,
    page: int = 1,
    page_size: int = 100,
    status: str | None = None,
) -> DataItemListResponse:
    db = get_db()
    offset = (page - 1) * page_size
    where = "WHERE dataset_id = ?"
    params = [dataset_id]
    if status:
        where += " AND status = ?"
        params.append(status)

    total = await db.fetchval(f"SELECT COUNT(*) FROM data_items {where}", tuple(params))
    items = await db.fetchall(
        f"SELECT * FROM data_items {where} ORDER BY sort_order LIMIT ? OFFSET ?",
        (*params, page_size, offset)
    )
    return DataItemListResponse(
        items=[DataItemResponse(**item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/datasets/{dataset_id}/items/{item_id}", response_model=DataItemResponse)
async def get_item(dataset_id: int, item_id: int) -> DataItemResponse:
    db = get_db()
    item = await db.fetchone(
        "SELECT * FROM data_items WHERE id = ? AND dataset_id = ?",
        (item_id, dataset_id)
    )
    if not item:
        raise HTTPException(404, "Item not found")
    return DataItemResponse(**item)


@router.patch("/datasets/{dataset_id}/items/{item_id}/status")
async def update_item_status(dataset_id: int, item_id: int, status: str) -> dict[str, str]:
    db = get_db()
    valid_statuses = ["pending", "in_progress", "done", "skipped"]
    if status not in valid_statuses:
        raise HTTPException(400, f"Invalid status. Must be one of: {valid_statuses}")

    item = await db.fetchone(
        "SELECT * FROM data_items WHERE id = ? AND dataset_id = ?",
        (item_id, dataset_id)
    )
    if not item:
        raise HTTPException(404, "Item not found")

    await db.execute(
        "UPDATE data_items SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (status, item_id)
    )
    return {"status": "updated"}


@router.get("/datasets/{dataset_id}/stats")
async def get_dataset_stats(dataset_id: int) -> dict[str, Any]:
    db = get_db()

    total_items = await db.fetchval(
        "SELECT COUNT(*) FROM data_items WHERE dataset_id = ?", (dataset_id,)
    )
    pending_items = await db.fetchval(
        "SELECT COUNT(*) FROM data_items WHERE dataset_id = ? AND status = 'pending'", (dataset_id,)
    )
    in_progress_items = await db.fetchval(
        "SELECT COUNT(*) FROM data_items WHERE dataset_id = ? AND status = 'in_progress'", (dataset_id,)
    )
    done_items = await db.fetchval(
        "SELECT COUNT(*) FROM data_items WHERE dataset_id = ? AND status = 'done'", (dataset_id,)
    )
    skipped_items = await db.fetchval(
        "SELECT COUNT(*) FROM data_items WHERE dataset_id = ? AND status = 'skipped'", (dataset_id,)
    )

    total_annotations = await db.fetchval(
        """SELECT COUNT(*) FROM annotations a
           JOIN data_items di ON a.data_item_id = di.id
           WHERE di.dataset_id = ?""", (dataset_id,)
    )

    annotations_by_type = await db.fetchall(
        """SELECT a.annotation_type, COUNT(*) as count
           FROM annotations a
           JOIN data_items di ON a.data_item_id = di.id
           WHERE di.dataset_id = ?
           GROUP BY a.annotation_type""", (dataset_id,)
    )

    return {
        "total_items": total_items or 0,
        "pending_items": pending_items or 0,
        "in_progress_items": in_progress_items or 0,
        "done_items": done_items or 0,
        "skipped_items": skipped_items or 0,
        "total_annotations": total_annotations or 0,
        "annotations_by_type": {row["annotation_type"]: row["count"] for row in annotations_by_type},
    }


@router.post("/config/validate", response_model=ConfigValidationResponse)
async def validate_config(request: ConfigValidationRequest) -> ConfigValidationResponse:
    import yaml
    from backend.config import AppConfig
    try:
        raw = yaml.safe_load(request.config_yaml)
        cfg = AppConfig(**raw)
        return ConfigValidationResponse(valid=True, config=cfg.model_dump(mode="json"))
    except Exception as e:
        return ConfigValidationResponse(valid=False, errors=[str(e)])