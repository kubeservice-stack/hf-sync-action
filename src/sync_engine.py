"""Sync engine: orchestrates the full sync workflow."""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Literal

from src.adapters.base import PlatformAdapter
from src.adapters.huggingface_adapter import HuggingFaceAdapter
from src.adapters.modelscope_adapter import ModelScopeAdapter
from src.change_detector import BidirectionalChangeDetector, ChangeDetector
from src.config import ItemConfig, SyncConfig, load_config
from src.models import (
    FileAction,
    FileActionType,
    SyncDirection,
    SyncItem,
    SyncResult,
    SyncState,
    SyncStatus,
)
from src.utils import (
    create_temp_dir,
    format_bytes,
    get_env_token,
    load_sync_states,
    now_utc,
    save_sync_states,
    setup_logging,
)

logger = logging.getLogger(__name__)


class SyncEngine:
    """Main sync orchestrator."""

    def __init__(
        self,
        config: SyncConfig,
        hf_adapter: PlatformAdapter,
        ms_adapter: PlatformAdapter,
        state_dir: Path,
        dry_run: bool = False,
        direction_override: str | None = None,
        target_filter: str | None = None,
    ) -> None:
        self.config = config
        self.global_config = config.global_config
        self.hf = hf_adapter
        self.ms = ms_adapter
        self.state_dir = state_dir
        self.dry_run = dry_run
        self.direction_override = direction_override
        self.target_filter = target_filter

        # Load persisted state
        self.states: dict[str, SyncState] = load_sync_states(state_dir)

    def _build_sync_items(self) -> list[SyncItem]:
        """Convert config items to SyncItem objects."""
        items: list[SyncItem] = []

        for model_cfg in self.config.models:
            if not model_cfg.enabled:
                continue
            items.append(self._to_sync_item(model_cfg, "model"))

        for ds_cfg in self.config.datasets:
            if not ds_cfg.enabled:
                continue
            items.append(self._to_sync_item(ds_cfg, "dataset"))

        if self.target_filter:
            items = [i for i in items if i.name == self.target_filter]
            if not items:
                logger.warning("No sync items match target filter: %s", self.target_filter)

        return items

    def _to_sync_item(
        self,
        cfg: ItemConfig,
        resource_type: Literal["model", "dataset"],
    ) -> SyncItem:
        direction = cfg.direction or self.global_config.sync_direction
        if self.direction_override and self.direction_override != "config":
            direction = SyncDirection(self.direction_override)

        return SyncItem(
            name=cfg.name,
            resource_type=resource_type,
            hf_repo_id=cfg.hf_repo_id,
            ms_repo_id=cfg.ms_repo_id,
            direction=direction,
            include_patterns=cfg.include_patterns,
            exclude_patterns=cfg.exclude_patterns,
        )

    def _get_adapter(self, platform: Literal["hf", "ms"]) -> PlatformAdapter:
        return self.hf if platform == "hf" else self.ms

    def sync_item(self, item: SyncItem) -> SyncResult:
        """Sync a single item (model or dataset)."""
        start_time = time.monotonic()
        result = SyncResult(
            item_name=item.name,
            resource_type=item.resource_type,
            direction=item.direction.value,
        )

        logger.info(
            "━━━ Syncing %s (%s) [%s] ━━━",
            item.name,
            item.resource_type,
            item.direction.value,
        )

        try:
            gc = self.global_config

            # Ensure target repos exist
            if item.direction in (SyncDirection.HF_TO_MS, SyncDirection.BIDIRECTIONAL):
                self.ms.create_repo_if_needed(item.ms_repo_id, item.resource_type)
            if item.direction in (SyncDirection.MS_TO_HF, SyncDirection.BIDIRECTIONAL):
                self.hf.create_repo_if_needed(item.hf_repo_id, item.resource_type)

            # Fetch snapshots
            hf_snapshot = self.hf.get_repo_snapshot(item.hf_repo_id, item.resource_type)
            ms_snapshot = None
            try:
                ms_snapshot = self.ms.get_repo_snapshot(item.ms_repo_id, item.resource_type)
            except Exception as e:
                logger.warning("[MS] Could not fetch snapshot for %s: %s", item.ms_repo_id, e)

            # Detect changes
            detector_kwargs = dict(
                conflict_strategy=gc.conflict_strategy,
                include_patterns=item.include_patterns,
                exclude_patterns=item.exclude_patterns,
                max_file_size_bytes=gc.max_file_size_bytes,
                delete_orphaned=gc.delete_orphaned,
            )

            if item.direction == SyncDirection.BIDIRECTIONAL:
                bd = BidirectionalChangeDetector(**detector_kwargs)
                hf_state = self.states.get(
                    SyncState.make_key("hf", item.resource_type, item.hf_repo_id)
                )
                ms_state = self.states.get(
                    SyncState.make_key("ms", item.resource_type, item.ms_repo_id)
                )
                hf_to_ms_actions, ms_to_hf_actions = bd.detect_bidirectional(
                    hf_snapshot,
                    ms_snapshot,
                    hf_state,
                    ms_state,
                )
                all_actions = hf_to_ms_actions + ms_to_hf_actions
            elif item.direction == SyncDirection.HF_TO_MS:
                detector = ChangeDetector(**detector_kwargs)
                state = self.states.get(
                    SyncState.make_key("hf", item.resource_type, item.hf_repo_id)
                )
                all_actions = detector.detect_changes(hf_snapshot, ms_snapshot, state)
            else:  # MS_TO_HF
                if ms_snapshot is None:
                    raise RuntimeError(
                        f"Cannot sync MS_TO_HF: failed to fetch ModelScope "
                        f"snapshot for {item.ms_repo_id}"
                    )
                detector = ChangeDetector(**detector_kwargs)
                state = self.states.get(
                    SyncState.make_key("ms", item.resource_type, item.ms_repo_id)
                )
                all_actions = detector.detect_changes(
                    ms_snapshot,
                    hf_snapshot,
                    state,
                )

            # Filter to actionable items
            actionable = [
                a for a in all_actions if a.action in (FileActionType.ADD, FileActionType.UPDATE)
            ]
            skipped = [a for a in all_actions if a.action == FileActionType.SKIP]

            result.files_skipped = [a.file_path for a in skipped]

            if not actionable:
                logger.info("No changes to sync for %s", item.name)
                result.status = SyncStatus.SUCCESS
                result.duration_seconds = time.monotonic() - start_time
                return result

            logger.info(
                "Transferring %d files (%s)",
                len(actionable),
                format_bytes(sum(a.size for a in actionable)),
            )

            # Execute transfers
            if self.dry_run:
                logger.info("[DRY RUN] Would transfer:")
                for action in actionable:
                    logger.info(
                        "  %s %s (%s)",
                        action.action.value,
                        action.file_path,
                        format_bytes(action.size),
                    )
                    result.files_synced.append(action.file_path)
                result.status = SyncStatus.SUCCESS
            else:
                success, failed, bytes_tx = self._execute_transfers(
                    actionable,
                    item,
                    gc.max_parallel_downloads,
                )
                result.files_synced = success
                result.files_failed = failed
                result.bytes_transferred = bytes_tx
                result.status = (
                    SyncStatus.SUCCESS
                    if not failed
                    else (SyncStatus.PARTIAL if success else SyncStatus.FAILED)
                )

            # Update sync state
            self._update_state(item, hf_snapshot, ms_snapshot, result.files_synced)

        except Exception as e:
            logger.error("Failed to sync %s: %s", item.name, e, exc_info=True)
            result.status = SyncStatus.FAILED
            result.error_message = str(e)

        result.duration_seconds = time.monotonic() - start_time
        return result

    def _execute_transfers(
        self,
        actions: list[FileAction],
        item: SyncItem,
        max_parallel: int,
    ) -> tuple[list[str], list[str], int]:
        """Execute file transfers with concurrency control.

        Returns (success_files, failed_files, total_bytes).
        """
        success: list[str] = []
        failed: list[str] = []
        total_bytes = 0
        temp_dir = create_temp_dir()

        try:
            # Sort: small files first for faster feedback
            sorted_actions = sorted(actions, key=lambda a: a.size)

            with ThreadPoolExecutor(max_workers=max_parallel) as pool:
                futures = {}
                for action in sorted_actions:
                    future = pool.submit(self._transfer_file, action, item, temp_dir)
                    futures[future] = action

                for future in as_completed(futures):
                    action = futures[future]
                    try:
                        transferred_bytes = future.result()
                        success.append(action.file_path)
                        total_bytes += transferred_bytes
                        logger.info(
                            "  ✓ %s (%s)",
                            action.file_path,
                            format_bytes(transferred_bytes),
                        )
                    except Exception as e:
                        failed.append(action.file_path)
                        logger.error("  ✗ %s: %s", action.file_path, e)
        finally:
            # Clean up temp files
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)

        return success, failed, total_bytes

    def _transfer_file(
        self,
        action: FileAction,
        item: SyncItem,
        temp_dir: Path,
    ) -> int:
        """Download from source → upload to target. Returns bytes transferred."""
        source_adapter = self._get_adapter(action.source_platform)

        # Determine target platform
        if action.source_platform == "hf":
            target_adapter = self.ms
            source_repo_id = item.hf_repo_id
            target_repo_id = item.ms_repo_id
        else:
            target_adapter = self.hf
            source_repo_id = item.ms_repo_id
            target_repo_id = item.hf_repo_id

        # Download
        local_path = source_adapter.download_file(
            repo_id=source_repo_id,
            file_path=action.file_path,
            local_dir=temp_dir,
            resource_type=item.resource_type,
        )

        file_size = local_path.stat().st_size if local_path.exists() else action.size

        # Upload
        target_adapter.upload_file(
            repo_id=target_repo_id,
            local_path=local_path,
            remote_path=action.file_path,
            resource_type=item.resource_type,
        )

        # Clean up local file immediately
        if local_path.exists():
            local_path.unlink()

        return file_size

    def _update_state(
        self,
        item: SyncItem,
        hf_snapshot,
        ms_snapshot,
        synced_files: list[str],
    ) -> None:
        """Update persisted sync state after a successful sync."""
        now = now_utc()

        # Build sha256 map from source snapshot for synced files
        hf_file_map = hf_snapshot.get_file_map() if hf_snapshot else {}
        ms_file_map = ms_snapshot.get_file_map() if ms_snapshot else {}

        # Update HF state
        hf_key = SyncState.make_key("hf", item.resource_type, item.hf_repo_id)
        hf_state = self.states.get(hf_key, SyncState(repo_key=hf_key))
        hf_state.last_synced_commit = hf_snapshot.last_commit_hash
        hf_state.last_synced_at = now
        for fp in synced_files:
            hf_file = hf_file_map.get(fp)
            if hf_file and hf_file.sha256:
                hf_state.synced_files[fp] = hf_file.sha256
        self.states[hf_key] = hf_state

        # Update MS state
        ms_key = SyncState.make_key("ms", item.resource_type, item.ms_repo_id)
        ms_state = self.states.get(ms_key, SyncState(repo_key=ms_key))
        if ms_snapshot:
            ms_state.last_synced_commit = ms_snapshot.last_commit_hash
        ms_state.last_synced_at = now
        for fp in synced_files:
            ms_file = ms_file_map.get(fp)
            if ms_file and ms_file.sha256:
                ms_state.synced_files[fp] = ms_file.sha256
        self.states[ms_key] = ms_state

    def sync_all(self) -> list[SyncResult]:
        """Sync all configured items and return results."""
        items = self._build_sync_items()
        if not items:
            logger.warning("No sync items configured")
            results: list[SyncResult] = []
            self._write_results(results)
            self._write_github_outputs(results)
            return results

        logger.info("Starting sync for %d items (dry_run=%s)", len(items), self.dry_run)
        results: list[SyncResult] = []

        for item in items:
            result = self.sync_item(item)
            results.append(result)

        # Persist state
        if not self.dry_run:
            save_sync_states(self.states, self.state_dir)

        # Write results JSON for report consumption
        self._write_results(results)

        # Write outputs for GitHub Actions
        self._write_github_outputs(results)

        return results

    def _write_results(self, results: list[SyncResult]) -> None:
        """Write last_results.json for the report step to consume."""
        self.state_dir.mkdir(parents=True, exist_ok=True)
        result_file = self.state_dir / "last_results.json"

        data = []
        for r in results:
            data.append(
                {
                    "item_name": r.item_name,
                    "resource_type": r.resource_type,
                    "direction": r.direction,
                    "status": r.status.value,
                    "files_synced": len(r.files_synced),
                    "files_skipped": len(r.files_skipped),
                    "files_failed": len(r.files_failed),
                    "bytes_transferred": r.bytes_transferred,
                    "duration_seconds": round(r.duration_seconds, 2),
                    "error_message": r.error_message,
                }
            )

        with open(result_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info("Wrote results to %s", result_file)

    def _write_github_outputs(self, results: list[SyncResult]) -> None:
        """Write sync outputs to $GITHUB_OUTPUT for GitHub Actions."""
        import os

        output_file = os.environ.get("GITHUB_OUTPUT")
        if not output_file:
            return

        total_synced = sum(len(r.files_synced) for r in results)
        total_bytes = sum(r.bytes_transferred for r in results)

        statuses = [r.status for r in results]
        if not results:
            overall = "success"
        elif any(s == SyncStatus.FAILED for s in statuses):
            overall = "failed"
        elif any(s == SyncStatus.PARTIAL for s in statuses):
            overall = "partial"
        else:
            overall = "success"

        with open(output_file, "a", encoding="utf-8") as f:
            f.write(f"sync_status={overall}\n")
            f.write(f"files_synced={total_synced}\n")
            f.write(f"bytes_transferred={total_bytes}\n")

        logger.info(
            "GitHub outputs: sync_status=%s, files_synced=%d, bytes_transferred=%d",
            overall,
            total_synced,
            total_bytes,
        )


# ── CLI Entry Point ──────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="HF-MS Sync Engine")
    parser.add_argument(
        "--config",
        default="config/sync_config.yaml",
        help="Path to config YAML",
    )
    parser.add_argument(
        "--state-dir",
        default=".sync_state",
        help="Directory for sync state persistence",
    )
    parser.add_argument("--direction", default="config", help="Override sync direction")
    parser.add_argument("--target", default="", help="Sync only a specific item by name")
    parser.add_argument("--dry-run", default="false", help="Dry run mode (true/false)")
    parser.add_argument("--log-level", default="INFO", help="Logging level")

    args = parser.parse_args()

    setup_logging(args.log_level)

    dry_run = args.dry_run.lower() in ("true", "1", "yes")
    direction_override = args.direction if args.direction != "config" else None
    target_filter = args.target if args.target else None

    # Load config
    config = load_config(args.config)

    # Initialize adapters
    hf_token = get_env_token("HF_TOKEN")
    ms_token = get_env_token("MODELSCOPE_TOKEN")

    hf_adapter = HuggingFaceAdapter(token=hf_token)
    ms_adapter = ModelScopeAdapter(token=ms_token)

    # Run sync
    engine = SyncEngine(
        config=config,
        hf_adapter=hf_adapter,
        ms_adapter=ms_adapter,
        state_dir=Path(args.state_dir),
        dry_run=dry_run,
        direction_override=direction_override,
        target_filter=target_filter,
    )

    results = engine.sync_all()

    # Generate report
    from src.report import print_summary

    print_summary(results)

    # Exit with error code if any failures
    if any(r.status == SyncStatus.FAILED for r in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
