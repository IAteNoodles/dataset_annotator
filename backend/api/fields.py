from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from backend.deps import get_config, get_db
from backend.models import (
    SuggestionRequest, SuggestionResponse,
    FieldCategoryCreate, FieldCategoryResponse,
)

router = APIRouter(tags=["fields"])


@router.post("/suggestions", response_model=SuggestionResponse)
async def get_suggestions(request: SuggestionRequest) -> SuggestionResponse:
    config = get_config()
    db = get_db()

    dataset_row = await db.fetchone("SELECT id FROM datasets WHERE name = ?", (config.dataset.name,))
    if not dataset_row:
        return SuggestionResponse(suggestions=[])

    dataset_id = dataset_row["id"]
    field_name = request.field_name
    query = request.query
    limit = request.limit

    if config.suggestions.case_insensitive:
        normalized_query = query.lower()
        sql_query = """
            SELECT category_value, count FROM field_categories
            WHERE dataset_id = ? AND field_name = ? AND normalized_value LIKE ?
            ORDER BY count DESC LIMIT ?
        """
        params = (dataset_id, field_name, f"%{normalized_query}%", limit)
    else:
        sql_query = """
            SELECT category_value, count FROM field_categories
            WHERE dataset_id = ? AND field_name = ? AND category_value LIKE ?
            ORDER BY count DESC LIMIT ?
        """
        params = (dataset_id, field_name, f"%{query}%", limit)

    if config.suggestions.ranking == "recency":
        sql_query = sql_query.replace("ORDER BY count DESC", "ORDER BY created_at DESC")
    elif config.suggestions.ranking == "alphabetical":
        sql_query = sql_query.replace("ORDER BY count DESC", "ORDER BY category_value ASC")

    rows = await db.fetchall(sql_query, params)
    suggestions = [row["category_value"] for row in rows]

    if config.suggestions.fuzzy_threshold < 1.0 and query:
        all_rows = await db.fetchall(
            "SELECT category_value FROM field_categories WHERE dataset_id = ? AND field_name = ?",
            (dataset_id, field_name)
        )
        all_values = [row["category_value"] for row in all_rows]
        fuzzy_suggestions = _fuzzy_match(query, all_values, config.suggestions.fuzzy_threshold, limit)
        for s in fuzzy_suggestions:
            if s not in suggestions:
                suggestions.append(s)
        suggestions = suggestions[:limit]

    return SuggestionResponse(suggestions=suggestions)


def _fuzzy_match(query: str, values: list[str], threshold: float, limit: int) -> list[str]:
    from difflib import SequenceMatcher
    query_lower = query.lower()
    matches = []
    for value in values:
        ratio = SequenceMatcher(None, query_lower, value.lower()).ratio()
        if ratio >= threshold:
            matches.append((ratio, value))
    matches.sort(reverse=True)
    return [v for _, v in matches[:limit]]


@router.post("/field-categories", response_model=FieldCategoryResponse)
async def add_field_category(category: FieldCategoryCreate) -> FieldCategoryResponse:
    config = get_config()
    db = get_db()

    dataset_row = await db.fetchone("SELECT id FROM datasets WHERE name = ?", (config.dataset.name,))
    if not dataset_row:
        raise HTTPException(404, "Dataset not found")

    dataset_id = dataset_row["id"]
    normalized = category.category_value.lower()

    await db.execute(
        """INSERT INTO field_categories (dataset_id, field_name, category_value, normalized_value, source)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(dataset_id, field_name, normalized_value) DO UPDATE SET
               count = count + 1, category_value = excluded.category_value""",
        (dataset_id, category.field_name, category.category_value, normalized, category.source)
    )

    cat = await db.fetchone(
        "SELECT * FROM field_categories WHERE dataset_id = ? AND field_name = ? AND normalized_value = ?",
        (dataset_id, category.field_name, normalized)
    )
    return FieldCategoryResponse(**cat)


@router.get("/field-categories", response_model=list[FieldCategoryResponse])
async def list_field_categories(
    dataset_id: int,
    field_name: str | None = Query(None),
) -> list[FieldCategoryResponse]:
    db = get_db()

    if field_name:
        rows = await db.fetchall(
            "SELECT * FROM field_categories WHERE dataset_id = ? AND field_name = ? ORDER BY count DESC",
            (dataset_id, field_name)
        )
    else:
        rows = await db.fetchall(
            "SELECT * FROM field_categories WHERE dataset_id = ? ORDER BY field_name, count DESC",
            (dataset_id,)
        )
    return [FieldCategoryResponse(**row) for row in rows]


@router.get("/fields/config")
async def get_field_configs() -> list[dict]:
    config = get_config()
    return [field.model_dump() for field in config.fields]


@router.get("/fields/enum-values/{field_name}")
async def get_enum_values(field_name: str) -> list[str]:
    config = get_config()
    db = get_db()

    field_config = next((f for f in config.fields if f.name == field_name), None)
    if not field_config or field_config.datatype != "enum":
        raise HTTPException(404, "Field not found or not an enum")

    dataset_row = await db.fetchone("SELECT id FROM datasets WHERE name = ?", (config.dataset.name,))
    if not dataset_row:
        return field_config.enum_values or []

    dataset_id = dataset_row["id"]
    rows = await db.fetchall(
        "SELECT category_value FROM field_categories WHERE dataset_id = ? AND field_name = ? ORDER BY count DESC",
        (dataset_id, field_name)
    )
    dynamic_values = [row["category_value"] for row in rows]

    base_values = field_config.enum_values or []
    all_values = list(dict.fromkeys(base_values + dynamic_values))

    if field_config.allow_custom:
        all_values.append(field_config.custom_label)

    return all_values