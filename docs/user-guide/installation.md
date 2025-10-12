# Installation

## Prerequisites

Before installing LeanInteract, ensure you have the following prerequisites:

- Python 3.10 or newer
- Git (for Lean installation)
- [Lean 4](https://leanprover-community.github.io/get_started.html) (optional - LeanInteract can install it for you)

We recommend using Linux or macOS for the best experience, but LeanInteract also supports Windows.

## Installation Steps

### 1. Install the Package

You can install LeanInteract directly from PyPI:

```bash
pip install lean-interact
```

### 2. Install Lean 4 (if not already installed)

LeanInteract provides a convenient command to install Lean 4 along with its official [Elan](https://github.com/leanprover/elan) version manager:

```bash
install-lean
```

This command will install Elan, which manages Lean versions.

!!! warning "Elan Version"
    Your Elan version should be at least 4.0.0.

## Verifying Installation

You can verify that LeanInteract is properly installed by running a simple Python script:

```python exec="on" source="above" session="install" result="python"
from lean_interact import LeanREPLConfig, LeanServer, Command

# Create a configuration
config = LeanREPLConfig(verbose=True)

# Initialize the server
server = LeanServer(config)

# Execute a simple Lean command
response = server.run(Command(cmd="#eval 2 + 2"))
print(response)
```

If everything is set up correctly, the script should output a successful response.

!!! note
    The first time you run LeanInteract, it might take some time as it downloads the requested Lean version and builds Lean REPL. Subsequent runs will be significantly faster due to caching.

## System-Specific Notes

### Windows

On Windows, you might encounter path length limitations. If you get an error related to path length, you can enable long paths in Windows 10 and later versions by running the following command in an administrator PowerShell:

```powershell
New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name LongPathsEnabled -Value 1 -PropertyType DWord -Force
git config --system core.longpaths true
```

For more information, refer to the [Microsoft documentation](https://learn.microsoft.com/en-us/windows/win32/fileio/maximum-file-path-limitation).

### Docker

If you're using LeanInteract in a Docker container, make sure to include Git in your container and have sufficient memory allocated, especially if you're working with Mathlib.

## Uninstallation

If you need to clear the LeanInteract cache (for troubleshooting or disk space reasons), you can use:

```bash
clear-lean-cache
```

To completely uninstall:

```bash
pip uninstall lean-interact
```
