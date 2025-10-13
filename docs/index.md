---
hide:
  - navigation
---

# LeanInteract

[![PyPI version](https://img.shields.io/pypi/v/lean-interact.svg)](https://pypi.org/project/lean-interact/)
[![PyPI downloads](https://img.shields.io/pepy/dt/lean-interact.svg)](https://pypi.org/project/lean-interact/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**LeanInteract** is a Python package designed to seamlessly interact with Lean 4 through the [Lean REPL](https://github.com/leanprover-community/repl).

## Key Features

- **🔗 Interactivity**: Execute Lean code and files directly from Python
- **🚀 Ease of Use**: LeanInteract abstracts the complexities of Lean setup and interaction
- **💻 Cross-platform**: Works on Windows, macOS, and Linux operating systems
- **🔧 Compatibility**: Supports all Lean versions between `v4.8.0-rc1` and `v4.24.0-rc1`
    - We backport the latest features of Lean REPL to older versions of Lean (see [fork](https://github.com/augustepoiroux/repl)).
- **📦 Temporary Projects**: Easily instantiate temporary Lean environments
    - Useful for experimenting with benchmarks depending on [Mathlib](https://github.com/leanprover-community/mathlib4) like [ProofNet#](https://huggingface.co/datasets/PAug/ProofNetSharp) and [MiniF2F](https://github.com/yangky11/miniF2F-lean4)
- **🧾 Data extraction**: Extract declarations and info trees for analysis and dataset building.
- **⚡ Incremental + Parallel elaboration**: Automatically reuse partial computations from previous commands, and enable `Elab.async` for faster processing.

## Quick Start

### Install the package

```bash
pip install lean-interact
```

Install Lean 4 (if not already installed) using the following command coming with LeanInteract:

```bash
install-lean
```

### Start using it in your Python scripts

```python
from lean_interact import LeanREPLConfig, LeanServer, Command

# Create a configuration for the Lean REPL
config = LeanREPLConfig(verbose=True)  

# Start the Lean server
server = LeanServer(config)  

# Run a simple Lean theorem
server.run(Command(cmd="theorem ex (n : Nat) : n = 5 → n = 5 := id"))
```

Check out the [Installation](user-guide/installation.md) guide for detailed setup instructions and the [User Guide](user-guide/getting-started.md) for usage examples.
