from __future__ import annotations

from backend.plugins.image.plugin import ImagePlugin
from backend.plugins.image.geometry import (
    Point, Rectangle, Polygon,
    polygons_intersect, rect_polygon_intersect, sat_collision,
    geometry_to_dict, dict_to_geometry
)
from backend.plugins.image.crops import save_crop, regenerate_crop, encode_image_base64

__all__ = [
    "ImagePlugin",
    "Point", "Rectangle", "Polygon",
    "polygons_intersect", "rect_polygon_intersect", "sat_collision",
    "geometry_to_dict", "dict_to_geometry",
    "save_crop", "regenerate_crop", "encode_image_base64",
]