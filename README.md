# Dataset Annotator

A **recovery-first**, **S3-native**, **plugin-extensible** dataset annotator for medical documents and beyond.

## Features

- **Annotation Engine**: Rectangles, polygons, points, lines with move/resize/lock
- **Dynamic Fields**: Enum with "Other" → custom value, suggestions, conditional visibility
- **SQLite + WAL**: ACID transactions, crash-safe
- **Snapshots**: Auto (interval/export/shutdown) + manual, gzip compressed, verified
- **Exports**: Full & incremental Parquet with embedded images (base64) for standalone recovery
- **S3 Integration**: Fetch on startup, push after ops, multipart upload, checksums
- **Recovery**: From S3 (auto) or local export, verification built-in
- **Import**: COCO, YOLO, LabelMe, Custom JSON with field mapping
- **Web UI**: React + Fabric.js, all operations in one panel

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure

Edit `config/dataset_config.yaml`:

```yaml
dataset:
  name: "my_dataset"
  path: "/path/to/images"
  recursive: true

s3:
  enabled: true
  bucket: "my-bucket"
  region: "us-east-1"
```

Set S3 credentials via environment:
```bash
export AWS_ACCESS_KEY_ID=xxx
export AWS_SECRET_ACCESS_KEY=xxx
```

### 3. Initialize & Scan

```bash
dataset-annotator init
dataset-annotator scan
```

### 4. Start Server

```bash
dataset-annotator serve --port 8080
```

Open http://localhost:8080

## Commands

| Command | Description |
|---------|-------------|
| `init` | Initialize database from config |
| `scan` | Scan dataset folder for images |
| `serve` | Start web server |
| `export estimate` | Estimate export size/time |
| `export run` | Run full/incremental export |
| `export status` | Check export progress |
| `s3 sync` | Fetch/push from/to S3 |
| `s3 list` | List S3 objects |
| `recover verify` | Verify export integrity |
| `recover from-export` | Recover from local export |
| `recover from-s3` | Recover from S3 |
| `snapshot create` | Create manual snapshot |
| `snapshot list` | List snapshots |
| `snapshot restore` | Restore from snapshot |
| `import preview` | Preview import file |
| `import run` | Execute import |

## Export Format

Exports are self-contained Parquet files with:
- All metadata (annotations, fields, geometry)
- Source images embedded as base64 PNG
- Crops embedded as base64 PNG
- Manifest with SHA256 checksums for verification

## Recovery

```bash
# From local export
dataset-annotator recover from-export ./exports/dataset.parquet ./recovered

# From S3 (auto-discovers latest full + incrementals)
dataset-annotator recover from-s3 --bucket my-bucket --target ./recovered
```

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

## Configuration

All settings in `config/dataset_config.yaml` with full documentation. Key sections:

- `dataset`: Name, path, plugin, recursive scan
- `plugin_config`: Annotation mode, intersections, movement, display, crops
- `fields`: Field definitions (internal + user-facing)
- `ui`: Theme, layout, canvas colors, shortcuts
- `snapshot`: Interval, triggers, retention, compression
- `export`: Embedding, compression, incremental settings
- `s3`: Bucket, region, multipart, fetch/push settings
- `suggestions`: Debounce, ranking, fuzzy matching

## Plugin Development

Create a plugin in `plugins/your_plugin/`:
```python
from backend.plugins.base import BasePlugin

class YourPlugin(BasePlugin):
    name = "your_plugin"
    # Implement required methods
```

Register in config:
```yaml
plugins:
  search_paths: ["./plugins"]
```

## License

MIT