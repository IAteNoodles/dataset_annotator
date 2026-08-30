from __future__ import annotations

import hashlib
import mimetypes
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image

from backend.config import AppConfig
from backend.database import Database


async def scan_dataset(db: Database, config: AppConfig) -> dict[str, int]:
    dataset = config.dataset
    root_path = Path(dataset.path).expanduser().resolve()

    if not root_path.exists():
        raise FileNotFoundError(f"Dataset path does not exist: {root_path}")

    dataset_row = await db.fetchone("SELECT id FROM datasets WHERE name = ?", (dataset.name,))
    if not dataset_row:
        dataset_id = await _create_dataset(db, config)
    else:
        dataset_id = dataset_row["id"]

    extensions = set(ext.lower() for ext in dataset.extensions)
    pattern = "**/*" if dataset.recursive else "*"

    files: list[Path] = []
    for ext in extensions:
        files.extend(root_path.glob(f"{pattern}{ext}"))

    files = [f for f in files if f.is_file()]

    if dataset.sort_by == "path":
        files.sort(key=lambda f: str(f.relative_to(root_path)))
    elif dataset.sort_by == "mtime":
        files.sort(key=lambda f: f.stat().st_mtime)
    elif dataset.sort_by == "size":
        files.sort(key=lambda f: f.stat().st_size)
    elif dataset.sort_by == "random":
        import random
        random.shuffle(files)

    inserted = 0
    updated = 0
    skipped = 0

    batch_size = config.performance.batch_size
    batch: list[tuple] = []

    for idx, file_path in enumerate(files):
        rel_path = file_path.relative_to(root_path)
        stat = file_path.stat()
        mime_type, _ = mimetypes.guess_type(str(file_path))

        sha256_hash = await _compute_sha256(file_path)
        width, height = await _get_image_dimensions(file_path)

        metadata = {
            "width": width,
            "height": height,
            "mime_type": mime_type,
        }

        batch.append((
            dataset_id,
            str(file_path),
            str(rel_path),
            mime_type,
            stat.st_size,
            sha256_hash,
            width,
            height,
            None,
            json_dumps(metadata),
            "pending",
            idx,
        ))

        if len(batch) >= batch_size:
            i, u = await _batch_upsert_items(db, batch)
            inserted += i
            updated += u
            batch.clear()

    if batch:
        i, u = await _batch_upsert_items(db, batch)
        inserted += i
        updated += u

    await db.execute(
        "UPDATE datasets SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (dataset_id,)
    )

    return {
        "dataset_id": dataset_id,
        "scanned": len(files),
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
    }


async def _create_dataset(db: Database, config: AppConfig) -> int:
    import json
    config_hash = config.compute_hash()
    config_json = json.dumps(config.model_dump(mode="json"))

    cursor = await db.execute_returning(
        """INSERT INTO datasets (name, plugin_type, config_hash, config_json)
           VALUES (?, ?, ?, ?)""",
        (config.dataset.name, config.dataset.plugin, config_hash, config_json)
    )
    return cursor.lastrowid


async def _batch_upsert_items(db: Database, batch: list[tuple]) -> tuple[int, int]:
    inserted = 0
    updated = 0

    for item in batch:
        existing = await db.fetchone(
            "SELECT id FROM data_items WHERE dataset_id = ? AND rel_path = ?",
            (item[0], item[2])
        )

        if existing:
            await db.execute(
                """UPDATE data_items SET
                    source_path = ?, mime_type = ?, size_bytes = ?, sha256 = ?,
                    width = ?, height = ?, metadata_json = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (*item[1:10], existing["id"])
            )
            updated += 1
        else:
            await db.execute(
                """INSERT INTO data_items
                    (dataset_id, source_path, rel_path, mime_type, size_bytes, sha256,
                     width, height, duration_ms, metadata_json, status, sort_order)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                item
            )
            inserted += 1

    return inserted, updated


async def _compute_sha256(file_path: Path) -> str:
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256_hash.update(chunk)
    return sha256_hash.hexdigest()


async def _get_image_dimensions(file_path: Path) -> tuple[int | None, int | None]:
    try:
        with Image.open(file_path) as img:
            return img.width, img.height
    except Exception:
        return None, None


def json_dumps(obj: Any) -> str:
    import json
    return json.dumps(obj, separators=(",", ":"))