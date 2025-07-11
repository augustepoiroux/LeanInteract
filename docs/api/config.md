# Configuration API

This page documents the configuration class used to set up the Lean REPL.

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

# Working with projects
config = LeanREPLConfig(
    project=LocalProject(directory="/path/to/project"),
    verbose=True
)
```
