# Custom Lean Configuration

LeanInteract provides flexible ways to configure the Lean environment to suit different use cases. This guide covers the various configuration options available.

## Specifying Lean Versions

You can specify which version of Lean 4 you want to use when no project is specified:

```python
from lean_interact import LeanREPLConfig, LeanServer

# Use a specific Lean version
config = LeanREPLConfig(lean_version="v4.8.0")
server = LeanServer(config)
```

## Working with Existing Projects

!!! note
    When using a project through the `project` attribute, the Lean version is automatically inferred from the project. You cannot specify both `lean_version` and `project` parameters.

### Local Lean Projects

To work with a local Lean project, create a `LocalProject` instance:

```python
from lean_interact import LeanREPLConfig, LocalProject, LeanServer

# Configure with a local project
project = LocalProject(
    directory="path/to/your/project",
    auto_build=True  # Automatically build the project (default is True)
)
config = LeanREPLConfig(project=project)
server = LeanServer(config)
```

!!! important
    Ensure the project can be successfully built with `lake build` before using it with LeanInteract.

!!! tip
    Setting `auto_build=False` will skip building the project, which can be useful if you've already built it.

### Git-Based Projects

You can work with projects hosted on Git repositories:

```python
from lean_interact import LeanREPLConfig, GitProject, LeanServer

# Configure with a Git-hosted project
project = GitProject(
    url="https://github.com/yangky11/lean4-example",
    rev="main",  # Optional: specific branch, tag, or commit
    directory="/custom/cache/path",  # Optional: custom directory where the project will be cloned
    force_pull=False  # Optional: force update from remote. Useful in case you already have the project cloned and the branch has been updated.
)
config = LeanREPLConfig(project=project)
server = LeanServer(config)
```

The `GitProject` will automatically:

- Clone the repository if it doesn't exist (including submodules if present)
- Update to the specified revision
- Build the project with `lake build`

!!! tip
    Use the `directory` parameter to control where projects are cached

## Working with Temporary Projects

LeanInteract allows you to create temporary projects with dependencies for quick experimentation and automated reproducible setups.

### Simple Temporary Projects with Dependencies

To create a temporary project with dependencies:

```python
from lean_interact import LeanREPLConfig, TempRequireProject, LeanRequire

# Create a temporary project with Mathlib as a dependency
project = TempRequireProject(
    lean_version="v4.8.0",
    require=[
        LeanRequire(
            name="mathlib",
            git="https://github.com/leanprover-community/mathlib4.git",
            rev="v4.8.0"
        )
    ]
)
config = LeanREPLConfig(project=project)
```

For the common case of requiring Mathlib, there's a shortcut:

```python
project = TempRequireProject(lean_version="v4.8.0", require="mathlib")
config = LeanREPLConfig(project=project)
```

### Fine-Grained Temporary Projects

For more control over the temporary project, you can specify the complete lakefile content:

```python
from lean_interact import LeanREPLConfig, TemporaryProject

project = TemporaryProject(
    lean_version="v4.18.0",
    content="""
import Lake
open Lake DSL

package "dummy" where
  version := v!"0.1.0"

@[default_target]
lean_exe "dummy" where
  root := `Main

require mathlib from git
  "https://github.com/leanprover-community/mathlib4.git" @ "v4.18.0"
""",
    lakefile_type="lean"  # or "toml"
)
config = LeanREPLConfig(project=project)
```

This approach gives you full control over the Lake configuration.
Alternatively, you can define the lakefile content using the TOML format by setting `lakefile_type="toml"`.

## Using Custom REPL Revisions

LeanInteract uses the Lean REPL from a git repository to interact with Lean. By default, it uses a specific version of the REPL from the default forked repository (`https://github.com/augustepoiroux/repl`) which manages compatibility with Lean versions. However, you can customize this by specifying a different REPL revision or repository:

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
    Custom/older REPL implementations may have interfaces that are incompatible with LeanInteract's current commands. If you encounter issues, consider using the `run_dict` method from `LeanServer` to communicate directly with the REPL:

    ```python
    result = server.run_dict({"cmd": "your_command_here"})
    ```

!!! note
    The `repl_rev` and `repl_git` parameters are ignored if you specify `local_repl_path`.

### Using a Local REPL Installation

If you are developing the Lean REPL or have a custom version, you can use your local copy instead of downloading from a git repository:

```python
from lean_interact import LeanREPLConfig, LeanServer

config = LeanREPLConfig(local_repl_path="path/to/your/local/repl", build_repl=True)
server = LeanServer(config)
```

!!! note
    When using `local_repl_path`, any specified `repl_rev`, and `repl_git` parameters are ignored as the local REPL is used directly.

!!! note
    Make sure you are using a compatible Lean version between your local REPL and the project you will interact with.
