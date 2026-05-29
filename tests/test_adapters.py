"""Tests for platform adapters using mock SDK calls."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.models import FileInfo


class TestHuggingFaceAdapterInit:
    def test_init_with_token(self):
        with patch("src.adapters.huggingface_adapter.HfApi") as MockHfApi:
            from src.adapters.huggingface_adapter import HuggingFaceAdapter
            adapter = HuggingFaceAdapter(token="hf_test123")
            MockHfApi.assert_called_once_with(token="hf_test123")
            assert adapter._token == "hf_test123"

    def test_init_without_token(self):
        with patch("src.adapters.huggingface_adapter.HfApi") as MockHfApi:
            from src.adapters.huggingface_adapter import HuggingFaceAdapter
            adapter = HuggingFaceAdapter(token=None)
            MockHfApi.assert_called_once_with(token=None)
            assert adapter._token is None

    def test_platform_is_hf(self):
        with patch("src.adapters.huggingface_adapter.HfApi"):
            from src.adapters.huggingface_adapter import HuggingFaceAdapter
            adapter = HuggingFaceAdapter()
            assert adapter.platform == "hf"

    def test_repo_type_mapping(self):
        with patch("src.adapters.huggingface_adapter.HfApi"):
            from src.adapters.huggingface_adapter import HuggingFaceAdapter
            adapter = HuggingFaceAdapter()
            assert adapter._repo_type("model") == "model"
            assert adapter._repo_type("dataset") == "dataset"


class TestModelScopeAdapterInit:
    def test_platform_is_ms(self):
        with patch("src.adapters.modelscope_adapter.ModelScopeAdapter._init_api", return_value=None):
            from src.adapters.modelscope_adapter import ModelScopeAdapter
            adapter = ModelScopeAdapter(token=None)
            assert adapter.platform == "ms"

    def test_fallback_when_no_sdk(self):
        with patch("src.adapters.modelscope_adapter.ModelScopeAdapter._init_api", return_value=None):
            from src.adapters.modelscope_adapter import ModelScopeAdapter
            adapter = ModelScopeAdapter(token=None)
            assert adapter._use_hf_fallback() is True

    def test_no_fallback_when_sdk_present(self):
        mock_api = MagicMock()
        with patch("src.adapters.modelscope_adapter.ModelScopeAdapter._init_api", return_value=mock_api):
            from src.adapters.modelscope_adapter import ModelScopeAdapter
            adapter = ModelScopeAdapter(token="ms_test")
            assert adapter._use_hf_fallback() is False


class TestChangeDetectorSyncedFilesState:
    """Test that sync_state.synced_files is correctly used in change detection."""

    def test_state_based_change_detection(self):
        """File has no sha256, but state shows it was previously synced with different hash."""
        from src.change_detector import ChangeDetector
        from src.models import FileActionType, RepoSnapshot, SyncState

        source = RepoSnapshot(
            repo_id="test/repo",
            platform="hf",
            resource_type="model",
            file_list=[FileInfo(path="model.bin", size=1000, sha256="new_hash")],
            total_size_bytes=1000,
        )
        target = RepoSnapshot(
            repo_id="test/repo",
            platform="ms",
            resource_type="model",
            # Target has same file, no sha256 available, same size
            file_list=[FileInfo(path="model.bin", size=1000, sha256=None)],
            total_size_bytes=1000,
        )
        state = SyncState(
            repo_key="hf:model:test/repo",
            synced_files={"model.bin": "old_hash"},
        )

        detector = ChangeDetector()
        actions = detector.detect_changes(source, target, state)

        # Source sha256 ("new_hash") differs from state's prev hash ("old_hash") → UPDATE
        assert len(actions) == 1
        assert actions[0].action == FileActionType.UPDATE

    def test_state_based_no_change(self):
        """File unchanged per state — should skip."""
        from src.change_detector import ChangeDetector
        from src.models import FileActionType, RepoSnapshot, SyncState

        source = RepoSnapshot(
            repo_id="test/repo",
            platform="hf",
            resource_type="model",
            file_list=[FileInfo(path="model.bin", size=1000, sha256="same_hash")],
            total_size_bytes=1000,
        )
        target = RepoSnapshot(
            repo_id="test/repo",
            platform="ms",
            resource_type="model",
            file_list=[FileInfo(path="model.bin", size=1000, sha256=None)],
            total_size_bytes=1000,
        )
        state = SyncState(
            repo_key="hf:model:test/repo",
            synced_files={"model.bin": "same_hash"},
        )

        detector = ChangeDetector()
        actions = detector.detect_changes(source, target, state)

        # Source hash matches state's prev hash → no change
        assert len(actions) == 0
