from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatasetConfig(BaseModel):
    name: str
    plugin: Literal["image", "text", "audio"] = "image"
    path: str
    recursive: bool = True
    extensions: list[str] = Field(default_factory=lambda: [".jpg", ".jpeg", ".png", ".tiff", ".bmp", ".webp"])
    sort_by: Literal["path", "mtime", "size", "random"] = "path"
    page_size: int = 100

    @field_validator("path")
    @classmethod
    def resolve_path(cls, v: str) -> str:
        return str(Path(v).expanduser().resolve())


class PluginDisplayConfig(BaseModel):
    max_dimension: int = 2560
    show_grid: bool = False
    grid_size: int = 50
    default_zoom: str = "fit"
    zoom_steps: list[float] = Field(default_factory=lambda: [0.25, 0.5, 0.75, 1, 1.5, 2, 3, 4])


class PluginCropsConfig(BaseModel):
    auto_save: bool = True
    output_dir: str = ".crops"
    naming_template: str = "{dataset}_{item_id}_{annotation_id}"
    format: Literal["png", "jpeg", "webp"] = "png"
    quality: int = 95
    padding: int = 5
    context_padding: int = 0


class PluginConfig(BaseModel):
    annotation_mode: Literal["rectangle_box", "rotated_box", "polygon", "point", "line"] = "rectangle_box"
    allow_intersections: bool = True
    allow_movement: bool = True
    snap_threshold: int = 5
    min_annotation_size: int = 10
    display: PluginDisplayConfig = Field(default_factory=PluginDisplayConfig)
    crops: PluginCropsConfig = Field(default_factory=PluginCropsConfig)


class FieldValidationConfig(BaseModel):
    min_length: int | None = None
    max_length: int | None = None


class FieldVisibleWhenConfig(BaseModel):
    field: str
    value: str | list[str]


class FieldConfig(BaseModel):
    name: str
    label: str
    datatype: Literal["string", "number", "enum", "boolean", "json"]
    required: bool = False
    internal: bool = False
    hidden: bool = False
    source: str | None = None
    provide_suggestions: bool = False
    suggestion_limit: int = 10
    case_insensitive: bool = True
    placeholder: str | None = None
    validation: FieldValidationConfig | None = None
    description: str | None = None
    enum_values: list[str] | None = None
    dynamic_enum: bool = False
    allow_custom: bool = False
    custom_label: str = "Other (specify)"
    visible_when: FieldVisibleWhenConfig | None = None
    default: Any = None
    min: float | None = None
    max: float | None = None
    step: float | None = None
    multiline: bool = False


class UILayoutConfig(BaseModel):
    sidebar_width: int = 320
    toolbar_position: Literal["top", "bottom", "left", "right"] = "top"
    show_thumbnails: bool = True
    thumbnail_size: int = 120
    show_status_badges: bool = True


class UICanvasConfig(BaseModel):
    type_colors: dict[str, str] = Field(default_factory=dict)
    default_color: str = "#2ecc71"
    line_width: int = 2
    fill_opacity: float = 0.15
    show_labels: bool = True
    label_template: str = "{Type}: {Text}"
    highlight_selected: bool = True
    highlight_color: str = "#fff"
    highlight_width: int = 3


class UIShortcutsConfig(BaseModel):
    next_item: str = "ArrowRight"
    prev_item: str = "ArrowLeft"
    save: str = "Ctrl+S"
    new_annotation: str = "N"
    delete_annotation: str = "Delete"
    undo: str = "Ctrl+Z"
    redo: str = "Ctrl+Y"
    zoom_in: str = "="
    zoom_out: str = "-"
    zoom_fit: str = "0"
    pan: str = "Space"
    toggle_sidebar: str = "B"
    copy_annotation: str = "Ctrl+C"
    paste_annotation: str = "Ctrl+V"
    duplicate_annotation: str = "D"
    lock_annotation: str = "L"


class UIFieldPanelConfig(BaseModel):
    auto_focus_first: bool = True
    show_field_descriptions: bool = True
    compact_mode: bool = False
    group_by_section: bool = True


class UIOperationsConfig(BaseModel):
    show_export: bool = True
    show_s3_sync: bool = True
    show_recovery: bool = True
    show_snapshots: bool = True
    show_import: bool = True


class UIConfig(BaseModel):
    theme: Literal["light", "dark", "auto"] = "dark"
    language: str = "en"
    layout: UILayoutConfig = Field(default_factory=UILayoutConfig)
    canvas: UICanvasConfig = Field(default_factory=UICanvasConfig)
    shortcuts: UIShortcutsConfig = Field(default_factory=UIShortcutsConfig)
    field_panel: UIFieldPanelConfig = Field(default_factory=UIFieldPanelConfig)
    operations: UIOperationsConfig = Field(default_factory=UIOperationsConfig)


class SnapshotConfig(BaseModel):
    enabled: bool = True
    interval: int = 100
    triggers: list[str] = Field(default_factory=lambda: ["interval", "export", "shutdown", "manual"])
    max_snapshots: int = 10
    path: str = "./snapshots"
    compress: bool = True
    verify: bool = True


class ExportImageEncodingConfig(BaseModel):
    format: Literal["png", "jpeg", "webp"] = "png"
    quality: int = 100
    max_dimension: int = 0


class ExportParquetConfig(BaseModel):
    compression: Literal["zstd", "snappy", "gzip", "brotli", "lz4", "none"] = "zstd"
    compression_level: int = 3
    row_group_size: int = 50000
    data_page_size: int = 524288
    write_statistics: bool = True
    use_dictionary: bool = True
    dictionary_pagesize_limit: int = 1048576
    write_page_checksums: bool = True
    write_footer_checksums: bool = True


