"""Utility functions for HF-MS Sync."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from src.models import SyncState

logger = logging.getLogger(__name__)


def setup_logging(level: str = "INFO") -> None:
    """Configure logging for the sync engine."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Suppress noisy library logs
    logging.getLogger("huggingface_hub").setLevel(logging.WARNING)
    logging.getLogger("modelscope").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def matches_patterns(
    file_path: str,
    include_patterns: list[str] | None = None,
    exclude_patterns: list[str] | None = None,
) -> bool:
    """Check if a file path matches include/exclude glob patterns."""
    if include_patterns:
        if not any(fnmatch.fnmatch(file_path, p) for p in include_patterns):
            return False
    if exclude_patterns:
        if any(fnmatch.fnmatch(file_path, p) for p in exclude_patterns):
            return False
    return True


def file_sha256(file_path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    """Compute SHA-256 hash of a local file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def format_bytes(n: int) -> str:
    """Format byte count as human-readable string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def create_temp_dir(prefix: str = "hf_ms_sync_") -> Path:
    """Create a temporary directory for file transfers."""
    return Path(tempfile.mkdtemp(prefix=prefix))


# ── Sync State Persistence ────────────────────────────────────────────


def load_sync_states(state_dir: Path) -> dict[str, SyncState]:
    """Load all sync states from the state directory."""
    state_file = state_dir / "sync_state.json"
    if not state_file.exists():
        logger.info("No existing sync state found at %s", state_file)
        return {}

    with open(state_file, "r", encoding="utf-8") as f:
        raw: dict = json.load(f)

    states: dict[str, SyncState] = {}
    for key, data in raw.items():
        states[key] = SyncState(
            repo_key=key,
            last_synced_commit=data.get("last_synced_commit"),
            last_synced_at=(
                datetime.fromisoformat(data["last_synced_at"])
                if data.get("last_synced_at")
                else None
            ),
            synced_files=data.get("synced_files", {}),
        )

    logger.info("Loaded %d sync states from %s", len(states), state_file)
    return states


def save_sync_states(states: dict[str, SyncState], state_dir: Path) -> None:
    """Save all sync states to the state directory."""
    state_dir.mkdir(parents=True, exist_ok=True)
    state_file = state_dir / "sync_state.json"

    raw: dict = {}
    for key, state in states.items():
        raw[key] = {
            "last_synced_commit": state.last_synced_commit,
            "last_synced_at": (
                state.last_synced_at.isoformat() if state.last_synced_at else None
            ),
            "synced_files": state.synced_files,
        }

    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(raw, f, indent=2, ensure_ascii=False)

    logger.info("Saved %d sync states to %s", len(states), state_file)


def now_utc() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


def mask_token(token: str | None) -> str:
    """Mask a token for safe logging."""
    if not token:
        return "<not set>"
    if len(token) <= 8:
        return "****"
    return token[:4] + "****" + token[-4:]


def get_env_token(name: str) -> str | None:
    """Get a token from environment, with logging."""
    token = os.environ.get(name)
    if token:
        logger.info("Token %s: %s", name, mask_token(token))
    else:
        logger.warning("Token %s not set in environment", name)
    return token
