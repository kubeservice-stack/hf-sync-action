<p align="center">
  <h1 align="center">HF-MS Sync</h1>
  <p align="center">
    <strong>Bidirectional sync of AI models and datasets between HuggingFace and ModelScope</strong>
  </p>
  <p align="center">
    <a href="https://github.com/marketplace/actions/hf-ms-sync">
      <img src="https://img.shields.io/badge/GitHub%20Marketplace-Available-blue?style=flat-square" alt="Marketplace">
    </a>
    <a href="https://github.com/kubeservice-stack/hf-sync-action/actions">
      <img src="https://img.shields.io/github/actions/workflow/status/kubeservice-stack/hf-sync-action/sync.yml?style=flat-square" alt="CI">
    </a>
    <a href="https://github.com/kubeservice-stack/hf-sync-action/blob/main/LICENSE">
      <img src="https://img.shields.io/github/license/kubeservice-stack/hf-sync-action?style=flat-square" alt="License">
    </a>
    <a href="https://github.com/kubeservice-stack/hf-sync-action/releases">
      <img src="https://img.shields.io/github/v/release/kubeservice-stack/hf-sync-action?style=flat-square" alt="Release">
    </a>
  </p>
</p>

---

## Overview

**HF-MS Sync** is a GitHub Action that automatically synchronizes AI models and datasets between [HuggingFace Hub](https://huggingface.co) and [ModelScope](https://modelscope.cn). It provides a flexible, configuration-driven approach to keeping your model and dataset repositories in sync across both platforms.

### Key Features

- **Bidirectional Sync** - Sync from HuggingFace to ModelScope, ModelScope to HuggingFace, or both directions
- **Model & Dataset Support** - Sync any type of repository: models, datasets, and more
- **Smart Change Detection** - Only transfers files that have actually changed, saving bandwidth and time
- **Conflict Resolution** - Configurable strategies: newer-wins, platform priority, or skip
- **Multiple Triggers** - Scheduled (cron), manual (workflow_dispatch), and webhook (repository_dispatch)
- **Dry Run Mode** - Preview what would be synced without actually transferring files
- **Large File Support** - Git LFS compatible, handles multi-GB model weights efficiently
- **State Persistence** - Tracks sync history across runs via GitHub Actions artifacts
- **GitHub Job Summary** - Generates detailed Markdown reports in your workflow run summary

## Quick Start

### 1. Create Configuration

Create `config/sync_config.yaml` in your repository:

```yaml
global:
  sync_direction: "hf_to_ms"       # hf_to_ms | ms_to_hf | bidirectional
  conflict_strategy: "newer_wins"  # newer_wins | hf_priority | ms_priority | skip
  max_file_size_gb: 50
  max_parallel_downloads: 4

models:
  - name: "qwen2.5-7b"
    hf_repo_id: "Qwen/Qwen2.5-7B-Instruct"
    ms_repo_id: "Qwen/Qwen2.5-7B-Instruct"
    direction: "hf_to_ms"
    include_patterns:
      - "*.safetensors"
      - "*.json"
      - "tokenizer*"
    exclude_patterns:
      - "*.msgpack"
    enabled: true

datasets:
  - name: "my-dataset"
    hf_repo_id: "my-org/my-dataset"
    ms_repo_id: "my-org/my-dataset"
    direction: "hf_to_ms"
    enabled: true
```

### 2. Set Up Secrets

Add these secrets to your GitHub repository (**Settings > Secrets and variables > Actions**):

| Secret | Description |
|--------|-------------|
| `HF_TOKEN` | HuggingFace API token with write access |
| `MODELSCOPE_TOKEN` | ModelScope API token with write access |

### 3. Create Workflow

Create `.github/workflows/sync.yml`:

```yaml
name: Sync HF <-> ModelScope

on:
  schedule:
    - cron: '0 */6 * * *'    # Every 6 hours
  workflow_dispatch:
    inputs:
      sync_target:
        description: 'Specific item to sync (empty = all)'
        required: false
      direction:
        description: 'Override direction'
        type: choice
        options: [config, hf_to_ms, ms_to_hf, bidirectional]
      dry_run:
        description: 'Dry run'
        type: boolean
        default: false

jobs:
  sync:
    runs-on: ubuntu-latest
    timeout-minutes: 360
    steps:
      - uses: actions/checkout@v4

      - uses: kubeservice-stack/hf-sync-action@v1
        with:
          config: config/sync_config.yaml
          direction: ${{ inputs.direction || 'config' }}
          dry_run: ${{ inputs.dry_run || 'false' }}
          target: ${{ inputs.sync_target || '' }}
        env:
          HF_TOKEN: ${{ secrets.HF_TOKEN }}
          MODELSCOPE_TOKEN: ${{ secrets.MODELSCOPE_TOKEN }}
```

## Usage

### As a GitHub Action (Recommended)

```yaml
- uses: kubeservice-stack/hf-sync-action@v1
  with:
    config: 'config/sync_config.yaml'
    direction: 'hf_to_ms'
    dry_run: 'false'
    target: ''
    log_level: 'INFO'
  env:
    HF_TOKEN: ${{ secrets.HF_TOKEN }}
    MODELSCOPE_TOKEN: ${{ secrets.MODELSCOPE_TOKEN }}
```

### Standalone (Python CLI)

```bash
# Install dependencies
pip install -r requirements.txt

# Run sync
HF_TOKEN=hf_xxx MODELSCOPE_TOKEN=ms_xxx \
  python -m src.sync_engine \
    --config config/sync_config.yaml \
    --state-dir .sync_state/

# Dry run
python -m src.sync_engine --config config/sync_config.yaml --dry-run true
```

### Webhook Trigger

Trigger sync from an external service:

```bash
curl -X POST \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer $GITHUB_TOKEN" \
  https://api.github.com/repos/{owner}/{repo}/dispatches \
  -d '{
    "event_type": "sync-trigger",
    "client_payload": {
      "target": "qwen2.5-7b",
      "direction": "hf_to_ms",
      "platform": "hf"
    }
  }'
```

## Configuration Reference

### Global Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `sync_direction` | string | `bidirectional` | Default sync direction (`hf_to_ms`, `ms_to_hf`, `bidirectional`) |
| `conflict_strategy` | string | `newer_wins` | How to resolve conflicts (`newer_wins`, `hf_priority`, `ms_priority`, `skip`) |
| `max_file_size_gb` | float | `50` | Skip files larger than this size |
| `retry_attempts` | int | `3` | Number of retry attempts for failed transfers |
| `retry_delay_seconds` | int | `30` | Delay between retries |
| `max_parallel_downloads` | int | `4` | Maximum concurrent downloads |
| `max_parallel_uploads` | int | `2` | Maximum concurrent uploads |
| `delete_orphaned` | bool | `false` | Delete files on target that don't exist on source |

### Item Settings (per model/dataset)

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `name` | string | *required* | Unique identifier for this sync item |
| `hf_repo_id` | string | *required* | HuggingFace repository ID (e.g., `org/model-name`) |
| `ms_repo_id` | string | *required* | ModelScope repository ID |
| `direction` | string | global | Override global direction for this item |
| `include_patterns` | list | `["*"]` | Glob patterns for files to include |
| `exclude_patterns` | list | `[]` | Glob patterns for files to exclude |
| `enabled` | bool | `true` | Enable/disable this sync item |

### Conflict Resolution

| Strategy | Behavior |
|----------|----------|
| `newer_wins` | The file with the more recent modification timestamp wins |
| `hf_priority` | HuggingFace version always wins on conflict |
| `ms_priority` | ModelScope version always wins on conflict |
| `skip` | Skip conflicting files (keep both versions as-is) |

## Action Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `config` | No | `config/sync_config.yaml` | Path to configuration file |
| `direction` | No | `config` | Override sync direction |
| `dry_run` | No | `false` | Preview changes without transferring |
| `target` | No | *(all)* | Sync only a specific item by name |
| `log_level` | No | `INFO` | Logging verbosity |

## Architecture

```
Triggers (cron / manual / webhook)
         │
         ▼
   Sync Engine (Python)
   ├── Config Loader      ← YAML configuration
   ├── Change Detector    ← Compares file snapshots between platforms
   └── Transfer Executor  ← Downloads from source, uploads to target
         │
    ┌────┴────┐
    ▼         ▼
HF Adapter  MS Adapter    ← Platform-specific API wrappers
    │         │
    ▼         ▼
HuggingFace  ModelScope   ← Remote platforms
```

### How It Works

1. **Snapshot** - Fetches file lists and metadata from both platforms
2. **Detect** - Compares snapshots to identify new, updated, and deleted files
3. **Transfer** - Downloads changed files from source and uploads to target
4. **State** - Persists sync state as GitHub Actions artifacts for next run
5. **Report** - Generates a Markdown summary in the GitHub Actions run

## Examples

The [`examples/`](examples/) directory contains ready-to-use configurations and workflows for common scenarios:

### Configuration Examples

| Example | Scenario |
|---------|----------|
| [01-hf-to-ms-mirror.yaml](examples/01-hf-to-ms-mirror.yaml) | One-way HF -> MS mirror for popular models |
| [02-bidirectional-sync.yaml](examples/02-bidirectional-sync.yaml) | Bidirectional sync with conflict resolution |
| [03-multi-model-batch.yaml](examples/03-multi-model-batch.yaml) | Batch sync many models at once |
| [04-dataset-sync.yaml](examples/04-dataset-sync.yaml) | Dataset sync (parquet, jsonl, images) |
| [05-minimal-external.yaml](examples/05-minimal-external.yaml) | Minimal config for external projects |
| [06-selective-patterns.yaml](examples/06-selective-patterns.yaml) | Selective file patterns (inference-ready only) |

### Workflow Examples

| Example | Scenario |
|---------|----------|
| [simple-mirror.yml](examples/workflows/simple-mirror.yml) | Scheduled one-way sync with manual trigger |
| [bidirectional-with-notify.yml](examples/workflows/bidirectional-with-notify.yml) | Bidirectional + DingTalk/Feishu notifications |
| [webhook-triggered.yml](examples/workflows/webhook-triggered.yml) | Event-driven sync via webhook |
| [matrix-sync.yml](examples/workflows/matrix-sync.yml) | Parallel matrix sync (one job per model) |

### Using in Your Own Project

```bash
# 1. Copy config
cp examples/05-minimal-external.yaml config/sync_config.yaml
# Edit with your repo IDs

# 2. Copy workflow
cp examples/workflows/simple-mirror.yml .github/workflows/sync.yml

# 3. Add secrets HF_TOKEN and MODELSCOPE_TOKEN in GitHub Settings

# 4. Push
git add config/ .github/workflows/sync.yml
git commit -m "Add HF-MS sync"
git push
```

See [examples/README.md](examples/README.md) for full details.

## E2E Testing

The project includes an end-to-end test workflow that performs a real sync with a tiny model and verifies file consistency.

### Run E2E Test

1. Go to **Actions** > **E2E Test - Bidirectional Sync**
2. Click **Run workflow**
3. Fill in:
   - **HF Repo**: `sshleifer/tiny-gpt2` (default, ~60MB)
   - **MS Repo**: your test repo ID (e.g., `your-org/e2e-test`)
   - **Direction**: `hf_to_ms`, `ms_to_hf`, or `bidirectional`
   - **Cleanup**: `true` to delete the MS test repo after verification

### What the E2E Test Validates

| Stage | Check |
|-------|-------|
| Unit tests | All 48 unit tests pass |
| Sync execution | Real file transfer between HF and MS |
| File verification | File lists match on both platforms |
| Idempotency | Second sync detects zero changes |
| Cleanup | Optionally deletes test repo |

### PR Validation

On pull requests, the E2E workflow also runs a lightweight validation (no secrets needed):
- Config parsing and validation
- Module import checks for all adapters

## Development

### Setup

```bash
git clone https://github.com/kubeservice-stack/hf-sync-action.git
cd hf-sync-action
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

### Test

```bash
pytest tests/ -v
```

### Project Structure

```
├── .github/workflows/     # CI/CD workflows (sync, e2e-test, webhook)
├── src/
│   ├── adapters/          # Platform adapters (HF, MS)
│   ├── config.py          # Configuration loading
│   ├── change_detector.py # Change detection logic
│   ├── sync_engine.py     # Main sync orchestrator
│   ├── models.py          # Data models
│   ├── report.py          # Report generation
│   └── utils.py           # Utilities
├── config/                # Default sync configuration
├── examples/              # Ready-to-use configs and workflows
│   ├── workflows/         # Example GitHub Action workflows
│   └── *.yaml             # Scenario-based config examples
├── tests/                 # Test suite
│   ├── e2e/               # End-to-end test scripts
│   └── test_*.py          # Unit tests
├── action.yml             # GitHub Action definition
├── Dockerfile             # Action runtime
└── pyproject.toml         # Python project config
```

## FAQ

**Q: How long does syncing take?**
A: Depends on the number and size of files. Initial sync of a 7B model (~14GB) typically takes 20-40 minutes. Subsequent syncs only transfer changed files.

**Q: Does it support private repositories?**
A: Yes, as long as your API tokens have the necessary permissions for both platforms.

**Q: What happens if a sync is interrupted?**
A: The sync state is persisted after each successful run. On the next run, it will only transfer files that have changed since the last successful sync.

**Q: Can I sync only specific file types?**
A: Yes, use `include_patterns` and `exclude_patterns` in your configuration. For example, sync only `*.safetensors` files.

**Q: What if both platforms have different versions of a file?**
A: The `conflict_strategy` setting determines the behavior. `newer_wins` uses timestamps, or you can set platform priority.

## License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request
