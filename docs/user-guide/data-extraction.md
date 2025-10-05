---
execute: true
---

# Data Extraction: Declarations, Tactics, and InfoTrees

LeanInteract makes it easy to extract rich data from elaboration, including declarations, tactics, and detailed InfoTrees.

## Declarations

Set `declarations=True` to retrieve a list of `DeclarationInfo` for each declaration introduced in your Lean code.

```python tags=["execute"]
from lean_interact import Command, LeanServer, LeanREPLConfig
from lean_interact.interface import CommandResponse

code = """
theorem ex (n : Nat) : n = 5 → n = 5 := by
  intro h; exact h
"""

config = LeanREPLConfig()
server = LeanServer(config)
res = server.run(Command(cmd=code, declarations=True))
assert isinstance(res, CommandResponse)
for d in res.declarations:
    print(d.full_name, "::", d.signature.pp)
```

For files:

```python
from lean_interact import FileCommand
res = server.run(FileCommand(path="myfile.lean", declarations=True))
```

Tip: See [`examples/extract_mathlib_decls.py`](https://github.com/augustepoiroux/LeanInteract/blob/main/examples/extract_mathlib_decls.py) for a scalable, per-file parallel extractor over Mathlib.

## Tactics

Use `all_tactics=True` to collect tactic applications with their goals and used constants.

```python tags=["execute"]
from lean_interact import Command

code = """
theorem ex (n : Nat) : n = 5 → n = 5 := by
  intro h
  exact h
"""

resp = server.run(Command(cmd=code, all_tactics=True))
for t in resp.tactics:
  print(t.tactic, "| used:", t.used_constants)
```

## InfoTrees

Request `infotree` to obtain structured elaboration information. Accepted values include `"full"`, `"tactics"`, `"original"`, and `"substantive"`.

```python tags=["execute"]
from lean_interact import Command
from lean_interact.interface import InfoTree

res = server.run(Command(cmd=code, infotree="substantive"))
trees: list[InfoTree] = res.infotree or []

# Example: iterate over all command-level nodes and print their kind
for tree in trees:
    for cmd_node in tree.commands():
        print(cmd_node.kind, getattr(cmd_node.node, "elaborator", None))
```

## Root goals and messages

You can also ask for `root_goals=True` to retrieve initial goals for declarations (even if already proved).

```python
from lean_interact import FileCommand

server.run(FileCommand(path="myfile.lean", root_goals=True))
```
