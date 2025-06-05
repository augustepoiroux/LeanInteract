# Configuration API

This page documents the configuration classes used to set up the Lean environment.

## LeanREPLConfig

::: lean_interact.config.LeanREPLConfig
    options:
      show_root_heading: true
      show_source: true
      heading_level: 3

### Examples

```python
# Basic configuration with default settings
config = LeanREPLConfig(verbose=True)

# Configuration with specific Lean version
config = LeanREPLConfig(lean_version="v4.19.0", verbose=True)

# Configuration with memory limits
config = LeanREPLConfig(memory_hard_limit_mb=2000)

# Configuration with custom REPL version and repository
config = LeanREPLConfig(
    repl_rev="v4.21.0-rc3",
    repl_git="https://github.com/leanprover-community/repl"
)
```

## Project Classes

### BaseProject

::: lean_interact.config.BaseProject
    options:
      show_root_heading: true
      show_source: true
      heading_level: 3

### LocalProject

::: lean_interact.config.LocalProject
    options:
      show_root_heading: true
      show_source: true
      heading_level: 3

### GitProject

::: lean_interact.config.GitProject
    options:
      show_root_heading: true
      show_source: true
      heading_level: 3

### BaseTempProject

::: lean_interact.config.BaseTempProject
    options:
      show_root_heading: true
      show_source: true
      heading_level: 3

### TemporaryProject

::: lean_interact.config.TemporaryProject
    options:
      show_root_heading: true
      show_source: true
      heading_level: 3

## Project Dependencies

### LeanRequire

::: lean_interact.config.LeanRequire
    options:
      show_root_heading: true
      show_source: true
      heading_level: 3

### TempRequireProject

::: lean_interact.config.TempRequireProject
    options:
      show_root_heading: true
      show_source: true
      heading_level: 3
