"""Tests for config loading and validation."""

from __future__ import annotations

import pytest
import yaml

from src.config import GlobalConfig, ItemConfig, SyncConfig, load_config
from src.models import ConflictStrategy, SyncDirection


class TestGlobalConfig:
    def test_defaults(self):
        gc = GlobalConfig()
        assert gc.sync_direction == SyncDirection.BIDIRECTIONAL
        assert gc.conflict_strategy == ConflictStrategy.NEWER_WINS
        assert gc.max_file_size_gb == 50.0
        assert gc.retry_attempts == 3
        assert gc.max_parallel_downloads == 4

    def test_max_file_size_bytes(self):
        gc = GlobalConfig(max_file_size_gb=1.0)
        assert gc.max_file_size_bytes == 1024 * 1024 * 1024


class TestItemConfig:
    def test_valid_item(self):
        item = ItemConfig(
            name="test-model",
            hf_repo_id="org/model",
            ms_repo_id="org/model",
        )
        assert item.name == "test-model"
        assert item.enabled is True
        assert item.direction is None

    def test_empty_name_rejected(self):
        with pytest.raises(ValueError, match="name must not be empty"):
            ItemConfig(name="  ", hf_repo_id="a/b", ms_repo_id="a/b")

    def test_custom_patterns(self):
        item = ItemConfig(
            name="test",
            hf_repo_id="a/b",
            ms_repo_id="a/b",
            include_patterns=["*.safetensors"],
            exclude_patterns=["*.bin"],
        )
        assert item.include_patterns == ["*.safetensors"]
        assert item.exclude_patterns == ["*.bin"]


class TestSyncConfig:
    def test_empty_config(self):
        cfg = SyncConfig(global_config=GlobalConfig())
        assert cfg.models == []
        assert cfg.datasets == []

    def test_from_dict(self):
        raw = {
            "global": {
                "sync_direction": "hf_to_ms",
                "conflict_strategy": "skip",
            },
            "models": [
                {
                    "name": "m1",
                    "hf_repo_id": "a/b",
                    "ms_repo_id": "a/b",
                    "direction": "hf_to_ms",
                }
            ],
            "datasets": [],
        }
        cfg = SyncConfig.model_validate(raw)
        assert cfg.global_config.sync_direction == SyncDirection.HF_TO_MS
        assert cfg.global_config.conflict_strategy == ConflictStrategy.SKIP
        assert len(cfg.models) == 1


class TestLoadConfig:
    def test_load_valid_yaml(self, tmp_path):
        config_data = {
            "global": {"sync_direction": "hf_to_ms"},
            "models": [{"name": "test", "hf_repo_id": "a/b", "ms_repo_id": "a/b"}],
        }
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(config_data))

        cfg = load_config(config_file)
        assert cfg.global_config.sync_direction == SyncDirection.HF_TO_MS
        assert len(cfg.models) == 1

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            load_config("/nonexistent/config.yaml")

    def test_empty_yaml(self, tmp_path):
        config_file = tmp_path / "empty.yaml"
        config_file.write_text("")
        cfg = load_config(config_file)
        assert cfg.models == []
        assert cfg.datasets == []
