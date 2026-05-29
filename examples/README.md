# Examples

This directory contains ready-to-use configuration examples for different sync scenarios.

## Configuration Examples (copy to `config/sync_config.yaml`)

| File | Scenario | Description |
|------|----------|-------------|
| [01-hf-to-ms-mirror.yaml](01-hf-to-ms-mirror.yaml) | One-way mirror | HF -> MS for popular open-source models |
| [02-bidirectional-sync.yaml](02-bidirectional-sync.yaml) | Bidirectional | Keep HF and MS repos in sync both ways |
| [03-multi-model-batch.yaml](03-multi-model-batch.yaml) | Batch sync | Sync many models at once |
| [04-dataset-sync.yaml](04-dataset-sync.yaml) | Datasets | Sync datasets (parquet, jsonl, images) |
| [05-minimal-external.yaml](05-minimal-external.yaml) | Minimal | Smallest config for external projects |
| [06-selective-patterns.yaml](06-selective-patterns.yaml) | Selective | Only sync inference-ready files |

## Workflow Examples (copy to `.github/workflows/`)

| File | Scenario | Description |
|------|----------|-------------|
| [simple-mirror.yml](workflows/simple-mirror.yml) | Basic | Scheduled one-way sync with manual trigger |
| [bidirectional-with-notify.yml](workflows/bidirectional-with-notify.yml) | Notifications | Bidirectional sync with DingTalk alerts |
| [webhook-triggered.yml](workflows/webhook-triggered.yml) | Event-driven | Sync triggered by external webhook |
| [matrix-sync.yml](workflows/matrix-sync.yml) | Parallel | Sync multiple models in parallel jobs |

## Quick Start for External Projects

### Step 1: Copy config

```bash
# Pick the example closest to your use case
cp examples/05-minimal-external.yaml config/sync_config.yaml
# Edit with your repo IDs
```

### Step 2: Copy workflow

```bash
cp examples/workflows/simple-mirror.yml .github/workflows/sync.yml
```

### Step 3: Add secrets

In your GitHub repo: **Settings > Secrets and variables > Actions**

| Secret | Where to get it |
|--------|----------------|
| `HF_TOKEN` | https://huggingface.co/settings/tokens |
| `MODELSCOPE_TOKEN` | https://modelscope.cn/my/myaccesstoken |

### Step 4: Commit and push

```bash
git add config/sync_config.yaml .github/workflows/sync.yml
git commit -m "Add HF-MS sync"
git push
```

The sync will run on the next scheduled time, or you can trigger it manually from the **Actions** tab.
