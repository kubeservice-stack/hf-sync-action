"""Configuration loading and validation for HF-MS Sync."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

from src.models import ConflictStrategy, SyncDirection

logger = logging.getLogger(__name__)


class GlobalConfig(BaseModel):
    """Global sync settings."""

    sync_direction: SyncDirection = SyncDirection.BIDIRECTIONAL
    conflict_strategy: ConflictStrategy = ConflictStrategy.NEWER_WINS
    max_file_size_gb: float = 50.0
    retry_attempts: int = 3
    retry_delay_seconds: int = 30
    max_parallel_downloads: int = 4
    max_parallel_uploads: int = 2
    delete_orphaned: bool = False  # delete files on target that don't exist on source

    @property
    def max_file_size_bytes(self) -> int:
        return int(self.max_file_size_gb * 1024 * 1024 * 1024)


class ItemConfig(BaseModel):
    """Configuration for a single sync item (model or dataset)."""

    name: str
    hf_repo_id: str
    ms_repo_id: str
    direction: SyncDirection | None = None  # None means use global
    include_patterns: list[str] = Field(default_factory=lambda: ["*"])
    exclude_patterns: list[str] = Field(default_factory=list)
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("name must not be empty")
        return v.strip()


class SyncConfig(BaseModel):
    """Root configuration model."""

    global_config: GlobalConfig = Field(default_factory=GlobalConfig, alias="global")
    models: list[ItemConfig] = Field(default_factory=list)
    datasets: list[ItemConfig] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


def load_config(config_path: str | Path) -> SyncConfig:
    """Load and validate sync configuration from a YAML file."""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    logger.info("Loading config from %s", path)

    with open(path, "r", encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    config = SyncConfig.model_validate(raw)

    model_count = sum(1 for m in config.models if m.enabled)
    dataset_count = sum(1 for d in config.datasets if d.enabled)
    logger.info(
        "Config loaded: %d models, %d datasets (direction=%s)",
        model_count,
        dataset_count,
        config.global_config.sync_direction.value,
    )

    return config
