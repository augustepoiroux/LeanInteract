# Examples

This page provides practical examples of using LeanInteract in different scenarios. You can find a few full example scripts in the [`examples`](https://github.com/augustepoiroux/LeanInteract/tree/main/examples) directory of the repository.

## Basic Theorem Proving

This example demonstrates how to define a simple theorem with a partial proof in Lean using LeanInteract:

```python exec="on" source="above" result="python"
from lean_interact import LeanREPLConfig, LeanServer, Command

# Initialize configuration and server
config = LeanREPLConfig()
server = LeanServer(config)

# Define a simple theorem
print(server.run(Command(cmd="""
theorem add_comm (a b : Nat) : a + b = b + a := by
  induction a with
  | zero => simp
  | succ a ih => sorry
""")))
```

## Working with Mathlib

This example shows how to use Mathlib to work with more advanced mathematical concepts:

```python exec="on" source="above" result="python"
from lean_interact import LeanREPLConfig, LeanServer, Command, TempRequireProject

# Create configuration with Mathlib
config = LeanREPLConfig(project=TempRequireProject(lean_version="v4.19.0", require="mathlib"))
server = LeanServer(config)

# Define a theorem using Mathlib's real numbers
print(server.run(Command(cmd="""
import Mathlib

theorem irrational_plus_rational 
  (x : ℝ) (y : ℚ) : Irrational x → Irrational (x + y) := by
  intro h
  simp
  assumption
""")))
```

## Using Custom REPL Versions

This example demonstrates how to use a specific REPL version from a custom repository:

```python exec="on" source="above" result="python"
from lean_interact import LeanREPLConfig, LeanServer, Command

# Use a specific REPL version from the official Lean repository
config = LeanREPLConfig(
    repl_rev="v4.21.0-rc3", 
    repl_git="https://github.com/leanprover-community/repl"
)
server = LeanServer(config)

# Check the Lean version
response = server.run(Command(cmd="#eval Lean.versionString"))
print(response.messages[0].data)  # Output: "4.21.0-rc3"

# If you encounter interface compatibility issues with custom REPLs,
# you can use run_dict to communicate directly with the REPL:
result = server.run_dict({"cmd": "#eval Lean.versionString"})
print(result)  # Example raw output from the REPL
```

## Real-World Examples

For more comprehensive examples, check out the following scripts in the examples directory:

1. [**multi_processing.py**](https://github.com/augustepoiroux/LeanInteract/blob/main/examples/multi_processing.py)  
   Shows how to use multiprocessing with LeanInteract for parallel proof checking.

2. [**proof_generation_and_autoformalization.py**](https://github.com/augustepoiroux/LeanInteract/blob/main/examples/proof_generation_and_autoformalization.py)  
   Shows how to use models like DeepSeek-Prover-V1.5 and Goedel-Prover on MiniF2F and ProofNet# benchmarks.

3. [**beq_plus.py**](https://github.com/augustepoiroux/LeanInteract/blob/main/examples/beq_plus.py)  
   Demonstrates how to run the autoformalization BEq+ metric on the ProofNetVerif benchmark.

4. [**type_check.py**](https://github.com/augustepoiroux/LeanInteract/blob/main/examples/type_check.py)  
   Shows how to optimize type checking using environment states.
