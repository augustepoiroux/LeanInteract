# Session Cache API

This page documents the session cache classes responsible for storing and retrieving Lean proof states and environments.
Session cache is used internally by the `AutoLeanServer` class.
It enables efficient resumption of proofs and environments after server restarts, timeouts, and automated recover from crashes. While by default `AutoLeanServer` instantiates a fresh `PickleSessionCache` instance, you can also use a custom one. It can be useful to share a session cache between multiple `AutoLeanServer` instances, or to use a custom session cache implementation.

```python
from lean_interact.sessioncache import PickleSessionCache
from lean_interact.server import AutoLeanServer

# Create a session cache
cache = PickleSessionCache(working_dir="./cache")

# Create a Lean server with the cache
server = AutoLeanServer(config=..., session_cache=cache)
```

## Session State Classes

### SessionState

::: lean_interact.sessioncache.SessionState
    options:
      show_root_heading: true
      show_source: true
      heading_level: 3

### PickleSessionState

::: lean_interact.sessioncache.PickleSessionState
    options:
      show_root_heading: true
      show_source: true
      heading_level: 3

## Cache Implementation

### BaseSessionCache

::: lean_interact.sessioncache.BaseSessionCache
    options:
      show_root_heading: true
      show_source: true
      heading_level: 3

### PickleSessionCache

::: lean_interact.sessioncache.PickleSessionCache
    options:
      show_root_heading: true
      show_source: true
      heading_level: 3
