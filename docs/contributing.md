---
hide:
  - navigation
---

# Contributing to LeanInteract

Thank you for your interest in contributing to LeanInteract! This guide will help you get started, follow best practices, and make your contributions easy to review.

## Pull Request Guidelines

- **Describe your changes** clearly and concisely in the PR description.
- **Link to relevant issues** using `#` (e.g., #42).
- **Include tests** for new features or bug fixes.
- **Update documentation** if your change affects usage or APIs.
- **Ensure all tests pass** before requesting review.

## Getting Started

1. **Fork the repository** on GitHub and clone your fork locally.

2. **Install development dependencies**: we recommend using [uv](https://docs.astral.sh/uv/).

   ```bash
   uv pip install -e ".[dev]"
   ```

## Code Style & Quality

- **Type hints:** All functions and methods should have type annotations.
- **Docstrings:** Write clear, descriptive docstrings for all public classes, functions, and modules.
- **Tests:** All new features and bug fixes must include unit tests.
- **Documentation:** Update or add documentation as needed.

## Testing

- **Run all tests:**

   ```bash
   uv run python -m unittest discover tests
   ```

- **Run a specific test module:**

   ```bash
   uv run python -m unittest tests/test_server.py
   ```

- **First-time setup is slow:** Lean toolchain and dependencies may take several minutes to install/compile.
- **Concurrency tests timeout:** Use generous timeouts and check system resources.

## Documentation & Versioning

LeanInteract uses [`mkdocs`](https://www.mkdocs.org/) and [`mike`](https://github.com/jimporter/mike) for versioned documentation. Documentation is auto-deployed on `main` branch changes and version tags.

- **Preview docs locally:**

```bash
uv run mkdocs serve
```

## Reporting Issues & Getting Help

**Bugs/Feature requests:**

1. Check [GitHub issues](https://github.com/augustepoiroux/LeanInteract/issues) first (open or closed).
2. If new, open an issue with a clear description and steps to reproduce.

**Contact:** For questions, contact the [maintainer](mailto:auguste.poiroux@epfl.ch).

---

Thank you for contributing to LeanInteract!
