# Basic Usage

This guide covers the fundamental operations and command types in LeanInteract.

## Basic Command Execution

The most common operation in LeanInteract is executing Lean code directly using the `Command` class:

```python exec="on" source="above" session="base" result="python"
from lean_interact import LeanREPLConfig, LeanServer, Command

# Setup
config = LeanREPLConfig()
server = LeanServer(config)

# Run a simple theorem
print(server.run(Command(cmd="theorem ex (n : Nat) : n = 5 → n = 5 := id")))
```

The response contains:

- Messages returned by Lean if any (errors, information, etc.)
- An environment state (`env`) that can be used for subsequent commands.

### Working with Environment States

Each command execution creates a new environment state. You can use this state in subsequent commands:

```python exec="on" source="above" session="base" result="python"
# First command creates environment state
response1 = server.run(Command(cmd="def x := 5"))

# Use environment state 0 for the next command
print(server.run(Command(cmd="#check x", env=response1.env)))
```

## Processing Lean Files

You can process entire Lean files using the `FileCommand` class:

```python
from lean_interact import FileCommand

# Process a Lean file
response = server.run(FileCommand(path="myfile.lean"))

# With options to get more information about goals
response = server.run(FileCommand(path="myfile.lean", root_goals=True))
```

## Available Options

Both `Command` and `FileCommand` support several options:

- `all_tactics`: Get information about tactics used
- `declarations`: Extract fine-grained information about declarations in the code
- `root_goals`: Get information about goals in theorems and definitions
- `infotree`: Get Lean infotree containing various informations from the Lean syntax tree
- `incrementality`: Enable or disable incremental elaboration for this specific command.
- `set_options`: Set Lean options for this command (see [Set Options](set-options.md))
- `env`: The environment from a previous command to be used as context. If `env = None`, starts from scratch.

Example with options:

```python exec="on" source="above" session="base" result="python"
response = server.run(Command(
    cmd="theorem ex (n : Nat) : n = 5 → n = 5 := by simp",
    all_tactics=True
))
print(response.tactics)  # Shows tactics used
```

## Working with Sorries

When Lean code contains `sorry` (incomplete proofs), LeanInteract returns information about these `sorry`:

```python exec="on" source="above" session="base" result="python"
response = server.run(Command(cmd="theorem ex (n : Nat) : n = 5 → n = 5 := sorry"))
print(response.sorries[0])
```

This response will include a list of `Sorry` objects, each containing:

- Position in the code
- Goal to be proven
- Proof state ID (can be used with `ProofStep` commands)

## Error Handling

```python exec="on" source="above" session="base" result="python"
from lean_interact.interface import LeanError

try:
    response = server.run(Command(cmd="invalid Lean code"))
    if isinstance(response, LeanError):
        print("Command failed with fatal error(s):", response.message)
    else:
        print("Command succeeded:", response) # but the content may contain errors !!
except Exception as e:
    print(f"An error occurred: {e}")
```

## Next Steps

- Learn about [tactic mode](tactic-mode.md) for step-by-step proof interaction
- Configure [custom Lean environments](custom-lean-configuration.md)
- Explore the [API Reference](../api/interface.md) for more command options
