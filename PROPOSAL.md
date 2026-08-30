# Final Complete Dataset Annotator Proposal

## Overview

A **recovery-first**, **S3-native**, **plugin-extensible** dataset annotator with a web UI for all operations. Built for medical document annotation (image plugin) but architected for any data type.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            WEB UI (React + TS)                              │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐           │
│  │  Annotate   │ │  Explorer   │ │  Operations │ │  Settings   │           │
│  │  Canvas     │ │  Gallery    │ │  Panel      │ │  Config     │           │
│  └─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘           │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                    ┌─────────────────┼─────────────────┐
                    ▼                 ▼                 ▼
            ┌───────────────┐ ┌───────────────┐ ┌───────────────┐
            │  FastAPI      │ │  SQLite       │ │  S3 Client    │
            │  Backend      │ │  (WAL)        │ │  (boto3)      │
            └───────────────┘ └───────────────┘ └───────────────┘
                    │                 │                 │
                    ▼                 ▼                 ▼
            ┌───────────────────────────────────────────────────┐
            │           Plugin System (Image, Text, Audio)      │
            └───────────────────────────────────────────────────┘
```

---

## Core Features

### 1. Annotation Engine (Image Plugin)
- **Modes**: rectangle, rotated rectangle, polygon, point, line
- **Movable/resizable** annotations with snap-to-grid
- **Intersections allowed** (configurable)
- **Crop hierarchy** (crops of crops via `parent_annotation_id`)
- **Lock annotations** to prevent accidental moves
- **Real-time suggestions** from existing field values (case-insensitive, fuzzy)
- **Dynamic enums**: "Other" → text input → adds to dropdown

### 2. Storage (SQLite + WAL)
- ACID transactions, crash-safe
- Automatic snapshots (interval, export, shutdown, manual)
- Gzip-compressed, verified snapshots
- Export cursor for incremental tracking

### 3. Export System (Recovery-First)
| Export Type | Use Case |
|-------------|----------|
| **Full** | Complete disaster recovery artifact |
| **Incremental** | Fast sync of changes since last export |

**Pre-export estimation** (shown in UI):
- Estimated size (GB)
- Estimated time (minutes)
- Row count breakdown

**Output**: Self-contained Parquet + Manifest
- Full source images embedded (base64, ≤50MB, ≤1440p)
- Crops embedded
- All fields flattened (wide table)
- zstd compression + page/footer checksums
- Manifest with SHA256 for every image + row group

### 4. S3 Integration
- **Fetch on startup**: Latest full export + incrementals + snapshots + cursor
- **Push after operations**: Exports, snapshots, cursor
- Multipart upload for large files
- Checksum verification on download/upload
- Bandwidth limiting (optional)

### 5. Recovery System
- **From S3**: Auto-discover latest full + incrementals → reconstruct
- **From local export**: Parquet → DB + images + config
- **Verification**: Row counts, checksums, referential integrity
- **Result**: Ready-to-annotate instance

### 6. UI Operations Panel (All in One Place)
```
┌────────────────────────────────────────────────────────────┐
│  OPERATIONS PANEL                                          │
├────────────────────────────────────────────────────────────┤
│  ┌─ EXPORT ─────────────────────────────────────────────┐  │
│  │  Type:  ○ Full    ○ Incremental                      │  │
│  │  Est. Size: 12.4 GB    Est. Time: 8 min              │  │
│  │  [Estimate]  [Export to Local]  [Export & Push S3]   │  │
│  └──────────────────────────────────────────────────────┘  │
│  ┌─ S3 SYNC ────────────────────────────────────────────┐  │
│  │  Status: Synced 2 min ago                            │  │
│  │  [Fetch Latest]  [Push Pending]  [View S3 Objects]   │  │
│  └──────────────────────────────────────────────────────┘  │
│  ┌─ RECOVERY ───────────────────────────────────────────┐  │
│  │  Source:  ○ S3 (auto)   ○ Local Export File          │  │
│  │  Target: ./recovered_dataset                         │  │
│  │  [Verify Export]  [Recover]  [Verify Recovery]       │  │
│  └──────────────────────────────────────────────────────┘  │
│  ┌─ SNAPSHOTS ──────────────────────────────────────────┐  │
│  │  Latest: snapshot_012.db.gz (5 min ago, 87K ann)     │  │
│  │  [Create Now]  [List/Restore]  [Verify All]          │  │
│  └──────────────────────────────────────────────────────┘  │
│  ┌─ IMPORT ─────────────────────────────────────────────┐  │
│  │  Import annotations from: COCO / YOLO / LabelMe      │  │
│  │  [Select File]  [Preview]  [Import]                  │  │
│  └──────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────┘
```

---

## Complete Configuration (All Knobs Documented)

```yaml
# dataset_config.yaml
# =============================================================================
# DATASET ANNOTATOR - COMPLETE CONFIGURATION
# =============================================================================
# All paths relative to this file unless absolute.
# Comments explain every knob. Modify and restart server to apply.
# =============================================================================

