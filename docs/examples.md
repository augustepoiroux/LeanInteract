---
execute: true
---

# Examples

This page provides practical examples of using LeanInteract in different scenarios. You can find the full examples in the [`examples`](https://github.com/augustepoiroux/LeanInteract/tree/main/examples) directory of the repository.

## Basic Theorem Proving

This example demonstrates how to define a simple theorem with a partial proof in Lean using LeanInteract:

```python tags=["execute"]
from lean_interact import LeanREPLConfig, LeanServer, Command

# Initialize configuration and server
config = LeanREPLConfig()
server = LeanServer(config)

# Define a simple theorem
server.run(Command(cmd="""
theorem add_comm (a b : Nat) : a + b = b + a := by
  induction a with
  | zero => simp
  | succ a ih => sorry
"""))
```

## Working with Mathlib

This example shows how to use Mathlib to work with more advanced mathematical concepts:

```python
from lean_interact import LeanREPLConfig, LeanServer, Command, TempRequireProject

# Create configuration with Mathlib
config = LeanREPLConfig(
    lean_version="v4.19.0", 
    project=TempRequireProject("mathlib")
)
server = LeanServer(config)

# Define a theorem using Mathlib's real numbers
server.run(Command(cmd="""
import Mathlib

theorem irrational_plus_rational 
  (x : ℝ) (y : ℚ) : Irrational x → Irrational (x + y) := by
  intro h
  simp
  assumption
"""))
```

## Real-World Examples

For more comprehensive examples, check out the following scripts in the examples directory:

1. [**proof_generation_and_autoformalization.py**](https://github.com/augustepoiroux/LeanInteract/blob/main/examples/proof_generation_and_autoformalization.py)  
   Shows how to use models like DeepSeek-Prover-V1.5 and Goedel-Prover on MiniF2F and ProofNet# benchmarks.

2. [**beq_plus.py**](https://github.com/augustepoiroux/LeanInteract/blob/main/examples/beq_plus.py)  
   Demonstrates how to run the autoformalization BEq+ metric on the ProofNetVerif benchmark.

3. [**type_check.py**](https://github.com/augustepoiroux/LeanInteract/blob/main/examples/type_check.py)  
   Shows how to optimize type checking using environment states.
