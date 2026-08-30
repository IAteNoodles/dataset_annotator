from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq


def compute_file_sha256(file_path: Path) -> str:
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256_hash.update(chunk)
    return sha256_hash.hexdigest()


def compute_parquet_row_group_checksums(parquet_path: Path) -> list[dict[str, Any]]:
    pf = pq.ParquetFile(parquet_path)
    checksums = []
    for i in range(pf.num_row_groups):
        rg = pf.metadata.row_group(i)
        checksums.append({
            "row_group_index": i,
            "num_rows": rg.num_rows,
            "total_byte_size": rg.total_byte_size,
            "columns": rg.num_columns,
        })
    return checksums


def create_manifest(
    dataset_name: str,
    config: dict[str, Any],
    config_hash: str,
    parquet_path: Path,
    export_type: str,
    since_timestamp: str | None = None,
) -> dict[str, Any]:
    parquet_sha256 = compute_file_sha256(parquet_path)
    parquet_size = parquet_path.stat().st_size
    row_group_checksums = compute_parquet_row_group_checksums(parquet_path)

    pf = pq.ParquetFile(parquet_path)
    total_rows = pf.metadata.num_rows

    manifest = {
        "export_version": "1.0",
        "dataset_name": dataset_name,
        "export_type": export_type,
        "export_timestamp": datetime.utcnow().isoformat() + "Z",
        "config_hash": config_hash,
        "config_json": json.dumps(config, sort_keys=True),
        "since_timestamp": since_timestamp,
        "counts": {
            "total_rows": total_rows,
            "row_groups": pf.num_row_groups,
        },
        "integrity": {
            "parquet_sha256": parquet_sha256,
            "parquet_size_bytes": parquet_size,
            "row_group_checksums": row_group_checksums,
        },
        "recovery": {
            "can_reconstruct_database": True,
            "can_reconstruct_images": True,
            "requires_original_images": False,
            "recovery_tool": "dataset_annotator recover --from-export",
            "estimated_recovery_time_seconds": max(10, total_rows // 1000),
        },
        "plugin": {
            "type": config.get("dataset", {}).get("plugin", "image"),
            "version": "1.0",
        },
    }

    return manifest


def write_manifest(manifest: dict[str, Any], manifest_path: Path) -> None:
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    sha256_path = manifest_path.with_suffix(".manifest.json.sha256")
    sha256_hash = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    sha256_path.write_text(sha256_hash, encoding="utf-8")


def verify_manifest(manifest_path: Path) -> tuple[bool, list[str]]:
    errors = []

    if not manifest_path.exists():
        return False, ["Manifest file not found"]

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return False, [f"Invalid JSON: {e}"]

    sha256_path = manifest_path.with_suffix(".manifest.json.sha256")
    if sha256_path.exists():
        expected_sha256 = sha256_path.read_text().strip()
        actual_sha256 = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
        if expected_sha256 != actual_sha256:
            errors.append("Manifest checksum mismatch")

    required_fields = [
        "export_version", "dataset_name", "export_type", "export_timestamp",
        "config_hash", "config_json", "counts", "integrity", "recovery", "plugin"
    ]
    for field in required_fields:
        if field not in manifest:
            errors.append(f"Missing required field: {field}")

    return len(errors) == 0, errors