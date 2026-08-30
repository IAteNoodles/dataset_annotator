from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import shutil
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from backend.config import AppConfig
from backend.database import Database
from backend.plugins.base import BasePlugin, CropResult, Geometry, plugin_registry


class ImagePlugin(BasePlugin):
    name = "image"
    supported_modes = ["rectangle_box", "rotated_box", "polygon", "point", "line"]
    mime_types = ["image/jpeg", "image/png", "image/tiff", "image/bmp", "image/webp"]

    def __init__(self, config: AppConfig):
        self.config = config
        self.plugin_config = config.plugin_config

    async def validate_geometry(self, geometry: Geometry) -> bool:
        if geometry.type == "rectangle":
            coords = geometry.coordinates
            if not isinstance(coords, list) or len(coords) != 2:
                return False
            for point in coords:
                if not isinstance(point, list) or len(point) != 2:
                    return False
            x1, y1 = coords[0]
            x2, y2 = coords[1]
            min_size = self.plugin_config.min_annotation_size
            return abs(x2 - x1) >= min_size and abs(y2 - y1) >= min_size

        elif geometry.type == "polygon":
            coords = geometry.coordinates
            if not isinstance(coords, list) or len(coords) < 3:
                return False
            for point in coords:
                if not isinstance(point, list) or len(point) != 2:
                    return False
            return True

        elif geometry.type == "point":
            coords = geometry.coordinates
            return isinstance(coords, list) and len(coords) == 2

        elif geometry.type == "line":
            coords = geometry.coordinates
            if not isinstance(coords, list) or len(coords) != 2:
                return False
            for point in coords:
                if not isinstance(point, list) or len(point) != 2:
                    return False
            return True

        elif geometry.type == "rotated_rectangle":
            coords = geometry.coordinates
            if not isinstance(coords, list) or len(coords) != 5:
                return False
            return True

        return False

    async def create_crop(
        self,
        db: Database,
        config: AppConfig,
        data_item: dict[str, Any],
        annotation_id: int,
        geometry: Geometry,
    ) -> CropResult | None:
        if not self.plugin_config.crops.auto_save:
            return None

        return await self._generate_crop(db, config, data_item, annotation_id, geometry, None)

    async def regenerate_crop(
        self,
        db: Database,
        config: AppConfig,
        data_item: dict[str, Any],
        annotation_id: int,
        geometry: Geometry,
        old_crop_path: str | None,
    ) -> CropResult | None:
        if not self.plugin_config.crops.auto_save:
            return None

        if old_crop_path:
            full_old_path = Path(config.dataset.path) / old_crop_path
            if full_old_path.exists():
                full_old_path.unlink(missing_ok=True)

        return await self._generate_crop(db, config, data_item, annotation_id, geometry, old_crop_path)

    async def _generate_crop(
        self,
        db: Database,
        config: AppConfig,
        data_item: dict[str, Any],
        annotation_id: int,
        geometry: Geometry,
        old_crop_path: str | None,
    ) -> CropResult | None:
        try:
            source_path = Path(data_item["source_path"])
            if not source_path.exists():
                return None

            with Image.open(source_path) as img:
                img_width, img_height = img.size

                if geometry.type == "rectangle":
                    coords = geometry.coordinates
                    x1, y1 = coords[0]
                    x2, y2 = coords[1]

                    left = max(0, min(x1, x2))
                    top = max(0, min(y1, y2))
                    right = min(img_width, max(x1, x2))
                    bottom = min(img_height, max(y1, y2))

                    padding = self.plugin_config.crops.padding
                    left = max(0, left - padding)
                    top = max(0, top - padding)
                    right = min(img_width, right + padding)
                    bottom = min(img_height, bottom + padding)

                    if right <= left or bottom <= top:
                        return None

                    crop = img.crop((left, top, right, bottom))

                elif geometry.type == "polygon":
                    coords = geometry.coordinates
                    mask = Image.new("L", (img_width, img_height), 0)
                    draw = ImageDraw.Draw(mask)
                    draw.polygon([tuple(p) for p in coords], fill=255)

                    crop = Image.new("RGBA", (img_width, img_height))
                    crop.paste(img.convert("RGBA"), mask=mask)

                    bbox = mask.getbbox()
                    if bbox:
                        padding = self.plugin_config.crops.padding
                        bbox = (
                            max(0, bbox[0] - padding),
                            max(0, bbox[1] - padding),
                            min(img_width, bbox[2] + padding),
                            min(img_height, bbox[3] + padding),
                        )
                        crop = crop.crop(bbox)
                    else:
                        return None

                else:
                    return None

            crops_dir = Path(config.dataset.path) / self.plugin_config.crops.output_dir
            crops_dir.mkdir(parents=True, exist_ok=True)

            naming = self.plugin_config.crops.naming_template
            crop_filename = naming.format(
                dataset=config.dataset.name,
                item_id=data_item["id"],
                annotation_id=annotation_id,
            ) + f".{self.plugin_config.crops.format}"

            crop_path = crops_dir / crop_filename

            crop.save(
                crop_path,
                format=self.plugin_config.crops.format.upper(),
                quality=self.plugin_config.crops.quality,
            )

            sha256_hash = hashlib.sha256()
            with open(crop_path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    sha256_hash.update(chunk)

            rel_crop_path = crop_path.relative_to(Path(config.dataset.path))

            return CropResult(
                crop_path=str(rel_crop_path),
                crop_sha256=sha256_hash.hexdigest(),
                width=crop.width,
                height=crop.height,
            )

        except Exception as e:
            print(f"Crop generation failed: {e}")
            return None

    async def check_intersection(
        self,
        db: Database,
        data_item_id: int,
        geometry: Geometry,
        exclude_annotation_id: int | None = None,
    ) -> bool:
        if not self.plugin_config.allow_intersections:
            existing = await db.fetchall(
                "SELECT geometry_json FROM annotations WHERE data_item_id = ? AND id != ?",
                (data_item_id, exclude_annotation_id or -1)
            )

            for ann in existing:
                existing_geom = Geometry.from_json(ann["geometry_json"])
                if self._geometries_intersect(geometry, existing_geom):
                    return True
        return False

    def _geometries_intersect(self, g1: Geometry, g2: Geometry) -> bool:
        if g1.type == "rectangle" and g2.type == "rectangle":
            return self._rectangles_intersect(g1.coordinates, g2.coordinates)
        elif g1.type == "polygon" and g2.type == "polygon":
            return self._polygons_intersect(g1.coordinates, g2.coordinates)
        elif g1.type == "rectangle" and g2.type == "polygon":
            return self._rect_polygon_intersect(g1.coordinates, g2.coordinates)
        elif g1.type == "polygon" and g2.type == "rectangle":
            return self._rect_polygon_intersect(g2.coordinates, g1.coordinates)
        return False

    def _rectangles_intersect(self, r1: list[list[float]], r2: list[list[float]]) -> bool:
        x1_min, y1_min = min(r1[0][0], r1[1][0]), min(r1[0][1], r1[1][1])
        x1_max, y1_max = max(r1[0][0], r1[1][0]), max(r1[0][1], r1[1][1])
        x2_min, y2_min = min(r2[0][0], r2[1][0]), min(r2[0][1], r2[1][1])
        x2_max, y2_max = max(r2[0][0], r2[1][0]), max(r2[0][1], r2[1][1])

        return not (x1_max < x2_min or x2_max < x1_min or y1_max < y2_min or y2_max < y1_min)

    def _polygons_intersect(self, p1: list[list[float]], p2: list[list[float]]) -> bool:
        return self._sat_collision(p1, p2)

    def _rect_polygon_intersect(self, rect: list[list[float]], poly: list[list[float]]) -> bool:
        x_min, y_min = min(rect[0][0], rect[1][0]), min(rect[0][1], rect[1][1])
        x_max, y_max = max(rect[0][0], rect[1][0]), max(rect[0][1], rect[1][1])
        rect_poly = [[x_min, y_min], [x_max, y_min], [x_max, y_max], [x_min, y_max]]
        return self._sat_collision(rect_poly, poly)

    def _sat_collision(self, poly1: list[list[float]], poly2: list[list[float]]) -> bool:
        def get_axes(poly):
            axes = []
            n = len(poly)
            for i in range(n):
                p1 = poly[i]
                p2 = poly[(i + 1) % n]
                edge = [p2[0] - p1[0], p2[1] - p1[1]]
                length = (edge[0] ** 2 + edge[1] ** 2) ** 0.5
                if length > 0:
                    axes.append([-edge[1] / length, edge[0] / length])
            return axes

        def project(poly, axis):
            dots = [p[0] * axis[0] + p[1] * axis[1] for p in poly]
            return min(dots), max(dots)

        for axis in get_axes(poly1) + get_axes(poly2):
            min1, max1 = project(poly1, axis)
            min2, max2 = project(poly2, axis)
            if max1 < min2 or max2 < min1:
                return False
        return True

    def get_default_geometry(self) -> Geometry:
        return Geometry(type="rectangle", coordinates=[[100, 100], [300, 300]])

    def geometry_to_canvas(self, geometry: Geometry) -> dict[str, Any]:
        if geometry.type == "rectangle":
            coords = geometry.coordinates
            x1, y1 = coords[0]
            x2, y2 = coords[1]
            return {
                "type": "rect",
                "left": min(x1, x2),
                "top": min(y1, y2),
                "width": abs(x2 - x1),
                "height": abs(y2 - y1),
            }
        elif geometry.type == "polygon":
            return {
                "type": "polygon",
                "points": geometry.coordinates,
            }
        elif geometry.type == "point":
            return {
                "type": "circle",
                "left": geometry.coordinates[0],
                "top": geometry.coordinates[1],
                "radius": 5,
            }
        elif geometry.type == "line":
            return {
                "type": "line",
                "x1": geometry.coordinates[0][0],
                "y1": geometry.coordinates[0][1],
                "x2": geometry.coordinates[1][0],
                "y2": geometry.coordinates[1][1],
            }
        return {}

    def canvas_to_geometry(self, canvas_obj: dict[str, Any]) -> Geometry:
        obj_type = canvas_obj.get("type")

        if obj_type == "rect":
            left = canvas_obj["left"]
            top = canvas_obj["top"]
            width = canvas_obj["width"]
            height = canvas_obj["height"]
            return Geometry(
                type="rectangle",
                coordinates=[[left, top], [left + width, top + height]]
            )
        elif obj_type == "polygon":
            return Geometry(type="polygon", coordinates=canvas_obj["points"])
        elif obj_type == "circle":
            return Geometry(type="point", coordinates=[canvas_obj["left"], canvas_obj["top"]])
        elif obj_type == "line":
            return Geometry(
                type="line",
                coordinates=[[canvas_obj["x1"], canvas_obj["y1"]], [canvas_obj["x2"], canvas_obj["y2"]]]
            )
        return Geometry(type="rectangle", coordinates=[[0, 0], [100, 100]])

    async def encode_image_base64(self, image_path: Path, max_dimension: int = 0) -> str:
        with Image.open(image_path) as img:
            if max_dimension > 0:
                img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)

            buffer = io.BytesIO()
            img.save(buffer, format="PNG")
            return base64.b64encode(buffer.getvalue()).decode()