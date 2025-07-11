# LeanInteract AI Coding Guidelines

## Project Overview
LeanInteract is a Python package that provides a high-level interface to the Lean 4 theorem prover through the Lean REPL. It abstracts project setup, dependency management, and REPL communication to enable seamless Lean-Python integration for theorem proving, autoformalization, and mathematical verification tasks.

## Architecture Overview

### Core Components
- **Projects**: Self-contained Lean project configurations that handle their own setup and building
- **REPL Configuration**: Manages REPL-specific settings
- **Servers**: Thread-safe wrappers around Lean REPL processes with async support
- **Interface**: Pydantic models for type-safe communication with Lean REPL

### Project Instantiation Pattern
```python
# Projects are instantiated independently and passed to config
project = TempRequireProject(lean_version="v4.8.0", require="mathlib")
config = LeanREPLConfig(project=project)
```

### Key Project Types
- `LocalProject(directory="path")`: Existing local Lean projects
- `GitProject(url="...", rev="...")`: Auto-cloning git repositories
- `TempRequireProject(lean_version="...", require=[...])`: Temporary projects with dependencies
- `TemporaryProject(lean_version="...", content="...")`: Custom lakefile content

## Critical Development Patterns

### File Locking for Concurrency
All project operations use `FileLock(f"{directory}.lock")` to prevent race conditions during setup:
```python
with FileLock(f"{directory}.lock"):
    # Setup operations here
```

### Environment State Management
Commands return `CommandResponse` with `env` field for chaining:
```python
result1 = server.run(Command(cmd="def x := 1"))
result2 = server.run(Command(cmd="def y := x + 1", env=result1.env))
```

### Thread-Safe Server Operations
Both sync and async operations use internal locking:
```python
# Synchronous
result = server.run(Command(cmd="..."))
# Asynchronous
result = await server.async_run(Command(cmd="..."))
```

## Testing Conventions

### Configuration Setup
Always pre-instantiate config for multiprocessing tests:
```python
@classmethod
def setUpClass(cls):
    cls.config = LeanREPLConfig(cache_dir=tempfile.mkdtemp())
```

### Concurrency Testing
Use `mp.get_context("spawn")` for cross-platform process spawning and proper timeout handling:
```python
ctx = mp.get_context("spawn")
p = ctx.Process(target=worker_func, args=(config,))
p.start()
p.join(timeout=60)
```

### First-Time Setup Timeouts
Initial Lean setup can take minutes - use generous timeouts (60s+) for setup-related tests.

## Build & Development Workflow

### Essential Commands
- **All scripts, tests, and commands should be run using [`uv`](https://github.com/astral-sh/uv) for speed and reproducibility.**
- **Tests are run with the standard `unittest` framework, not pytest.**

```bash
# Setup: Install with dev dependencies
uv pip install -e ".[dev]"

# Testing: Run all tests with unittest
uv run python -m unittest discover tests
# Or run a specific test module
uv run python -m unittest tests/test_server.py
uv run python -m unittest tests/test_concurrency.py

# Documentation: Local preview
uv run mkdocs serve

# Cache management
uv run clear-lean-cache  # Clear all cached projects
```

### Project Structure
- `src/lean_interact/`: Core package modules
- `tests/`: Comprehensive test suite with concurrency tests
- `examples/`: Real-world usage examples (autoformalization, benchmarks)
- `docs/`: MkDocs documentation with API reference

## Integration Patterns

### Error Handling
Commands can return `LeanError` instead of `CommandResponse`:
```python
result = server.run(command)
if isinstance(result, LeanError):
    # Handle error
elif isinstance(result, CommandResponse):
    # Process successful result
```

### Memory Management
Set memory limits for Linux platforms:
```python
config = LeanREPLConfig(memory_hard_limit_mb=4096)
```

### Session Caching
Use `AutoLeanServer` for automatic session state management across commands.

## External Dependencies
- **Lean 4**: Managed via `elan` toolchain, versions v4.8.0+ supported
- **Lake**: Lean's build system, used for project initialization and building
- **Git**: Required for project cloning and REPL setup
- **FileSystem**: Heavy use of file locking, temp directories, and path manipulation

## Common Pitfalls
- Don't pass `lean_version` when providing a `project` - version is inferred from project
- Use absolute paths for all file operations
- First-time project setup requires internet access and can be slow
- Concurrency tests may timeout on slow systems due to Lean compilation
