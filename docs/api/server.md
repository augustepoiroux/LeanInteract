# LeanServer API

This page documents the server classes responsible for communicating with the Lean REPL.

## LeanServer

::: lean_interact.server.LeanServer
    options:
      show_root_heading: true
      show_source: true
      heading_level: 3

### Using `run_dict` for custom REPLs

When working with custom REPL implementations that might have incompatible interfaces with LeanInteract's standard commands, you can use the `run_dict` method to communicate directly with the REPL using the raw JSON protocol:

```python
# Using run_dict to send a raw command to the REPL
result = server.run_dict({"cmd": "your_command_here"})
```

This method bypasses the command-specific parsing and validation, allowing you to work with custom REPL interfaces.

## AutoLeanServer

::: lean_interact.server.AutoLeanServer
    options:
      show_root_heading: true
      show_source: true
      heading_level: 3

## Timeout Configuration

::: lean_interact.server.DEFAULT_TIMEOUT
