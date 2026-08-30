from __future__ import annotations

from backend.config import AppConfig
from backend.database import Database

config: AppConfig | None = None
db: Database | None = None


def set_config(cfg: AppConfig) -> None:
    global config
    config = cfg


def get_config() -> AppConfig:
    if config is None:
        raise RuntimeError("Config not initialized")
    return config


def set_db(database: Database) -> None:
    global db
    db = database


def get_db() -> Database:
    if db is None:
        raise RuntimeError("Database not initialized")
    return db