"""Change detection between two platform snapshots."""

from __future__ import annotations

import logging
from typing import Literal

from src.models import (
    ConflictStrategy,
    FileAction,
    FileActionType,
    RepoSnapshot,
    SyncState,
)
from src.utils import matches_patterns

logger = logging.getLogger(__name__)


class ChangeDetector:
    """Detect file-level changes between source and target snapshots."""

    def __init__(
        self,
        conflict_strategy: ConflictStrategy = ConflictStrategy.NEWER_WINS,
        include_patterns: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
        max_file_size_bytes: int = 0,
        delete_orphaned: bool = False,
    ) -> None:
        self.conflict_strategy = conflict_strategy
        self.include_patterns = include_patterns or ["*"]
        self.exclude_patterns = exclude_patterns or []
        self.max_file_size_bytes = max_file_size_bytes
        self.delete_orphaned = delete_orphaned

    def detect_changes(
        self,
        source_snapshot: RepoSnapshot,
        target_snapshot: RepoSnapshot | None,
        sync_state: SyncState | None = None,
    ) -> list[FileAction]:
        """Compare source and target snapshots, return list of file actions.

        Args:
            source_snapshot: Snapshot of the source platform repo.
            target_snapshot: Snapshot of the target platform repo (None if doesn't exist).
            sync_state: Previous sync state for this repo pair.

        Returns:
            List of FileAction describing what to do for each file.
        """
        source_map = source_snapshot.get_file_map()
        target_map = target_snapshot.get_file_map() if target_snapshot else {}

        actions: list[FileAction] = []

        # --- Files in source ---
        for path, src_file in source_map.items():
            if not matches_patterns(path, self.include_patterns, self.exclude_patterns):
                continue

            # Size guard
            if self.max_file_size_bytes and src_file.size > self.max_file_size_bytes:
                logger.warning(
                    "Skipping %s: size %d exceeds max %d",
                    path,
                    src_file.size,
                    self.max_file_size_bytes,
                )
                actions.append(
                    FileAction(
                        action=FileActionType.SKIP,
                        file_path=path,
                        source_platform=source_snapshot.platform,
                        size=src_file.size,
                        reason="exceeds max file size",
                    )
                )
                continue

            tgt_file = target_map.get(path)

            if tgt_file is None:
                # Source has it, target doesn't → ADD
                actions.append(
                    FileAction(
                        action=FileActionType.ADD,
                        file_path=path,
                        source_platform=source_snapshot.platform,
                        size=src_file.size,
                        reason="new file on source",
                    )
                )
            elif self._files_differ(src_file, tgt_file, source_snapshot.platform, sync_state):
                # Both have it but content differs → UPDATE or SKIP
                action = self._resolve_conflict(
                    path,
                    src_file,
                    tgt_file,
                    source_snapshot.platform,
                    target_snapshot.platform if target_snapshot else "ms",
                    source_snapshot,
                    target_snapshot,
                )
                if action:
                    actions.append(action)
            # else: files are identical → skip silently

        # --- Files only on target (orphaned) ---
        if self.delete_orphaned:
            for path in target_map:
                if path not in source_map:
                    if not matches_patterns(path, self.include_patterns, self.exclude_patterns):
                        continue
                    actions.append(
                        FileAction(
                            action=FileActionType.DELETE,
                            file_path=path,
                            source_platform=source_snapshot.platform,
                            size=target_map[path].size,
                            reason="orphaned on target",
                        )
                    )

        add_count = sum(1 for a in actions if a.action == FileActionType.ADD)
        update_count = sum(1 for a in actions if a.action == FileActionType.UPDATE)
        skip_count = sum(1 for a in actions if a.action == FileActionType.SKIP)
        delete_count = sum(1 for a in actions if a.action == FileActionType.DELETE)

        logger.info(
            "Change detection: %d add, %d update, %d delete, %d skip",
            add_count,
            update_count,
            delete_count,
            skip_count,
        )

        return actions

    def _files_differ(
        self,
        src_file,
        tgt_file,
        source_platform: Literal["hf", "ms"],
        sync_state: SyncState | None,
    ) -> bool:
        """Determine if two files are different."""
        # Compare by hash if both have one
        if src_file.sha256 and tgt_file.sha256:
            return src_file.sha256 != tgt_file.sha256

        # Compare by size as fallback
        if src_file.size != tgt_file.size and src_file.size > 0 and tgt_file.size > 0:
            return True

        # If we have a previous sync state, check if the file was synced before
        if sync_state and src_file.path in sync_state.synced_files:
            prev_hash = sync_state.synced_files[src_file.path]
            if src_file.sha256 and src_file.sha256 != prev_hash:
                return True

        # Can't determine → assume same
        return False

    def _resolve_conflict(
        self,
        path: str,
        src_file,
        tgt_file,
        source_platform: Literal["hf", "ms"],
        target_platform: Literal["hf", "ms"],
        source_snapshot: RepoSnapshot,
        target_snapshot: RepoSnapshot | None,
    ) -> FileAction | None:
        """Resolve a conflict where both sides have different content."""
        strategy = self.conflict_strategy

        if strategy == ConflictStrategy.SKIP:
            return FileAction(
                action=FileActionType.SKIP,
                file_path=path,
                source_platform=source_platform,
                size=src_file.size,
                reason="conflict (strategy=skip)",
            )

        if strategy == ConflictStrategy.NEWER_WINS:
            # Compare last_modified timestamps
            src_time = src_file.last_modified or source_snapshot.last_modified
            tgt_time = tgt_file.last_modified or (
                target_snapshot.last_modified if target_snapshot else None
            )

            if src_time and tgt_time:
                if src_time >= tgt_time:
                    return FileAction(
                        action=FileActionType.UPDATE,
                        file_path=path,
                        source_platform=source_platform,
                        size=src_file.size,
                        reason="source is newer",
                    )
                else:
                    return None  # target is newer, skip
            # Can't determine → default to source
            return FileAction(
                action=FileActionType.UPDATE,
                file_path=path,
                source_platform=source_platform,
                size=src_file.size,
                reason="conflict (cannot compare timestamps, defaulting to source)",
            )

        if strategy == ConflictStrategy.HF_PRIORITY:
            winner = source_platform if source_platform == "hf" else target_platform
            return FileAction(
                action=FileActionType.UPDATE,
                file_path=path,
                source_platform=winner,
                size=src_file.size if winner == source_platform else tgt_file.size,
                reason=f"conflict (strategy=hf_priority, winner={winner})",
            )

        if strategy == ConflictStrategy.MS_PRIORITY:
            winner = source_platform if source_platform == "ms" else target_platform
            return FileAction(
                action=FileActionType.UPDATE,
                file_path=path,
                source_platform=winner,
                size=src_file.size if winner == source_platform else tgt_file.size,
                reason=f"conflict (strategy=ms_priority, winner={winner})",
            )

        return None