class ExportArrowConfig(BaseModel):
    compression: Literal["zstd", "lz4", "none"] = "zstd"
    compression_level: int = 3


class ExportEstimationConfig(BaseModel):
    sample_rows: int = 1000
    include_images_in_estimate: bool = True


class ExportIncrementalConfig(BaseModel):
    enabled: bool = True
    strategy: Literal["annotation_updated_at"] = "annotation_updated_at"
    include_item_status_changes: bool = True
    min_interval_minutes: int = 30
    full_export_every: int = 10


class ExportConfig(BaseModel):
    output_dir: str = "./exports"
    default_formats: list[Literal["parquet", "arrow"]] = Field(default_factory=lambda: ["parquet"])
    embed_source_images: bool = True
    embed_crops: bool = True
    image_encoding: ExportImageEncodingConfig = Field(default_factory=ExportImageEncodingConfig)
    parquet: ExportParquetConfig = Field(default_factory=ExportParquetConfig)
    arrow: ExportArrowConfig = Field(default_factory=ExportArrowConfig)
    flatten_fields: bool = True
    partition_by: list[str] = Field(default_factory=lambda: ["dataset_name"])
    only_completed: bool = False
    include_skipped: bool = True
    include_pending: bool = True
    include_internal_fields: bool = True
    verify_after_write: bool = True
    generate_manifest: bool = True
    estimation: ExportEstimationConfig = Field(default_factory=ExportEstimationConfig)
    incremental: ExportIncrementalConfig = Field(default_factory=ExportIncrementalConfig)


class S3FetchConfig(BaseModel):
    exports: bool = True
    snapshots: bool = True
    cursor: bool = True
    verify_checksums: bool = True


class S3PushConfig(BaseModel):
    exports: bool = True
    snapshots: bool = True
    cursor: bool = True
    overwrite: bool = False


class S3Config(BaseModel):
    enabled: bool = True
    bucket: str
    region: str = "us-east-1"
    prefix: str = "datasets/"
    multipart_threshold_mb: int = 100
    multipart_chunksize_mb: int = 50
    fetch_on_startup: bool = True
    fetch: S3FetchConfig = Field(default_factory=S3FetchConfig)
    push: S3PushConfig = Field(default_factory=S3PushConfig)
    max_bandwidth_mbps: int = 0
    access_key_id: str = ""
    secret_access_key: str = ""
    endpoint_url: str = ""


class SuggestionsConfig(BaseModel):
    enabled: bool = True
    debounce_ms: int = 300
    max_suggestions: int = 10
    min_chars: int = 1
    ranking: Literal["frequency", "recency", "alphabetical"] = "frequency"
    scope: Literal["current_dataset", "all_datasets"] = "current_dataset"
    fuzzy_threshold: float = 0.8
    pre_populate_sources: list[str] = Field(default_factory=list)


class PerformanceConfig(BaseModel):
    wal_mode: bool = True
    busy_timeout: int = 5000
    pool_size: int = 5
    batch_size: int = 1000
    auto_vacuum: bool = True


class PluginsConfig(BaseModel):
    search_paths: list[str] = Field(default_factory=lambda: ["./plugins", "~/.dataset_annotator/plugins"])
    builtin: list[str] = Field(default_factory=lambda: ["image", "text", "audio"])
    overrides: dict[str, Any] = Field(default_factory=dict)


class AppConfig(BaseModel):
    dataset: DatasetConfig
    plugin_config: PluginConfig = Field(default_factory=PluginConfig)
    fields: list[FieldConfig] = Field(default_factory=list)
    ui: UIConfig = Field(default_factory=UIConfig)
    snapshot: SnapshotConfig = Field(default_factory=SnapshotConfig)
    export: ExportConfig = Field(default_factory=ExportConfig)
    s3: S3Config | None = None
    suggestions: SuggestionsConfig = Field(default_factory=SuggestionsConfig)
    performance: PerformanceConfig = Field(default_factory=PerformanceConfig)
    plugins: PluginsConfig = Field(default_factory=PluginsConfig)

    @model_validator(mode="after")
    def validate_s3_bucket(self) -> AppConfig:
        if self.s3 and self.s3.enabled and not self.s3.bucket:
            raise ValueError("S3 bucket is required when S3 is enabled")
        return self

    def compute_hash(self) -> str:
        """Compute SHA256 hash of the config (excluding runtime-only fields)."""
        import json
        config_dict = self.model_dump(mode="json")
        config_json = json.dumps(config_dict, sort_keys=True)
        return hashlib.sha256(config_json.encode()).hexdigest()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    s3_endpoint_url: str | None = None
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_endpoint_url: str | None = None


def load_config(config_path: str | Path) -> AppConfig:
    """Load and validate configuration from YAML file."""
    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        raw_config = yaml.safe_load(f)

    settings = Settings()

    if raw_config.get("s3") and raw_config["s3"].get("enabled"):
        s3_config = raw_config["s3"]
        if settings.s3_access_key_id or settings.aws_access_key_id:
            s3_config["access_key_id"] = settings.s3_access_key_id or settings.aws_access_key_id
        if settings.s3_secret_access_key or settings.aws_secret_access_key:
            s3_config["secret_access_key"] = settings.s3_secret_access_key or settings.aws_secret_access_key
        if settings.s3_endpoint_url or settings.aws_endpoint_url:
            s3_config["endpoint_url"] = settings.s3_endpoint_url or settings.aws_endpoint_url

    return AppConfig(**raw_config)


def save_config(config: AppConfig, config_path: str | Path) -> None:
    """Save configuration to YAML file."""
    config_path = Path(config_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config.model_dump(mode="json"), f, default_flow_style=False, sort_keys=False)