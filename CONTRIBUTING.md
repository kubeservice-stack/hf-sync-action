# Contributing to HF-MS Sync

Thank you for your interest in contributing! This document provides guidelines and information for contributors.

## Getting Started

### Prerequisites

- Python 3.10+
- Git and Git LFS
- GitHub account

### Setup

```bash
git clone https://github.com/kubeservice-stack/hf-sync-action.git
cd hf-sync-action
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

### Run Tests

```bash
pytest tests/ -v
```

### Lint

```bash
ruff check src/ tests/
ruff format src/ tests/
```

## Development Workflow

1. **Fork** the repository
2. **Create a branch**: `git checkout -b feature/your-feature`
3. **Make changes** and write tests
4. **Run tests**: `pytest tests/ -v`
5. **Run lint**: `ruff check src/ tests/`
6. **Commit**: `git commit -m "Add feature: description"`
7. **Push**: `git push origin feature/your-feature`
8. **Open a Pull Request**

## Code Style

- We use **ruff** for linting and formatting
- Line length: 100 characters
- Target Python versions: 3.10–3.12
- Use type hints where practical
- Follow existing patterns in the codebase

## Project Structure

```text
src/
├── adapters/          # Platform adapters (HuggingFace, ModelScope)
├── config.py          # Configuration loading and validation
├── change_detector.py # File-level change detection
├── sync_engine.py     # Main sync orchestration
├── models.py          # Data models (dataclasses)
├── report.py          # Report generation
└── utils.py           # Utility functions

tests/                 # Test suite
config/                # Example configurations
examples/              # Ready-to-use configs and workflows
```

## Testing Guidelines

- **Unit tests**: Mock external API calls, test logic in isolation
- **Integration tests**: Use `MockAdapter` for end-to-end flow testing
- **E2E tests**: Real API calls with small models (requires secrets)

All new features should include tests. Bug fixes should include a regression test.

## Pull Request Process

1. Ensure all tests pass
2. Update documentation if applicable
3. Add an entry to CHANGELOG.md under "Unreleased"
4. Request review from maintainers

## Reporting Issues

Use GitHub Issues:
- **Bug reports**: Use the Bug Report template
- **Feature requests**: Use the Feature Request template

## License

By contributing, you agree that your contributions will be licensed under the Apache License 2.0.
