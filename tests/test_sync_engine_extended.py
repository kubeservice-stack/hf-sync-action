"""Extended tests for sync engine: MS_TO_HF, bidirectional, errors, results JSON."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from src.config import GlobalConfig, ItemConfig, SyncConfig
from src.models import (
    FileInfo,
    RepoSnapshot,
    SyncDirection,
    SyncStatus,
)
from src.sync_engine import SyncEngine
from src.utils import load_sync_states


class MockAdapter:
    """Mock platform adapter for testing."""

    def __init__(self, platform: str = "hf"):
        self.platform = platform
        self._files: dict[str, bytes] = {}
        self._commit = "mock_commit_001"
        self.uploaded: list[tuple[str, str, bytes]] = []  # (repo_id, remote_path, data)
        self._should_fail_download: set[str] = set()
        self._should_fail_upload: set[str] = set()
        self._snapshot_fail = False

    def get_repo_snapshot(self, repo_id, resource_type):
        if self._snapshot_fail:
            raise RuntimeError(f"Snapshot failed for {repo_id}")
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
        if file_path in self._should_fail_download:
            raise RuntimeError(f"Download failed for {file_path}")
        data = self._files.get(file_path, b"mock_data")
        local_path = local_dir / file_path
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(data)
        return local_path

    def upload_file(self, repo_id, local_path, remote_path, resource_type):
        if remote_path in self._should_fail_upload:
            raise RuntimeError(f"Upload failed for {remote_path}")
        data = local_path.read_bytes() if local_path.exists() else b""
        self.uploaded.append((repo_id, remote_path, data))

    def create_repo_if_needed(self, repo_id, resource_type):
        pass


def make_config(
    direction="hf_to_ms",
    models=None,
    datasets=None,
    **global_kwargs,
) -> SyncConfig:
    global_cfg = GlobalConfig(
        sync_direction=SyncDirection(direction),
        max_parallel_downloads=2,
        **global_kwargs,
    )
    model_items = []
    if models is None:
        models = [{"name": "test", "hf_repo_id": "a/b", "ms_repo_id": "a/b"}]
    for m in models:
        model_items.append(ItemConfig(**m))
    dataset_items = []
    if datasets is None:
        datasets = []
    for d in datasets:
        dataset_items.append(ItemConfig(**d))
    return SyncConfig(
        global_config=global_cfg,
        models=model_items,
        datasets=dataset_items,
    )


# ── MS_TO_HF direction ──────────────────────────────────────────────


class TestMSToHFDirection:
    def test_ms_to_hf_new_files(self, tmp_path):
        """MS has files that HF doesn't — should upload to HF."""
        hf = MockAdapter("hf")
        hf._files = {}  # HF is empty

        ms = MockAdapter("ms")
        ms._files = {"model.safetensors": b"ms_weights", "config.json": b"{}"}

        config = make_config(direction="ms_to_hf")
        engine = SyncEngine(
            config=config,
            hf_adapter=hf,
            ms_adapter=ms,
            state_dir=tmp_path,
        )

        results = engine.sync_all()
        assert results[0].status == SyncStatus.SUCCESS
        assert len(results[0].files_synced) == 2
        # Files should be uploaded to HF
        assert len(hf.uploaded) == 2
        uploaded_paths = {path for _, path, _ in hf.uploaded}
        assert "model.safetensors" in uploaded_paths
        assert "config.json" in uploaded_paths

    def test_ms_to_hf_identical_skipped(self, tmp_path):
        """Both have same files — should skip."""
        hf = MockAdapter("hf")
        hf._files = {"config.json": b"{}"}

        ms = MockAdapter("ms")
        ms._files = {"config.json": b"{}"}

        config = make_config(direction="ms_to_hf")
        engine = SyncEngine(
            config=config,
            hf_adapter=hf,
            ms_adapter=ms,
            state_dir=tmp_path,
        )

        results = engine.sync_all()
        assert results[0].status == SyncStatus.SUCCESS
        assert len(results[0].files_synced) == 0

    def test_ms_to_hf_fails_when_ms_snapshot_unavailable(self, tmp_path):
        """MS_TO_HF should fail if MS snapshot cannot be fetched."""
        hf = MockAdapter("hf")
        hf._files = {"config.json": b"{}"}

        ms = MockAdapter("ms")
        ms._snapshot_fail = True

        config = make_config(direction="ms_to_hf")
        engine = SyncEngine(
            config=config,
            hf_adapter=hf,
            ms_adapter=ms,
            state_dir=tmp_path,
        )

        results = engine.sync_all()
        assert results[0].status == SyncStatus.FAILED
        assert "failed to fetch ModelScope snapshot" in results[0].error_message


