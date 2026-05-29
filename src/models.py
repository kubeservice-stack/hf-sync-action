"""Data models for HF-MS Sync."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Literal


class SyncDirection(str, Enum):
    HF_TO_MS = "hf_to_ms"
    MS_TO_HF = "ms_to_hf"
    BIDIRECTIONAL = "bidirectional"


class ConflictStrategy(str, Enum):
    NEWER_WINS = "newer_wins"
    HF_PRIORITY = "hf_priority"
    MS_PRIORITY = "ms_priority"
    SKIP = "skip"


class SyncStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"


class FileActionType(str, Enum):
    ADD = "add"
    UPDATE = "update"
    DELETE = "delete"
    SKIP = "skip"


@dataclass
class FileInfo:
    """Metadata for a single file in a repository."""

    path: str
    size: int
    sha256: str | None = None
    last_modified: datetime | None = None
    lfs: bool = False


@dataclass
class RepoSnapshot:
    """Snapshot of a repository at a point in time."""

    repo_id: str
    platform: Literal["hf", "ms"]
    resource_type: Literal["model", "dataset"]
    last_commit_hash: str | None = None
    last_modified: datetime | None = None
    file_list: list[FileInfo] = field(default_factory=list)
    total_size_bytes: int = 0

    def get_file_map(self) -> dict[str, FileInfo]:
        """Return a dict mapping file path to FileInfo."""
        return {f.path: f for f in self.file_list}


@dataclass
class FileAction:
    """A single file-level sync action to perform."""

    action: FileActionType
    file_path: str
    source_platform: Literal["hf", "ms"]
    size: int = 0
    reason: str = ""


@dataclass
class SyncItem:
    """A resource (model or dataset) to be synced."""

    name: str
    resource_type: Literal["model", "dataset"]
    hf_repo_id: str
    ms_repo_id: str
    direction: SyncDirection = SyncDirection.BIDIRECTIONAL
    include_patterns: list[str] = field(default_factory=lambda: ["*"])
    exclude_patterns: list[str] = field(default_factory=list)
    enabled: bool = True


@dataclass
class SyncResult:
    """Result of syncing a single SyncItem."""

    item_name: str
    resource_type: str
    direction: str
    files_synced: list[str] = field(default_factory=list)
    files_skipped: list[str] = field(default_factory=list)
    files_failed: list[str] = field(default_factory=list)
    bytes_transferred: int = 0
    status: SyncStatus = SyncStatus.SUCCESS
    error_message: str | None = None
    duration_seconds: float = 0.0


@dataclass
class SyncState:
    """Persisted state from a previous sync run."""

    repo_key: str  # "{platform}:{resource_type}:{repo_id}"
    last_synced_commit: str | None = None
    last_synced_at: datetime | None = None
    synced_files: dict[str, str] = field(default_factory=dict)  # path -> sha256

    @staticmethod
    def make_key(platform: str, resource_type: str, repo_id: str) -> str:
        return f"{platform}:{resource_type}:{repo_id}"
