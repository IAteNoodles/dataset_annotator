from __future__ import annotations

import hashlib
import io
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from backend.config import AppConfig
from backend.plugins.image.geometry import Rectangle, Polygon


async def save_crop(
    config: AppConfig,
    data_item: dict[str, Any],
    annotation_id: int,
    geometry_type: str,
    coordinates: Any,
) -> dict[str, Any] | None:
    plugin_config = config.plugin_config
    if not plugin_config.crops.auto_save:
        return None

    return await _generate_crop(config, data_item, annotation_id, geometry_type, coordinates)


async def regenerate_crop(
    config: AppConfig,
    data_item: dict[str, Any],
    annotation_id: int,
    geometry_type: str,
    coordinates: Any,
    old_crop_path: str | None,
) -> dict[str, Any] | None:
    plugin_config = config.plugin_config
    if not plugin_config.crops.auto_save:
        return None

    if old_crop_path:
        full_old_path = Path(config.dataset.path) / old_crop_path
        if full_old_path.exists():
            full_old_path.unlink(missing_ok=True)

    return await _generate_crop(config, data_item, annotation_id, geometry_type, coordinates)


async def _generate_crop(
    config: AppConfig,
    data_item: dict[str, Any],
    annotation_id: int,
    geometry_type: str,
    coordinates: Any,
) -> dict[str, Any] | None:
    try:
        source_path = Path(data_item["source_path"])
        if not source_path.exists():
            return None

        with Image.open(source_path) as img:
            img_width, img_height = img.size

            if geometry_type == "rectangle":
                coords = coordinates
                x1, y1 = coords[0]
                x2, y2 = coords[1]

                left = max(0, min(x1, x2))
                top = max(0, min(y1, y2))
                right = min(img_width, max(x1, x2))
                bottom = min(img_height, max(y1, y2))

                padding = plugin_config.crops.padding
                left = max(0, left - padding)
                top = max(0, top - padding)
                right = min(img_width, right + padding)
                bottom = min(img_height, bottom + padding)

                if right <= left or bottom <= top:
                    return None

                crop = img.crop((left, top, right, bottom))

            elif geometry_type == "polygon":
                coords = coordinates
                mask = Image.new("L", (img_width, img_height), 0)
                draw = ImageDraw.Draw(mask)
                draw.polygon([tuple(p) for p in coords], fill=255)

                crop = Image.new("RGBA", (img_width, img_height))
                crop.paste(img.convert("RGBA"), mask=mask)

                bbox = mask.getbbox()
                if bbox:
                    padding = plugin_config.crops.padding
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

        crops_dir = Path(config.dataset.path) / plugin_config.crops.output_dir
        crops_dir.mkdir(parents=True, exist_ok=True)

        naming = plugin_config.crops.naming_template
        crop_filename = naming.format(
            dataset=config.dataset.name,
            item_id=data_item["id"],
            annotation_id=annotation_id,
        ) + f".{plugin_config.crops.format}"

        crop_path = crops_dir / crop_filename

        crop.save(
            crop_path,
            format=plugin_config.crops.format.upper(),
            quality=plugin_config.crops.quality,
        )

        sha256_hash = hashlib.sha256()
        with open(crop_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256_hash.update(chunk)

        rel_crop_path = crop_path.relative_to(Path(config.dataset.path))

        return {
            "crop_path": str(rel_crop_path),
            "crop_sha256": sha256_hash.hexdigest(),
            "width": crop.width,
            "height": crop.height,
        }

    except Exception as e:
        print(f"Crop generation failed: {e}")
        return None


def encode_image_base64(image_path: Path, max_dimension: int = 0) -> str:
    import base64
    with Image.open(image_path) as img:
        if max_dimension > 0:
            img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)

        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode()