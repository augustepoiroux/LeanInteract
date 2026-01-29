::: lean_interact.server
    options:
      heading_level: 1
      heading: "Lean Servers"
      show_symbol_type_heading: false
      members:
        - LeanServer
        - AutoLeanServer

---

## Notes on performance features

LeanInteract automatically augments [`Command`](interface.md#lean_interact.interface.Command) and [`FileCommand`](interface.md#lean_interact.interface.FileCommand) requests to speed up elaboration and processing of files:

- Incremental elaboration is enabled by default
- Parallel elaboration is enabled via `set_option Elab.async true` by default when supported (Lean >= v4.19.0)

These behaviors can be disabled in [`LeanREPLConfig`](config.md#lean_interact.config.LeanREPLConfig) by setting
[`enable_incremental_optimization`](config.md#lean_interact.config.LeanREPLConfig.enable_incremental_optimization) to `False` and/or [`enable_parallel_elaboration`](config.md#lean_interact.config.LeanREPLConfig.enable_parallel_elaboration) to `False`.
