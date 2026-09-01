from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from backend.deps import get_config, get_db
from backend.plugins.base import Geometry
from backend.models import (
    AnnotationCreate, AnnotationUpdate, AnnotationResponse,
    AnnotationWithFields, AnnotationFieldCreate, AnnotationFieldUpdate, AnnotationFieldResponse,
)
from backend.plugins import plugin_registry


router = APIRouter(tags=["annotations"])


@router.post("/annotations", response_model=AnnotationResponse)
async def create_annotation(annotation: AnnotationCreate) -> AnnotationResponse:
    config = get_config()
    db = get_db()

    plugin = plugin_registry.get_for_dataset(config)
    geometry_dict = annotation.geometry.model_dump()
    geometry_json = json.dumps(geometry_dict)

    if not await plugin.validate_geometry(annotation.geometry):
        raise HTTPException(400, "Invalid geometry")

    if not config.plugin_config.allow_intersections:
        intersects = await plugin.check_intersection(
            db, annotation.data_item_id, annotation.geometry
        )
        if intersects:
            raise HTTPException(400, "Annotation intersects with existing annotation")

    cursor = await db.execute_returning(
        """INSERT INTO annotations (data_item_id, annotation_type, geometry_json, parent_annotation_id)
           VALUES (?, ?, ?, ?)""",
        (annotation.data_item_id, annotation.annotation_type, geometry_json, annotation.parent_annotation_id)
    )
    ann_id = cursor.lastrowid

    plugin_config = config.plugin_config
    if plugin_config.crops.auto_save:
        data_item = await db.fetchone("SELECT * FROM data_items WHERE id = ?", (annotation.data_item_id,))
        if data_item:
            crop_result = await plugin.create_crop(db, config, data_item, ann_id, annotation.geometry)
            if crop_result:
                await db.execute(
                    "UPDATE annotations SET crop_path = ? WHERE id = ?",
                    (crop_result.crop_path, ann_id)
                )

    ann = await db.fetchone("SELECT * FROM annotations WHERE id = ?", (ann_id,))
    return AnnotationResponse(**ann)


@router.get("/annotations/{annotation_id}", response_model=AnnotationWithFields)
async def get_annotation(annotation_id: int) -> AnnotationWithFields:
    db = get_db()

    ann = await db.fetchone("SELECT * FROM annotations WHERE id = ?", (annotation_id,))
    if not ann:
        raise HTTPException(404, "Annotation not found")

    fields = await db.fetchall(
        "SELECT * FROM annotation_fields WHERE annotation_id = ?",
        (annotation_id,)
    )
    fields_dict = {f["field_name"]: AnnotationFieldResponse(**f) for f in fields}

    return AnnotationWithFields(
        annotation=AnnotationResponse(**ann),
        fields=fields_dict,
    )


@router.patch("/annotations/{annotation_id}", response_model=AnnotationResponse)
async def update_annotation(annotation_id: int, update: AnnotationUpdate) -> AnnotationResponse:
    config = get_config()
    db = get_db()

    plugin = plugin_registry.get_for_dataset(config)

    ann = await db.fetchone("SELECT * FROM annotations WHERE id = ?", (annotation_id,))
    if not ann:
        raise HTTPException(404, "Annotation not found")

    if ann["is_locked"] and not update.is_locked:
        raise HTTPException(400, "Annotation is locked")

    updates = []
    params = []

    if update.geometry is not None:
        if not await plugin.validate_geometry(update.geometry):
            raise HTTPException(400, "Invalid geometry")

        if not config.plugin_config.allow_intersections:
            intersects = await plugin.check_intersection(
                db, ann["data_item_id"], update.geometry, annotation_id
            )
            if intersects:
                raise HTTPException(400, "Annotation intersects with existing annotation")

        updates.append("geometry_json = ?")
        params.append(json.dumps(update.geometry.model_dump()))

        if config.plugin_config.crops.auto_save:
            data_item = await db.fetchone("SELECT * FROM data_items WHERE id = ?", (ann["data_item_id"],))
            if data_item:
                crop_result = await plugin.regenerate_crop(
                    db, config, data_item, annotation_id, update.geometry, ann["crop_path"]
                )
                if crop_result:
                    await db.execute(
                        "UPDATE annotations SET crop_path = ? WHERE id = ?",
                        (crop_result.crop_path, annotation_id)
                    )

    if update.is_locked is not None:
        updates.append("is_locked = ?")
        params.append(update.is_locked)

    if update.annotation_order is not None:
        updates.append("annotation_order = ?")
        params.append(update.annotation_order)

    if not updates:
        raise HTTPException(400, "No fields to update")

    updates.append("updated_at = CURRENT_TIMESTAMP")
    params.append(annotation_id)

    await db.execute(
        f"UPDATE annotations SET {', '.join(updates)} WHERE id = ?",
        tuple(params)
    )

    ann = await db.fetchone("SELECT * FROM annotations WHERE id = ?", (annotation_id,))
    return AnnotationResponse(**ann)


