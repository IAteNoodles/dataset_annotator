from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class DatasetCreate(BaseModel):
    name: str
    plugin: Literal["image", "text", "audio"] = "image"
    path: str
    recursive: bool = True
    extensions: list[str] = Field(default_factory=lambda: [".jpg", ".jpeg", ".png", ".tiff", ".bmp", ".webp"])
    sort_by: Literal["path", "mtime", "size", "random"] = "path"
    page_size: int = 100


class DatasetResponse(BaseModel):
    id: int
    name: str
    plugin_type: str
    config_hash: str
    created_at: datetime
    updated_at: datetime
    path: str | None = None


class DatasetOpenRequest(BaseModel):
    path: str


class DatasetListResponse(BaseModel):
    datasets: list[DatasetResponse]
    total: int


class DataItemResponse(BaseModel):
    id: int
    dataset_id: int
    source_path: str
    rel_path: str
    mime_type: str | None
    size_bytes: int
    sha256: str
    width: int | None
    height: int | None
    duration_ms: int | None
    metadata_json: str | None
    status: str
    sort_order: int
    created_at: datetime
    updated_at: datetime


class DataItemListResponse(BaseModel):
    items: list[DataItemResponse]
    total: int
    page: int
    page_size: int


class AnnotationGeometry(BaseModel):
    type: Literal["rectangle", "rotated_rectangle", "polygon", "point", "line"]
    coordinates: list[list[float]] | list[float]
    rotation: float = 0


class AnnotationCreate(BaseModel):
    data_item_id: int
    annotation_type: Literal["rectangle", "rotated_rectangle", "polygon", "point", "line"]
    geometry: AnnotationGeometry
    parent_annotation_id: int | None = None


class AnnotationUpdate(BaseModel):
    geometry: AnnotationGeometry | None = None
    is_locked: bool | None = None
    annotation_order: int | None = None


class AnnotationResponse(BaseModel):
    id: int
    data_item_id: int
    annotation_type: str
    geometry_json: str
    crop_path: str | None
    parent_annotation_id: int | None
    is_locked: bool
    annotation_order: int
    created_at: datetime
    updated_at: datetime


class AnnotationFieldCreate(BaseModel):
    field_name: str
    field_value: str | None = None
    datatype: Literal["string", "number", "enum", "boolean", "json"]
    field_config_json: str | None = None


class AnnotationFieldUpdate(BaseModel):
    field_value: str | None = None


class AnnotationFieldResponse(BaseModel):
    id: int
    annotation_id: int
    field_name: str
    field_value: str | None
    datatype: str
    field_config_json: str | None
    created_at: datetime
    updated_at: datetime


class AnnotationWithFields(BaseModel):
    annotation: AnnotationResponse
    fields: dict[str, AnnotationFieldResponse]


class SuggestionRequest(BaseModel):
    field_name: str
    query: str
    limit: int = 10


class SuggestionResponse(BaseModel):
    suggestions: list[str]


class FieldCategoryCreate(BaseModel):
    field_name: str
    category_value: str
    source: str = "manual"


class FieldCategoryResponse(BaseModel):
    id: int
    dataset_id: int
    field_name: str
    category_value: str
    normalized_value: str
    count: int
    source: str
    created_at: datetime


class ExportEstimateRequest(BaseModel):
    dataset_id: int
    type: Literal["full", "incremental"]
    export_mode: Literal["annotated", "full"] = "annotated"


class ExportEstimateResponse(BaseModel):
    estimated_size_gb: float
    estimated_time_minutes: int
    annotation_count: int
    image_count: int
    crop_count: int
    output_path: str


class ExportRequest(BaseModel):
    dataset_id: int
    type: Literal["full", "incremental"]
    push_s3: bool = False
    export_mode: Literal["annotated", "full"] = "annotated"
    verify_images: bool = False
    formats: list[Literal["parquet", "arrow"]] = Field(default_factory=lambda: ["parquet"])


class ExportResponse(BaseModel):
    export_id: str
    status: Literal["started", "completed", "failed"]
    message: str


class ExportStatusResponse(BaseModel):
    export_id: str
    status: Literal["pending", "running", "completed", "failed"]
    progress: float
    current_step: str
    records_processed: int
    total_records: int
    error: str | None = None
    output_paths: list[str] = Field(default_factory=list)