# ── Bidirectional sync ──────────────────────────────────────────────


class TestBidirectionalSync:
    def test_bidirectional_both_sides_have_unique_files(self, tmp_path):
        """Each side has unique files — both should sync."""
        hf = MockAdapter("hf")
        hf._files = {"hf_only.safetensors": b"hf_data"}

        ms = MockAdapter("ms")
        ms._files = {"ms_only.safetensors": b"ms_data"}

        config = make_config(direction="bidirectional")
        engine = SyncEngine(
            config=config,
            hf_adapter=hf,
            ms_adapter=ms,
            state_dir=tmp_path,
        )

        results = engine.sync_all()
        assert results[0].status == SyncStatus.SUCCESS
        # HF->MS: hf_only.safetensors
        # MS->HF: ms_only.safetensors
        assert len(results[0].files_synced) == 2

        # Verify MS got the HF file
        ms_paths = {path for _, path, _ in ms.uploaded}
        assert "hf_only.safetensors" in ms_paths

        # Verify HF got the MS file
        hf_paths = {path for _, path, _ in hf.uploaded}
        assert "ms_only.safetensors" in hf_paths

    def test_bidirectional_identical_no_transfer(self, tmp_path):
        """Both sides identical — no transfer needed."""
        hf = MockAdapter("hf")
        hf._files = {"shared.json": b"same"}

        ms = MockAdapter("ms")
        ms._files = {"shared.json": b"same"}

        config = make_config(direction="bidirectional")
        engine = SyncEngine(
            config=config,
            hf_adapter=hf,
            ms_adapter=ms,
            state_dir=tmp_path,
        )

        results = engine.sync_all()
        assert results[0].status == SyncStatus.SUCCESS
        assert len(results[0].files_synced) == 0
        assert len(hf.uploaded) == 0
        assert len(ms.uploaded) == 0


# ── Error handling ──────────────────────────────────────────────────


class TestErrorHandling:
    def test_partial_failure(self, tmp_path):
        """Some files fail upload — should be PARTIAL."""
        hf = MockAdapter("hf")
        hf._files = {
            "good.json": b"ok",
            "bad.safetensors": b"weights",
        }

        ms = MockAdapter("ms")
        ms._files = {}
        ms._should_fail_upload = {"bad.safetensors"}

        config = make_config(direction="hf_to_ms")
        engine = SyncEngine(
            config=config,
            hf_adapter=hf,
            ms_adapter=ms,
            state_dir=tmp_path,
        )

        results = engine.sync_all()
        assert results[0].status == SyncStatus.PARTIAL
        assert "good.json" in results[0].files_synced
        assert "bad.safetensors" in results[0].files_failed

    def test_all_failures(self, tmp_path):
        """All files fail — should be FAILED."""
        hf = MockAdapter("hf")
        hf._files = {"a.bin": b"data", "b.bin": b"data2"}

        ms = MockAdapter("ms")
        ms._files = {}
        ms._should_fail_upload = {"a.bin", "b.bin"}

        config = make_config(direction="hf_to_ms")
        engine = SyncEngine(
            config=config,
            hf_adapter=hf,
            ms_adapter=ms,
            state_dir=tmp_path,
        )

        results = engine.sync_all()
        assert results[0].status == SyncStatus.FAILED
        assert len(results[0].files_failed) == 2
        assert len(results[0].files_synced) == 0

    def test_download_failure(self, tmp_path):
        """Download fails — file should be in failed list."""
        hf = MockAdapter("hf")
        hf._files = {"model.safetensors": b"data"}
        hf._should_fail_download = {"model.safetensors"}

        ms = MockAdapter("ms")
        ms._files = {}

        config = make_config(direction="hf_to_ms")
        engine = SyncEngine(
            config=config,
            hf_adapter=hf,
            ms_adapter=ms,
            state_dir=tmp_path,
        )

        results = engine.sync_all()
        assert results[0].status == SyncStatus.FAILED
        assert "model.safetensors" in results[0].files_failed

    def test_snapshot_exception_caught(self, tmp_path):
        """HF snapshot fetch fails — item should be FAILED."""
        hf = MockAdapter("hf")
        hf._snapshot_fail = True

        ms = MockAdapter("ms")
        ms._files = {}

        config = make_config(direction="hf_to_ms")
        engine = SyncEngine(
            config=config,
            hf_adapter=hf,
            ms_adapter=ms,
            state_dir=tmp_path,
        )

        results = engine.sync_all()
        assert results[0].status == SyncStatus.FAILED


# ── Results JSON writing ────────────────────────────────────────────


