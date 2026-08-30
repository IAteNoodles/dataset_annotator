from __future__ import annotations

import json
from typing import Any

from backend.config import AppConfig
from backend.database import Database
from backend.plugins import plugin_registry


async def preview_import(format: str, file_content: str) -> dict[str, Any]:
    if format == "coco":
        return await _preview_coco(file_content)
    elif format == "yolo":
        return await _preview_yolo(file_content)
    elif format == "labelme":
        return await _preview_labelme(file_content)
    else:
        return await _preview_custom(file_content)


async def _preview_coco(file_content: str) -> dict[str, Any]:
    data = json.loads(file_content)

    annotations = data.get("annotations", [])
    categories = {c["id"]: c["name"] for c in data.get("categories", [])}
    images = {img["id"]: img for img in data.get("images", [])}

    fields_found = set()
    for ann in annotations[:10]:
        for key in ann.keys():
            if key not in ["id", "image_id", "category_id", "bbox", "segmentation", "area", "iscrowd"]:
                fields_found.add(key)

    sample = []
    for ann in annotations[:5]:
        img = images.get(ann.get("image_id"), {})
        cat = categories.get(ann.get("category_id"), "unknown")
        sample.append({
            "image": img.get("file_name", "unknown"),
            "category": cat,
            "bbox": ann.get("bbox"),
            "fields": {k: v for k, v in ann.items() if k not in ["id", "image_id", "category_id", "bbox", "segmentation", "area", "iscrowd"]},
        })

    return {
        "annotation_count": len(annotations),
        "fields_found": list(fields_found),
        "sample_annotations": sample,
        "warnings": ["COCO format imports bounding boxes as rectangles"],
    }


async def _preview_yolo(file_content: str) -> dict[str, Any]:
    lines = file_content.strip().split("\n")
    annotations = []

    for line in lines[:100]:
        parts = line.strip().split()
        if len(parts) >= 5:
            annotations.append({
                "class_id": int(parts[0]),
                "x_center": float(parts[1]),
                "y_center": float(parts[2]),
                "width": float(parts[3]),
                "height": float(parts[4]),
            })

    return {
        "annotation_count": len(annotations),
        "fields_found": ["class_id", "x_center", "y_center", "width", "height"],
        "sample_annotations": annotations[:5],
        "warnings": ["YOLO format requires class mapping file", "Coordinates are normalized (0-1)"],
    }


async def _preview_labelme(file_content: str) -> dict[str, Any]:
    data = json.loads(file_content)

    shapes = data.get("shapes", [])
    fields_found = set()

    for shape in shapes[:10]:
        for key in shape.keys():
            if key not in ["label", "points", "group_id", "shape_type", "flags"]:
                fields_found.add(key)

    sample = []
    for shape in shapes[:5]:
        sample.append({
            "label": shape.get("label"),
            "shape_type": shape.get("shape_type"),
            "points": shape.get("points"),
            "fields": {k: v for k, v in shape.items() if k not in ["label", "points", "group_id", "shape_type", "flags"]},
        })

    return {
        "annotation_count": len(shapes),
        "fields_found": list(fields_found),
        "sample_annotations": sample,
        "warnings": ["LabelMe imports polygons/rectangles based on shape_type"],
    }


async def _preview_custom(file_content: str) -> dict[str, Any]:
    data = json.loads(file_content)

    if isinstance(data, list):
        annotations = data
    elif isinstance(data, dict) and "annotations" in data:
        annotations = data["annotations"]
    else:
        annotations = [data]

    fields_found = set()
    for ann in annotations[:10]:
        if isinstance(ann, dict):
            fields_found.update(ann.keys())

    sample = annotations[:5] if isinstance(annotations, list) else [annotations]

    return {
        "annotation_count": len(annotations) if isinstance(annotations, list) else 1,
        "fields_found": list(fields_found),
        "sample_annotations": sample,
        "warnings": ["Custom JSON format - ensure field mapping is correct"],
    }


