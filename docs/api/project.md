# Configuration API

This page documents the project classes used to set up the Lean environment.

## BaseProject

All project types inherit from `BaseProject` and handle their own setup independently.

::: lean_interact.project.BaseProject
    options:
      show_root_heading: true
      show_source: true
      heading_level: 3

## LocalProject

::: lean_interact.project.LocalProject
    options:
      show_root_heading: true
      show_source: true
      heading_level: 3

### Example

```python
# Use an existing local project
project = LocalProject(
    directory="/path/to/my/lean/project",
    auto_build=True  # Build the project automatically
)

config = LeanREPLConfig(project=project)
```

## GitProject

::: lean_interact.project.GitProject
    options:
      show_root_heading: true
      show_source: true
      heading_level: 3

### Example

```python
# Clone and use a Git repository
project = GitProject(
    url="https://github.com/user/lean-project",
    rev="main",  # Optional: specific branch/tag/commit
    directory="/custom/cache/dir",  # Optional: custom directory
    force_pull=False  # Optional: force update on each use
)

config = LeanREPLConfig(project=project)
```

## Temporary Projects

For creating temporary Lean projects with custom configurations.

### BaseTempProject

::: lean_interact.project.BaseTempProject
    options:
      show_root_heading: true
      show_source: true
      heading_level: 4

### TemporaryProject

::: lean_interact.project.TemporaryProject
    options:
      show_root_heading: true
      show_source: true
      heading_level: 4

#### Example

```python
# Create a temporary project with custom lakefile
project = TemporaryProject(
    lean_version="v4.19.0",
    content="""
import Lake
open Lake DSL

package "my_temp_project" where
  version := v!"0.1.0"

require mathlib from git
  "https://github.com/leanprover-community/mathlib4.git" @ "v4.19.0"
""",
    lakefile_type="lean"  # or "toml"
)

config = LeanREPLConfig(project=project)
```

### TempRequireProject

::: lean_interact.project.TempRequireProject
    options:
      show_root_heading: true
      show_source: true
      heading_level: 4

#### Example

```python
# Create a temporary project with Mathlib
project = TempRequireProject(
    lean_version="v4.19.0",
    require="mathlib"  # Shortcut for Mathlib
)

# Or with custom dependencies
project = TempRequireProject(
    lean_version="v4.19.0",
    require=[
        LeanRequire("mathlib", "https://github.com/leanprover-community/mathlib4.git", "v4.19.0"),
        LeanRequire("my_lib", "https://github.com/user/my-lib.git", "v1.0.0")
    ]
)

config = LeanREPLConfig(project=project)
```

### LeanRequire

::: lean_interact.project.LeanRequire
    options:
      show_root_heading: true
      show_source: true
      heading_level: 4
