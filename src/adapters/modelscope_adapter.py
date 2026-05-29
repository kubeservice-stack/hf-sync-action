"""ModelScope platform adapter using modelscope SDK."""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Literal

from tenacity import retry, stop_after_attempt, wait_exponential

from src.adapters.base import PlatformAdapter
from src.models import FileInfo, RepoSnapshot

logger = logging.getLogger(__name__)


class ModelScopeAdapter(PlatformAdapter):
    """Adapter for ModelScope Hub."""

    platform: Literal["ms"] = "ms"

    def __init__(self, token: str | None = None) -> None:
        self._token = token
        if token:
            os.environ["MODELSCOPE_API_TOKEN"] = token

        # Lazy imports to allow optional installation
        self._api = self._init_api()

    def _init_api(self):
        """Initialize the ModelScope HubApi."""
        try:
            from modelscope.hub.api import HubApi

            return HubApi()
        except ImportError:
            logger.warning(
                "modelscope SDK not installed; adapter will use huggingface_hub fallback"
            )
            return None

    def _use_hf_fallback(self) -> bool:
        """ModelScope repos are also accessible via HuggingFace Hub API."""
        return self._api is None

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=5, max=60))
    def get_repo_snapshot(
        self,
        repo_id: str,
        resource_type: Literal["model", "dataset"],
    ) -> RepoSnapshot:
        logger.info("[MS] Fetching snapshot for %s (%s)", repo_id, resource_type)

        if self._use_hf_fallback():
            return self._snapshot_via_hf(repo_id, resource_type)

        file_list: list[FileInfo] = []
        total_size = 0
        commit_hash = None

        try:
            # List files using the correct SDK methods
            if resource_type == "dataset":
                files = self._api.get_dataset_files(repo_id, recursive=True)
            else:
                files = self._api.get_model_files(repo_id, recursive=True)

            for entry in files:
                if isinstance(entry, str):
                    file_list.append(FileInfo(path=entry, size=0))
                elif isinstance(entry, dict):
                    path = entry.get("Name", entry.get("Path", ""))
                    size = entry.get("Size", 0) or 0
                    sha = entry.get("Revision", entry.get("sha256"))
                    if path:
                        file_list.append(FileInfo(path=path, size=size, sha256=sha))
                        total_size += size
                else:
                    path = getattr(entry, "Name", getattr(entry, "Path", str(entry)))
                    size = getattr(entry, "Size", 0) or 0
                    sha = getattr(entry, "Revision", None)
                    file_list.append(FileInfo(path=str(path), size=size, sha256=sha))
                    total_size += size
        except Exception as e:
            logger.warning("[MS] Failed to list files for %s: %s, trying HF fallback", repo_id, e)
            return self._snapshot_via_hf(repo_id, resource_type)

        # Try to get commit info
        try:
            if resource_type == "dataset":
                info = self._api.dataset_info(repo_id)
            else:
                info = self._api.model_info(repo_id)
            commit_hash = getattr(info, "Revision", getattr(info, "revision", None))
        except Exception:
            pass

        return RepoSnapshot(
            repo_id=repo_id,
            platform="ms",
            resource_type=resource_type,
            last_commit_hash=commit_hash,
            file_list=file_list,
            total_size_bytes=total_size,
        )

    def _snapshot_via_hf(
        self,
        repo_id: str,
        resource_type: Literal["model", "dataset"],
    ) -> RepoSnapshot:
        """Fallback: fetch ModelScope repo via HuggingFace-compatible endpoint."""
        from huggingface_hub import HfApi

        # ModelScope repos can be mirrored; use a direct HTTP listing if SDK unavailable
        api = HfApi(endpoint="https://modelscope.cn")
        try:
            files = api.list_repo_files(
                repo_id=repo_id,
                repo_type="dataset" if resource_type == "dataset" else "model",
            )
            file_list = [FileInfo(path=f, size=0) for f in files]
        except Exception:
            file_list = []

        return RepoSnapshot(
            repo_id=repo_id,
            platform="ms",
            resource_type=resource_type,
            file_list=file_list,
            total_size_bytes=0,
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=5, max=120))
    def download_file(
        self,
        repo_id: str,
        file_path: str,
        local_dir: Path,
        resource_type: Literal["model", "dataset"],
    ) -> Path:
        logger.info("[MS] Downloading %s from %s", file_path, repo_id)

        if self._use_hf_fallback():
            return self._download_via_hf(repo_id, file_path, local_dir, resource_type)

        try:
            if resource_type == "dataset":
                # Use snapshot_download for datasets
                from modelscope.hub.snapshot_download import dataset_snapshot_download

                cache_dir = dataset_snapshot_download(repo_id, allow_patterns=[file_path])
                src = Path(cache_dir) / file_path
            else:
                from modelscope.hub.snapshot_download import snapshot_download

                cache_dir = snapshot_download(repo_id, allow_patterns=[file_path])
                src = Path(cache_dir) / file_path

            dest = local_dir / file_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src), str(dest))
            return dest
        except Exception as e:
            logger.warning("[MS] SDK download failed for %s: %s, trying HF fallback", file_path, e)
            return self._download_via_hf(repo_id, file_path, local_dir, resource_type)

    def _download_via_hf(
        self,
        repo_id: str,
        file_path: str,
        local_dir: Path,
        resource_type: Literal["model", "dataset"],
    ) -> Path:
        """Download from ModelScope via huggingface_hub with MS endpoint."""
        from huggingface_hub import hf_hub_download

        repo_type = "dataset" if resource_type == "dataset" else "model"
        local_path = hf_hub_download(
            repo_id=repo_id,
            filename=file_path,
            repo_type=repo_type,
            local_dir=str(local_dir),
            endpoint="https://modelscope.cn",
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
        logger.info("[MS] Uploading %s to %s/%s", local_path.name, repo_id, remote_path)

        if self._use_hf_fallback():
            self._upload_via_hf(repo_id, local_path, remote_path, resource_type)
            return

        try:
            self._api.upload_file(
                path_or_fileobj=str(local_path),
                path_in_repo=remote_path,
                repo_id=repo_id,
                repo_type="dataset" if resource_type == "dataset" else "model",
            )
        except Exception as e:
            error_msg = str(e).lower()
            # Detect permission errors and provide clear message
            if "does not exist" in error_msg or "403" in error_msg or "401" in error_msg or "forbidden" in error_msg:
                raise PermissionError(
                    f"Cannot upload to {repo_id}: you don't have write access. "
                    f"Make sure you own this repo or use your own namespace "
                    f"(e.g., 'your-username/model-name' instead of 'Qwen/model-name')."
                ) from e
            logger.warning("[MS] SDK upload failed: %s, trying HF fallback", e)
            self._upload_via_hf(repo_id, local_path, remote_path, resource_type)

    def _upload_via_hf(
        self,
        repo_id: str,
        local_path: Path,
        remote_path: str,
        resource_type: Literal["model", "dataset"],
    ) -> None:
        from huggingface_hub import HfApi

        api = HfApi(endpoint="https://modelscope.cn", token=self._token)
        repo_type = "dataset" if resource_type == "dataset" else "model"
        try:
            with open(local_path, "rb") as f:
                api.upload_file(
                    path_or_fileobj=f,
                    path_in_repo=remote_path,
                    repo_id=repo_id,
                    repo_type=repo_type,
                )
        except Exception as e:
            error_msg = str(e).lower()
            # Detect permission errors and provide clear message
            if "does not exist" in error_msg or "403" in error_msg or "401" in error_msg or "forbidden" in error_msg:
                raise PermissionError(
                    f"Cannot upload to {repo_id}: you don't have write access. "
                    f"Make sure you own this repo or use your own namespace "
                    f"(e.g., 'your-username/model-name' instead of 'Qwen/model-name')."
                ) from e
            raise

    def create_repo_if_needed(
        self,
        repo_id: str,
        resource_type: Literal["model", "dataset"],
    ) -> None:
        try:
            if self._api:
                exists = self._api.repo_exists(repo_id)
            else:
                from huggingface_hub import HfApi

                api = HfApi(endpoint="https://modelscope.cn", token=self._token)
                exists = api.repo_exists(
                    repo_id=repo_id,
                    repo_type="dataset" if resource_type == "dataset" else "model",
                )

            if exists:
                logger.info("[MS] Repo %s already exists", repo_id)
                return

            logger.info("[MS] Creating repo %s (%s)", repo_id, resource_type)
            if self._api:
                self._api.create_repo(
                    repo_id=repo_id,
                    repo_type="dataset" if resource_type == "dataset" else "model",
                )
            else:
                api.create_repo(
                    repo_id=repo_id,
                    repo_type="dataset" if resource_type == "dataset" else "model",
                    exist_ok=True,
                )
        except Exception as e:
            logger.warning("[MS] create_repo_if_needed failed for %s: %s", repo_id, e)
            # Non-fatal: sync will fail naturally if repo doesn't exist