@router.delete("/annotations/{annotation_id}")
async def delete_annotation(annotation_id: int) -> dict[str, str]:
    config = get_config()
    db = get_db()

    ann = await db.fetchone("SELECT * FROM annotations WHERE id = ?", (annotation_id,))
    if not ann:
        raise HTTPException(404, "Annotation not found")

    if ann["crop_path"]:
        crop_full_path = Path(config.dataset.path) / ann["crop_path"]
        if crop_full_path.exists():
            crop_full_path.unlink(missing_ok=True)

    await db.execute("DELETE FROM annotations WHERE id = ?", (annotation_id,))
    return {"status": "deleted"}


@router.get("/data-items/{item_id}/annotations", response_model=list[AnnotationWithFields])
async def list_annotations(item_id: int) -> list[AnnotationWithFields]:
    db = get_db()

    annotations = await db.fetchall(
        "SELECT * FROM annotations WHERE data_item_id = ? ORDER BY annotation_order",
        (item_id,)
    )
    result = []
    for ann in annotations:
        fields = await db.fetchall(
            "SELECT * FROM annotation_fields WHERE annotation_id = ?",
            (ann["id"],)
        )
        fields_dict = {f["field_name"]: AnnotationFieldResponse(**f) for f in fields}
        result.append(AnnotationWithFields(
            annotation=AnnotationResponse(**ann),
            fields=fields_dict,
        ))
    return result


@router.post("/annotations/{annotation_id}/fields", response_model=AnnotationFieldResponse)
async def create_field(annotation_id: int, field: AnnotationFieldCreate) -> AnnotationFieldResponse:
    db = get_db()

    ann = await db.fetchone("SELECT * FROM annotations WHERE id = ?", (annotation_id,))
    if not ann:
        raise HTTPException(404, "Annotation not found")

    import json
    field_config_json = field.field_config_json or json.dumps({})

    # One annotation holds a single field (name+value). Adding a new field
    # replaces whatever field text was stored on this annotation before.
    async with db.acquire() as conn:
        try:
            await conn.execute(
                "DELETE FROM annotation_fields WHERE annotation_id = ?",
                (annotation_id,)
            )
            cursor = await conn.execute(
                """INSERT INTO annotation_fields (annotation_id, field_name, field_value, datatype, field_config_json)
                   VALUES (?, ?, ?, ?, ?)""",
                (annotation_id, field.field_name, field.field_value, field.datatype, field_config_json)
            )
            await conn.commit()
        except Exception:
            await conn.rollback()
            raise
    field_row = await db.fetchone(
        "SELECT * FROM annotation_fields WHERE id = ?",
        (cursor.lastrowid,)
    )
    return AnnotationFieldResponse(**field_row)


