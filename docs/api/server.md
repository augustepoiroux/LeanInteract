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

LeanInteract automatically augments `Command` and `FileCommand` requests to speed up elaboration and processing of files:

- Incremental elaboration is enabled by default
- Parallel elaboration is enabled via `set_option Elab.async true` by default when supported (Lean >= v4.19.0)

You can disable these behaviors in `LeanREPLConfig` by setting
`enable_incremental_optimization=False` and/or `enable_parallel_elaboration=False`.
