"""Tests for change detection logic."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.change_detector import BidirectionalChangeDetector, ChangeDetector
from src.models import (
    ConflictStrategy,
    FileActionType,
    FileInfo,
    RepoSnapshot,
    SyncState,
)


def make_snapshot(
    platform="hf",
    files: list[tuple[str, int, str | None]] | None = None,
    commit="abc123",
    last_modified=None,
) -> RepoSnapshot:
    """Helper to create a RepoSnapshot."""
    file_list = []
    total = 0
    for path, size, sha in (files or []):
        file_list.append(FileInfo(path=path, size=size, sha256=sha))
        total += size
    return RepoSnapshot(
        repo_id="test/repo",
        platform=platform,
        resource_type="model",
        last_commit_hash=commit,
        last_modified=last_modified or datetime(2025, 1, 1, tzinfo=timezone.utc),
        file_list=file_list,
        total_size_bytes=total,
    )


class TestChangeDetector:
    def test_new_file_detected(self):
        source = make_snapshot(files=[("model.safetensors", 1000, "aaa")])
        target = make_snapshot(platform="ms", files=[])

        detector = ChangeDetector()
        actions = detector.detect_changes(source, target)

        assert len(actions) == 1
        assert actions[0].action == FileActionType.ADD
        assert actions[0].file_path == "model.safetensors"

    def test_identical_files_skipped(self):
        source = make_snapshot(files=[("model.safetensors", 1000, "aaa")])
        target = make_snapshot(platform="ms", files=[("model.safetensors", 1000, "aaa")])

        detector = ChangeDetector()
        actions = detector.detect_changes(source, target)

        assert len(actions) == 0

    def test_updated_file_detected(self):
        source = make_snapshot(files=[("model.safetensors", 1000, "aaa")])
        target = make_snapshot(platform="ms", files=[("model.safetensors", 1000, "bbb")])

        detector = ChangeDetector()
        actions = detector.detect_changes(source, target)

        assert len(actions) == 1
        assert actions[0].action == FileActionType.UPDATE

    def test_include_pattern_filter(self):
        source = make_snapshot(files=[
            ("model.safetensors", 1000, "aaa"),
            ("README.md", 100, "bbb"),
        ])
        target = make_snapshot(platform="ms", files=[])

        detector = ChangeDetector(include_patterns=["*.safetensors"])
        actions = detector.detect_changes(source, target)

        assert len(actions) == 1
        assert actions[0].file_path == "model.safetensors"

    def test_exclude_pattern_filter(self):
        source = make_snapshot(files=[
            ("model.safetensors", 1000, "aaa"),
            ("old.bin", 500, "ccc"),
        ])
        target = make_snapshot(platform="ms", files=[])

        detector = ChangeDetector(exclude_patterns=["*.bin"])
        actions = detector.detect_changes(source, target)

        assert len(actions) == 1
        assert actions[0].file_path == "model.safetensors"

    def test_max_file_size_skip(self):
        source = make_snapshot(files=[("huge.safetensors", 100 * 1024**3, "aaa")])
        target = make_snapshot(platform="ms", files=[])

        detector = ChangeDetector(max_file_size_bytes=50 * 1024**3)
        actions = detector.detect_changes(source, target)

        assert len(actions) == 1
        assert actions[0].action == FileActionType.SKIP

    def test_skip_conflict_strategy(self):
        source = make_snapshot(
            files=[("model.safetensors", 1000, "aaa")],
            last_modified=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        target = make_snapshot(
            platform="ms",
            files=[("model.safetensors", 1000, "bbb")],
            last_modified=datetime(2025, 1, 2, tzinfo=timezone.utc),
        )

        detector = ChangeDetector(conflict_strategy=ConflictStrategy.SKIP)
        actions = detector.detect_changes(source, target)

        assert len(actions) == 1
        assert actions[0].action == FileActionType.SKIP

    def test_newer_wins_source_newer(self):
        source = make_snapshot(
            files=[("model.safetensors", 1000, "aaa")],
            last_modified=datetime(2025, 2, 1, tzinfo=timezone.utc),
        )
        target = make_snapshot(
            platform="ms",
            files=[("model.safetensors", 1000, "bbb")],
            last_modified=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )

        detector = ChangeDetector(conflict_strategy=ConflictStrategy.NEWER_WINS)
        actions = detector.detect_changes(source, target)

        assert len(actions) == 1
        assert actions[0].action == FileActionType.UPDATE

    def test_newer_wins_target_newer(self):
        source = make_snapshot(
            files=[("model.safetensors", 1000, "aaa")],
            last_modified=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        target = make_snapshot(
            platform="ms",
            files=[("model.safetensors", 1000, "bbb")],
            last_modified=datetime(2025, 2, 1, tzinfo=timezone.utc),
        )

        detector = ChangeDetector(conflict_strategy=ConflictStrategy.NEWER_WINS)
        actions = detector.detect_changes(source, target)

        # Target is newer, so no action needed
        assert len(actions) == 0

    def test_delete_orphaned(self):
        source = make_snapshot(files=[])
        target = make_snapshot(
            platform="ms",
            files=[("orphan.safetensors", 500, "xxx")],
        )

        detector = ChangeDetector(delete_orphaned=True)
        actions = detector.detect_changes(source, target)

        assert len(actions) == 1
        assert actions[0].action == FileActionType.DELETE

    def test_no_delete_orphaned_by_default(self):
        source = make_snapshot(files=[])
        target = make_snapshot(
            platform="ms",
            files=[("orphan.safetensors", 500, "xxx")],
        )

        detector = ChangeDetector(delete_orphaned=False)
        actions = detector.detect_changes(source, target)

        assert len(actions) == 0

    def test_none_target_snapshot(self):
        """Target repo doesn't exist yet."""
        source = make_snapshot(files=[("model.safetensors", 1000, "aaa")])

        detector = ChangeDetector()
        actions = detector.detect_changes(source, None)

        assert len(actions) == 1
        assert actions[0].action == FileActionType.ADD


