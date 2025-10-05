# LeanInteract

[![Documentation](https://img.shields.io/badge/docs-latest-purple.svg)](https://augustepoiroux.github.io/LeanInteract/)
[![PyPI version](https://img.shields.io/pypi/v/lean-interact.svg)](https://pypi.org/project/lean-interact/)
[![PyPI downloads](https://img.shields.io/pepy/dt/lean-interact.svg)](https://pypi.org/project/lean-interact/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**LeanInteract** is a Python package designed to seamlessly interact with Lean 4 through the [Lean REPL](https://github.com/leanprover-community/repl).

Check the [documentation](https://augustepoiroux.github.io/LeanInteract/) for detailed usage and examples.

## Key Features

- **🔗 Interactivity**: Execute Lean code and files directly from Python.
- **🚀 Ease of Use**: LeanInteract abstracts the complexities of Lean setup and interaction.
- **💻 Cross-platform**: Works on Windows, macOS, and Linux operating systems.
- **🔧 Compatibility**: Supports all Lean versions between `v4.8.0-rc1` and `v4.24.0-rc1`.
  - We backport the latest features of Lean REPL to older versions of Lean (see [fork](https://github.com/augustepoiroux/repl)).
- **📦 Temporary Projects**: Easily instantiate temporary Lean environments.
  - Useful for experimenting with benchmarks depending on [Mathlib](https://github.com/leanprover-community/mathlib4) like [ProofNet#](https://huggingface.co/datasets/PAug/ProofNetSharp) and [MiniF2F](https://github.com/yangky11/miniF2F-lean4).
- **🧾 Data extraction (new in v0.9.0)**: Extract declarations and info trees for analysis and dataset building.
- **⚡ Incremental + Parallel elaboration (new in v0.9.0)**: Automatically reuse partial computations from previous commands, and enable `Elab.async` for faster processing.

## Table of Contents

- [Key Features](#key-features)
- [Installation and Setup](#installation-and-setup)
- [Script examples](#script-examples)
- [Usage](#usage)
  - [Basic example](#basic-example)
  - [Tactic mode](#tactic-mode)
  - [Custom Lean configuration](#custom-lean-configuration)
    - [Specific Lean version](#specific-lean-version)
    - [Existing Lean projects](#existing-lean-projects)
    - [Temporary project with dependencies](#temporary-project-with-dependencies)
    - [Fine-grained temporary project](#fine-grained-temporary-project)
- [Available Queries](#available-queries)
  - [Command](#command)
  - [FileCommand](#filecommand)
  - [ProofStep](#proofstep)
  - [Environment Pickling](#environment-pickling)
  - [ProofState Pickling](#proofstate-pickling)
- [Helper Commands](#helper-commands)
- [Advanced options](#advanced-options)
  - [LeanServer](#leanserver)
  - [Custom Lean REPL](#custom-lean-repl)
- [Similar tools](#similar-tools)
- [Troubleshooting](#troubleshooting)
- [Citation](#citation)
- [License](#license)

## Installation and Setup

You can install the LeanInteract package using the following command:

```bash
pip install lean-interact
```

Requirements:

- Python >= 3.10
- git
- [Lean 4](https://leanprover-community.github.io/get_started.html)
  - **Tip:** use the cross-platform `install-lean` command from LeanInteract.
  - Your `elan` version should be at least `4.0.0` (`elan --version`).

## Script examples

In the [`examples`](examples) directory, you will find a few scripts demonstrating how to use LeanInteract.

- [`proof_generation_and_autoformalization.py`](examples/proof_generation_and_autoformalization.py): use [DeepSeek-Prover-V1.5](https://arxiv.org/abs/2408.08152), [Goedel-Prover](https://goedel-lm.github.io/), and other models on [MiniF2F](https://github.com/yangky11/miniF2F-lean4) and [ProofNet#](https://huggingface.co/datasets/PAug/ProofNetSharp) benchmarks.
- [`beq_plus.py`](examples/beq_plus.py): run the autoformalization [BEq+](https://arxiv.org/abs/2406.07222) metric on the [ProofNetVerif](https://huggingface.co/datasets/PAug/ProofNetVerif) benchmark.
- [`type_check.py`](examples/type_check.py): optimize type checking using environment states.

## Usage

Full documentation is available [here](https://augustepoiroux.github.io/LeanInteract/).

### Basic example

The following code will use the default Lean version (latest available):

```python
from lean_interact import LeanREPLConfig, LeanServer, Command

config = LeanREPLConfig(verbose=True) # download and build Lean REPL
server = LeanServer(config) # start Lean REPL
server.run(Command(cmd="theorem ex (n : Nat) : n = 5 → n = 5 := id"))
```

<details>
<summary>Output</summary>

```python
CommandResponse(
  env=0,
  messages=[
    Message(start_pos=Pos(line=1, column=0),
    end_pos=Pos(line=1, column=42),
    data='Goals accomplished!',
    severity='info')
  ]
)
```

</details>

Iterate on the environment state:

```python
server.run(Command(cmd="example (x : Nat) : x = 5 → x = 5 := by exact ex x", env=0))
```

<details>
<summary>Output</summary>

```python
CommandResponse(
  env=1,
  messages=[
    Message(start_pos=Pos(line=1, column=0),
    end_pos=Pos(line=1, column=50),
    data='Goals accomplished!',
    severity='info')
  ]
)
```

</details>

See [Available Queries](#available-queries) for all available commands.

> [!NOTE]
> The initial invocation of `LeanREPLConfig` might take some time as it downloads and builds Lean REPL. Future executions with identical parameters will be significantly quicker due to caching.

### Tactic mode

> [!WARNING]
> This feature is experimental in Lean REPL and may not work as expected: some valid proofs might be incorrectly rejected. Please report any issues you encounter [here](https://github.com/leanprover-community/repl/issues).

First, let's run a command to create a theorem with a `sorry` proof:

```python
server.run(Command(cmd="theorem ex (n : Nat) : n = 5 → n = 5 := sorry"))
```

<details>
<summary>Output</summary>

```python
CommandResponse(
  sorries=[
    Sorry(start_pos=Pos(line=1, column=40),
    end_pos=Pos(line=1, column=45),
    goal='n : Nat\n⊢ n = 5 → n = 5',
    proof_state=0)
  ],
  env=0,
  messages=[
    Message(start_pos=Pos(line=1, column=8),
    end_pos=Pos(line=1, column=10),
    data="declaration uses 'sorry'",
    severity='warning')
  ]
)
```

</details>

You can then iterate on the proof state by executing tactics:

```python
from lean_interact import ProofStep

server.run(ProofStep(tactic="intro h", proof_state=0))
```

<details>
<summary>Output</summary>

```python
ProofStepResponse(
  proof_state=1,
  goals=['n : Nat\nh : n = 5\n⊢ n = 5'],
  proof_status='Incomplete: open goals remain'
)
```

</details>

```python
server.run(ProofStep(tactic="exact h", proof_state=1))
```

<details>
<summary>Output</summary>

```python
ProofStepResponse(proof_state=2, goals=[], proof_status='Completed')
```

</details>

or by directly running the entire proof:

```python
server.run(ProofStep(tactic="(\nintro h\nexact h)", proof_state=0))
```

<details>
<summary>Output</summary>

```python
ProofStepResponse(proof_state=3, goals=[], proof_status='Completed')
```

</details>

### Custom Lean configuration

#### Specific Lean version

```python
config = LeanREPLConfig(lean_version="v4.8.0")
```

#### Existing Lean projects

```python
# Local project
project = LocalProject(directory="path/to/your/project")
config = LeanREPLConfig(project=project)
```

or

```python
# Git project
project = GitProject(url="https://github.com/yangky11/lean4-example", rev="main")
config = LeanREPLConfig(project=project)
```

You can then use `run` as usual:

```python
from lean_interact import FileCommand

server = LeanServer(config)
server.run(FileCommand(path="file.lean"))
```

> [!IMPORTANT]
> Ensure the project can be *successfully* built with `lake build` before using LeanInteract.

#### Temporary project with dependencies

```python
from lean_interact import TempRequireProject, LeanRequire

project = TempRequireProject(
    lean_version="v4.8.0", 
    require=[LeanRequire(
        name="mathlib",
        git="https://github.com/leanprover-community/mathlib4.git",
        rev="v4.8.0"
    )]
)
config = LeanREPLConfig(project=project)
```

Mathlib being a frequent requirement, a shortcut is available:

```python
project = TempRequireProject(lean_version="v4.8.0", require="mathlib")
config = LeanREPLConfig(project=project)
```

You can then use Mathlib as follows:

```python
server = LeanServer(config)
server.run(Command(cmd="""import Mathlib
theorem ex_mathlib (x : ℝ) (y : ℚ) :
  ( Irrational x ) -> Irrational ( x + y ) := sorry"""))
```

<details>
<summary>Output</summary>

```python
CommandResponse(
  env=0,
  sorries=[
    Sorry(end_pos=Pos(line=3, column=51),
    goal='x : ℝ\ny : ℚ\n⊢ Irrational x → Irrational (x + ↑y)',
    start_pos=Pos(line=3, column=46),
    proof_state=0)
  ],
  messages=[
    Message(end_pos=Pos(line=2, column=18),
    data="declaration uses 'sorry'",
    start_pos=Pos(line=2, column=8),
    severity='warning')
  ]
)
```

</details>

> [!NOTE]
>
> - Mathlib is a large library and may take some time to download and build.
> - A separate cache is used for each unique set of dependencies.

#### Fine-grained temporary project

For more control over the temporary project, you can use `TemporaryProject` to specify the content of the lakefile (`.lean` format).

```python
from lean_interact import TemporaryProject

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
"""
)
config = LeanREPLConfig(project=project)
```

## Available Queries

LeanInteract supports various types of queries to interact with the Lean REPL. We briefly describe them in this section. You can check the file [interface.py](src/lean_interact/interface.py) for more details.

### Command

Execute Lean code directly:

```python
from lean_interact import Command

# Execute a simple theorem
response = server.run(Command(cmd="theorem ex (n : Nat) : n = 5 → n = 5 := id"))

# Execute with options to get tactics information
response = server.run(Command(cmd="theorem ex (n : Nat) : n = 5 → n = 5 := by simp", all_tactics=True))

# Continue in the same environment
response = server.run(Command(cmd="#check ex", env=response.env))
```

### FileCommand

Process Lean files:

```python
from lean_interact import FileCommand

# Execute a Lean file
response = server.run(FileCommand(path="myfile.lean"))

# With options for more information
response = server.run(FileCommand(path="myfile.lean", root_goals=True))
```

Extract Lean declarations while processing a file:

```python
response = server.run(FileCommand(path="myfile.lean", declarations=True))
for d in response.declarations:
  print(d.full_name, d.signature.pp)
```

### ProofStep

Work with proofs step by step using tactics:

```python
from lean_interact import ProofStep

# Apply a tactic to a proof state
response = server.run(ProofStep(proof_state=0, tactic="intro h"))

# Apply multiple tactics at once
response = server.run(ProofStep(proof_state=0, tactic="(\nintro h\nexact h)"))
```

### Environment Pickling

Save and restore environment states:

```python
from lean_interact import PickleEnvironment, UnpickleEnvironment

# Save an environment
server.run(PickleEnvironment(env=1, pickle_to="env_state.olean"))

# Restore an environment
server.run(UnpickleEnvironment(unpickle_env_from="env_state.olean"))
```

### ProofState Pickling

Save and restore proof states:

```python
from lean_interact import PickleProofState, UnpickleProofState

# Save a proof state
server.run(PickleProofState(proof_state=2, pickle_to="proof_state.olean"))

# Restore a proof state
server.run(UnpickleProofState(unpickle_proof_state_from="proof_state.olean", env=1))
```

## Helper Commands

The following commands are installed with LeanInteract:

- `install-lean`: Installs Lean 4 version manager `elan`.
- `clear-lean-cache`: Removes all Lean REPL versions and temporary projects in the package cache. This can help resolve some issues. If it does, please open an issue.

## Advanced options

### LeanServer

Two versions of Lean servers are available:

- **`LeanServer`**: A wrapper around Lean REPL. Interact with it using the `run` method.
- **`AutoLeanServer`**: An experimental subclass of `LeanServer` automatically recovering from some crashes and timeouts. It also monitors memory usage to limit *out of memory* issues in multiprocessing contexts. Use the `add_to_session_cache` attribute available in the `run` method to prevent selected environment/proof states to be cleared.

> [!TIP]
>
> - To run multiple requests in parallel, we recommend using multiprocessing with one global `LeanREPLConfig` instance, and one `AutoLeanServer` instance per process.
> - Make sure to instantiate `LeanREPLConfig` before starting the processes to avoid conflicts during Lean REPL's download and build.
> - While `AutoLeanServer` can help prevent crashes, it is not a complete solution. If you encounter crashes, consider reducing the number of parallel processes or increasing the memory available to your system.

### Custom Lean REPL

To use a forked Lean REPL project, specify the git repository using the `repl_git` parameter in the `LeanREPLConfig` and the target revision using the `repl_rev` parameter. For example:

```python
config = LeanREPLConfig(repl_rev="v4.21.0-rc3", repl_git="https://github.com/leanprover-community/repl", verbose=True)
```

> [!WARNING]
>
> Custom REPL implementations may have interfaces that are incompatible with LeanInteract's standard commands. If you encounter incompatibility issues, you can use the `run_dict` method from `LeanServer` to communicate directly with the REPL using the raw JSON protocol:
>
> ```python
> # Using run_dict instead of the standard commands
> result = server.run_dict({"cmd": "your_command_here"})
> ```

For assistance, feel free to contact [us](mailto:auguste.poiroux@epfl.ch).

## Similar tools

We recommend checking out these tools:

- **[PyPantograph](https://github.com/lenianiva/PyPantograph)**: Based on Pantograph, offering more options for proof interactions than Lean REPL.
- **[LeanDojo](https://github.com/lean-dojo/LeanDojo)**: Parses Lean projects to create datasets and interact with proof states.
- **[itp-interface](https://github.com/trishullab/itp-interface)**: A Python interface for interacting and extracting data from Lean 4 and Coq.
- **[leanclient](https://github.com/oOo0oOo/leanclient)**: Interact with the Lean LSP server.

LeanInteract is inspired by **[pylean](https://github.com/zhangir-azerbayev/repl)** and **[lean4_jupyter](https://github.com/utensil/lean4_jupyter)**.

## Troubleshooting

Common issues and their solutions:

1. **Out of memory errors**: Reduce parallel processing or increase system memory. Alternatively, use `AutoLeanServer` with conservative memory settings

2. **Timeout errors**: Currently, `LeanServer` simply stops the Lean REPL if a command times out. Use `AutoLeanServer` for automatic recovery.

3. **Long waiting times during first run**: This is expected as Lean REPL is being downloaded and built. Additionally, if you are importing Mathlib it will take even more time. Subsequent runs will be much faster.

4. **`Failed during Lean project setup: Command '['lake', 'update']' returned non-zero exit status 1.`**: This error may occur if your `elan` version is outdated (i.e. < 4.0.0). To resolve this, update `elan` using `elan self update` or read the documentation [here](https://leanprover-community.github.io/get_started.html).

5. **(Windows) Path too long error**: Windows has a maximum path length limitation of 260 characters.
If you get an error similar to the following one, you are likely affected by this problem:

    ```
    error: external command 'git' exited with code 128
    ERROR    Failed during Lean project setup: Command '['lake', 'update']' returned non-zero exit status 1.
    ```

    To resolve this, you can enable long paths in Windows 10 and later versions. For more information, refer to the [Microsoft documentation](https://learn.microsoft.com/en-us/windows/win32/fileio/maximum-file-path-limitation).
    Alternatively, run the following command in a terminal with administrator privileges:

    ```bash
    New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name LongPathsEnabled -Value 1 -PropertyType DWord -Force
    git config --system core.longpaths true
    ```

## Citation

If you use LeanInteract in your research, please cite it as follows:

```bibtex
@software{leaninteract,
  author = {Poiroux, Auguste and Kuncak, Viktor and Bosselut, Antoine},
  title = {LeanInteract: A Python Interface for Lean 4},
  url = {https://github.com/augustepoiroux/LeanInteract},
  year = {2025}
}
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
