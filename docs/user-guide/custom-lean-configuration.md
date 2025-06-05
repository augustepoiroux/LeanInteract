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

### Using a Local REPL Installation

If you're developing the Lean REPL or have a custom version, you can use your local copy instead of downloading from the Git repository:

```python
from lean_interact import LeanREPLConfig, LeanServer

config = LeanREPLConfig(local_repl_path="path/to/your/local/repl", build_repl=True)
server = LeanServer(config)
```

!!! note
    When using `local_repl_path`, any specified `repl_rev`, and `repl_git` parameters are ignored as the local REPL is used directly.

!!! note
    You are responsible for using a compatible Lean version between your local REPL and the project you will interact with.

!!! tip
    Setting `build_repl=False` will skip building the local REPL, which can be useful if you've already built it and want to avoid rebuilding.

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

# Using lakefile.lean (default)
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
Alternatively, you can define the lakefile content using the TOML format by setting `lakefile_type="toml"`.

## Using Custom REPL Revisions

LeanInteract uses a Lean REPL (Read-Eval-Print Loop) from a Git repository to interact with Lean. By default, it uses a specific version (`v1.0.9`) of the REPL from the default repository (`https://github.com/augustepoiroux/repl`). However, you can customize this by specifying a different REPL revision or repository:

```python
from lean_interact import LeanREPLConfig, LeanServer

# Use a specific REPL revision
config = LeanREPLConfig(
    repl_rev="v4.21.0-rc3",
    repl_git="https://github.com/leanprover-community/repl"
)
server = LeanServer(config)
```

When you specify a `repl_rev`, LeanInteract will try to:

1. Find a tagged revision with the format `{repl_rev}_lean-toolchain-{lean_version}`
2. If such tag doesn't exist, fall back to using the specified `repl_rev` directly
3. If `lean_version` is not specified, it will use the latest available Lean version compatible with the REPL

This approach allows for better matching between REPL versions and Lean versions, ensuring compatibility.

!!! warning
    Custom/older REPL implementations may have interfaces that are incompatible with LeanInteract's standard commands. If you encounter issues, consider using the `run_dict` method from `LeanServer` to communicate directly with the REPL:
    ```python
    # Using run_dict instead of the standard commands
    result = server.run_dict({"cmd": "your_command_here"})
    ```

!!! note
    The `repl_rev` and `repl_git` parameters are ignored if you specify `local_repl_path`.

## Best Practices

- Check the Lean version your project is compatible with and use that version in your configuration
- Initialize `LeanREPLConfig` before starting parallel processes to avoid conflicts, and then copy it in the child processes when instantiating `LeanServer`
- When working with custom Lean or Lake installations, specify the paths explicitly for reproducibility
- Use compatible REPL and Lean versions to avoid unexpected behavior