@router.patch("/annotation-fields/{field_id}", response_model=AnnotationFieldResponse)
async def update_field(field_id: int, update: AnnotationFieldUpdate) -> AnnotationFieldResponse:
    db = get_db()

    field = await db.fetchone("SELECT * FROM annotation_fields WHERE id = ?", (field_id,))
    if not field:
        raise HTTPException(404, "Field not found")

    await db.execute(
        "UPDATE annotation_fields SET field_value = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (update.field_value, field_id)
    )

    if update.field_value and field["datatype"] == "enum":
        config = get_config()
        dataset_row = await db.fetchone("SELECT id FROM datasets WHERE name = ?", (config.dataset.name,))
        if dataset_row:
            await _add_category_if_new(db, dataset_row["id"], field["field_name"], update.field_value)

    field_row = await db.fetchone("SELECT * FROM annotation_fields WHERE id = ?", (field_id,))
    return AnnotationFieldResponse(**field_row)


async def _add_category_if_new(db, dataset_id: int, field_name: str, value: str) -> None:
    normalized = value.lower()
    await db.execute(
        """INSERT INTO field_categories (dataset_id, field_name, category_value, normalized_value, source)
           VALUES (?, ?, ?, ?, 'manual')
           ON CONFLICT(dataset_id, field_name, normalized_value) DO UPDATE SET
               count = count + 1, category_value = excluded.category_value""",
        (dataset_id, field_name, value, normalized)
    )


@router.post("/annotations/{annotation_id}/lock")
async def lock_annotation(annotation_id: int) -> dict[str, bool]:
    db = get_db()
    await db.execute(
        "UPDATE annotations SET is_locked = TRUE, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (annotation_id,)
    )
    return {"locked": True}


@router.post("/annotations/{annotation_id}/unlock")
async def unlock_annotation(annotation_id: int) -> dict[str, bool]:
    db = get_db()
    await db.execute(
        "UPDATE annotations SET is_locked = FALSE, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (annotation_id,)
    )
    return {"locked": False}


@router.post("/annotations/{annotation_id}/duplicate")
async def duplicate_annotation(annotation_id: int) -> AnnotationResponse:
    config = get_config()
    db = get_db()

    ann = await db.fetchone("SELECT * FROM annotations WHERE id = ?", (annotation_id,))
    if not ann:
        raise HTTPException(404, "Annotation not found")

    geometry_json = ann["geometry_json"]

    cursor = await db.execute_returning(
        """INSERT INTO annotations (data_item_id, annotation_type, geometry_json, parent_annotation_id, annotation_order)
           VALUES (?, ?, ?, ?, (SELECT COALESCE(MAX(annotation_order), 0) + 1 FROM annotations WHERE data_item_id = ?))""",
        (ann["data_item_id"], ann["annotation_type"], geometry_json, ann["parent_annotation_id"], ann["data_item_id"])
    )
    new_ann_id = cursor.lastrowid

    fields = await db.fetchall(
        "SELECT * FROM annotation_fields WHERE annotation_id = ?",
        (annotation_id,)
    )
    for field in fields:
        await db.execute(
            """INSERT INTO annotation_fields (annotation_id, field_name, field_value, datatype, field_config_json)
               VALUES (?, ?, ?, ?, ?)""",
            (new_ann_id, field["field_name"], field["field_value"], field["datatype"], field["field_config_json"])
        )

    if config.plugin_config.crops.auto_save:
        plugin = plugin_registry.get_for_dataset(config)
        data_item = await db.fetchone("SELECT * FROM data_items WHERE id = ?", (ann["data_item_id"],))
        if data_item:
            g = json.loads(geometry_json)
            geometry = Geometry(
                type=g["type"],
                coordinates=g["coordinates"],
                rotation=g.get("rotation", 0) or 0,
            )
            crop_result = await plugin.create_crop(db, config, data_item, new_ann_id, geometry)
            if crop_result:
                await db.execute(
                    "UPDATE annotations SET crop_path = ? WHERE id = ?",
                    (crop_result.crop_path, new_ann_id)
                )

    new_ann = await db.fetchone("SELECT * FROM annotations WHERE id = ?", (new_ann_id,))
    return AnnotationResponse(**new_ann)


from pathlib import Path