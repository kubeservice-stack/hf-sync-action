"""Abstract base class for platform adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Literal

from src.models import RepoSnapshot


class PlatformAdapter(ABC):
    """Abstract base class for HuggingFace / ModelScope adapters."""

    platform: Literal["hf", "ms"]

    @abstractmethod
    def get_repo_snapshot(
        self,
        repo_id: str,
        resource_type: Literal["model", "dataset"],
    ) -> RepoSnapshot:
        """Fetch a snapshot of the repo: file list, commit hash, metadata."""

    @abstractmethod
    def download_file(
        self,
        repo_id: str,
        file_path: str,
        local_dir: Path,
        resource_type: Literal["model", "dataset"],
    ) -> Path:
        """Download a single file from the remote repo to local_dir.

        Returns the local path of the downloaded file.
        """

    @abstractmethod
    def upload_file(
        self,
        repo_id: str,
        local_path: Path,
        remote_path: str,
        resource_type: Literal["model", "dataset"],
    ) -> None:
        """Upload a single local file to the remote repo."""

    @abstractmethod
    def create_repo_if_needed(
        self,
        repo_id: str,
        resource_type: Literal["model", "dataset"],
    ) -> None:
        """Create the remote repo if it does not already exist."""

    def repo_exists(self, repo_id: str, resource_type: Literal["model", "dataset"]) -> bool:
        """Check whether a repo exists on this platform."""
        try:
            self.get_repo_snapshot(repo_id, resource_type)
            return True
        except Exception:
            return False