class S3SyncRequest(BaseModel):
    dataset_id: int
    fetch: bool = True
    push: bool = False


class S3SyncResponse(BaseModel):
    synced: bool
    fetched: int
    pushed: int
    errors: list[str] = Field(default_factory=list)


class S3ObjectResponse(BaseModel):
    key: str
    size: int
    last_modified: datetime
    etag: str


class RecoverVerifyRequest(BaseModel):
    export_path: str


class RecoverVerifyResponse(BaseModel):
    valid: bool
    manifest: dict[str, Any] | None = None
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class RecoverFromS3Request(BaseModel):
    dataset_name: str
    bucket: str
    target_dir: str
    region: str | None = None


class RecoverFromExportRequest(BaseModel):
    export_path: str
    target_dir: str


class RecoverResponse(BaseModel):
    success: bool
    target_dir: str
    dataset_id: int | None = None
    errors: list[str] = Field(default_factory=list)


class SnapshotCreateRequest(BaseModel):
    dataset_id: int
    trigger: str = "manual"


class SnapshotResponse(BaseModel):
    id: int
    dataset_id: int
    snapshot_path: str
    annotation_count: int
    data_item_count: int
    trigger: str
    sha256: str
    size_bytes: int
    created_at: datetime


class SnapshotRestoreRequest(BaseModel):
    dataset_id: int
    snapshot_id: int


class ImportPreviewRequest(BaseModel):
    format: Literal["coco", "yolo", "labelme", "custom"]
    file_content: str


class ImportPreviewResponse(BaseModel):
    annotation_count: int
    fields_found: list[str]
    sample_annotations: list[dict[str, Any]]
    warnings: list[str] = Field(default_factory=list)


class ImportExecuteRequest(BaseModel):
    dataset_id: int
    format: Literal["coco", "yolo", "labelme", "custom"]
    file_content: str
    field_mapping: dict[str, str]


class ImportExecuteResponse(BaseModel):
    imported: int
    skipped: int
    errors: list[str] = Field(default_factory=list)


class ConfigValidationRequest(BaseModel):
    config_yaml: str


class ConfigValidationResponse(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    config: dict[str, Any] | None = None


class HealthResponse(BaseModel):
    status: str
    version: str
    database: str
    uptime_seconds: float


class WSMessage(BaseModel):
    type: str
    payload: dict[str, Any]


# S3 Configuration Models
class S3ConfigRequest(BaseModel):
    enabled: bool = False
    bucket: str = ""
    region: str = "us-east-1"
    prefix: str = "datasets/"
    multipart_threshold_mb: int = 100
    multipart_chunksize_mb: int = 50
    fetch_on_startup: bool = False
    fetch: dict = Field(default_factory=lambda: {
        "exports": True,
        "snapshots": True,
        "cursor": True,
        "verify_checksums": True
    })
    push: dict = Field(default_factory=lambda: {
        "exports": True,
        "snapshots": True,
        "cursor": True,
        "overwrite": False
    })
    max_bandwidth_mbps: int = 0
    access_key_id: str = ""
    secret_access_key: str = ""
    endpoint_url: str = ""


class S3TestConnectionRequest(BaseModel):
    config: S3ConfigRequest


class S3TestConnectionResponse(BaseModel):
    success: bool
    message: str


class S3CreateBucketRequest(BaseModel):
    config: S3ConfigRequest


class S3CreateBucketResponse(BaseModel):
    success: bool
    message: str


class S3SaveConfigRequest(BaseModel):
    config: S3ConfigRequest


class S3SaveConfigResponse(BaseModel):
    success: bool
    message: str
    config: S3ConfigRequest | None = None


class WSMessage(BaseModel):
    type: str
    payload: dict[str, Any]


class WSAnnotationUpdate(BaseModel):
    type: Literal["annotation_created", "annotation_updated", "annotation_deleted", "annotation_moved"]
    annotation_id: int
    data_item_id: int
    geometry: dict[str, Any] | None = None
    fields: dict[str, str] | None = None


class WSSuggestionUpdate(BaseModel):
    type: Literal["suggestions_updated"]
    field_name: str
    suggestions: list[str]


class WSExportProgress(BaseModel):
    type: Literal["export_progress"]
    export_id: str
    progress: float
    current_step: str
    records_processed: int
    total_records: int