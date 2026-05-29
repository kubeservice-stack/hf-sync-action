#!/bin/bash
set -e

# ── Bridge Docker Action inputs (INPUT_*) to Python CLI arguments ────────────
# GitHub Actions automatically sets INPUT_<NAME> env vars from action inputs.
# Input names are uppercased and hyphens become underscores.

CONFIG="${INPUT_CONFIG:-config/sync_config.yaml}"
DIRECTION="${INPUT_DIRECTION:-config}"
DRY_RUN="${INPUT_DRY_RUN:-false}"
TARGET="${INPUT_TARGET:-}"
LOG_LEVEL="${INPUT_LOG_LEVEL:-INFO}"
STATE_DIR="${INPUT_STATE_DIR:-.sync_state}"

# Tokens can be passed via inputs or directly via env
if [ -n "${INPUT_HF_TOKEN:-}" ]; then
    export HF_TOKEN="${INPUT_HF_TOKEN}"
fi
if [ -n "${INPUT_MODELSCOPE_TOKEN:-}" ]; then
    export MODELSCOPE_TOKEN="${INPUT_MODELSCOPE_TOKEN}"
fi

# ── Cleanup handler ─────────────────────────────────────────────────────────
cleanup() {
    for tmpdir in /tmp/hf_ms_sync_*; do
        if [ -d "$tmpdir" ]; then
            rm -rf "$tmpdir" 2>/dev/null || true
        fi
    done
}
trap cleanup EXIT

# ── Build CLI arguments ─────────────────────────────────────────────────────
ARGS="--config ${CONFIG}"
ARGS="${ARGS} --state-dir ${STATE_DIR}"
ARGS="${ARGS} --direction ${DIRECTION}"
ARGS="${ARGS} --dry-run ${DRY_RUN}"
ARGS="${ARGS} --log-level ${LOG_LEVEL}"

if [ -n "${TARGET}" ]; then
    ARGS="${ARGS} --target ${TARGET}"
fi

echo "::group::HF-MS Sync"
echo "Config:    ${CONFIG}"
echo "Direction: ${DIRECTION}"
echo "Dry run:   ${DRY_RUN}"
echo "Target:    ${TARGET:-<all>}"
echo "Log level: ${LOG_LEVEL}"
echo "State dir: ${STATE_DIR}"
echo "::endgroup::"

# ── Run the sync engine ─────────────────────────────────────────────────────
EXIT_CODE=0
python -m src.sync_engine ${ARGS} || EXIT_CODE=$?

# ── Set outputs from last_results.json ───────────────────────────────────────
if [ -f "${STATE_DIR}/last_results.json" ]; then
    python3 << 'PYEOF'
import json
import os

output_file = os.environ.get("GITHUB_OUTPUT", "")
state_dir = os.environ.get("INPUT_STATE_DIR", ".sync_state")

if not output_file:
    exit(0)

try:
    with open(f"{state_dir}/last_results.json") as f:
        results = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    exit(0)

total_synced = sum(r.get("files_synced", 0) for r in results)
total_bytes = sum(r.get("bytes_transferred", 0) for r in results)

# Determine overall status
statuses = [r.get("status", "success") for r in results]
if not results:
    overall = "success"
elif any(s == "failed" for s in statuses):
    overall = "failed"
elif any(s == "partial" for s in statuses):
    overall = "partial"
else:
    overall = "success"

with open(output_file, "a") as f:
    f.write(f"sync_status={overall}\n")
    f.write(f"files_synced={total_synced}\n")
    f.write(f"bytes_transferred={total_bytes}\n")

print(f"::notice::Sync complete: {overall} | {total_synced} files | {total_bytes} bytes")
PYEOF
fi

# ── Write job summary ───────────────────────────────────────────────────────
if [ -f "${STATE_DIR}/last_results.json" ]; then
    python3 << 'PYEOF'
import json
import os

summary_file = os.environ.get("GITHUB_STEP_SUMMARY", "")
state_dir = os.environ.get("INPUT_STATE_DIR", ".sync_state")

if not summary_file:
    exit(0)

try:
    with open(f"{state_dir}/last_results.json") as f:
        results = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    exit(0)

def fmt_bytes(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"

ICON = {"success": "✅", "partial": "⚠️", "failed": "❌", "skipped": "⏭️"}

lines = ["## HF-MS Sync Results", ""]
lines.append("| Item | Type | Direction | Status | Synced | Failed | Transferred | Duration |")
lines.append("|------|------|-----------|--------|--------|--------|-------------|----------|")

for r in results:
    icon = ICON.get(r.get("status", "success"), "❓")
    lines.append(
        f"| {r['item_name']} "
        f"| {r['resource_type']} "
        f"| {r['direction']} "
        f"| {icon} {r['status']} "
        f"| {r.get('files_synced', 0)} "
        f"| {r.get('files_failed', 0)} "
        f"| {fmt_bytes(r.get('bytes_transferred', 0))} "
        f"| {r.get('duration_seconds', 0):.1f}s |"
    )

total = len(results)
ok = sum(1 for r in results if r.get("status") == "success")
fail = sum(1 for r in results if r.get("status") == "failed")
lines.append("")
lines.append(f"**Total**: {total} items, {ok} success, {fail} failed")

with open(summary_file, "a") as f:
    f.write("\n".join(lines) + "\n")
PYEOF
fi

exit ${EXIT_CODE}
