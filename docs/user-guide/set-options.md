---
execute: true
---

# Set Options from Python (`set_option`)

You can pass Lean options per request using the `setOptions` field on `Command` and `FileCommand`. This mirrors Lean’s `set_option` commands and lets you customize elaboration or pretty-printing on a per-request basis.

## Shape

- `setOptions` is a list of pairs `(Name, DataValue)`
- `Name` is a list of components, e.g. `["pp", "unicode"]`
- `DataValue` can be `bool | int | str | Name`

Example:

```python tags=["execute"]
from lean_interact import Command, LeanServer, LeanREPLConfig

config = LeanREPLConfig()
server = LeanServer(config)

res = server.run(Command(
    cmd="#check Nat.succ",
    setOptions=[
        (["pp", "unicode"], False),  # ASCII pretty-printing
        (["pp", "raw"], True),       # show raw terms
    ],
))
```

LeanInteract will also merge your `setOptions` with its own defaults when enabled (e.g., it may add `(["Elab","async"], True)` to enable parallel elaboration). Your explicitly provided options are appended and forwarded with the request.

## Common options

- Pretty-printer controls under `pp.*` (e.g. `pp.unicode`, `pp.raw`, `pp.useNotation`)
- Elaboration options such as `Elab.async` (parallel elaboration)
- Tracing or debugging flags depending on your use case

```python tags=["execute"]
res = server.run(Command(
    cmd="#check List.map",
    setOptions=[(["pp","useNotation"], True)],
))
```

## With files

```python
from lean_interact import FileCommand
res = server.run(FileCommand(
    path="myfile.lean",
    setOptions=[(["pp","unicode"], False)],
))
```

## Notes and tips

- Options apply only to the single request you send; pass them again for subsequent calls