class BidirectionalChangeDetector:
    """Handle bidirectional sync by running change detection in both directions."""

    def __init__(self, conflict_strategy: ConflictStrategy, **kwargs) -> None:
        self._detector = ChangeDetector(
            conflict_strategy=conflict_strategy,
            **kwargs,
        )

    def detect_bidirectional(
        self,
        hf_snapshot: RepoSnapshot,
        ms_snapshot: RepoSnapshot | None,
        hf_state: SyncState | None = None,
        ms_state: SyncState | None = None,
    ) -> tuple[list[FileAction], list[FileAction]]:
        """Detect changes in both directions.

        Returns:
            (hf_to_ms_actions, ms_to_hf_actions)
        """
        hf_to_ms = self._detector.detect_changes(hf_snapshot, ms_snapshot, hf_state)

        # For ms_to_hf, swap source and target
        if ms_snapshot:
            ms_to_hf = self._detector.detect_changes(ms_snapshot, hf_snapshot, ms_state)
        else:
            ms_to_hf = []

        # De-duplicate: if both directions want to update the same file,
        # use conflict strategy to pick one winner
        self._deduplicate(hf_to_ms, ms_to_hf)

        return hf_to_ms, ms_to_hf

    def _deduplicate(
        self,
        hf_to_ms: list[FileAction],
        ms_to_hf: list[FileAction],
    ) -> None:
        """Remove conflicting actions for the same file."""
        actionable = (FileActionType.ADD, FileActionType.UPDATE)
        hf_files = {a.file_path for a in hf_to_ms if a.action in actionable}
        ms_files = {a.file_path for a in ms_to_hf if a.action in actionable}

        conflicts = hf_files & ms_files
        if not conflicts:
            return

        logger.warning(
            "Bidirectional conflict detected on %d files, resolving by conflict strategy",
            len(conflicts),
        )

        for path in conflicts:
            # Keep the HF→MS action, skip the MS→HF action
            # (This is a simple default; real resolution uses the conflict strategy)
            for action in ms_to_hf:
                if action.file_path == path and action.action in (
                    FileActionType.ADD,
                    FileActionType.UPDATE,
                ):
                    action.action = FileActionType.SKIP
                    action.reason = "bidirectional conflict (resolved: HF wins)"
