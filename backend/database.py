from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import shutil
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite

from backend.config import AppConfig


SCHEMA_VERSION = 7

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA busy_timeout = 5000;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS datasets (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    plugin_type TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    config_json TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS data_items (
    id INTEGER PRIMARY KEY,
    dataset_id INTEGER NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    source_path TEXT NOT NULL,
    rel_path TEXT NOT NULL,
    mime_type TEXT,
    size_bytes INTEGER,
    sha256 TEXT,
    width INTEGER,
    height INTEGER,
    duration_ms INTEGER,
    metadata_json TEXT,
    status TEXT DEFAULT 'pending',
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(dataset_id, rel_path)
);

CREATE INDEX IF NOT EXISTS idx_data_items_dataset ON data_items(dataset_id);
CREATE INDEX IF NOT EXISTS idx_data_items_status ON data_items(dataset_id, status);
CREATE INDEX IF NOT EXISTS idx_data_items_sort ON data_items(dataset_id, sort_order);

CREATE TABLE IF NOT EXISTS annotations (
    id INTEGER PRIMARY KEY,
    data_item_id INTEGER NOT NULL REFERENCES data_items(id) ON DELETE CASCADE,
    annotation_type TEXT NOT NULL,
    geometry_json TEXT NOT NULL,
    crop_path TEXT,
    parent_annotation_id INTEGER REFERENCES annotations(id) ON DELETE SET NULL,
    is_locked BOOLEAN DEFAULT FALSE,
    annotation_order INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_annotations_item ON annotations(data_item_id);
CREATE INDEX IF NOT EXISTS idx_annotations_parent ON annotations(parent_annotation_id);
CREATE INDEX IF NOT EXISTS idx_annotations_updated ON annotations(updated_at);

CREATE TABLE IF NOT EXISTS annotation_fields (
    id INTEGER PRIMARY KEY,
    annotation_id INTEGER NOT NULL REFERENCES annotations(id) ON DELETE CASCADE,
    field_name TEXT NOT NULL,
    field_value TEXT,
    datatype TEXT NOT NULL,
    field_config_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(annotation_id, field_name)
);

CREATE INDEX IF NOT EXISTS idx_annotation_fields_annotation ON annotation_fields(annotation_id);
CREATE INDEX IF NOT EXISTS idx_annotation_fields_name ON annotation_fields(field_name);

CREATE TABLE IF NOT EXISTS field_categories (
    id INTEGER PRIMARY KEY,
    dataset_id INTEGER NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    field_name TEXT NOT NULL,
    category_value TEXT NOT NULL,
    normalized_value TEXT NOT NULL,
    count INTEGER DEFAULT 1,
    source TEXT DEFAULT 'manual',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(dataset_id, field_name, normalized_value)
);

CREATE INDEX IF NOT EXISTS idx_field_categories_lookup ON field_categories(dataset_id, field_name, normalized_value);

CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY,
    dataset_id INTEGER NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    snapshot_path TEXT NOT NULL UNIQUE,
    annotation_count INTEGER,
    data_item_count INTEGER,
    trigger TEXT,
    sha256 TEXT,
    size_bytes INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_snapshots_dataset ON snapshots(dataset_id);

CREATE TABLE IF NOT EXISTS exports (
    id INTEGER PRIMARY KEY,
    dataset_id INTEGER NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    format TEXT NOT NULL,
    output_path TEXT NOT NULL,
    record_count INTEGER,
    config_snapshot_json TEXT,
    sha256 TEXT,
    size_bytes INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_exports_dataset ON exports(dataset_id);

CREATE TABLE IF NOT EXISTS export_cursors (
    id INTEGER PRIMARY KEY,
    dataset_id INTEGER NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    export_type TEXT NOT NULL,
    last_exported_annotation_id INTEGER,
    last_exported_item_id INTEGER,
    last_exported_updated_at TIMESTAMP,
    s3_export_path TEXT,
    s3_manifest_path TEXT,
    status TEXT DEFAULT 'completed',
    records_exported INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS s3_sync_state (
    id INTEGER PRIMARY KEY,
    dataset_id INTEGER NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    object_type TEXT NOT NULL,
    s3_key TEXT NOT NULL,
    local_path TEXT,
    sha256 TEXT,
    size_bytes INTEGER,
    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(dataset_id, object_type, s3_key)
);
"""


class Database:
    def __init__(self, db_path: str | Path, config: AppConfig):
        self.db_path = Path(db_path)
        self.config = config
        self._pool: asyncio.Queue[aiosqlite.Connection] | None = None

    async def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        await self._run_migrations()
        await self._init_connection_pool()

    async def _run_migrations(self) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(SCHEMA)
            await db.commit()

            cursor = await db.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1")
            row = await cursor.fetchone()
            current_version = row[0] if row else 0

            if current_version < SCHEMA_VERSION:
                await self._apply_migrations(db, current_version)
                await db.execute("INSERT OR REPLACE INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
                await db.commit()

    async def _apply_migrations(self, db: aiosqlite.Connection, from_version: int) -> None:
        migrations = {
            1: [],
            2: [],
            3: [],
            4: [],
            5: [],
            6: [],
            7: [],
        }

        for version in range(from_version + 1, SCHEMA_VERSION + 1):
            for stmt in migrations.get(version, []):
                await db.execute(stmt)

    async def _init_connection_pool(self) -> None:
        self._pool = asyncio.Queue(maxsize=self.config.performance.pool_size)
        for _ in range(self.config.performance.pool_size):
            conn = await aiosqlite.connect(self.db_path)
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA journal_mode = WAL")
            await conn.execute("PRAGMA busy_timeout = 5000")
            await conn.execute("PRAGMA foreign_keys = ON")
            await self._pool.put(conn)

    @asynccontextmanager
    async def acquire(self):
        conn = await self._pool.get()
        try:
            yield conn
        finally:
            await self._pool.put(conn)

    async def close(self) -> None:
        if self._pool:
            while not self._pool.empty():
                conn = await self._pool.get()
                await conn.close()

    async def execute(self, query: str, params: tuple = ()) -> None:
        async with self.acquire() as conn:
            await conn.execute(query, params)
            await conn.commit()

    async def execute_returning(self, query: str, params: tuple = ()) -> aiosqlite.Cursor:
        async with self.acquire() as conn:
            cursor = await conn.execute(query, params)
            await conn.commit()
            return cursor

    async def executemany(self, query: str, params_list: list[tuple]) -> None:
        async with self.acquire() as conn:
            await conn.executemany(query, params_list)
            await conn.commit()

    async def fetchone(self, query: str, params: tuple = ()) -> dict[str, Any] | None:
        async with self.acquire() as conn:
            cursor = await conn.execute(query, params)
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def fetchall(self, query: str, params: tuple = ()) -> list[dict[str, Any]]:
        async with self.acquire() as conn:
            cursor = await conn.execute(query, params)
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def fetchval(self, query: str, params: tuple = ()) -> Any:
        async with self.acquire() as conn:
            cursor = await conn.execute(query, params)
            row = await cursor.fetchone()
            return row[0] if row else None

    async def begin(self) -> aiosqlite.Connection:
        conn = await self._pool.get()
        await conn.execute("BEGIN")
        return conn

    async def commit(self, conn: aiosqlite.Connection) -> None:
        await conn.commit()
        await self._pool.put(conn)

    async def rollback(self, conn: aiosqlite.Connection) -> None:
        await conn.rollback()
        await self._pool.put(conn)


async def create_snapshot(db: Database, dataset_id: int, snapshot_dir: Path, trigger: str = "manual") -> Path:
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    snapshot_name = f"snapshot_{dataset_id}_{timestamp}.db"
    snapshot_path = snapshot_dir / snapshot_name

    async with db.acquire() as conn:
        await conn.execute("PRAGMA wal_checkpoint(FULL)")
        await conn.commit()

        src_conn = sqlite3.connect(str(db.db_path))
        dst_conn = sqlite3.connect(str(snapshot_path))
        src_conn.backup(dst_conn)
        src_conn.close()
        dst_conn.close()

    if db.config.snapshot.compress:
        gz_path = snapshot_path.with_suffix(".db.gz")
        with open(snapshot_path, "rb") as f_in:
            with gzip.open(gz_path, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
        snapshot_path.unlink()
        snapshot_path = gz_path

    sha256_hash = hashlib.sha256()
    with open(snapshot_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256_hash.update(chunk)

    size_bytes = snapshot_path.stat().st_size
    annotation_count = await db.fetchval("SELECT COUNT(*) FROM annotations a JOIN data_items di ON a.data_item_id = di.id WHERE di.dataset_id = ?", (dataset_id,))
    item_count = await db.fetchval("SELECT COUNT(*) FROM data_items WHERE dataset_id = ?", (dataset_id,))

    await db.execute(
        """INSERT INTO snapshots (dataset_id, snapshot_path, annotation_count, data_item_count, trigger, sha256, size_bytes)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (dataset_id, str(snapshot_path), annotation_count or 0, item_count or 0, trigger, sha256_hash.hexdigest(), size_bytes)
    )

    await _cleanup_old_snapshots(db, dataset_id)

    return snapshot_path


async def _cleanup_old_snapshots(db: Database, dataset_id: int) -> None:
    snapshots = await db.fetchall(
        "SELECT id, snapshot_path FROM snapshots WHERE dataset_id = ? ORDER BY created_at DESC",
        (dataset_id,)
    )
    max_snapshots = db.config.snapshot.max_snapshots
    for snap in snapshots[max_snapshots:]:
        Path(snap["snapshot_path"]).unlink(missing_ok=True)
        await db.execute("DELETE FROM snapshots WHERE id = ?", (snap["id"],))


async def restore_snapshot(db: Database, dataset_id: int, snapshot_id: int) -> None:
    snap = await db.fetchone("SELECT snapshot_path FROM snapshots WHERE id = ? AND dataset_id = ?", (snapshot_id, dataset_id))
    if not snap:
        raise ValueError(f"Snapshot {snapshot_id} not found")

    snapshot_path = Path(snap["snapshot_path"])
    if not snapshot_path.exists():
        raise FileNotFoundError(f"Snapshot file not found: {snapshot_path}")

    await db.close()

    if snapshot_path.suffix == ".gz":
        import gzip
        with gzip.open(snapshot_path, "rb") as f_in:
            with open(db.db_path, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
    else:
        shutil.copy2(snapshot_path, db.db_path)

    await db.initialize()