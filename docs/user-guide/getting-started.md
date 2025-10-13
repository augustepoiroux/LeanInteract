# Getting Started with LeanInteract

## Overview

LeanInteract provides a Python interface to the Lean 4 theorem prover via the Lean REPL (Read-Evaluate-Print Loop). It enables you to:

- Execute Lean code from Python
- Process Lean files
- Interact with proofs step by step

## Quick Example

```python exec="on" source="above" session="getting-started" result="python"
from lean_interact import LeanREPLConfig, LeanServer, Command

# Create a Lean REPL configuration
config = LeanREPLConfig(verbose=True)

# Start a Lean server with the configuration
server = LeanServer(config)

# Execute a simple theorem
response = server.run(Command(cmd="theorem ex (n : Nat) : n = 5 → n = 5 := id"))

# Print the response
print(response)
```

This will:

1. Initialize a Lean REPL configuration: downloads and initializes the Lean environment
2. Start a Lean server
3. Execute a simple Lean theorem
4. Return a response containing the Lean environment state and any messages

## Core Components

### LeanREPLConfig

`LeanREPLConfig` sets up the Lean environment:

```python
config = LeanREPLConfig(
    lean_version="v4.19.0",  # Specify Lean version (optional, default is latest)
    verbose=True,            # Print detailed logs
)
```

### LeanServer

`LeanServer` manages communication with the Lean REPL:

```python
server = LeanServer(config)
```

A more robust alternative is `AutoLeanServer`, which automatically recovers from (some) crashes:

```python
from lean_interact import AutoLeanServer
auto_server = AutoLeanServer(config)
```

### Commands

LeanInteract provides several types of commands:

- `Command`: Execute Lean code directly
- `FileCommand`: Process Lean files
- `ProofStep`: Work with proofs step by step using tactics

Basic command execution:

```python
server.run(Command(cmd="theorem ex (n : Nat) : n = 5 → n = 5 := id"))
```

## Next Steps

- Learn about [basic usage patterns](basic-usage.md)
- Explore [tactic mode](tactic-mode.md) for step-by-step proof interaction
- Configure [custom Lean environments](custom-lean-configuration.md)

Or check out the [API Reference](../api/config.md) for detailed information on all available classes and methods.
