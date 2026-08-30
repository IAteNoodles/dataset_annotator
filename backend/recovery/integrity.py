from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from backend.exporters.manifest import verify_manifest
from backend.recovery.recovery_engine import RecoveryEngine


async def verify_export(export_path: str) -> dict[str, Any]:
    export_file = Path(export_path)
    manifest_file = export_file.with_suffix(".manifest.json")

    if not export_file.exists():
        return {"valid": False, "errors": [f"Export file not found: {export_file}"], "warnings": []}

    manifest_valid, manifest_errors = verify_manifest(manifest_file)
    if not manifest_valid:
        return {"valid": False, "errors": manifest_errors, "warnings": []}

    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))

    pf = pq.ParquetFile(export_file)
    expected_rows = pf.metadata.num_rows
    expected_sha256 = manifest["integrity"]["parquet_sha256"]

    actual_sha256 = hashlib.sha256()
    with open(export_file, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            actual_sha256.update(chunk)

    if actual_sha256.hexdigest() != expected_sha256:
        return {"valid": False, "errors": ["Parquet file checksum mismatch"], "warnings": []}

    actual_rows = 0
    for batch in pf.iter_batches(batch_size=10000):
        actual_rows += batch.num_rows

    if actual_rows != expected_rows:
        return {"valid": False, "errors": [f"Row count mismatch: expected {expected_rows}, got {actual_rows}"], "warnings": []}

    warnings = []
    if manifest["export_type"] == "incremental":
        warnings.append("This is an incremental export - requires full export for complete recovery")

    return {
        "valid": True,
        "manifest": manifest,
        "errors": [],
        "warnings": warnings,
    }


async def verify_recovery(target_dir: str) -> dict[str, Any]:
    target = Path(target_dir)
    db_path = target / "annotator.db"

    if not db_path.exists():
        return {"valid": False, "errors": ["Database not found in recovery target"], "warnings": []}

    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM datasets")
    dataset_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM data_items")
    item_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM annotations")
    ann_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM annotation_fields")
    field_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM field_categories")
    cat_count = cursor.fetchone()[0]

    orphaned_annotations = cursor.execute("""
        SELECT COUNT(*) FROM annotations a
        LEFT JOIN data_items di ON a.data_item_id = di.id
        WHERE di.id IS NULL
    """).fetchone()[0]

    orphaned_fields = cursor.execute("""
        SELECT COUNT(*) FROM annotation_fields af
        LEFT JOIN annotations a ON af.annotation_id = a.id
        WHERE a.id IS NULL
    """).fetchone()[0]

    missing_crops = cursor.execute("""
        SELECT COUNT(*) FROM annotations
        WHERE crop_path IS NOT NULL AND crop_path != ''
    """).fetchone()[0]

    config_path = target / "dataset_config.yaml"
    config_exists = config_path.exists()

    conn.close()

    errors = []
    if dataset_count == 0:
        errors.append("No datasets found")
    if orphaned_annotations > 0:
        errors.append(f"{orphaned_annotations} orphaned annotations (no data item)")
    if orphaned_fields > 0:
        errors.append(f"{orphaned_fields} orphaned fields (no annotation)")
    if not config_exists:
        errors.append("Config file missing")

    warnings = []
    if missing_crops > 0:
        warnings.append(f"{missing_crops} annotations reference crops - verify crop files exist")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "counts": {
            "datasets": dataset_count,
            "data_items": item_count,
            "annotations": ann_count,
            "fields": field_count,
            "field_categories": cat_count,
            "orphaned_annotations": orphaned_annotations,
            "orphaned_fields": orphaned_fields,
        },
    }