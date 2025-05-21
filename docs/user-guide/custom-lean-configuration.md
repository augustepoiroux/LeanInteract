# Custom Lean Configuration

LeanInteract provides flexible ways to configure the Lean environment to suit different use cases. This guide covers the various configuration options available.

## Specifying Lean Versions

You can specify which version of Lean 4 you want to use:

```python
from lean_interact import LeanREPLConfig, LeanServer

# Use a specific Lean version
config = LeanREPLConfig(lean_version="v4.7.0")
server = LeanServer(config)
```

LeanInteract supports all Lean versions between `v4.7.0-rc1` and `v4.19.0`.

## Working with Existing Projects

### Local Lean Projects

To work with a local Lean project:

```python
from lean_interact import LeanREPLConfig, LocalProject, LeanServer

# Configure with a local project
config = LeanREPLConfig(project=LocalProject("path/to/your/project"))
server = LeanServer(config)
```

!!! important
    Ensure the project can be successfully built with `lake build` before using it with LeanInteract.

### Git-Based Projects

You can also work with projects hosted on Git:

```python
from lean_interact import LeanREPLConfig, GitProject, LeanServer

# Configure with a Git-hosted project
config = LeanREPLConfig(project=GitProject("https://github.com/yangky11/lean4-example"))
server = LeanServer(config)
```

## Working with Temporary Projects

LeanInteract allows you to create temporary projects with dependencies for experimentation without affecting your local environment.

### Simple Temporary Projects with Dependencies

To create a temporary project with dependencies:

```python
from lean_interact import LeanREPLConfig, TempRequireProject, LeanRequire

# Create a temporary project with Mathlib as a dependency
config = LeanREPLConfig(
    lean_version="v4.7.0",
    project=TempRequireProject([
        LeanRequire(
            name="mathlib",
            git="https://github.com/leanprover-community/mathlib4.git",
            rev="v4.7.0"
        )
    ])
)
```

For the common case of requiring Mathlib, there's a shortcut:

```python
config = LeanREPLConfig(lean_version="v4.7.0", project=TempRequireProject("mathlib"))
```

### Fine-Grained Temporary Projects

For more control over the temporary project, you can specify the complete lakefile content:

```python
from lean_interact import LeanREPLConfig, TemporaryProject

config = LeanREPLConfig(
    lean_version="v4.18.0",
    project=TemporaryProject("""
import Lake
open Lake DSL

package "dummy" where
  version := v!"0.1.0"

@[default_target]
lean_exe "dummy" where
  root := `Main

require mathlib from git
  "https://github.com/leanprover-community/mathlib4.git" @ "v4.18.0"
""")
)
```

This approach gives you full control over the Lake configuration.

## Best Practices

- Check the Lean version your project is compatible with and use that version in your configuration
- Initialize `LeanREPLConfig` before starting parallel processes to avoid conflicts, and then copy it in the child processes when instantiating `LeanServer`
