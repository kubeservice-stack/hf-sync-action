"""Tests for utility functions."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.models import SyncState
from src.utils import (
    file_sha256,
    format_bytes,
    load_sync_states,
    mask_token,
    matches_patterns,
    save_sync_states,
)


class TestMatchesPatterns:
    def test_include_match(self):
        assert matches_patterns("model.safetensors", ["*.safetensors"])

    def test_include_no_match(self):
        assert not matches_patterns("model.bin", ["*.safetensors"])

    def test_exclude_match(self):
        assert not matches_patterns("old.bin", ["*"], ["*.bin"])

    def test_no_patterns(self):
        assert matches_patterns("anything.txt")

    def test_multiple_include(self):
        assert matches_patterns("config.json", ["*.json", "*.yaml"])
        assert not matches_patterns("config.toml", ["*.json", "*.yaml"])

    def test_nested_path(self):
        assert matches_patterns("subdir/model.safetensors", ["*.safetensors"])


class TestFormatBytes:
    def test_bytes(self):
        assert format_bytes(500) == "500.0 B"

    def test_kilobytes(self):
        assert format_bytes(1500) == "1.5 KB"

    def test_megabytes(self):
        assert format_bytes(5 * 1024 * 1024) == "5.0 MB"

    def test_gigabytes(self):
        assert format_bytes(2.5 * 1024**3) == "2.5 GB"


class TestFileSha256:
    def test_hash(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world")
        h = file_sha256(f)
        assert isinstance(h, str)
        assert len(h) == 64  # SHA-256 hex digest length


class TestMaskToken:
    def test_long_token(self):
        masked = mask_token("hf_abcdefghijklmnop")
        assert masked.startswith("hf_a")
        assert masked.endswith("mnop")
        assert "****" in masked

    def test_short_token(self):
        assert mask_token("short") == "****"

    def test_none(self):
        assert mask_token(None) == "<not set>"


class TestSyncStatePersistence:
    def test_save_and_load(self, tmp_path):
        state = SyncState(
            repo_key="hf:model:test/repo",
            last_synced_commit="abc123",
            last_synced_at=datetime(2025, 6, 1, tzinfo=timezone.utc),
            synced_files={"model.safetensors": "hash123"},
        )
        states = {"hf:model:test/repo": state}

        save_sync_states(states, tmp_path)

        loaded = load_sync_states(tmp_path)
        assert "hf:model:test/repo" in loaded
        assert loaded["hf:model:test/repo"].last_synced_commit == "abc123"
        assert loaded["hf:model:test/repo"].synced_files == {"model.safetensors": "hash123"}

    def test_load_empty_dir(self, tmp_path):
        states = load_sync_states(tmp_path)
        assert states == {}

    def test_make_key(self):
        key = SyncState.make_key("hf", "model", "test/repo")
        assert key == "hf:model:test/repo"
