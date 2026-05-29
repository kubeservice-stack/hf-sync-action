"""Reporting module: generates sync summaries for GitHub Actions."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.models import SyncResult, SyncStatus
from src.utils import format_bytes


def format_result_table(results: list[SyncResult]) -> str:
    """Format sync results as a Markdown table."""
    if not results:
        return "No sync items to report.\n"

    lines = [
        "## HF-MS Sync Report\n",
        "| Item | Type | Direction | Status | Synced | Skipped | Failed | Transferred | Duration |",
        "|------|------|-----------|--------|--------|---------|--------|-------------|----------|",
    ]

    for r in results:
        status_icon = {
            SyncStatus.SUCCESS: "✅",
            SyncStatus.PARTIAL: "⚠️",
            SyncStatus.FAILED: "❌",
            SyncStatus.SKIPPED: "⏭️",
        }.get(r.status, "❓")

        lines.append(
            f"| {r.item_name} "
            f"| {r.resource_type} "
            f"| {r.direction} "
            f"| {status_icon} {r.status.value} "
            f"| {len(r.files_synced)} "
            f"| {len(r.files_skipped)} "
            f"| {len(r.files_failed)} "
            f"| {format_bytes(r.bytes_transferred)} "
            f"| {r.duration_seconds:.1f}s |"
        )

    # Summary
    total = len(results)
    success = sum(1 for r in results if r.status == SyncStatus.SUCCESS)
    partial = sum(1 for r in results if r.status == SyncStatus.PARTIAL)
    failed = sum(1 for r in results if r.status == SyncStatus.FAILED)
    total_bytes = sum(r.bytes_transferred for r in results)
    total_files = sum(len(r.files_synced) for r in results)

    lines.append("")
    lines.append(f"**Total**: {total} items, {success} success, {partial} partial, {failed} failed")
    lines.append(f"**Transferred**: {total_files} files, {format_bytes(total_bytes)}")

    # Error details
    errors = [r for r in results if r.error_message]
    if errors:
        lines.append("\n### Errors\n")
        for r in errors:
            lines.append(f"- **{r.item_name}**: {r.error_message}")

    return "\n".join(lines) + "\n"


def print_summary(results: list[SyncResult]) -> None:
    """Print summary to stdout and GITHUB_STEP_SUMMARY if available."""
    import os

    table = format_result_table(results)

    # Print to stdout
    print(table)

    # Write to GitHub Step Summary if env var is set
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "a", encoding="utf-8") as f:
            f.write(table)


def generate_json_report(results: list[SyncResult]) -> str:
    """Generate a JSON report of sync results."""
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
    return json.dumps(data, indent=2, ensure_ascii=False)


def main() -> None:
    """CLI entry point for report generation from saved results."""
    parser = argparse.ArgumentParser(description="Generate sync report")
    parser.add_argument("--state-dir", default=".sync_state", help="State directory")
    args = parser.parse_args()

    state_dir = Path(args.state_dir)
    result_file = state_dir / "last_results.json"

    if result_file.exists():
        with open(result_file, "r", encoding="utf-8") as f:
            raw = json.load(f)
        # Reconstruct minimal results for display
        results = []
        for r in raw:
            results.append(
                SyncResult(
                    item_name=r["item_name"],
                    resource_type=r["resource_type"],
                    direction=r["direction"],
                    status=SyncStatus(r["status"]),
                    files_synced=[""] * r.get("files_synced", 0),
                    files_skipped=[""] * r.get("files_skipped", 0),
                    files_failed=[""] * r.get("files_failed", 0),
                    bytes_transferred=r.get("bytes_transferred", 0),
                    duration_seconds=r.get("duration_seconds", 0),
                    error_message=r.get("error_message"),
                )
            )
        print_summary(results)
    else:
        print("No previous results found.")
        sys.exit(1)


if __name__ == "__main__":
    main()