dataset:
  # REQUIRED: Unique dataset identifier (used in DB, S3 paths, exports)
  name: "medical_documents_v1"
  
  # REQUIRED: Plugin type - determines UI and data handling
  # Built-in: 'image', 'text', 'audio' | Custom: plugin directory name
  plugin: "image"
  
  # REQUIRED: Root path to source data
  path: "D:/datasets/medical"
  
  # Recursively scan subdirectories
  recursive: true
  
  # File extensions to include (case-insensitive). Empty = all files.
  extensions: [".jpg", ".jpeg", ".png", ".tiff", ".bmp", ".webp"]
  
  # Sort order for gallery/navigation: 'path' | 'mtime' | 'size' | 'random'
  sort_by: "path"
  
  # Pagination: items per page (0 = no limit)
  page_size: 100

# =============================================================================
# PLUGIN CONFIGURATION: IMAGE
# =============================================================================
plugin_config:
  # Annotation geometry type
  # rectangle_box: [x1,y1,x2,y2] axis-aligned
  # rotated_box: [cx,cy,w,h,angle] 
  # polygon: [[x1,y1],[x2,y2],...] min 3 points
  # point: [x,y]
  # line: [[x1,y1],[x2,y2]]
  annotation_mode: "rectangle_box"
  
  # Allow annotations to overlap/intersect
  allow_intersections: true
  
  # Allow moving/resizing after creation
  allow_movement: true
  
  # Snap to grid/other annotations (pixels)
  snap_threshold: 5
  
  # Minimum annotation size (prevents tiny accidental boxes)
  min_annotation_size: 10
  
  # Display settings
  display:
    max_dimension: 2560      # Max display dimension (1440p)
    show_grid: false
    grid_size: 50
    default_zoom: "fit"      # 'fit' | '100' | '200' | number
    zoom_steps: [0.25, 0.5, 0.75, 1, 1.5, 2, 3, 4]
  
  # Crop settings
  crops:
    auto_save: true
    output_dir: "crops"
    naming_template: "{dataset}_{item_id}_{annotation_id}"
    format: "png"
    quality: 95
    padding: 5
    context_padding: 0

