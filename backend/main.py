from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.config import load_config, AppConfig
from backend.database import Database, create_snapshot
from backend.services.scanner import scan_dataset
from backend.plugins import init_plugins
from backend.ws.manager import websocket_endpoint
from backend.deps import set_config, set_db, get_config, get_db


CONFIG_PATH = Path(os.getenv("DATASET_ANNOTATOR_CONFIG", "config/dataset_config.yaml"))
DB_PATH = Path(os.getenv("DATASET_ANNOTATOR_DB", "data/annotator.db"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = load_config(CONFIG_PATH)
    init_plugins(cfg)
    database = Database(DB_PATH, cfg)
    await database.initialize()

    set_config(cfg)
    set_db(database)

    # Optional: auto-open + scan a dataset folder at startup (used by Docker).
    env_dataset_path = os.getenv("DATASET_ANNOTATOR_DATASET_PATH")
    if env_dataset_path:
        from backend.config import save_config
        try:
            p = Path(env_dataset_path).expanduser().resolve()
            if p.is_dir():
                cfg.dataset.path = str(p)
                cfg.dataset.name = p.name
                save_config(cfg, CONFIG_PATH)
                await scan_dataset(database, cfg)
        except Exception as e:
            print(f"Auto-open dataset failed: {e}")

    if cfg.s3 and cfg.s3.enabled and cfg.s3.fetch_on_startup:
        asyncio.create_task(sync_from_s3_on_startup())

    yield

    if cfg and cfg.snapshot.enabled:
        await create_snapshot(database, 1, Path(cfg.snapshot.path), trigger="shutdown")

    await database.close()


app = FastAPI(
    title="Dataset Annotator API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend HTML page if dist doesn't exist yet
frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
else:
    # Serve a simple embedded frontend HTML page
    from fastapi.responses import HTMLResponse
    from fastapi import Request, Response
    
    # Also serve CSS from frontend directory
    frontend_dir = Path(__file__).parent.parent / "frontend"
    
    @app.get("/style.css")
    async def serve_css():
        css_path = frontend_dir / "style.css"
        if css_path.exists():
            return Response(content=css_path.read_text(encoding="utf-8"), media_type="text/css")
        return Response(content="", media_type="text/css")
    
    @app.get("/app.js")
    async def serve_js():
        js_path = frontend_dir / "app.js"
        if js_path.exists():
            return Response(content=js_path.read_text(encoding="utf-8"), media_type="application/javascript")
        return Response(content="", media_type="application/javascript")
    
    @app.get("/")
    async def frontend_root(request: Request):
        html_path = frontend_dir / "index.html"
        if html_path.exists():
            html = html_path.read_text(encoding="utf-8")
            # Replace the CSS path to be relative
            html = html.replace('href="style.css"', 'href="/style.css"')
            return HTMLResponse(content=html, status_code=200)
        return HTMLResponse(content="""
<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Dataset Annotator</title>
<style>body{font-family:sans-serif;padding:2rem}</style>
</head><body><div style="padding:2rem"><h1>Dataset Annotator</h1>
<p>Frontend not fully built. Use the API at <a href="http://localhost:8080/api/docs">http://localhost:8080/api/docs</a></p>
<p>Backend: <code>http://localhost:8080</code></p></div></html>
""", status_code=200)


# Serve images from dataset
@app.get("/api/images/{item_id}")
async def serve_image(item_id: int):
    from fastapi.responses import FileResponse
    from backend.deps import get_db
    db = get_db()
    item = await db.fetchone("SELECT * FROM data_items WHERE id = ?", (item_id,))
    if not item:
        raise HTTPException(404, "Image not found")
    
    config = get_config()
    base_path = Path(config.dataset.path)
    full_path = base_path / item["rel_path"]
    
    if not full_path.exists():
        # Try absolute source path
        if item["source_path"] and Path(item["source_path"]).exists():
            full_path = Path(item["source_path"])
        else:
            raise HTTPException(404, "Image file not found on disk")
    
    mime_type = item.get("mime_type", "image/jpeg")
    return FileResponse(full_path, media_type=mime_type)


@app.get("/api/images/crop/{annotation_id}")
async def serve_crop(annotation_id: int):
    from backend.deps import get_db
    from fastapi import HTTPException
    from fastapi.responses import FileResponse
    from pathlib import Path
    
    db = get_db()
    ann = await db.fetchone("SELECT crop_path FROM annotations WHERE id = ?", (annotation_id,))
    if not ann or not ann["crop_path"]:
        raise HTTPException(404, "Crop not found")
    
    config = get_config()
    base_path = Path(config.dataset.path)
    full_path = base_path / ann["crop_path"]
    
    if not full_path.exists():
        raise HTTPException(404, "Crop file not found on disk")
    
    return FileResponse(full_path, media_type="image/png")


@app.post("/api/reset-db")
async def reset_db():
    from backend.deps import get_db
    db = get_db()

    # Delete crop files on disk so a reset also clears generated crops.
    from backend.deps import get_config
    config = get_config()
    crops_dir = Path(config.dataset.path) / ".crops"
    if crops_dir.exists():
        for f in crops_dir.rglob("*"):
            if f.is_file():
                f.unlink(missing_ok=True)

    await db.execute('DELETE FROM annotations')
    await db.execute('DELETE FROM annotation_fields')
    await db.execute('DELETE FROM field_categories')
    await db.execute('DELETE FROM snapshots')
    await db.execute('DELETE FROM exports')
    await db.execute('DELETE FROM export_cursors')

    # Clear done/progress marks so the tree shows everything as pending again.
    await db.execute("UPDATE data_items SET status = 'pending', updated_at = CURRENT_TIMESTAMP")

    return {"status": "reset", "message": "Database cleared"}


async def sync_from_s3_on_startup() -> None:
    try:
        from backend.services.s3_service import S3Service
        s3_service = S3Service(get_config(), get_db())
        await s3_service.fetch_latest()
    except Exception as e:
        print(f"S3 sync on startup failed: {e}")


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": "1.0.0"}


@app.websocket("/ws/{dataset_id}")
async def ws_endpoint(websocket: WebSocket, dataset_id: int):
    from backend.ws.manager import websocket_endpoint
    await websocket_endpoint(websocket, dataset_id)


# Import and include routers AFTER app is created to avoid circular imports
from backend.api import datasets, annotations, fields, operations

app.include_router(datasets.router, prefix="/api")
app.include_router(annotations.router, prefix="/api")
app.include_router(fields.router, prefix="/api")
app.include_router(operations.router, prefix="/api")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)