from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from backend.config import AppConfig
from backend.database import Database


@dataclass
class Geometry:
    type: str
    coordinates: list[list[float]] | list[float]

    def to_json(self) -> str:
        import json
        return json.dumps({"type": self.type, "coordinates": self.coordinates})

    @classmethod
    def from_json(cls, json_str: str) -> Geometry:
        import json
        data = json.loads(json_str)
        return cls(type=data["type"], coordinates=data["coordinates"])


@dataclass
class CropResult:
    crop_path: str
    crop_sha256: str
    width: int
    height: int


class BasePlugin(ABC):
    name: str
    supported_modes: list[str]
    mime_types: list[str]

    @abstractmethod
    async def validate_geometry(self, geometry: Geometry) -> bool:
        pass

    @abstractmethod
    async def create_crop(
        self,
        db: Database,
        config: AppConfig,
        data_item: dict[str, Any],
        annotation_id: int,
        geometry: Geometry,
    ) -> CropResult | None:
        pass

    @abstractmethod
    async def regenerate_crop(
        self,
        db: Database,
        config: AppConfig,
        data_item: dict[str, Any],
        annotation_id: int,
        geometry: Geometry,
        old_crop_path: str | None,
    ) -> CropResult | None:
        pass

    @abstractmethod
    async def check_intersection(
        self,
        db: Database,
        data_item_id: int,
        geometry: Geometry,
        exclude_annotation_id: int | None = None,
    ) -> bool:
        pass

    @abstractmethod
    def get_default_geometry(self) -> Geometry:
        pass

    @abstractmethod
    def geometry_to_canvas(self, geometry: Geometry) -> dict[str, Any]:
        pass

    @abstractmethod
    def canvas_to_geometry(self, canvas_obj: dict[str, Any]) -> Geometry:
        pass


class PluginRegistry:
    def __init__(self):
        self._plugins: dict[str, BasePlugin] = {}

    def register(self, plugin: BasePlugin) -> None:
        self._plugins[plugin.name] = plugin

    def get(self, name: str) -> BasePlugin | None:
        return self._plugins.get(name)

    def get_for_dataset(self, config: AppConfig) -> BasePlugin:
        plugin = self._plugins.get(config.dataset.plugin)
        if not plugin:
            raise ValueError(f"Plugin not found: {config.dataset.plugin}")
        return plugin


plugin_registry = PluginRegistry()