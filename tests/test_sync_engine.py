"""Tests for sync engine using mock adapters."""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.config import GlobalConfig, ItemConfig, SyncConfig
from src.models import (
    FileInfo,
    RepoSnapshot,
    SyncDirection,
    SyncResult,
    SyncStatus,
)
from src.sync_engine import SyncEngine


class MockAdapter:
    """Mock platform adapter for testing."""

    def __init__(self, platform: str = "hf"):
        self.platform = platform
        self._files: dict[str, bytes] = {}
        self._commit = "mock_commit_001"
        self.uploaded: list[tuple[str, str]] = []  # (repo_id, remote_path)

    def get_repo_snapshot(self, repo_id, resource_type):
        file_list = [
            FileInfo(path=name, size=len(data), sha256=f"hash_{name}")
            for name, data in self._files.items()
        ]
        return RepoSnapshot(
            repo_id=repo_id,
            platform=self.platform,
            resource_type=resource_type,
            last_commit_hash=self._commit,
            last_modified=datetime(2025, 1, 1, tzinfo=timezone.utc),
            file_list=file_list,
            total_size_bytes=sum(len(d) for d in self._files.values()),
        )

    def download_file(self, repo_id, file_path, local_dir, resource_type):
        data = self._files.get(file_path, b"mock_data")
        local_path = local_dir / file_path
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(data)
        return local_path

    def upload_file(self, repo_id, local_path, remote_path, resource_type):
        self.uploaded.append((repo_id, remote_path))

    def create_repo_if_needed(self, repo_id, resource_type):
        pass


def make_config(
    direction="hf_to_ms",
    models=None,
    datasets=None,
) -> SyncConfig:
    global_cfg = GlobalConfig(
        sync_direction=SyncDirection(direction),
        max_parallel_downloads=2,
    )
    model_items = []
    for m in (models or [{"name": "test", "hf_repo_id": "a/b", "ms_repo_id": "a/b"}]):
        model_items.append(ItemConfig(**m))
    dataset_items = []
    for d in (datasets or []):
        dataset_items.append(ItemConfig(**d))

    return SyncConfig(
        global_config=global_cfg,
        models=model_items,
        datasets=dataset_items,
    )


class TestSyncEngine:
    def test_sync_new_files_hf_to_ms(self, tmp_path):
        hf = MockAdapter("hf")
        hf._files = {"model.safetensors": b"weights_data", "config.json": b"{}"}

        ms = MockAdapter("ms")
        ms._files = {}  # Empty target

        config = make_config(direction="hf_to_ms")
        engine = SyncEngine(
            config=config,
            hf_adapter=hf,
            ms_adapter=ms,
            state_dir=tmp_path,
            dry_run=False,
        )

        results = engine.sync_all()

        assert len(results) == 1
        assert results[0].status == SyncStatus.SUCCESS
        assert len(results[0].files_synced) == 2
        # Verify files were uploaded to MS
        assert len(ms.uploaded) == 2
        uploaded_paths = {path for _, path in ms.uploaded}
        assert "model.safetensors" in uploaded_paths
        assert "config.json" in uploaded_paths

    def test_sync_skips_identical_files(self, tmp_path):
        hf = MockAdapter("hf")
        hf._files = {"config.json": b"{}"}

        ms = MockAdapter("ms")
        ms._files = {"config.json": b"{}"}

        config = make_config(direction="hf_to_ms")
        engine = SyncEngine(
            config=config, hf_adapter=hf, ms_adapter=ms, state_dir=tmp_path,
        )

        results = engine.sync_all()
        assert results[0].status == SyncStatus.SUCCESS
        assert len(results[0].files_synced) == 0
        assert len(ms.uploaded) == 0

    def test_dry_run_no_transfer(self, tmp_path):
        hf = MockAdapter("hf")
        hf._files = {"model.safetensors": b"data"}

        ms = MockAdapter("ms")
        ms._files = {}

        config = make_config(direction="hf_to_ms")
        engine = SyncEngine(
            config=config, hf_adapter=hf, ms_adapter=ms,
            state_dir=tmp_path, dry_run=True,
        )

        results = engine.sync_all()
        assert results[0].status == SyncStatus.SUCCESS
        assert len(results[0].files_synced) == 1
        # Dry run: no actual uploads
        assert len(ms.uploaded) == 0

    def test_target_filter(self, tmp_path):
        hf = MockAdapter("hf")
        hf._files = {"model.safetensors": b"data"}

        ms = MockAdapter("ms")
        ms._files = {}

        config = make_config(
            direction="hf_to_ms",
            models=[
                {"name": "model-a", "hf_repo_id": "a/a", "ms_repo_id": "a/a"},
                {"name": "model-b", "hf_repo_id": "b/b", "ms_repo_id": "b/b"},
            ],
        )
        engine = SyncEngine(
            config=config, hf_adapter=hf, ms_adapter=ms,
            state_dir=tmp_path, target_filter="model-a",
        )

        results = engine.sync_all()
        assert len(results) == 1
        assert results[0].item_name == "model-a"

    def test_disabled_items_skipped(self, tmp_path):
        config = make_config(
            direction="hf_to_ms",
            models=[
                {"name": "enabled", "hf_repo_id": "a/b", "ms_repo_id": "a/b", "enabled": True},
                {"name": "disabled", "hf_repo_id": "c/d", "ms_repo_id": "c/d", "enabled": False},
            ],
        )
        hf = MockAdapter("hf")
        hf._files = {"model.safetensors": b"data"}
        ms = MockAdapter("ms")

        engine = SyncEngine(
            config=config, hf_adapter=hf, ms_adapter=ms, state_dir=tmp_path,
        )

        results = engine.sync_all()
        assert len(results) == 1
        assert results[0].item_name == "enabled"

    def test_direction_override(self, tmp_path):
        hf = MockAdapter("hf")
        hf._files = {"model.safetensors": b"data"}
        ms = MockAdapter("ms")
        ms._files = {}

        config = make_config(direction="hf_to_ms")
        engine = SyncEngine(
            config=config, hf_adapter=hf, ms_adapter=ms,
            state_dir=tmp_path, direction_override="ms_to_hf",
        )

        results = engine.sync_all()
        assert results[0].direction == "ms_to_hf"

    def test_state_persisted(self, tmp_path):
        hf = MockAdapter("hf")
        hf._files = {"config.json": b"{}"}
        ms = MockAdapter("ms")
        ms._files = {}

        config = make_config(direction="hf_to_ms")
        engine = SyncEngine(
            config=config, hf_adapter=hf, ms_adapter=ms, state_dir=tmp_path,
        )

        engine.sync_all()

        state_file = tmp_path / "sync_state.json"
        assert state_file.exists()
