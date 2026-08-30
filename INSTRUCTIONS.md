# Instructions for Dataset Annotator Implementation

## Project Context
Building a complete dataset annotator with:
- SQLite + WAL for storage
- S3-native incremental/full exports with pre-export estimation
- Self-contained Parquet exports (images embedded base64) for disaster recovery
- Web UI (React + Fabric.js) with all operations in one panel
- Plugin architecture (image plugin first for medical documents)

## Key Principles
1. **Recovery-first**: Every export must be a standalone recovery artifact
2. **S3-native**: Fetch on startup, push after operations, multipart uploads
3. **Config-driven**: All knobs in YAML with documentation
4. **Incremental by default**: Cursor-based, full export every 10 incrementals
4. **No encryption**: Integrity via checksums (SHA256, zstd page checksums)
5. **Case-insensitive by default**: Suggestions, enums, field matching
6. **Movable annotations**: Rectangles/polygons can be moved after creation, intersections allowed

## Phase 1: Foundation (Days 1-3)

### 1.1 Config Loader (`backend/config.py`)
- Pydantic Settings with YAML loading
- Validate all config sections
- Environment variable overrides for secrets (S3 credentials)
- Config hash generation for export manifest

### 1.2 Database (`backend/database.py`)
- SQLite with WAL mode enabled
- Connection pool (aiosqlite)
- Migration system (versioned schema)
- Schema from PROPOSAL.md

### 1.3 Scanner (`backend/services/scanner.py`)
- Recursive folder scan preserving sort_order
- Hash each file (SHA256) for integrity
- Extract metadata (dimensions for images)
- Batch insert with transaction

### 1.4 Models (`backend/models.py`)
- All Pydantic models for API requests/responses
- Config models matching YAML structure
- Export estimation models

### 1.5 Main App (`backend/main.py`)
- FastAPI with lifespan (startup/shutdown)
- CORS for frontend
- Static file serving for frontend build
- WebSocket manager initialization
- S3 sync on startup if enabled

## Phase 2: Core API (Days 4-7)

### 2.1 Plugin System (`backend/plugins/`)
- Base plugin interface
- Image plugin with geometry ops, intersection detection, crop handling

### 2.2 Annotations API (`backend/api/annotations.py`)
- CRUD for annotations
- Move/resize with geometry update
- Crop regeneration on move
- Lock/unlock
- Intersection checking (configurable)

### 2.3 Fields API (`backend/api/fields.py`)
- Field value CRUD
- Dynamic enum expansion ("Other" → new value)
- Conditional visibility (visible_when)
- Suggestions endpoint (debounced, fuzzy, case-insensitive)

### 2.4 WebSocket (`backend/ws/manager.py`)
- Real-time suggestion updates
- Annotation changes broadcast
- Export progress streaming

## Phase 3: Frontend - Annotate (Days 8-12)

### 3.1 Canvas (`frontend/src/components/canvas/`)
- Fabric.js integration
- Annotation layer (rect, polygon, point, line)
- Selection, move, resize, rotate
- Snap to grid
- Keyboard shortcuts

### 3.2 Field Panel (`frontend/src/components/panel/`)
- Dynamic field rendering from config
- Suggestion dropdown (debounced)
- Dynamic enum with "Other" text input
- Conditional field visibility

### 3.3 Filmstrip (`frontend/src/components/gallery/`)
- Thumbnail grid with status badges
- Virtual scrolling for large datasets
- Keyboard navigation

### 3.4 State Management (`frontend/src/stores/`)
- Zustand store for annotations, UI state
- Optimistic updates with server sync

## Phase 4: Frontend - Operations (Days 13-15)

### 4.1 Operations Page (`frontend/src/pages/OperationsPage.tsx`)
- ExportCard with estimation
- S3SyncCard with status
- RecoveryCard (S3 auto / local file)
- SnapshotsCard (list, create, restore, verify)
- ImportCard (COCO/YOLO/LabelMe preview)

### 4.2 API Hooks (`frontend/src/hooks/`)
- useExport (estimate, run, progress SSE)
- useS3Sync (fetch, push, list)
- useRecovery (verify, run, verify-recovery)

## Phase 5: Export Engine (Days 16-19)

### 5.1 Parquet Exporter (`backend/exporters/parquet_exporter.py`)
- Streaming write (row groups, memory efficient)
- Base64 image embedding
- Flattened fields (wide table)
- zstd compression + checksums

### 5.2 Manifest (`backend/exporters/manifest.py`)
- SHA256 for every image + row group
- Export metadata for recovery

### 5.3 Estimation (`backend/services/estimation.py`)
- Sample-based size estimation
- Time estimation based on throughput

### 5.4 Incremental Cursor (`backend/services/export_service.py`)
- Track by annotation_updated_at
- Handle item status changes
- Full export every N incrementals

## Phase 6: S3 Integration (Days 20-22)

### 6.1 S3 Service (`backend/services/s3_service.py`)
- Multipart upload for large files
- Checksum verification on upload/download
- Bandwidth limiting
- List objects with pagination

### 6.2 Sync on Startup (`backend/main.py` lifespan)
- Fetch latest full export + incrementals
- Fetch latest snapshot
- Fetch cursor
- Verify checksums
- Recover if local behind

## Phase 7: Recovery (Days 23-25)

### 7.1 Recovery Engine (`backend/recovery/recovery_engine.py`)
- Stream Parquet → reconstruct DB
- Decode base64 images → write files
- Recreate folder structure
- Verify row counts, checksums, referential integrity

### 7.2 S3 Recovery (`backend/recovery/s3_recovery.py`)
- Auto-discover latest full + incrementals
- Download in order
- Apply incrementals sequentially

## Phase 8: Snapshots (Days 26-27)

### 8.1 Snapshot Service (`backend/services/snapshot_service.py`)
- SQLite .backup to gzipped file
- Verify after creation
- Auto on interval/export/shutdown
- Max snapshots retention

### 8.2 CLI Commands (`backend/cli.py`)
- snapshot create/list/restore/verify

## Phase 9: Import (Days 28-29)

### 9.1 Import Parsers (`backend/services/import_service.py`)
- COCO JSON
- YOLO TXT
- LabelMe JSON
- Field mapping UI preview

## Phase 10: Polish (Days 30-32)

### 10.1 Testing
- Round-trip: annotate → export → recover → verify
- Incremental export + recovery
- S3 sync + recovery
- Annotation movement + intersection
- Dynamic enum expansion

### 10.2 Documentation
- README with quickstart
- Config reference
- CLI reference
- Recovery procedures

---

## Development Rules

### Code Style
- Type hints everywhere (Python 3.11+)
- Pydantic for all data validation
- No raw SQL in API layer (use database.py helpers)
- React functional components + hooks
- Zustand for state (not Redux)

### Testing
- Write test for each new feature before implementing
- Use pytest for backend, Vitest for frontend
- Integration tests for export/recovery round-trip

### Git
- Commit after each completed sub-task
- Conventional commits: `feat:`, `fix:`, `refactor:`, `test:`

### Safety
- Never commit secrets (use env vars)
- Verify all S3 operations with checksums
- Atomic writes (tmp → rename)
- Backup before destructive operations

---

## Current Task
**Phase 1.1: Config Loader**

Create `backend/config.py` with:
- Pydantic Settings class for each config section
- YAML loading with validation
- Config hash computation
- Environment variable support for S3 credentials

Then proceed to 1.2 Database.