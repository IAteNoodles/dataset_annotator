from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import sqlite3
import json
import os
import hashlib
import uuid
from pathlib import Path
from datetime import datetime
from PIL import Image
import yaml
from contextlib import contextmanager
import shutil

# Load config
with open("config.yaml") as f:
    CONFIG = yaml.safe_load(f)

DB_PATH = CONFIG["storage"]["db_path"]
CROPS_DIR = Path(CONFIG["storage"]["crops_dir"])
CROPS_DIR.mkdir(parents=True, exist_ok=True)
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Dataset Annotator API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@contextmanager
def get_db():
    conn = sqlite3.connect(CONFIG["storage"]["db_path"])
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    with get_db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS datasets (
            id INTEGER PRIMARY KEY,
            name TEXT UNIQUE,
            path TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS images (
            id INTEGER PRIMARY KEY,
            dataset_id INTEGER REFERENCES datasets(id),
            file_path TEXT UNIQUE,
            rel_path TEXT,
            width INTEGER,
            height INTEGER,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS annotations (
            id INTEGER PRIMARY KEY,
            image_id INTEGER REFERENCES images(id),
            type TEXT,  -- rect, poly, rrect
            x REAL, y REAL, w REAL, h REAL,
            angle REAL DEFAULT 0,
            points TEXT,  -- JSON array for polygons
            text TEXT DEFAULT '',
            type TEXT DEFAULT '',
            custom_type TEXT DEFAULT '',
            shape TEXT DEFAULT 'rect',
            angle REAL DEFAULT 0,
            points TEXT DEFAULT '[]',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS image_labels (
            id INTEGER PRIMARY KEY,
            image_id INTEGER REFERENCES images(id),
            tag TEXT,
            UNIQUE(image_id, tag)
        );

        CREATE TABLE IF NOT EXISTS image_ocr (
            image_id INTEGER PRIMARY KEY REFERENCES images(id),
            text TEXT DEFAULT ''
        );

        CREATE INDEX IF NOT EXISTS idx_images_dataset ON images(dataset_id);
        CREATE INDEX IF NOT EXISTS idx_annotations_image ON annotations(image_id);
        """)
        conn.commit()

# Initialize
init_db()

# Models
class AnnotationCreate(BaseModel):
    image_id: int
    type: str  # rect, poly, rrect
    x: float
    y: float
    w: float
    h: float
    angle: float = 0
    points: Optional[List[List[float]]] = None
    text: str = ""
    type: str = ""
    custom_type: str = ""

class AnnotationUpdate(BaseModel):
    x: Optional[float] = None
    y: Optional[float] = None
    w: Optional[float] = None
    h: Optional[float] = None
    angle: Optional[float] = None
    points: Optional[List[List[float]]] = None
    text: Optional[str] = None
    type: Optional[str] = None
    custom_type: Optional[str] = None

class ImageUpdate(BaseModel):
    status: Optional[str] = None
    labels: Optional[List[str]] = None
    ocr: Optional[str] = None

class CropRequest(BaseModel):
    image_id: int
    words: List[Dict[str, Any]]

class SaveRequest(BaseModel):
    image_id: int
    words: List[Dict[str, Any]]
    labels: List[Dict[str, str]]
    ocr: str = ""
    crop_files: List[str] = []

# Routes
@app.get("/api/datasets")
def list_datasets():
    with get_db() as conn:
        datasets = conn.execute("SELECT * FROM datasets").fetchall()
        return [dict(d) for d in datasets]

@app.post("/api/datasets")
def create_dataset(name: str = Form(...), path: str = Form(...)):
    with get_db() as conn:
        try:
            cursor = conn.execute(
                "INSERT INTO datasets (name, path) VALUES (?, ?)",
                (name, path)
            )
            conn.commit()
            return {"id": cursor.lastrowid, "name": name, "path": path}
        except sqlite3.IntegrityError:
            raise HTTPException(400, "Dataset name already exists")

@app.get("/api/datasets/{dataset_id}/images")
def list_images(dataset_id: int, status: Optional[str] = None):
    with get_db() as conn:
        query = "SELECT * FROM images WHERE dataset_id = ?"
        params = [dataset_id]
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at"
        images = conn.execute(query, params).fetchall()
        return [dict(img) for img in images]

@app.post("/api/datasets/{dataset_id}/scan")
def scan_dataset(dataset_id: int):
    with get_db() as conn:
        ds = conn.execute("SELECT path FROM datasets WHERE id=?", (dataset_id,)).fetchone()
        if not ds:
            raise HTTPException(404, "Dataset not found")
        
        base_path = Path(ds["path"])
        if not base_path.exists():
            raise HTTPException(400, "Dataset path does not exist")
        
        extensions = {".jpg", ".jpeg", ".png", ".tiff", ".bmp"}
        files = []
        for ext in extensions:
            files.extend(base_path.rglob(f"*{ext}"))
        
        added = 0
        for f in files:
            if not f.is_file():
                continue
            try:
                with Image.open(f) as img:
                    w, h = img.size
                rel = f.relative_to(base_path)
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO images (dataset_id, file_path, rel_path, width, height) VALUES (?, ?, ?, ?, ?)",
                    (dataset_id, str(f), str(rel), w, h)
                )
                if cursor.rowcount > 0:
                    added += 1
            except Exception as e:
                print(f"Error processing {f}: {e}")
        
        conn.commit()
        return {"added": added}

@app.get("/api/images/{image_id}")
def get_image(image_id: int):
    with get_db() as conn:
        img = conn.execute("SELECT * FROM images WHERE id=?", (image_id,)).fetchone()
        if not img:
            raise HTTPException(404, "Image not found")
        return dict(img)

@app.get("/api/images/{image_id}/file")
def get_image_file(image_id: int):
    with get_db() as conn:
        img = conn.execute("SELECT file_path FROM images WHERE id=?", (image_id,)).fetchone()
        if not img:
            raise HTTPException(404, "Image not found")
        return FileResponse(img["file_path"])

@app.get("/api/images/{image_id}/annotations")
def get_annotations(image_id: int):
    with get_db() as conn:
        anns = conn.execute("SELECT * FROM annotations WHERE image_id=? ORDER BY id", (image_id,)).fetchall()
        result = []
        for a in anns:
            d = dict(a)
            if d["points"]:
                try:
                    d["points"] = json.loads(d["points"])
                except:
                    d["points"] = []
            result.append(d)
        return result

@app.post("/api/annotations")
def create_annotation(ann: AnnotationCreate):
    with get_db() as conn:
        points_json = json.dumps(ann.points) if ann.points else "[]"
        cursor = conn.execute("""
            INSERT INTO annotations (image_id, type, x, y, w, h, angle, points, text, type, custom_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (ann.image_id, ann.type, ann.x, ann.y, ann.w, ann.h, ann.angle,
              json.dumps(ann.points) if ann.points else "[]", ann.text, ann.type, ann.custom_type))
        conn.commit()
        return {"id": cursor.lastrowid, **ann.dict()}

@app.patch("/api/annotations/{ann_id}")
def update_annotation(ann_id: int, update: AnnotationUpdate):
    with get_db() as conn:
        fields = []
        values = []
        for field, value in update.dict(exclude_unset=True).items():
            if field == "points" and value is not None:
                value = json.dumps(value)
            fields.append(f"{field} = ?")
            values.append(value)
        
        if not fields:
            raise HTTPException(400, "No fields to update")
        
        fields.append("updated_at = datetime('now')")
        values.append(ann_id)
        
        conn.execute(f"UPDATE annotations SET {', '.join(fields)} WHERE id = ?", values)
        conn.commit()
        return {"success": True}

@app.delete("/api/annotations/{ann_id}")
def delete_annotation(ann_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM annotations WHERE id=?", (ann_id,))
        conn.commit()
        return {"success": True}

@app.patch("/api/images/{image_id}")
def update_image(image_id: int, update: ImageUpdate):
    with get_db() as conn:
        # Update status
        if update.status:
            conn.execute("UPDATE images SET status=? WHERE id=?", (update.status, image_id))
        
        # Update labels
        if update.labels is not None:
            conn.execute("DELETE FROM image_labels WHERE image_id=?", (image_id,))
            for label in update.labels:
                conn.execute("INSERT OR IGNORE INTO image_labels (image_id, tag) VALUES (?, ?)", (image_id, label["tag"]))
        
        # Update OCR
        if update.ocr is not None:
            conn.execute("""
                INSERT INTO image_ocr (image_id, text) VALUES (?, ?)
                ON CONFLICT(image_id) DO UPDATE SET text=excluded.text
            """, (image_id, update.ocr))
        
        conn.commit()
        return {"success": True}

@app.get("/api/images/{image_id}/labels")
def get_labels(image_id: int):
    with get_db() as conn:
        labels = conn.execute("SELECT tag FROM image_labels WHERE image_id=?", (image_id,)).fetchall()
        return [{"tag": l["tag"]} for l in labels]

@app.get("/api/images/{image_id}/ocr")
def get_ocr(image_id: int):
    with get_db() as conn:
        ocr = conn.execute("SELECT text FROM image_ocr WHERE image_id=?", (image_id,)).fetchone()
        return {"text": ocr["text"] if ocr else ""}

@app.post("/api/crop")
def generate_crops(req: CropRequest):
    """Generate crop images for annotations"""
    with get_db() as conn:
        img_row = conn.execute("SELECT file_path FROM images WHERE id=?", (req.image_id,)).fetchone()
        if not img_row:
            raise HTTPException(404, "Image not found")
        
        img_path = img_row["file_path"]
        if not Path(img_path).exists():
            raise HTTPException(404, "Image file not found")
        
        with Image.open(img_path) as img:
            crops = []
            for i, word in enumerate(req.words):
                x, y, w, h = word["x"], word["y"], word["w"], word["h"]
                
                # Crop with padding
                pad = 5
                x1 = max(0, int(word["x"]) - pad)
                y1 = max(0, int(word["y"]) - pad)
                x2 = min(img.width, int(word["x"] + word["w"]) + pad)
                y2 = min(img.height, int(word["y"] + word["h"]) + pad)
                
                if x2 > x1 and y2 > y1:
                    crop = img.crop((x1, y1, x2, y2))
                    crop_name = f"crop_{req.image_id}_{i}_{uuid.uuid4().hex[:8]}.png"
                    crop_path = CROPS_DIR / crop_name
                    crop.save(crop_path)
                    crops.append(str(crop_path.relative_to(CROPS_DIR.parent)))
            
            return {"crops": crops}

@app.post("/api/save")
def save_annotations(req: SaveRequest):
    with get_db() as conn:
        # Update annotations
        for word in req.words:
            ann_data = {k: v for k, v in word.items() if k != "points"}
            if "points" in word:
                ann_data["points"] = json.dumps(word.get("points", []))
            
            if "id" in word and word["id"]:
                # Update existing
                fields = []
                values = []
                for k, v in ann_data.items():
                    if k == "points" and isinstance(v, (list, dict)):
                        v = json.dumps(v)
                    fields.append(f"{k} = ?")
                    values.append(v)
                values.append(word["id"])
                conn.execute(f"UPDATE annotations SET {', '.join(fields)}, updated_at=datetime('now') WHERE id=?", 
                           values + [word["id"]])
            else:
                # Insert new
                fields = ["image_id"] + list(ann_data.keys())
                values = [req.image_id] + list(ann_data.values())
                placeholders = ", ".join(["?"] * len(values))
                conn.execute(f"INSERT INTO annotations ({', '.join(fields)}) VALUES ({', '.join(['?']*len(values))})", values)
        
        # Update image labels
        conn.execute("DELETE FROM image_labels WHERE image_id=?", (req.image_id,))
        for label in req.labels:
            conn.execute("INSERT OR IGNORE INTO image_labels (image_id, tag) VALUES (?, ?)", 
                        (req.image_id, label["tag"]))
        
        # Update OCR
        if req.ocr:
            conn.execute("""
                INSERT INTO image_ocr (image_id, text) VALUES (?, ?)
                ON CONFLICT(image_id) DO UPDATE SET text=excluded.text
            """, (req.image_id, req.ocr))
        
        conn.commit()
        return {"success": True}

@app.get("/api/stats")
def get_stats():
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]
        done = conn.execute("SELECT COUNT(*) FROM images WHERE status='done'").fetchone()[0]
        pending = conn.execute("SELECT COUNT(*) FROM images WHERE status='pending'").fetchone()[0]
        annotated = conn.execute("SELECT COUNT(DISTINCT image_id) FROM annotations").fetchone()[0]
        return {
            "total": total,
            "done": done,
            "pending": pending,
            "annotated": annotated
        }

# Serve frontend
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)