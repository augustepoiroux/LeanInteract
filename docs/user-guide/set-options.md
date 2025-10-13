# Set Lean Options from Python (`set_option`)

You can pass Lean options per request using the `setOptions` field on `Command` and `FileCommand`. This mirrors Lean’s `set_option` commands and lets you customize elaboration or pretty-printing on a per-request basis.

## Shape

- `setOptions` is a list of pairs `(Name, DataValue)`
- `Name` is a list of components, e.g. `["pp", "unicode"]`
- `DataValue` can be `bool | int | str | Name`

Example:

```python exec="on" source="above" session="options" result="python"
from lean_interact import Command, LeanServer, LeanREPLConfig

server = LeanServer(LeanREPLConfig())
print(server.run(Command(
    cmd="variable (n : Nat)\n#check n+0=n",
    setOptions=[(["pp", "raw"], True)],
)))
```

LeanInteract will also merge your `setOptions` with its own defaults when enabled (e.g., it may add `(["Elab","async"], True)` to enable parallel elaboration). Your explicitly provided options are appended and forwarded with the request.

!!! note
    Options apply only to the single request you send; pass them again for subsequent calls
