from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.config import AppConfig
from backend.database import Database
from backend.exporters.streaming_s3 import S3Exporter
from backend.ws.manager import broadcast_s3_sync_progress


class S3Service:
    def __init__(self, config: AppConfig, db: Database):
        self.config = config
        self.db = db
        self.exporter = S3Exporter(config, db)

    async def sync(self, fetch: bool, push: bool) -> dict[str, Any]:
        result = {"synced": True, "fetched": 0, "pushed": 0, "errors": []}

        if fetch:
            try:
                await broadcast_s3_sync_progress(1, "fetch", 0.1, "Fetching latest exports")
                fetched = await self.fetch_latest()
                result["fetched"] = fetched
            except Exception as e:
                result["errors"].append(f"Fetch failed: {e}")
                result["synced"] = False

        if push:
            try:
                await broadcast_s3_sync_progress(1, "push", 0.1, "Pushing pending changes")
                pushed = await self.push_pending()
                result["pushed"] = pushed
            except Exception as e:
                result["errors"].append(f"Push failed: {e}")
                result["synced"] = False

        return result

    async def fetch_latest(self) -> int:
        dataset_name = self.config.dataset.name
        dataset_id = await self._get_dataset_id()
        if not dataset_id:
            return 0

        fetched = 0

        await broadcast_s3_sync_progress(dataset_id, "fetch", 0.2, "Listing S3 objects")

        exports = await self.exporter.list_objects(dataset_id, "exports/")
        snapshots = await self.exporter.list_objects(dataset_id, "snapshots/")
        cursors = await self.exporter.list_objects(dataset_id, "state/")

        await broadcast_s3_sync_progress(dataset_id, "fetch", 0.4, f"Found {len(exports)} exports, {len(snapshots)} snapshots")

        if self.config.s3.fetch.exports:
            for exp in exports:
                if exp["key"].endswith(".parquet"):
                    local_path = Path("data") / "s3_cache" / exp["key"].replace("/", "_")
                    await self.exporter.download_file(exp["key"], local_path)
                    await self._record_sync(dataset_id, "export", exp["key"], local_path, exp["etag"], exp["size"])
                    fetched += 1

        if self.config.s3.fetch.snapshots:
            for snap in snapshots:
                if snap["key"].endswith(".db.gz") or snap["key"].endswith(".db"):
                    local_path = Path("data") / "s3_cache" / snap["key"].replace("/", "_")
                    await self.exporter.download_file(snap["key"], local_path)
                    await self._record_sync(dataset_id, "snapshot", snap["key"], local_path, snap["etag"], snap["size"])
                    fetched += 1

        if self.config.s3.fetch.cursor:
            for cur in cursors:
                if cur["key"].endswith("export_cursor.json"):
                    local_path = Path("data") / "s3_cache" / cur["key"].replace("/", "_")
                    await self.exporter.download_file(cur["key"], local_path)
                    await self._record_sync(dataset_id, "cursor", cur["key"], local_path, cur["etag"], cur["size"])
                    fetched += 1

        await broadcast_s3_sync_progress(dataset_id, "fetch", 1.0, f"Fetched {fetched} objects")
        return fetched

    async def push_pending(self) -> int:
        dataset_id = await self._get_dataset_id()
        if not dataset_id:
            return 0

        pushed = 0

        pending_exports = await self.db.fetchall(
            "SELECT * FROM exports WHERE dataset_id = ? AND output_path IS NOT NULL",
            (dataset_id,)
        )

        for exp in pending_exports:
            local_path = Path(exp["output_path"])
            if local_path.exists():
                s3_key = f"{self.config.s3.prefix}{self.config.dataset.name}/exports/{local_path.name}"
                try:
                    await self.exporter.upload_file(local_path, s3_key)
                    await self._record_sync(dataset_id, "export", s3_key, local_path, "", local_path.stat().st_size)
                    pushed += 1
                except Exception as e:
                    print(f"Failed to push export {local_path}: {e}")

        snapshots = await self.db.fetchall(
            "SELECT snapshot_path FROM snapshots WHERE dataset_id = ?",
            (dataset_id,)
        )

        for snap in snapshots:
            local_path = Path(snap["snapshot_path"])
            if local_path.exists():
                s3_key = f"{self.config.s3.prefix}{self.config.dataset.name}/snapshots/{local_path.name}"
                try:
                    await self.exporter.upload_file(local_path, s3_key)
                    await self._record_sync(dataset_id, "snapshot", s3_key, local_path, "", local_path.stat().st_size)
                    pushed += 1
                except Exception as e:
                    print(f"Failed to push snapshot {local_path}: {e}")

        return pushed

    async def list_objects(self, dataset_id: int) -> list[dict[str, Any]]:
        return await self.exporter.list_objects(dataset_id, "")

    async def _get_dataset_id(self) -> int | None:
        row = await self.db.fetchone("SELECT id FROM datasets WHERE name = ?", (self.config.dataset.name,))
        return row["id"] if row else None

    async def _record_sync(
        self,
        dataset_id: int,
        object_type: str,
        s3_key: str,
        local_path: Path,
        sha256: str,
        size_bytes: int,
    ) -> None:
        await self.db.execute(
            """INSERT INTO s3_sync_state (dataset_id, object_type, s3_key, local_path, sha256, size_bytes)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(dataset_id, object_type, s3_key) DO UPDATE SET
                   local_path = excluded.local_path, sha256 = excluded.sha256, size_bytes = excluded.size_bytes, synced_at = CURRENT_TIMESTAMP""",
            (dataset_id, object_type, s3_key, str(local_path), sha256, size_bytes)
        )