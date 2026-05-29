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

# ── Build CLI arguments (bash array to avoid word-splitting / globbing) ──────
ARGS=(
    "--config" "${CONFIG}"
    "--state-dir" "${STATE_DIR}"
    "--direction" "${DIRECTION}"
    "--dry-run" "${DRY_RUN}"
    "--log-level" "${LOG_LEVEL}"
)

if [ -n "${TARGET}" ]; then
    ARGS+=("--target" "${TARGET}")
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
python -m src.sync_engine "${ARGS[@]}" || EXIT_CODE=$?

# ── Set outputs and job summary ──────────────────────────────────────────────
# These are handled directly by the sync engine (_write_github_outputs and
# _write_results in src/sync_engine.py), which writes to $GITHUB_OUTPUT and
# $GITHUB_STEP_SUMMARY itself. No post-processing needed here.

exit ${EXIT_CODE}
