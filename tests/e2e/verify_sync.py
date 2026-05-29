#!/usr/bin/env python3
"""E2E verification script.

Compares file lists between HuggingFace and ModelScope repos
after a sync to verify consistency.

Usage:
    python tests/e2e/verify_sync.py \
        --hf-repo sshleifer/tiny-gpt2 \
        --ms-repo my-org/test-repo \
        --include "*.bin" "*.json"
"""

from __future__ import annotations

import argparse
import fnmatch
import sys

from huggingface_hub import HfApi


def list_files(
    repo_id: str,
    endpoint: str,
    token: str | None,
    include_patterns: list[str],
    exclude_patterns: list[str] | None = None,
) -> dict[str, int]:
    """List files in a repo and return {path: size} map."""
    api = HfApi(endpoint=endpoint, token=token)
    try:
        files = api.list_repo_tree(
            repo_id=repo_id,
            repo_type="model",
            recursive=True,
        )
        result = {}
        for item in files:
            path = getattr(item, "rfilename", getattr(item, "path", None))
            if not path:
                continue
            # Apply include/exclude filters
            if include_patterns and not any(fnmatch.fnmatch(path, p) for p in include_patterns):
                continue
            if exclude_patterns and any(fnmatch.fnmatch(path, p) for p in exclude_patterns):
                continue
            size = getattr(item, "size", 0) or 0
            result[path] = size
        return result
    except Exception as e:
        print(f"  ERROR listing {repo_id} on {endpoint}: {e}")
        return {}


def verify_sync(
    hf_repo: str,
    ms_repo: str,
    hf_token: str | None,
    ms_token: str | None,
    include_patterns: list[str],
    exclude_patterns: list[str] | None = None,
) -> tuple[bool, str]:
    """Verify that HF and MS repos have the same files after sync.

    Returns (success, message).
    """
    print(f"\n{'=' * 60}")
    print(f"E2E Verification: {hf_repo} <-> {ms_repo}")
    print(f"{'=' * 60}")

    # List files from both platforms
    print(f"\n[1] Fetching HuggingFace file list: {hf_repo}")
    hf_files = list_files(
        hf_repo,
        "https://huggingface.co",
        hf_token,
        include_patterns,
        exclude_patterns,
    )
    print(f"    Found {len(hf_files)} files")

    print(f"\n[2] Fetching ModelScope file list: {ms_repo}")
    ms_files = list_files(
        ms_repo,
        "https://modelscope.cn",
        ms_token,
        include_patterns,
        exclude_patterns,
    )
    print(f"    Found {len(ms_files)} files")

    if not hf_files and not ms_files:
        return False, "Both repos returned empty file lists - check credentials and repo IDs"

    # Compare
    hf_only = set(hf_files.keys()) - set(ms_files.keys())
    ms_only = set(ms_files.keys()) - set(hf_files.keys())
    common = set(hf_files.keys()) & set(ms_files.keys())

    # Check size mismatches on common files
    size_mismatch = []
    for path in sorted(common):
        hf_size = hf_files[path]
        ms_size = ms_files[path]
        if hf_size != ms_size and hf_size > 0 and ms_size > 0:
            size_mismatch.append((path, hf_size, ms_size))

    # Report
    print("\n[3] Comparison Results:")
    print(f"    Common files:       {len(common)}")
    print(f"    Only on HuggingFace: {len(hf_only)}")
    print(f"    Only on ModelScope:  {len(ms_only)}")
    print(f"    Size mismatches:     {len(size_mismatch)}")

    if hf_only:
        print("\n    Files only on HuggingFace:")
        for f in sorted(hf_only):
            print(f"      - {f}")

    if ms_only:
        print("\n    Files only on ModelScope:")
        for f in sorted(ms_only):
            print(f"      - {f}")

    if size_mismatch:
        print("\n    Size mismatches:")
        for path, hf_s, ms_s in size_mismatch:
            print(f"      - {path}: HF={hf_s} MS={ms_s}")

    # Verdict
    errors = []
    if hf_only:
        errors.append(f"{len(hf_only)} file(s) missing on ModelScope")
    if ms_only:
        errors.append(f"{len(ms_only)} file(s) missing on HuggingFace")
    if size_mismatch:
        errors.append(f"{len(size_mismatch)} file(s) have size mismatches")

    if errors:
        msg = "VERIFICATION FAILED: " + "; ".join(errors)
        print(f"\n  ✗ {msg}")
        return False, msg
    else:
        msg = f"VERIFICATION PASSED: {len(common)} files in sync"
        print(f"\n  ✓ {msg}")
        return True, msg


def main():
    parser = argparse.ArgumentParser(description="Verify HF-MS sync consistency")
    parser.add_argument("--hf-repo", required=True, help="HuggingFace repo ID")
    parser.add_argument("--ms-repo", required=True, help="ModelScope repo ID")
    parser.add_argument("--hf-token", default=None, help="HF token")
    parser.add_argument("--ms-token", default=None, help="MS token")
    parser.add_argument("--include", nargs="+", default=["*"], help="Include glob patterns")
    parser.add_argument("--exclude", nargs="+", default=None, help="Exclude glob patterns")

    args = parser.parse_args()

    import os

    hf_token = args.hf_token or os.environ.get("HF_TOKEN")
    ms_token = args.ms_token or os.environ.get("MODELSCOPE_TOKEN")

    success, message = verify_sync(
        hf_repo=args.hf_repo,
        ms_repo=args.ms_repo,
        hf_token=hf_token,
        ms_token=ms_token,
        include_patterns=args.include,
        exclude_patterns=args.exclude,
    )

    print(f"\n{message}\n")
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
