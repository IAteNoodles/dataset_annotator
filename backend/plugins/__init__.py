from __future__ import annotations

from backend.plugins.base import BasePlugin, Geometry, CropResult, plugin_registry
from backend.plugins.image.plugin import ImagePlugin

__all__ = ["BasePlugin", "Geometry", "CropResult", "plugin_registry", "ImagePlugin"]


def init_plugins(config) -> None:
    plugin_registry.register(ImagePlugin(config))