# =============================================================================
# ANNOTATION FIELDS
# =============================================================================
# Each field defines a column in the annotation panel.
# internal=true → auto-populated, hidden by default
# =============================================================================
fields:
  # ---- INTERNAL FIELDS (auto-populated) ----
  - name: "coordinates"
    label: "Coordinates"
    datatype: "json"
    internal: true
    hidden: true
    source: "geometry"
    description: "Annotation geometry in plugin-specific format"
  
  - name: "file_path"
    label: "Crop Path"
    datatype: "string"
    internal: true
    hidden: true
    source: "crop_path"
    description: "Relative path to saved crop image"
  
  - name: "source_image"
    label: "Source Image"
    datatype: "string"
    internal: true
    hidden: true
    source: "data_item_path"
    description: "Original image file path"
  
  - name: "annotation_id"
    label: "Annotation ID"
    datatype: "integer"
    internal: true
    hidden: true
    source: "annotation_id"
    description: "Internal annotation identifier"
  
  # ---- USER-FACING FIELDS ----
  - name: "Text"
    label: "Text Content"
    datatype: "string"
    required: true
    provide_suggestions: true
    suggestion_limit: 10
    case_insensitive: true
    placeholder: "Enter text from image..."
    validation:
      min_length: 1
      max_length: 5000
    description: "Transcribed text from the annotated region"
  
  - name: "Type"
    label: "Entity Type"
    datatype: "enum"
    required: true
    enum_values: ["Medicine", "Advice", "Frequency", "Other"]
    dynamic_enum: true
    case_insensitive: true
    allow_custom: true
    custom_label: "Other (specify)"
    description: "Classification of the annotated entity"
  
  - name: "Dosage"
    label: "Dosage"
    datatype: "string"
    required: false
    provide_suggestions: true
    suggestion_limit: 10
    case_insensitive: true
    placeholder: "e.g., 500mg, 10ml, 1 tablet"
    visible_when:
      field: "Type"
      value: "Medicine"
    description: "Dosage information"
  
  - name: "Frequency"
    label: "Frequency"
    datatype: "enum"
    required: false
    enum_values: ["Once daily", "Twice daily", "Three times daily", "Four times daily", "As needed", "Weekly", "Monthly", "Other"]
    dynamic_enum: true
    case_insensitive: true
    visible_when:
      field: "Type"
      value: "Medicine"
  
  - name: "Route"
    label: "Route"
    datatype: "enum"
    required: false
    enum_values: ["Oral", "Topical", "Injection", "Inhalation", "Sublingual", "Rectal", "Other"]
    dynamic_enum: true
    case_insensitive: true
    visible_when:
      field: "Type"
      value: "Medicine"
  
  - name: "Confidence"
    label: "Confidence"
    datatype: "number"
    required: false
    default: 1.0
    min: 0.0
    max: 1.0
    step: 0.1
    description: "Annotator confidence (0-1)"
  
  - name: "Notes"
    label: "Notes"
    datatype: "string"
    required: false
    multiline: true
    placeholder: "Additional observations..."
    description: "Free-form notes"

# =============================================================================
# UI CONFIGURATION
# =============================================================================
ui:
  theme: "dark"                    # 'light' | 'dark' | 'auto'
  language: "en"
  
  layout:
    sidebar_width: 320
    toolbar_position: "top"
    show_thumbnails: true
    thumbnail_size: 120
    show_status_badges: true
  
  canvas:
    type_colors:
      Medicine: "#e74c3c"
      Advice: "#3498db"
      Frequency: "#f39c12"
      Other: "#95a5a6"
    default_color: "#2ecc71"
    line_width: 2
    fill_opacity: 0.15
    show_labels: true
    label_template: "{Type}: {Text}"
    highlight_selected: true
    highlight_color: "#fff"
    highlight_width: 3
  
  shortcuts:
    next_item: "ArrowRight"
    prev_item: "ArrowLeft"
    save: "Ctrl+S"
    new_annotation: "N"
    delete_annotation: "Delete"
    undo: "Ctrl+Z"
    redo: "Ctrl+Y"
    zoom_in: "="
    zoom_out: "-"
    zoom_fit: "0"
    pan: "Space"
    toggle_sidebar: "B"
    copy_annotation: "Ctrl+C"
    paste_annotation: "Ctrl+V"
    duplicate_annotation: "D"
    lock_annotation: "L"
  
  field_panel:
    auto_focus_first: true
    show_field_descriptions: true
    compact_mode: false
    group_by_section: true
  
  # Operations panel visibility
  operations:
    show_export: true
    show_s3_sync: true
    show_recovery: true
    show_snapshots: true
    show_import: true

# =============================================================================
# SNAPSHOTS
# =============================================================================
snapshot:
  enabled: true
  interval: 100                    # Annotations between auto-snapshots
  triggers: ["interval", "export", "shutdown", "manual"]
  max_snapshots: 10
  path: "./snapshots"
  compress: true                   # gzip compression
  verify: true                     # Verify after creation

# =============================================================================
# EXPORT
# =============================================================================
export:
  output_dir: "./exports"
  default_formats: ["parquet"]
  
  # RECOVERY-FIRST: Embed everything for standalone recovery
  embed_source_images: true
  embed_crops: true
  
  image_encoding:
    format: "png"
    quality: 100
    max_dimension: 0               # 0 = original (≤50MB, ≤1440p)
  
  parquet:
    compression: "zstd"
    compression_level: 3
    row_group_size: 50000
    data_page_size: 524288
    write_statistics: true
    use_dictionary: true
    dictionary_pagesize_limit: 1048576
    write_page_checksums: true
    write_footer_checksums: true
  
  arrow:
    compression: "zstd"
    compression_level: 3
  
  flatten_fields: true
  partition_by: ["dataset_name"]
  only_completed: false
  include_skipped: true
  include_pending: true
  include_internal_fields: true
  verify_after_write: true
  generate_manifest: true
  
  # Estimation (shown in UI before export)
  estimation:
    sample_rows: 1000              # Sample for size estimation
    include_images_in_estimate: true
  
  incremental:
    enabled: true
    strategy: "annotation_updated_at"
    include_item_status_changes: true
    min_interval_minutes: 30
    full_export_every: 10