async def execute_import(
    db: Database,
    config: AppConfig,
    dataset_id: int,
    format: str,
    file_content: str,
    field_mapping: dict[str, str],
) -> dict[str, Any]:
    plugin = plugin_registry.get_for_dataset(config)

    if format == "coco":
        return await _import_coco(db, config, dataset_id, file_content, field_mapping, plugin)
    elif format == "yolo":
        return await _import_yolo(db, config, dataset_id, file_content, field_mapping, plugin)
    elif format == "labelme":
        return await _import_labelme(db, config, dataset_id, file_content, field_mapping, plugin)
    else:
        return await _import_custom(db, config, dataset_id, file_content, field_mapping, plugin)


async def _import_coco(
    db: Database,
    config: AppConfig,
    dataset_id: int,
    file_content: str,
    field_mapping: dict[str, str],
    plugin,
) -> dict[str, Any]:
    data = json.loads(file_content)
    annotations = data.get("annotations", [])
    categories = {c["id"]: c["name"] for c in data.get("categories", [])}
    images = {img["id"]: img for img in data.get("images", [])}

    imported = 0
    skipped = 0
    errors = []

    for ann in annotations:
        try:
            img = images.get(ann.get("image_id"))
            if not img:
                skipped += 1
                continue

            data_item = await db.fetchone(
                "SELECT id FROM data_items WHERE dataset_id = ? AND rel_path = ?",
                (dataset_id, img.get("file_name", ""))
            )
            if not data_item:
                skipped += 1
                continue

            bbox = ann.get("bbox", [0, 0, 0, 0])
            x, y, w, h = bbox
            geometry = {
                "type": "rectangle",
                "coordinates": [[x, y], [x + w, y + h]],
            }

            if not await plugin.validate_geometry(type("Geometry", (), {"type": "rectangle", "coordinates": geometry["coordinates"]})()):
                skipped += 1
                continue

            cursor = await db.execute(
                """INSERT INTO annotations (data_item_id, annotation_type, geometry_json)
                   VALUES (?, ?, ?)""",
                (data_item["id"], "rectangle", json.dumps(geometry))
            )
            ann_id = cursor.lastrowid

            category_name = categories.get(ann.get("category_id"), "Other")
            await db.execute(
                """INSERT INTO annotation_fields (annotation_id, field_name, field_value, datatype)
                   VALUES (?, 'Type', ?, 'enum')""",
                (ann_id, category_name)
            )

            for src_field, dst_field in field_mapping.items():
                if src_field in ann:
                    await db.execute(
                        """INSERT INTO annotation_fields (annotation_id, field_name, field_value, datatype)
                           VALUES (?, ?, ?, 'string')""",
                        (ann_id, dst_field, str(ann[src_field]))
                    )

            imported += 1

        except Exception as e:
            errors.append(f"Annotation {ann.get('id')}: {e}")
            skipped += 1

    return {"imported": imported, "skipped": skipped, "errors": errors}


async def _import_yolo(
    db: Database,
    config: AppConfig,
    dataset_id: int,
    file_content: str,
    field_mapping: dict[str, str],
    plugin,
) -> dict[str, Any]:
    lines = file_content.strip().split("\n")
    imported = 0
    skipped = 0
    errors = []

    for line in lines:
        try:
            parts = line.strip().split()
            if len(parts) < 5:
                continue

            class_id = int(parts[0])
            x_center = float(parts[1])
            y_center = float(parts[2])
            width = float(parts[3])
            height = float(parts[4])

            data_item = await db.fetchone(
                "SELECT id, width, height FROM data_items WHERE dataset_id = ? ORDER BY sort_order LIMIT 1 OFFSET ?",
                (dataset_id, imported)
            )
            if not data_item:
                skipped += 1
                continue

            img_w = data_item["width"] or 1
            img_h = data_item["height"] or 1

            x = (x_center - width / 2) * img_w
            y = (y_center - height / 2) * img_h
            w = width * img_w
            h = height * img_h

            geometry = {
                "type": "rectangle",
                "coordinates": [[x, y], [x + w, y + h]],
            }

            cursor = await db.execute(
                """INSERT INTO annotations (data_item_id, annotation_type, geometry_json)
                   VALUES (?, ?, ?)""",
                (data_item["id"], "rectangle", json.dumps(geometry))
            )
            ann_id = cursor.lastrowid

            await db.execute(
                """INSERT INTO annotation_fields (annotation_id, field_name, field_value, datatype)
                   VALUES (?, 'Type', ?, 'enum')""",
                (ann_id, field_mapping.get("class", "Other"))
            )

            imported += 1

        except Exception as e:
            errors.append(f"Line: {e}")
            skipped += 1

    return {"imported": imported, "skipped": skipped, "errors": errors}


