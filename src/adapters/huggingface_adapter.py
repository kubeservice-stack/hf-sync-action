"""HuggingFace platform adapter using huggingface_hub SDK."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Literal

from huggingface_hub import HfApi, hf_hub_download
from huggingface_hub.utils import RepositoryNotFoundError
from tenacity import retry, stop_after_attempt, wait_exponential

from src.adapters.base import PlatformAdapter
from src.models import FileInfo, RepoSnapshot

logger = logging.getLogger(__name__)


class HuggingFaceAdapter(PlatformAdapter):
    """Adapter for HuggingFace Hub."""

    platform: Literal["hf"] = "hf"

    def __init__(self, token: str | None = None) -> None:
        self._api = HfApi(token=token)
        self._token = token

    def _repo_type(self, resource_type: Literal["model", "dataset"]) -> str:
        return "dataset" if resource_type == "dataset" else "model"

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=5, max=60))
    def get_repo_snapshot(
        self,
        repo_id: str,
        resource_type: Literal["model", "dataset"],
    ) -> RepoSnapshot:
        logger.info("[HF] Fetching snapshot for %s (%s)", repo_id, resource_type)
        repo_type = self._repo_type(resource_type)

        # Get repo info for commit hash
        info = self._api.repo_info(repo_id=repo_id, repo_type=repo_type)
        commit_hash = getattr(info, "sha", None) or getattr(info, "commit_hash", None)
        last_modified = getattr(info, "last_modified", None)
        if isinstance(last_modified, str):
            last_modified = datetime.fromisoformat(last_modified)

        # List files with metadata
        siblings = self._api.list_repo_files(repo_id=repo_id, repo_type=repo_type)
        file_list: list[FileInfo] = []
        total_size = 0

        # Get detailed file info via model_info / dataset_info
        try:
            if resource_type == "dataset":
                detail = self._api.dataset_info(repo_id)
            else:
                detail = self._api.model_info(repo_id, files_metadata=True)

            file_map = {}
            for sibling in getattr(detail, "siblings", []):
                file_map[sibling.rfilename] = sibling

            for fname in siblings:
                sib = file_map.get(fname)
                if sib is not None:
                    size = getattr(sib, "size", 0) or 0
                    sha = getattr(sib, "blob_id", None)
                    lfs_obj = getattr(sib, "lfs", None)
                    lfs = lfs_obj is not None and bool(lfs_obj)
                else:
                    size = 0
                    sha = None
                    lfs = False
                file_list.append(
                    FileInfo(
                        path=fname,
                        size=size,
                        sha256=sha,
                        lfs=lfs,
                    )
                )
                total_size += size
        except Exception:
            # Fallback: just list file names without sizes
            for fname in siblings:
                file_list.append(FileInfo(path=fname, size=0))

        return RepoSnapshot(
            repo_id=repo_id,
            platform="hf",
            resource_type=resource_type,
            last_commit_hash=commit_hash,
            last_modified=last_modified,
            file_list=file_list,
            total_size_bytes=total_size,
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=5, max=120))
    def download_file(
        self,
        repo_id: str,
        file_path: str,
        local_dir: Path,
        resource_type: Literal["model", "dataset"],
    ) -> Path:
        logger.info("[HF] Downloading %s from %s", file_path, repo_id)
        repo_type = self._repo_type(resource_type)

        local_path = hf_hub_download(
            repo_id=repo_id,
            filename=file_path,
            repo_type=repo_type,
            local_dir=str(local_dir),
            token=self._token,
            force_download=False,
        )
        return Path(local_path)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=5, max=120))
    def upload_file(
        self,
        repo_id: str,
        local_path: Path,
        remote_path: str,
        resource_type: Literal["model", "dataset"],
    ) -> None:
        logger.info("[HF] Uploading %s to %s/%s", local_path.name, repo_id, remote_path)
        repo_type = self._repo_type(resource_type)

        with open(local_path, "rb") as f:
            self._api.upload_file(
                path_or_fileobj=f,
                path_in_repo=remote_path,
                repo_id=repo_id,
                repo_type=repo_type,
            )

    def create_repo_if_needed(
        self,
        repo_id: str,
        resource_type: Literal["model", "dataset"],
    ) -> None:
        repo_type = self._repo_type(resource_type)
        try:
            self._api.repo_info(repo_id=repo_id, repo_type=repo_type)
            logger.info("[HF] Repo %s already exists", repo_id)
        except RepositoryNotFoundError:
            logger.info("[HF] Creating repo %s (%s)", repo_id, resource_type)
            self._api.create_repo(
                repo_id=repo_id,
                repo_type=repo_type,
                exist_ok=True,
            )