# =============================================================================
# S3 INTEGRATION
# =============================================================================
s3:
  enabled: true
  bucket: "my-annotation-datasets"
  region: "us-east-1"
  prefix: "datasets/"
  
  # Multipart upload
  multipart_threshold_mb: 100
  multipart_chunksize_mb: 50
  
  # Startup fetch
  fetch_on_startup: true
  fetch:
    exports: true
    snapshots: true
    cursor: true
    verify_checksums: true
  
  # Push after operations
  push:
    exports: true
    snapshots: true
    cursor: true
    overwrite: false
  
  # Bandwidth limit (0 = unlimited)
  max_bandwidth_mbps: 0

# =============================================================================
# SUGGESTIONS
# =============================================================================
suggestions:
  enabled: true
  debounce_ms: 300
  max_suggestions: 10
  min_chars: 1
  ranking: "frequency"             # 'frequency' | 'recency' | 'alphabetical'
  scope: "current_dataset"         # 'current_dataset' | 'all_datasets'
  fuzzy_threshold: 0.8
  pre_populate_sources: []

# =============================================================================
# PERFORMANCE
# =============================================================================
performance:
  wal_mode: true
  busy_timeout: 5000
  pool_size: 5
  batch_size: 1000
  auto_vacuum: true

# =============================================================================
# PLUGINS
# =============================================================================
plugins:
  search_paths: ["./plugins", "~/.dataset_annotator/plugins"]
  builtin: ["image", "text", "audio"]
  overrides: {}
```

---

## UI Pages & Components

### Page Structure
```
/                          → Annotate (canvas + panel)
/explorer                  → Gallery (thumbnails, filter, search)
/operations                → Export, S3 Sync, Recovery, Snapshots, Import
/settings                  → Config editor (YAML + validation)
```

### Annotate Page
- **Canvas**: Fabric.js, movable annotations, keyboard shortcuts
- **Sidebar**: Field panel (dynamic, conditional visibility), suggestions dropdown
- **Toolbar**: New box, polygon, delete, lock, duplicate, zoom, pan
- **Filmstrip**: Thumbnails with status badges (pending/in_progress/done)

### Operations Page (All-in-One)

```typescript
// frontend/src/pages/OperationsPage.tsx
export function OperationsPage() {
  return (
    <CardGrid>
      <ExportCard />
      <S3SyncCard />
      <RecoveryCard />
      <SnapshotsCard />
      <ImportCard />
    </CardGrid>
  );
}

// ExportCard - Shows estimation BEFORE export
function ExportCard() {
  const [estimate, setEstimate] = useState<ExportEstimate | null>(null);
  
  return (
    <Card title="Export Dataset">
      <RadioGroup value={exportType} onChange={setExportType}>
        <Radio value="full">Full Export (Complete Recovery)</Radio>
        <Radio value="incremental">Incremental Export (Changes Only)</Radio>
      </RadioGroup>
      
      {estimate && (
        <EstimateBox>
          <Row><Label>Estimated Size:</Label> <Value>{estimate.size_gb} GB</Value></Row>
          <Row><Label>Estimated Time:</Label> <Value>{estimate.time_min} min</Value></Row>
          <Row><Label>Annotations:</Label> <Value>{estimate.annotation_count}</Value></Row>
          <Row><Label>Images:</Label> <Value>{estimate.image_count}</Value></Row>
        </EstimateBox>
      )}
      
      <ButtonGroup>
        <Button onClick={runEstimate}>Estimate</Button>
        <Button variant="primary" onClick={exportLocal}>Export to Local</Button>
        <Button variant="secondary" onClick={exportAndPush}>Export & Push to S3</Button>
      </ButtonGroup>
      
      <ProgressModal />  // Shows real-time progress during export
    </Card>
  );
}

