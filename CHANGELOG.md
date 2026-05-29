# Changelog

All notable changes to HF-MS Sync will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- GitHub Marketplace-ready Docker Action with `entrypoint.sh`
- `GITHUB_OUTPUT` support: `sync_status`, `files_synced`, `bytes_transferred` outputs
- CI workflow: lint, test (Python 3.10/3.11/3.12), action validation, Docker build
- Release workflow: auto-tagging, GHCR Docker image publishing
- Issue templates (Bug Report, Feature Request) and PR template
- CONTRIBUTING.md with development guidelines
- `state_dir` and token inputs in `action.yml`
- Extended test suite: 90 tests covering MS-to-HF, bidirectional, error handling, datasets, GITHUB_OUTPUT
- Examples directory with 6 configuration scenarios and 4 workflow templates
- E2E test workflow for real HF-MS sync validation

### Fixed

- HuggingFace adapter: operator precedence bug in file size parsing
- HuggingFace adapter: incorrect LFS detection logic
- Sync engine: MS-to-HF direction incorrectly used HF snapshot as source when MS snapshot failed
- Sync engine: `last_results.json` was never written, breaking report step
- Sync engine: `synced_files` dict in state was never populated, weakening cross-run change detection

## [0.1.0] - Initial Release

### Added

- Bidirectional sync between HuggingFace and ModelScope
- Model and dataset support
- Smart change detection with SHA-256 comparison
- Configurable conflict resolution (newer-wins, platform priority, skip)
- Scheduled, manual, and webhook triggers
- Dry run mode
- Git LFS support
- State persistence via GitHub Actions artifacts
- GitHub Job Summary reports
