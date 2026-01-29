# Set Lean Options from Python (`set_option`)

Pass Lean options per request using the [`set_options`](../api/interface.md#lean_interact.interface.Command.set_options) field on [`Command`](../api/interface.md#lean_interact.interface.Command) and [`FileCommand`](../api/interface.md#lean_interact.interface.FileCommand). This mirrors Lean's [`set_option`](https://leanprover-community.github.io/lean4-metaprogramming-book/extra/01_options.html) commands and allows customizing elaboration or pretty-printing on a per-request basis.

## Shape

- `set_options` is a list of pairs `(Name, DataValue)`
- `Name` is a list of components, e.g. `["pp", "unicode"]`
- `DataValue` can be `bool | int | str | Name`

Example:

```python exec="on" source="above" session="options" result="python"
from lean_interact import Command, LeanServer, LeanREPLConfig

server = LeanServer(LeanREPLConfig())
print(server.run(Command(
    cmd="variable (n : Nat)\n#check n+0=n",
    set_options=[(["pp", "raw"], True)],
)))
```

LeanInteract will also merge the provided [`set_options`](../api/interface.md#lean_interact.interface.Command.set_options) with its own defaults when enabled (e.g., it may add `(["Elab","async"], True)` to enable parallel elaboration). Explicitly provided options are appended and forwarded with the request.

!!! note
    Options apply only to the single request; pass them again for subsequent calls
