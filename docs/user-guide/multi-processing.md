---
execute: false
---

# Multi-processing Guide

LeanInteract is designed with multi-processing in mind, allowing you to leverage multiple CPU cores for parallel theorem proving and verification tasks. This guide covers the best practices, patterns, and potential pitfalls when using LeanInteract in multi-process environments.

We recommend using `AutoLeanServer`.
It is specifically designed for multi-process environments with
automated restart on fatal Lean errors, timeouts, and when memory limits are reached.
On automated restarts, only commands run with `add_to_session_cache=True` (attribute of the `AutoLeanServer.run` method) will be preserved.

`AutoLeanServer` is still experimental, any feedback or issues encountered while using it are welcome.

## Best Practices Summary

1. **Always pre-instantiate** `LeanREPLConfig` before multiprocessing
2. **One lean server per process**
3. **Use `AutoLeanServer`**
4. **Configure memory limits** to prevent system overload
5. **Set appropriate timeouts** for long-running operations
6. **Use session caching** to keep context between requests
7. **Consider using `maxtasksperchild`** to limit memory accumulation

## Quick Start

Here is a minimal example of using LeanInteract with multiple processes:

```python
import multiprocessing as mp
from lean_interact import LeanREPLConfig, AutoLeanServer, Command

def worker(config: LeanREPLConfig, task_id):
    """Worker function that runs in each process"""
    server = AutoLeanServer(config)
    result = server.run(Command(cmd=f"#eval {task_id} * {task_id}"))
    return f"Task {task_id}: {result.messages[0].data if hasattr(result, 'messages') else 'Error'}"

if __name__ == "__main__":
    # Pre-instantiate config before multiprocessing
    # LeanREPLConfig downloads and initializes resources
    config = LeanREPLConfig(verbose=True)
    
    # Create processes
    ctx = mp.get_context("spawn")
    with ctx.Pool(processes=4) as pool:
        tasks = range(5)
        results = pool.starmap(worker, [(config, task_id) for task_id in tasks])
        
    for result in results:
        print(result)
```

For more examples, check the [examples directory](https://github.com/augustepoiroux/LeanInteract/tree/main/examples).

## Core Principles

### 1. Pre-instantiate Configuration

Always create your `LeanREPLConfig` instance **before** starting multiprocessing:

```python
from lean_interact import LeanREPLConfig, AutoLeanServer
import multiprocessing as mp

# ✅ CORRECT: Config created in main process
def correct_approach():
    config = LeanREPLConfig()  # Pre-setup in main process
    
    def worker(cfg):
        server = AutoLeanServer(cfg)  # Use pre-configured config
        # ... your work here
        pass
    
    ctx = mp.get_context("spawn")
    with ctx.Pool() as pool:
        pool.map(worker, [config] * 4)

# ❌ INCORRECT: Config created in each process
def incorrect_approach():
    def worker():
        config = LeanREPLConfig()
        server = AutoLeanServer(config)
        # ... your work here
        pass
    
    ctx = mp.get_context("spawn") 
    with ctx.Pool() as pool:
        pool.map(worker, range(4))
```

### 2. One Server Per Process

Each process should have its own `LeanServer` or `AutoLeanServer` instance.

```python
def worker(config, task_data):
    # Each process gets its own server
    server = AutoLeanServer(config)
    
    # Process your tasks
    for task in task_data:
        result = server.run(task)
        # Handle result
    
    return results
```

## Thread Safety

### Within a Single Process

`LeanServer` and `AutoLeanServer` are thread-safe within a single process thanks to internal locking mechanisms.
All concurrent requests will be processed sequentially.

### Across Processes

Servers are **NOT** safe to share across processes. Each process must have its own server instance:

```python
import multiprocessing as mp
from lean_interact import AutoLeanServer, LeanREPLConfig

# ✅ CORRECT: Each process creates its own server
def correct_multiprocess_worker(config: LeanREPLConfig, worker_id: int):
    server = AutoLeanServer(config)  # New server per process
    # ... work with server

# ❌ INCORRECT: Don't share servers across processes
def incorrect_multiprocess_pattern():
    config = LeanREPLConfig()
    server = AutoLeanServer(config)
    
    def worker(worker_id):
        # This will cause issues - server can't be pickled/shared
        result = server.run(Command(cmd="..."))
    
    with mp.Pool() as pool:
        pool.map(worker, range(4))  # Will fail!
```

## Memory Management

```python
from lean_interact import AutoLeanServer, LeanREPLConfig

# Configure memory limits for multi-process safety
config = LeanREPLConfig(memory_hard_limit_mb=8192)  # 8GB per server, works on Linux only

server = AutoLeanServer(
    config,
    max_total_memory=0.8,      # Restart when system uses >80% memory
    max_process_memory=0.8,    # Restart when process uses >80% of limit
    max_restart_attempts=5     # Allow up to 5 restart attempts per command
)
```

### Memory Configuration Options

- `max_total_memory`: System-wide memory threshold (0.0-1.0)
- `max_process_memory`: Per-process memory threshold (0.0-1.0)
- `memory_hard_limit_mb`: Hard memory limit in MB (Linux only)
- `max_restart_attempts`: Maximum consecutive restart attempts