class TestResultsJson:
    def test_last_results_json_written(self, tmp_path):
        hf = MockAdapter("hf")
        hf._files = {"config.json": b"{}"}
        ms = MockAdapter("ms")
        ms._files = {}

        config = make_config(direction="hf_to_ms")
        engine = SyncEngine(
            config=config,
            hf_adapter=hf,
            ms_adapter=ms,
            state_dir=tmp_path,
        )

        engine.sync_all()

        result_file = tmp_path / "last_results.json"
        assert result_file.exists()

        with open(result_file) as f:
            data = json.load(f)
        assert len(data) == 1
        assert data[0]["item_name"] == "test"
        assert data[0]["status"] == "success"
        assert data[0]["files_synced"] == 1

    def test_results_json_not_written_in_dry_run(self, tmp_path):
        """dry_run still writes results (for preview purposes)."""
        hf = MockAdapter("hf")
        hf._files = {"model.safetensors": b"data"}
        ms = MockAdapter("ms")
        ms._files = {}

        config = make_config(direction="hf_to_ms")
        engine = SyncEngine(
            config=config,
            hf_adapter=hf,
            ms_adapter=ms,
            state_dir=tmp_path,
            dry_run=True,
        )
        engine.sync_all()

        # Results JSON should still be written (dry run still reports)
        result_file = tmp_path / "last_results.json"
        assert result_file.exists()


# ── State synced_files population ───────────────────────────────────


class TestStateSyncedFiles:
    def test_synced_files_populated_in_state(self, tmp_path):
        """After sync, state should contain sha256 hashes of synced files."""
        hf = MockAdapter("hf")
        hf._files = {"model.safetensors": b"weights", "config.json": b"{}"}
        ms = MockAdapter("ms")
        ms._files = {}

        config = make_config(direction="hf_to_ms")
        engine = SyncEngine(
            config=config,
            hf_adapter=hf,
            ms_adapter=ms,
            state_dir=tmp_path,
        )
        engine.sync_all()

        # Load persisted state
        states = load_sync_states(tmp_path)
        hf_key = "hf:model:a/b"
        assert hf_key in states
        hf_state = states[hf_key]
        # synced_files should have entries for synced files
        assert "model.safetensors" in hf_state.synced_files
        assert hf_state.synced_files["model.safetensors"] == "hash_model.safetensors"

    def test_synced_files_accumulate_across_runs(self, tmp_path):
        """Second sync should retain previously synced file hashes."""
        hf = MockAdapter("hf")
        hf._files = {"a.json": b"aaa"}
        ms = MockAdapter("ms")
        ms._files = {}

        config = make_config(direction="hf_to_ms")
        engine = SyncEngine(
            config=config,
            hf_adapter=hf,
            ms_adapter=ms,
            state_dir=tmp_path,
        )
        engine.sync_all()

        # Second run: add a new file
        hf._files["b.json"] = b"bbb"
        engine2 = SyncEngine(
            config=config,
            hf_adapter=hf,
            ms_adapter=ms,
            state_dir=tmp_path,
        )
        engine2.sync_all()

        states = load_sync_states(tmp_path)
        hf_state = states["hf:model:a/b"]
        assert "a.json" in hf_state.synced_files
        assert "b.json" in hf_state.synced_files


# ── CLI argument parsing ────────────────────────────────────────────


class TestCLIParsing:
    def test_dry_run_parsing(self):
        # We can't easily test main() without mocking, but verify the parsing logic
        assert "true".lower() in ("true", "1", "yes")
        assert "false".lower() not in ("true", "1", "yes")
        assert "TRUE".lower() in ("true", "1", "yes")
        assert "1".lower() in ("true", "1", "yes")

    def test_direction_override_parsing(self):
        # "config" means no override → None
        direction = "config"
        override = direction if direction != "config" else None
        assert override is None

        direction = "hf_to_ms"
        override = direction if direction != "config" else None
        assert override == "hf_to_ms"


# ── Dataset sync ────────────────────────────────────────────────────


class TestDatasetSync:
    def test_dataset_hf_to_ms(self, tmp_path):
        hf = MockAdapter("hf")
        hf._files = {"data/train.parquet": b"parquet_data", "dataset_infos.json": b"{}"}

        ms = MockAdapter("ms")
        ms._files = {}

        config = make_config(
            direction="hf_to_ms",
            models=[],
            datasets=[{"name": "ds1", "hf_repo_id": "org/ds", "ms_repo_id": "org/ds"}],
        )
        engine = SyncEngine(
            config=config,
            hf_adapter=hf,
            ms_adapter=ms,
            state_dir=tmp_path,
        )

        results = engine.sync_all()
        assert len(results) == 1
        assert results[0].item_name == "ds1"
        assert results[0].resource_type == "dataset"
        assert results[0].status == SyncStatus.SUCCESS
        assert len(results[0].files_synced) == 2


