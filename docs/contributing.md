# Contributing to LeanInteract

Contributions to LeanInteract are welcome and appreciated! This guide will help you understand how you can contribute to the project.

## Getting Started

1. **Fork the repository** on GitHub.
2. **Clone your fork** to your local machine.
3. **Create a feature branch**: `git checkout -b feature-name`

## Development Setup

Install the package in development mode:

   ```bash
   pip install -e ".[dev]"
   ```

## Code Style and Guidelines

- Use **ruff** for code formatting.
- Write **descriptive docstrings**.
- Include **type hints** where appropriate.
- Follow the **existing code structure**.
- Write **unit tests** for new features.
- Update the **documentation** if necessary.

## Submitting Contributions

1. **Commit your changes**: `git commit -am 'Add new feature'`
2. **Push to your branch**: `git push origin feature-name`
3. **Submit a pull request** to the main repository.

### Pull Request Guidelines

- **Describe your changes** clearly and concisely.
- **Link to any relevant issues** using the # symbol (e.g., #42).
- Ensure your code **passes all tests**.
- Include **tests for new features** or bug fixes.

## Running Tests

```bash
python -m unittest discover -s ./tests
```

## Building Documentation

You can build and preview the documentation locally:

```bash
mkdocs serve
```

This will start a local web server at <http://127.0.0.1:8000/> where you can preview the documentation as you make changes.

### Multi-Version Documentation

LeanInteract uses [`mike`](https://github.com/jimporter/mike) for managing multiple documentation versions. For local development:

```bash
# Preview current documentation (development)
uv run mkdocs serve

# Deploy current version locally for testing
uv run mike deploy dev

# Deploy with a specific version and alias
uv run mike deploy v0.7.0 stable --update-aliases

# List all available versions
uv run mike list

# Serve a specific version
uv run mike serve v0.7.0

# Delete a version (if needed)
uv run mike delete v0.6.0
```

#### Documentation Versioning Workflow

When contributing documentation changes:

1. **For current development**: Just use `mkdocs serve`
2. **For testing versioned docs**: Use `mike deploy dev` then `mike serve`
3. **For version-specific testing**: Deploy with `mike deploy [version] [alias]`

The documentation is automatically deployed when:

- **Main branch changes**: Updates the `dev` version
- **Version tags**: Creates new version and sets as `stable`
- **Manual workflow**: Custom deployment via GitHub Actions

## Reporting Issues

If you find a bug or would like to request a feature:

1. Check if the issue already exists in the [GitHub issues](https://github.com/augustepoiroux/LeanInteract/issues).
2. If not, create a new issue with a clear description and, if applicable, steps to reproduce.

## Contact

If you have questions about contributing, feel free to contact the maintainer at [auguste.poiroux@epfl.ch](mailto:auguste.poiroux@epfl.ch).

## Code of Conduct

Please be respectful and inclusive when contributing to this project. Harassment or abusive behavior will not be tolerated.

Thank you for contributing to LeanInteract!
