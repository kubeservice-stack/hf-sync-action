"""Tests for report module."""

from __future__ import annotations

import json
import os

from src.models import SyncResult, SyncStatus
from src.report import format_result_table, generate_json_report, print_summary


def _make_result(
    name: str = "test-model",
    status: SyncStatus = SyncStatus.SUCCESS,
    synced: int = 3,
    skipped: int = 1,
    failed: int = 0,
    bytes_tx: int = 1024 * 1024,
    duration: float = 12.5,
    error: str | None = None,
) -> SyncResult:
    return SyncResult(
        item_name=name,
        resource_type="model",
        direction="hf_to_ms",
        files_synced=[f"file_{i}" for i in range(synced)],
        files_skipped=[f"skip_{i}" for i in range(skipped)],
        files_failed=[f"fail_{i}" for i in range(failed)],
        bytes_transferred=bytes_tx,
        status=status,
        error_message=error,
        duration_seconds=duration,
    )


class TestFormatResultTable:
    def test_empty_results(self):
        table = format_result_table([])
        assert "No sync items to report" in table

    def test_single_success(self):
        results = [_make_result()]
        table = format_result_table(results)
        assert "test-model" in table
        assert "hf_to_ms" in table
        assert "success" in table
        assert "3" in table  # synced count
        assert "1.0 MB" in table  # bytes

    def test_summary_counts(self):
        results = [
            _make_result("m1", SyncStatus.SUCCESS),
            _make_result("m2", SyncStatus.PARTIAL, failed=2),
            _make_result("m3", SyncStatus.FAILED, error="boom"),
        ]
        table = format_result_table(results)
        assert "3 items" in table
        assert "1 success" in table
        assert "1 partial" in table
        assert "1 failed" in table

    def test_error_details_shown(self):
        results = [_make_result("broken", SyncStatus.FAILED, error="network timeout")]
        table = format_result_table(results)
        assert "### Errors" in table
        assert "broken" in table
        assert "network timeout" in table

    def test_no_error_section_when_all_success(self):
        results = [_make_result()]
        table = format_result_table(results)
        assert "### Errors" not in table


class TestGenerateJsonReport:
    def test_json_structure(self):
        results = [_make_result("model-a", SyncStatus.SUCCESS, synced=5)]
        report = json.loads(generate_json_report(results))
        assert len(report) == 1
        item = report[0]
        assert item["item_name"] == "model-a"
        assert item["status"] == "success"
        assert item["files_synced"] == 5
        assert item["bytes_transferred"] == 1024 * 1024

    def test_json_multiple_results(self):
        results = [
            _make_result("a"),
            _make_result("b", SyncStatus.FAILED, error="err"),
        ]
        report = json.loads(generate_json_report(results))
        assert len(report) == 2
        assert report[0]["item_name"] == "a"
        assert report[1]["error_message"] == "err"


class TestPrintSummary:
    def test_writes_to_stdout(self, capsys):
        results = [_make_result()]
        print_summary(results)
        captured = capsys.readouterr()
        assert "test-model" in captured.out

    def test_writes_to_github_step_summary(self, tmp_path):
        summary_file = tmp_path / "step_summary.md"
        summary_file.write_text("")

        os.environ["GITHUB_STEP_SUMMARY"] = str(summary_file)
        try:
            results = [_make_result()]
            print_summary(results)
            content = summary_file.read_text()
            assert "test-model" in content
        finally:
            del os.environ["GITHUB_STEP_SUMMARY"]

    def test_no_github_summary_env(self, capsys):
        # Should not crash when GITHUB_STEP_SUMMARY is not set
        os.environ.pop("GITHUB_STEP_SUMMARY", None)
        results = [_make_result()]
        print_summary(results)
        captured = capsys.readouterr()
        assert "test-model" in captured.out