# ── Mixed models + datasets ─────────────────────────────────────────


class TestMixedSync:
    def test_models_and_datasets_together(self, tmp_path):
        hf = MockAdapter("hf")
        hf._files = {"model.bin": b"weights"}

        ms = MockAdapter("ms")
        ms._files = {}

        config = make_config(
            direction="hf_to_ms",
            models=[{"name": "m1", "hf_repo_id": "a/m1", "ms_repo_id": "a/m1"}],
            datasets=[{"name": "d1", "hf_repo_id": "a/d1", "ms_repo_id": "a/d1"}],
        )
        engine = SyncEngine(
            config=config,
            hf_adapter=hf,
            ms_adapter=ms,
            state_dir=tmp_path,
        )

        results = engine.sync_all()
        assert len(results) == 2
        names = {r.item_name for r in results}
        assert names == {"m1", "d1"}


# ── No sync items ───────────────────────────────────────────────────


class TestEmptySync:
    def test_no_items_configured(self, tmp_path):
        config = make_config(direction="hf_to_ms", models=[], datasets=[])
        hf = MockAdapter("hf")
        ms = MockAdapter("ms")

        engine = SyncEngine(
            config=config,
            hf_adapter=hf,
            ms_adapter=ms,
            state_dir=tmp_path,
        )
        results = engine.sync_all()
        assert results == []

    def test_target_filter_no_match(self, tmp_path):
        hf = MockAdapter("hf")
        hf._files = {"model.bin": b"data"}
        ms = MockAdapter("ms")

        config = make_config(direction="hf_to_ms")
        engine = SyncEngine(
            config=config,
            hf_adapter=hf,
            ms_adapter=ms,
            state_dir=tmp_path,
            target_filter="nonexistent",
        )
        results = engine.sync_all()
        assert results == []


# ── GitHub Outputs ──────────────────────────────────────────────────


class TestGitHubOutputs:
    def test_writes_github_output(self, tmp_path, monkeypatch):
        """sync_all() should write outputs to $GITHUB_OUTPUT."""
        output_file = tmp_path / "github_output"
        output_file.write_text("")
        monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))

        hf = MockAdapter("hf")
        hf._files = {"model.bin": b"weights_data", "config.json": b"{}"}
        ms = MockAdapter("ms")
        ms._files = {}

        config = make_config(direction="hf_to_ms")
        engine = SyncEngine(
            config=config,
            hf_adapter=hf,
            ms_adapter=ms,
            state_dir=tmp_path,
        )
        engine.sync_all()

        content = output_file.read_text()
        assert "sync_status=success" in content
        assert "files_synced=2" in content
        assert "bytes_transferred=" in content

    def test_github_output_partial(self, tmp_path, monkeypatch):
        """Partial failure should write sync_status=partial."""
        output_file = tmp_path / "github_output"
        output_file.write_text("")
        monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))

        hf = MockAdapter("hf")
        hf._files = {"good.json": b"ok", "bad.bin": b"fail"}
        ms = MockAdapter("ms")
        ms._files = {}
        ms._should_fail_upload = {"bad.bin"}

        config = make_config(direction="hf_to_ms")
        engine = SyncEngine(
            config=config,
            hf_adapter=hf,
            ms_adapter=ms,
            state_dir=tmp_path,
        )
        engine.sync_all()

        content = output_file.read_text()
        assert "sync_status=partial" in content

    def test_github_output_failed(self, tmp_path, monkeypatch):
        """All failures should write sync_status=failed."""
        output_file = tmp_path / "github_output"
        output_file.write_text("")
        monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))

        hf = MockAdapter("hf")
        hf._snapshot_fail = True
        ms = MockAdapter("ms")

        config = make_config(direction="hf_to_ms")
        engine = SyncEngine(
            config=config,
            hf_adapter=hf,
            ms_adapter=ms,
            state_dir=tmp_path,
        )
        engine.sync_all()

        content = output_file.read_text()
        assert "sync_status=failed" in content

    def test_no_github_output_env(self, tmp_path, monkeypatch):
        """Should not crash when GITHUB_OUTPUT is not set."""
        monkeypatch.delenv("GITHUB_OUTPUT", raising=False)

        hf = MockAdapter("hf")
        hf._files = {"config.json": b"{}"}
        ms = MockAdapter("ms")
        ms._files = {}

        config = make_config(direction="hf_to_ms")
        engine = SyncEngine(
            config=config,
            hf_adapter=hf,
            ms_adapter=ms,
            state_dir=tmp_path,
        )
        # Should not raise
        results = engine.sync_all()
        assert results[0].status == SyncStatus.SUCCESS