class TestBidirectionalChangeDetector:
    def test_bidirectional_no_conflict(self):
        hf = make_snapshot(
            platform="hf",
            files=[("hf_only.safetensors", 1000, "aaa")],
        )
        ms = make_snapshot(
            platform="ms",
            files=[("ms_only.safetensors", 1000, "bbb")],
        )

        bd = BidirectionalChangeDetector(conflict_strategy=ConflictStrategy.NEWER_WINS)
        hf_to_ms, ms_to_hf = bd.detect_bidirectional(hf, ms)

        assert len(hf_to_ms) == 1
        assert hf_to_ms[0].file_path == "hf_only.safetensors"
        assert len(ms_to_hf) == 1
        assert ms_to_hf[0].file_path == "ms_only.safetensors"

    def test_bidirectional_conflict_resolution(self):
        hf = make_snapshot(
            platform="hf",
            files=[("shared.safetensors", 1000, "aaa")],
            last_modified=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        ms = make_snapshot(
            platform="ms",
            files=[("shared.safetensors", 1000, "bbb")],
            last_modified=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )

        bd = BidirectionalChangeDetector(conflict_strategy=ConflictStrategy.NEWER_WINS)
        hf_to_ms, ms_to_hf = bd.detect_bidirectional(hf, ms)

        # One direction should win, the other should be skipped
        hf_actions = [a for a in hf_to_ms if a.action in (FileActionType.ADD, FileActionType.UPDATE)]
        ms_actions = [a for a in ms_to_hf if a.action in (FileActionType.ADD, FileActionType.UPDATE)]

        # At most one direction should have an active action for the same file
        total_active = len(hf_actions) + len(ms_actions)
        assert total_active <= 1
