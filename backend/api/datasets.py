from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException

from backend.deps import get_config, get_db
from backend.models import (
    DatasetResponse, DatasetOpenRequest, DataItemResponse, DataItemListResponse,
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
    out: list[DatasetResponse] = []
    for d in datasets:
        row = DatasetResponse(**d)
        try:
            cfg_json = json.loads(d["config_json"])
            p = cfg_json.get("dataset", {}).get("path")
            if p:
                row.path = str(Path(p))
        except Exception:
            row.path = None
        out.append(row)
    return DatasetListResponse(datasets=out, total=len(out))


@router.post("/datasets/open")
async def open_dataset(request: DatasetOpenRequest) -> dict[str, Any]:
    """Set the active dataset folder, (re)create its dataset row, and scan it."""
    db = get_db()
    config = get_config()
    from backend.config import save_config
    from backend.services.scanner import scan_dataset

    root = Path(str(request.path)).expanduser().resolve()
    if not root.is_dir():
        raise HTTPException(400, f"Path is not a directory: {root}")

    config.dataset.name = root.name
    config.dataset.path = str(root)

    config_path = Path(os.getenv("DATASET_ANNOTATOR_CONFIG", "config/dataset_config.yaml"))
    try:
        save_config(config, config_path)
    except Exception:
        pass  # non-fatal: in-memory config is already updated

    result = await scan_dataset(db, config)
    return {
        "dataset_id": result["dataset_id"],
        "name": config.dataset.name,
        "path": str(root),
        "scanned": result["scanned"],
        "inserted": result["inserted"],
        "updated": result["updated"],
    }


@router.get("/datasets/{dataset_id}/tree")
async def get_dataset_tree(dataset_id: int) -> dict[str, Any]:
    """Return a nested folder/file tree plus a flat, ordered item list."""
    db = get_db()
    items = await db.fetchall(
        "SELECT * FROM data_items WHERE dataset_id = ? ORDER BY sort_order",
        (dataset_id,)
    )
    return {
        "dataset_id": dataset_id,
        "total": len(items),
        "nodes": build_tree(items),
        "items": [DataItemResponse(**item) for item in items],
    }


def build_tree(items: list[dict]) -> list[dict]:
    """Build a nested {name,type,children|item_id,status} tree from rel_paths."""
    root: dict = {"children": []}

    def dir_key(node: dict) -> str:
        return str(id(node))

    index: dict[str, dict] = {dir_key(root): root}

    for it in items:
        rel = str(it["rel_path"]).replace("\\", "/")
        parts = [p for p in rel.split("/") if p]
        if not parts:
            continue

        cur = index[dir_key(root)]
        for part in parts[:-1]:
            nxt = next(
                (c for c in cur["children"] if c.get("type") == "dir" and c.get("name") == part),
                None,
            )
            if nxt is None:
                nxt = {"name": part, "type": "dir", "children": []}
                cur["children"].append(nxt)
                index[dir_key(nxt)] = nxt
            cur = nxt

        cur["children"].append({
            "name": parts[-1],
            "type": "file",
            "item_id": it["id"],
            "rel_path": str(it["rel_path"]),
            "status": it["status"],
        })

    def sort_nodes(nodes: list[dict]) -> None:
        nodes.sort(key=lambda n: (0 if n.get("type") == "dir" else 1, str(n.get("name", "")).lower()))
        for n in nodes:
            if n.get("children"):
                sort_nodes(n["children"])

    sort_nodes(root["children"])
    return root["children"]


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