// S3SyncCard
function S3SyncCard() {
  return (
    <Card title="S3 Synchronization">
      <StatusBadge>{syncStatus}</StatusBadge>
      <Detail>Last sync: {lastSyncTime}</Detail>
      <Detail>Pending pushes: {pendingCount}</Detail>
      <ButtonGroup>
        <Button onClick={fetchLatest}>Fetch Latest from S3</Button>
        <Button onClick={pushPending}>Push Pending to S3</Button>
        <Button variant="ghost" onClick={viewS3Objects}>View S3 Objects</Button>
      </ButtonGroup>
    </Card>
  );
}

// RecoveryCard
function RecoveryCard() {
  return (
    <Card title="Disaster Recovery">
      <RadioGroup value={recoverySource}>
        <Radio value="s3">From S3 (Auto-discover Latest)</Radio>
        <Radio value="local">From Local Export File</Radio>
      </RadioGroup>
      
      {recoverySource === 'local' && (
        <FileInput accept=".parquet" onChange={setExportFile} />
      )}
      
      <Input label="Recovery Target Directory" value={targetDir} />
      
      <ButtonGroup>
        <Button onClick={verifyExport}>Verify Export Integrity</Button>
        <Button variant="primary" onClick={runRecovery}>Recover Dataset</Button>
        <Button onClick={verifyRecovery}>Verify Recovery</Button>
      </ButtonGroup>
    </Card>
  );
}

// SnapshotsCard
function SnapshotsCard() {
  return (
    <Card title="Snapshots">
      <SnapshotList snapshots={snapshots} onRestore={handleRestore} />
      <ButtonGroup>
        <Button onClick={createSnapshot}>Create Snapshot Now</Button>
        <Button variant="ghost" onClick={verifyAll}>Verify All Snapshots</Button>
      </ButtonGroup>
    </Card>
  );
}

// ImportCard
function ImportCard() {
  return (
    <Card title="Import Annotations">
      <Select label="Format" options={['COCO', 'YOLO', 'LabelMe', 'Custom JSON']} />
      <FileInput accept=".json,.txt,.xml" onChange={setImportFile} />
      <Button onClick={previewImport}>Preview Import</Button>
      <Button variant="primary" onClick={runImport}>Import</Button>
    </Card>
  );
}
```

---

## API Endpoints (Backend)

```python
# backend/api/operations.py
router = APIRouter(prefix="/api/operations", tags=["operations"])

# Export
@router.post("/export/estimate")
async def estimate_export(dataset_id: int, type: Literal["full", "incremental"]):
    """Return size/time estimation before export."""

@router.post("/export/full")
async def export_full(dataset_id: int, push_s3: bool = False):
    """Full export with progress streaming."""

@router.post("/export/incremental")
async def export_incremental(dataset_id: int, push_s3: bool = False):
    """Incremental export since last cursor."""

@router.get("/export/status/{export_id}")
async def export_status(export_id: str):
    """Real-time progress via SSE/WebSocket."""

# S3 Sync
@router.post("/s3/fetch")
async def s3_fetch_latest(dataset_id: int):
    """Fetch latest exports/snapshots/cursor from S3."""

@router.post("/s3/push")
async def s3_push_pending(dataset_id: int):
    """Push pending exports/snapshots/cursor to S3."""

@router.get("/s3/objects")
async def s3_list_objects(dataset_id: int):
    """List all S3 objects for dataset."""

# Recovery
@router.post("/recover/verify")
async def verify_export(file_path: str):
    """Verify export integrity (checksums, row counts)."""

@router.post("/recover/from-s3")
async def recover_from_s3(dataset_name: str, bucket: str, target_dir: str):
    """Full recovery from S3 (latest full + incrementals)."""

@router.post("/recover/from-export")
async def recover_from_export(export_path: str, target_dir: str):
    """Recovery from local export file."""

@router.post("/recover/verify-recovery")
async def verify_recovery(target_dir: str):
    """Verify recovered dataset integrity."""

# Snapshots
@router.post("/snapshots/create")
async def create_snapshot(dataset_id: int, trigger: str = "manual"):
    """Create snapshot now."""

@router.get("/snapshots")
async def list_snapshots(dataset_id: int):
    """List all snapshots with metadata."""

