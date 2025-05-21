---
execute: true
---

# Tactic Mode

Tactic mode in LeanInteract allows you to work with Lean's proof tactics step-by-step, providing an interactive way to develop and explore proofs.

!!! warning "Experimental Feature"
    The tactic mode feature is experimental in Lean REPL and may not work as expected in all situations. Some valid proofs might be incorrectly rejected. Please report any issues you encounter on the [Lean REPL GitHub repository](https://github.com/leanprover-community/repl/issues).

## Getting Started with Tactics

Using tactics in LeanInteract involves two main steps:

1. Creating a proof state using `sorry` in a theorem
2. Applying tactics to this proof state using `ProofStep`

### Creating a Proof State

First, let's create a proof state by defining a theorem with `sorry`:

```python tags=["execute"]
from lean_interact import LeanREPLConfig, LeanServer, Command

# Setup
config = LeanREPLConfig()
server = LeanServer(config)

# Define a theorem with sorry
response = server.run(Command(cmd="theorem ex (n : Nat) : n = 5 → n = 5 := sorry"))
print(response.sorries[0])
```

This response contains a `Sorry` object that includes:

- A `proof_state` ID that you can use for tactic commands
- The current goal that needs to be proven

### Applying Tactics

Once you have a proof state, you can apply tactics using the `ProofStep` class:

```python tags=["execute"]
from lean_interact import LeanREPLConfig, LeanServer, Command, ProofStep

# Setup
config = LeanREPLConfig()
server = LeanServer(config)

# Define a theorem with sorry
theorem_response = server.run(Command(cmd="theorem ex (n : Nat) : n = 5 → n = 5 := sorry"))
proof_state_id = theorem_response.sorries[0].proof_state

# Apply a single tactic (intro) to the proof state
server.run(ProofStep(tactic="intro h", proof_state=proof_state_id))
```

The response contains:

- A new proof state ID for chaining additional tactics
- The current goal(s)
- The proof status (complete or incomplete)

### Chaining Tactics

You can chain multiple tactics by using the proof state from each response:

```python tags=["execute"]
from lean_interact import LeanREPLConfig, LeanServer, Command, ProofStep

# Setup
config = LeanREPLConfig()
server = LeanServer(config)

# Define a theorem with sorry
theorem_response = server.run(Command(cmd="theorem ex (n : Nat) : n = 5 → n = 5 := sorry"))
proof_state_id = theorem_response.sorries[0].proof_state

# Apply 'intro' tactic
intro_response = server.run(ProofStep(tactic="intro h", proof_state=proof_state_id))

# Apply 'exact' tactic to the resulting proof state
server.run(ProofStep(tactic="exact h", proof_state=intro_response.proof_state))
```

### Applying Multiple Tactics at Once

You can also apply multiple tactics at once by wrapping them in parentheses:

```python tags=["execute"]
from lean_interact import LeanREPLConfig, LeanServer, Command, ProofStep

# Setup
config = LeanREPLConfig()
server = LeanServer(config)

# Define a theorem with sorry
theorem_response = server.run(Command(cmd="theorem ex (n : Nat) : n = 5 → n = 5 := sorry"))
proof_state_id = theorem_response.sorries[0].proof_state

# Apply multiple tactics at once
multi_response = server.run(ProofStep(tactic="""(
intro h
exact h
)""", proof_state=proof_state_id))
print(multi_response)
```

## Complete Proof Session

The `ProofStepResponse` contains a `proof_status` field that indicates whether the proof is complete.
Here's a complete example of working with tactics:

```python tags=["execute"]
from lean_interact import LeanREPLConfig, LeanServer, Command, ProofStep

# Setup
config = LeanREPLConfig()
server = LeanServer(config)

# Create a theorem with sorry
theorem_response = server.run(Command(cmd="theorem my_theorem (x : Nat) : x = x := sorry"))
print("Initial goal:", theorem_response.sorries[0].goal)

# Get the proof state from the sorry
proof_state_id = theorem_response.sorries[0].proof_state

# Apply reflexivity tactic
final_response = server.run(ProofStep(tactic="rfl", proof_state=proof_state_id))

# Check if the proof is complete
if final_response.proof_status == "Completed":
    print("Proof completed successfully!")
else:
    print("Proof failed:", final_response)
```
