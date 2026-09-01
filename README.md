# Dataset Annotator

A **recovery-first**, **S3-native**, plugin-extensible dataset annotator. Draw boxes on images, attach structured fields (text / enum / number), snapshot and restore state, and export to self-contained Parquet files that can be pushed to S3 and recovered from later.

## Features

- **Annotation**: rectangle boxes with move/resize/lock, per-dataset plugin system (image plugin built in)
- **Fields**: one text field per annotation (name + value; a new entry replaces the previous one), enums with "Other → custom", conditional visibility, suggestions
- **Storage**: SQLite (WAL mode) via `aiosqlite`, ACID transactions
- **Snapshots**: manual + automatic (interval / export / shutdown), gzip-compressed, SHA-256 verified
- **Export**: full & incremental Parquet with manifest and checksums; optional image verification that embeds original byte content (`source_image_base64`) and verifies round-trip integrity
- **S3**: push/pull exports, snapshots, and cursors; multipart upload; optional fetch-on-startup
- **Recovery**: rebuild the DB from a local export or from S3 (auto-discovers latest full + incrementals), with verification
- **Import**: COCO / YOLO / LabelMe / custom JSON with field mapping (CLI)
- **Web UI**: vanilla JS frontend served from the same FastAPI origin — one port, no separate dev server

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  WEB UI (vanilla JS)                                    │
│  index.html + app.js + style.css                        │
│  served by FastAPI on the same port                     │
└──────────────────────────┬──────────────────────────────┘
                           │ HTTP  /api/*  +  WebSocket /ws/{dataset_id}
                           ▼
┌─────────────────────────────────────────────────────────┐
│  FastAPI backend (backend/main.py)                      │
│  - datasets / annotations / fields / operations routers │
│  - background export tasks (full + incremental)         │
│  - WAL-managed SQLite via aiosqlite                     │
│  - snapshot + recovery engines                          │
│  - AsyncTaskManager + progress estimation               │
└──────────────┬───────────────────────────┬──────────────┘
               ▼                           ▼
      ┌───────────────┐         ┌─────────────────────┐
      │ Plugins       │         │ S3 (boto3)          │
      │ backend/      │         │ exports, snapshots, │
      │ plugins/image │         │ cursors             │
      └───────────────┘         └─────────────────────┘
```

Only the `image` plugin ships in `backend/plugins/`. The config lists `text` / `audio` as builtin names, but they are not implemented yet.

## Quick Start

### 1. Install

```bash
pip install -r requirements.txt
# optional: install this package so the `dataset-annotator` command is on PATH
pip install -e .
```

### 2. Configure

Copy the example config and edit it:

```bash
cp config/dataset_config.example.yaml config/dataset_config.yaml
```

The real `config/dataset_config.yaml` is gitignored (your local paths / S3 bucket stay out of the repo). Example contents:

```yaml
dataset:
  name: my_dataset
  path: /path/to/images
  recursive: true
  extensions: [.jpg, .jpeg, .png, .tiff, .bmp, .webp]

s3:
  enabled: true
  bucket: my-bucket
  region: us-east-1
  prefix: datasets/
```

S3 credentials are read from the environment (or a project-root `.env` file) and **override** the YAML. Saving them from the UI's Settings panel writes them to `.env` (gitignored), not into the YAML. Start from the committed `.env.example`:

```bash
# .env
AWS_ACCESS_KEY_ID=xxx
AWS_SECRET_ACCESS_KEY=xxx
AWS_ENDPOINT_URL=            # optional, for S3-compatible endpoints
```

### 3. Init, scan, and serve

```bash
python -m backend.cli init            # create the database from config
python -m backend.cli scan            # index images under dataset.path
python -m backend.cli serve --port 8080
```

Open <http://localhost:8080>. API docs: <http://localhost:8080/api/docs>. Health: `GET /api/health`.

`serve` initializes the DB on startup and, if the `DATASET_ANNOTATOR_DATASET_PATH` env var points at a folder, auto-opens and scans it (this is how the Docker image boots with an empty dataset).

## CLI Reference

`python -m backend.cli <command>` (or `dataset-annotator <command>` after `pip install -e .`). Most commands take `--config/-c` and `--dataset/-d`.

| Command | Description |
|---|---|
| `init` | Create/initialize the database from config |
| `scan` | Scan the dataset folder for images |
| `serve --port 8080` | Start the web server |
| `export estimate --type full\|incremental` | Estimate export size and time |
| `export run --type full\|incremental [--push-s3] [--formats parquet]` | Run an export (async by default) |
| `export status <export_id>` | Check export progress and outputs |
| `s3 sync [--fetch] [--push]` | Sync with S3 |
| `s3 list` | List S3 objects |
| `recover verify <export_path>` | Verify an export's integrity and manifest |
| `recover from-export <export_path> <target_dir>` | Rebuild the DB from a local export |
| `recover from-s3 --bucket <bucket> --target <dir>` | Rebuild the DB from S3 (full + incrementals) |
| `recover verify-recovery <target_dir>` | Verify a recovered dataset |
| `snapshot create` | Create a manual snapshot |
| `snapshot list` | List snapshots |
| `snapshot restore --id <id>` | Restore the DB from a snapshot |
| `snapshot verify` | Check snapshot hashes against storage |
| `import preview --format coco\|yolo\|labelme\|custom <file>` | Preview an import |
| `import run --format <fmt> [--mapping src=dst] <file>` | Execute an import |

## Export Format

Exports are self-contained Parquet files written to `export.output_dir` (default `./exports`):

- Annotations, fields, geometry, and item metadata
- Crops embedded as base64
- Source images embedded as raw bytes (`source_image_base64` + `source_image_sha256`) **when "Verify images on export" is checked**
- A manifest with SHA-256 checksums for verification
- A `<name>_verify.json` report written after export, checked against the embedded hashes to confirm every image round-trips losslessly

After writing, exports can be pushed to S3 (multipart, page checksums). Cursor state (`export_cursors`) tracks the last exported update, so incremental exports only carry new/changed annotations.

## Recovery

Exports are the source of truth for recovery. Verify, then rebuild:

```bash
# verify a local export's manifest + embedded image hashes
python -m backend.cli recover verify ./exports/out_2026-09-01T000000.parquet

# rebuild the database into ./recovered
python -m backend.cli recover from-export ./exports/out_2026-09-01T000000.parquet ./recovered

# or discover the latest full + incrementals on S3
python -m backend.cli recover from-s3 --bucket my-bucket --target ./recovered

# confirm the recovered dataset
python -m backend.cli recover verify-recovery ./recovered
```

## Configuration

Environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `DATASET_ANNOTATOR_CONFIG` | `config/dataset_config.yaml` | Config file path |
| `DATASET_ANNOTATOR_DB` | `data/annotator.db` | SQLite database path |
| `DATASET_ANNOTATOR_DATASET_PATH` | unset | Folder to auto-open + scan on startup |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_DEFAULT_REGION` | unset | S3 credentials (also settable from the UI → `.env`) |

Config file sections (`config/dataset_config.yaml`):

- `dataset` — name, plugin, path, recursive scan, extensions
- `plugin_config` — annotation mode, intersections, movement, display, crops (saved to `.crops/` inside the dataset folder)
- `fields` — field definitions (internal + user-facing), enums, validation, conditional visibility
- `ui` — theme, layout, canvas colors, shortcuts, field panel, visible operations
- `snapshot` — interval, triggers, retention, compression, verification
- `export` — output dir, image embedding, Parquet/Arrow compression, incremental strategy
- `s3` — bucket, region, prefix, multipart limits, fetch/push toggles, **empty creds (use env/`.env`)**
- `suggestions` — debounce, ranking, fuzzy matching for field suggestions
- `performance` — WAL mode, busy timeout, pool/batch sizes
- `plugins` — search paths, builtin list

## Docker

```bash
# build and run in one step
docker compose up --build

# or manually
docker build -t dataset-annotator .
docker run -p 8080:8080 \
  -v "$PWD/dataset:/app/dataset" \
  -v "$PWD/data:/app/data" \
  -v "$PWD/exports:/app/exports" \
  -v "$PWD/snapshots:/app/snapshots" \
  -e AWS_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID" \
  -e AWS_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY" \
  dataset-annotator
```

The compose file mounts `./dataset` at `/app/dataset` (auto-scanned at startup), persists DB/exports/snapshots/crops to host folders, and forwards optional `AWS_*` env vars from your shell or `.env`.

## Plugin Development

Plugins live in `backend/plugins/` and are registered through the `plugins` config section:

```python
from backend.plugins.base import BasePlugin

class YourPlugin(BasePlugin):
    name = "your_plugin"
    # implement the abstract methods; see backend/plugins/image/plugin.py for a reference
```

## Project Layout

```
backend/
  api/            FastAPI routers (datasets, annotations, fields, operations)
  exporters/      parquet_exporter, streaming_s3, manifest
  plugins/        base + image plugin (crops, geometry)
  recovery/       integrity checks, recovery_engine, s3_recovery
  services/       scanner, estimation, export_service, import_service, s3_service
  ws/             WebSocket progress manager
  cli.py          Click CLI
  main.py         FastAPI app + static frontend serving
config/           dataset_config.example.yaml (committed example); dataset_config.yaml is gitignored
frontend/         vanilla JS UI (index.html, app.js, style.css)
data/             SQLite database (gitignored)
exports/          exported Parquet (gitignored)
snapshots/        DB snapshots (gitignored)
```

## License

MIT