@router.post("/snapshots/restore")
async def restore_snapshot(dataset_id: int, snapshot_id: int):
    """Restore from snapshot."""

# Import
@router.post("/import/preview")
async def preview_import(file: UploadFile, format: str):
    """Preview import (count, fields, sample)."""

@router.post("/import/execute")
async def execute_import(dataset_id: int, file: UploadFile, format: str, mapping: dict):
    """Execute import with field mapping."""
```

---

## Project Structure (Complete)

```
dataset_annotator/
├── backend/
│   ├── main.py                      # FastAPI app, lifespan, middleware
│   ├── config.py                    # Config loader + validation
│   ├── database.py                  # SQLite + WAL + migrations
│   ├── models.py                    # Pydantic models (request/response)
│   ├── plugin_registry.py           # Plugin system
│   ├── plugins/
│   │   ├── base.py                  # Plugin interface
│   │   └── image/
│   │       ├── __init__.py
│   │       ├── plugin.py            # ImagePlugin implementation
│   │       ├── geometry.py          # Geometry ops, intersection
│   │       └── crops.py             # Crop save/regenerate
│   ├── api/
│   │   ├── images.py                # Data items CRUD
│   │   ├── annotations.py           # Annotations CRUD + move
│   │   ├── fields.py                # Field values + suggestions
│   │   ├── suggestions.py           # Real-time suggestions WS
│   │   ├── datasets.py              # Dataset management
│   │   └── operations.py            # Export, S3, Recovery, Snapshots, Import
│   ├── services/
│   │   ├── export_service.py        # Export orchestration
│   │   ├── s3_service.py            # S3 operations
│   │   ├── recovery_service.py      # Recovery orchestration
│   │   ├── snapshot_service.py      # Snapshot management
│   │   ├── scanner.py               # Folder scanner
│   │   └── estimation.py            # Size/time estimation
│   ├── exporters/
│   │   ├── parquet_exporter.py      # Streaming Parquet writer
│   │   ├── manifest.py              # Manifest generation
│   │   └── streaming_s3.py          # S3 multipart upload
│   ├── recovery/
│   │   ├── recovery_engine.py       # Parquet → DB reconstruction
│   │   ├── s3_recovery.py           # S3 auto-discovery + recovery
│   │   └── integrity.py             # Checksum verification
│   ├── ws/
│   │   └── manager.py               # WebSocket manager
│   └── cli.py                       # CLI commands
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── AnnotatePage.tsx
│   │   │   ├── ExplorerPage.tsx
│   │   │   ├── OperationsPage.tsx   # All operations in one place
│   │   │   └── SettingsPage.tsx
│   │   ├── components/
│   │   │   ├── canvas/
│   │   │   │   ├── ImageCanvas.tsx
│   │   │   │   ├── AnnotationLayer.tsx
│   │   │   │   └── tools/
│   │   │   ├── panel/
│   │   │   │   ├── FieldPanel.tsx
│   │   │   │   ├── SuggestionBox.tsx
│   │   │   │   └── DynamicEnum.tsx
│   │   │   ├── operations/
│   │   │   │   ├── ExportCard.tsx
│   │   │   │   ├── S3SyncCard.tsx
│   │   │   │   ├── RecoveryCard.tsx
│   │   │   │   ├── SnapshotsCard.tsx
│   │   │   │   └── ImportCard.tsx
│   │   │   ├── gallery/
│   │   │   │   ├── ThumbnailGrid.tsx
│   │   │   │   └── StatusBadge.tsx
│   │   │   └── common/
│   │   ├── hooks/
│   │   │   ├── useAnnotations.ts
│   │   │   ├── useSuggestions.ts
│   │   │   ├── useKeyboard.ts
│   │   │   ├── useExport.ts
│   │   │   └── useS3Sync.ts
│   │   ├── stores/
│   │   │   └── annotationStore.ts
│   │   ├── services/
│   │   │   ├── api.ts
│   │   │   └── websocket.ts
│   │   ├── types/
│   │   │   └── index.ts
│   │   ├── App.tsx
│   │   └── main.tsx
│   ├── package.json
│   ├── vite.config.ts
│   └── tsconfig.json
├── config/
│   └── dataset_config.yaml
├── snapshots/
├── exports/
├── data/
│   └── annotator.db
├── plugins/                         # Custom plugins go here
├── tests/
│   ├── test_export_recovery.py
│   ├── test_incremental_export.py
│   ├── test_s3_sync.py
│   ├── test_annotation_movement.py
│   └── test_field_dynamics.py
├── requirements.txt
├── pyproject.toml
├── docker-compose.yml               # Optional: for containerized deployment
├── Dockerfile
└── README.md
```

---

## Implementation Phases

| Phase | Deliverable | Days |
|-------|-------------|------|
| **1. Foundation** | SQLite schema, config loader, scanner, migrations, WAL | 3 |
| **2. Core API** | REST + WS, annotations CRUD, field dynamics, suggestions | 4 |
| **3. Frontend - Annotate** | Canvas, movable annotations, field panel, shortcuts, filmstrip | 5 |
| **4. Frontend - Operations** | Operations page (Export, S3, Recovery, Snapshots, Import) | 3 |
| **5. Export Engine** | Streaming Parquet, manifest, estimation, incremental cursor | 4 |
| **6. S3 Integration** | Multipart upload, fetch/push, sync on startup, bandwidth limit | 3 |
| **7. Recovery** | Parquet→DB reconstruction, S3 auto-recovery, verification | 3 |
| **8. Snapshots** | Auto-snapshot, gzip, verify, restore, CLI | 2 |
| **9. Import** | COC/YOLO/LabelMe parsers, preview, field mapping | 2 |
| **10. Polish** | E2E tests, docs, performance, edge cases | 3 |

**Total: ~32 days**

---

## CLI Commands (For Automation)

```bash
# Dataset
dataset_annotator init --config config/dataset_config.yaml
dataset_annotator scan --dataset medical_documents_v1

