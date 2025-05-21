---
execute: true
---

# Getting Started with LeanInteract

This guide will help you take your first steps with LeanInteract and understand its core concepts.

## Overview

LeanInteract provides a Python interface to the Lean 4 theorem prover via the Lean REPL (Read-Evaluate-Print Loop). It enables you to:

- Execute Lean code from Python
- Process Lean files
- Interact with proofs step by step
- Save and restore proof states

## Quick Example

Here's a minimal example to help you get started:

```python tags=["execute"]
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

1. Initialize a Lean REPL configuration
2. Start a Lean server
3. Execute a simple Lean theorem
4. Return a response containing the Lean environment state and any messages

## Understanding Core Components

Let's break down the key components:

### LeanREPLConfig

`LeanREPLConfig` sets up the Lean environment:

```python
config = LeanREPLConfig(
    lean_version="v4.19.0",  # Specify Lean version (optional)
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
response = server.run(Command(cmd="theorem ex (n : Nat) : n = 5 → n = 5 := id"))
```

## Next Steps

Now that you understand the basics, you can:

- Learn about [basic usage patterns](basic-usage.md)
- Explore [tactic mode](tactic-mode.md) for step-by-step proof interaction
- Configure [custom Lean environments](custom-lean-configuration.md)

Or check out the [API Reference](../api/config.md) for detailed information on all available classes and methods.