async def _import_labelme(
    db: Database,
    config: AppConfig,
    dataset_id: int,
    file_content: str,
    field_mapping: dict[str, str],
    plugin,
) -> dict[str, Any]:
    data = json.loads(file_content)
    shapes = data.get("shapes", [])

    data_item = await db.fetchone(
        "SELECT id, width, height FROM data_items WHERE dataset_id = ? AND rel_path = ?",
        (dataset_id, data.get("imagePath", ""))
    )
    if not data_item:
        return {"imported": 0, "skipped": len(shapes), "errors": ["Image not found in dataset"]}

    imported = 0
    skipped = 0
    errors = []

    for shape in shapes:
        try:
            shape_type = shape.get("shape_type", "rectangle")
            points = shape.get("points", [])
            label = shape.get("label", "Other")

            if shape_type == "rectangle" and len(points) == 2:
                geometry = {
                    "type": "rectangle",
                    "coordinates": points,
                }
                ann_type = "rectangle"
            elif shape_type == "polygon" and len(points) >= 3:
                geometry = {
                    "type": "polygon",
                    "coordinates": points,
                }
                ann_type = "polygon"
            else:
                skipped += 1
                continue

            cursor = await db.execute(
                """INSERT INTO annotations (data_item_id, annotation_type, geometry_json)
                   VALUES (?, ?, ?)""",
                (data_item["id"], ann_type, json.dumps(geometry))
            )
            ann_id = cursor.lastrowid

            await db.execute(
                """INSERT INTO annotation_fields (annotation_id, field_name, field_value, datatype)
                   VALUES (?, 'Type', ?, 'enum')""",
                (ann_id, label)
            )

            for src_field, dst_field in field_mapping.items():
                if src_field in shape:
                    await db.execute(
                        """INSERT INTO annotation_fields (annotation_id, field_name, field_value, datatype)
                           VALUES (?, ?, ?, 'string')""",
                        (ann_id, dst_field, str(shape[src_field]))
                    )

            imported += 1

        except Exception as e:
            errors.append(f"Shape: {e}")
            skipped += 1

    return {"imported": imported, "skipped": skipped, "errors": errors}


async def _import_custom(
    db: Database,
    config: AppConfig,
    dataset_id: int,
    file_content: str,
    field_mapping: dict[str, str],
    plugin,
) -> dict[str, Any]:
    data = json.loads(file_content)

    if isinstance(data, list):
        annotations = data
    elif isinstance(data, dict) and "annotations" in data:
        annotations = data["annotations"]
    else:
        annotations = [data]

    imported = 0
    skipped = 0
    errors = []

    for ann in annotations:
        try:
            if not isinstance(ann, dict):
                skipped += 1
                continue

            item_id = ann.get("item_id") or ann.get("data_item_id")
            if not item_id:
                skipped += 1
                continue

            data_item = await db.fetchone(
                "SELECT id FROM data_items WHERE id = ? AND dataset_id = ?",
                (item_id, dataset_id)
            )
            if not data_item:
                skipped += 1
                continue

            geometry = ann.get("geometry") or ann.get("coordinates")
            ann_type = ann.get("annotation_type", "rectangle")

            if not geometry:
                skipped += 1
                continue

            cursor = await db.execute(
                """INSERT INTO annotations (data_item_id, annotation_type, geometry_json)
                   VALUES (?, ?, ?)""",
                (data_item["id"], ann_type, json.dumps(geometry))
            )
            ann_id = cursor.lastrowid

            for src_field, dst_field in field_mapping.items():
                if src_field in ann:
                    await db.execute(
                        """INSERT INTO annotation_fields (annotation_id, field_name, field_value, datatype)
                           VALUES (?, ?, ?, 'string')""",
                        (ann_id, dst_field, str(ann[src_field]))
                    )

            imported += 1

        except Exception as e:
            errors.append(f"Annotation: {e}")
            skipped += 1

    return {"imported": imported, "skipped": skipped, "errors": errors}