# Server
dataset_annotator serve --config config/dataset_config.yaml --port 8080

# Export (with estimation)
dataset_annotator export estimate --dataset medical_documents_v1 --type full
dataset_annotator export run --dataset medical_documents_v1 --type full --push-s3
dataset_annotator export run --dataset medical_documents_v1 --type incremental

# S3
dataset_annotator s3 sync --dataset medical_documents_v1 --fetch
dataset_annotator s3 sync --dataset medical_documents_v1 --push
dataset_annotator s3 list --dataset medical_documents_v1

# Recovery
dataset_annotator recover verify --export ./exports/ds.parquet
dataset_annotator recover from-s3 --dataset medical_documents_v1 --bucket my-bucket --target ./recovered
dataset_annotator recover from-export --export ./exports/ds.parquet --target ./recovered
dataset_annotator recover verify-recovery --target ./recovered

# Snapshots
dataset_annotator snapshot create --dataset medical_documents_v1
dataset_annotator snapshot list --dataset medical_documents_v1
dataset_annotator snapshot restore --dataset medical_documents_v1 --id 5
dataset_annotator snapshot verify --dataset medical_documents_v1

# Import
dataset_annotator import preview --file annotations.json --format coco
dataset_annotator import run --dataset medical_documents_v1 --file annotations.json --format coco
```

---

## Acceptance Criteria (Definition of Done)

| Feature | Criteria |
|---------|----------|
| **Annotation** | Create/move/resize/delete rectangles & polygons; intersections allowed; crops saved |
| **Fields** | Dynamic enums (Other→text→new value); suggestions (case-insensitive, fuzzy); conditional visibility |
| **Export** | Full + incremental; pre-export estimation (size/time); self-contained Parquet + manifest |
| **S3** | Fetch on startup; push after ops; multipart; checksum verification |
| **Recovery** | From S3 (auto); from local export; verification; ready-to-annotate result |
| **Snapshots** | Auto (interval/export/shutdown); manual; gzip; verify; restore |
| **Import** | COCO/YOLO/LabelMe; preview; field mapping |
| **UI** | All operations in Operations page; estimation before export; progress streaming |
| **Config** | YAML with documented knobs; validation; hot-reload not required (restart) |

---

## Ready to Implement?

**Phase 1** begins with:
1. `backend/config.py` - Config loader with validation (Pydantic Settings)
2. `backend/database.py` - SQLite + WAL + migration system
3. `backend/services/scanner.py` - Recursive folder scanner with sort_order
4. `backend/models.py` - All Pydantic models
5. `backend/main.py` - FastAPI app with lifespan, CORS, static files

**Confirm to start Phase 1.**