# Performance & Multi-processing

LeanInteract implements two complementary mechanisms for faster feedback by default:

- Incremental elaboration: reuse partial computations across commands/files
- Parallel elaboration: enable `Elab.async` to elaborate independent parts in parallel

## Incremental elaboration

Incremental elaboration reduces latency and memory by automatically reusing elaboration results from prior commands executed on the same `LeanServer`.
You can disable it if needed by setting `enable_incremental_optimization=False` in `LeanREPLConfig`.

### Example

Below is a small script that measures the elapsed time of a first "heavier" command and a second dependent command that benefits from incremental reuse:

```python exec="on" source="above" session="perf" result="python"
import time
from lean_interact import LeanREPLConfig, LeanServer, Command

server = LeanServer(LeanREPLConfig())

t1 = time.perf_counter()
print(server.run(Command(cmd="""
def fib : Nat → Nat
  | 0 => 0
  | 1 => 1
  | n + 2 => fib (n + 1) + fib n
#eval fib 35

theorem foo : n = n := by rfl
#check foo
""")))
print(f"First run:  {time.perf_counter() - t1:.3f}s")

t2 = time.perf_counter()
print(server.run(Command(cmd="""
def fib : Nat → Nat
  | 0 => 0
  | 1 => 1
  | n + 2 => fib (n + 1) + fib n
#eval fib 35

theorem foo2 : n = n+0 := by rfl
#check foo2
""")))
print(f"Second run: {time.perf_counter() - t2:.3f}s")
```

!!! warning Imports are cached
    Imports are cached in incremental mode, meaning that if the content of one of your imported file has changed, it will not be taken into account unless you restart the server.

## Parallel elaboration (Elab.async)

When supported (Lean >= v4.19.0), Lean can elaborate different parts of a command/file in parallel. LeanInteract auto-enables this by adding `set_option Elab.async true` to each request.
You can disable it if needed by setting `enable_parallel_elaboration=False` in `LeanREPLConfig`.

!!! note
    Only available for Lean >= v4.19.0

---

## Multi-processing Guide

LeanInteract is designed with multi-processing in mind, allowing you to leverage multiple CPU cores for parallel theorem proving and verification tasks.

We recommend using `AutoLeanServer`. It is specifically designed for multi-process environments with automated restart on fatal Lean errors, timeouts, and when memory limits are reached. On automated restarts, only commands run with `add_to_session_cache=True` (attribute of the `AutoLeanServer.run` method) will be preserved.

`AutoLeanServer` is still experimental; feedback and issues are welcome.

### Best Practices Summary

1. **Always pre-instantiate** `LeanREPLConfig` before multiprocessing
2. **One lean server per process**
3. **Use `AutoLeanServer`**
4. **Configure memory limits** to prevent system overload
5. **Set appropriate timeouts** for long-running operations
6. **Use session caching** to keep context between requests
7. **Consider using `maxtasksperchild`** to limit memory accumulation

### Quick Start

```python
from multiprocessing import Pool
from lean_interact import AutoLeanServer, Command, LeanREPLConfig
from lean_interact.interface import LeanError

def worker(config: LeanREPLConfig, task_id: int):
    """Worker function that runs in each process"""
    server = AutoLeanServer(config)
    result = server.run(Command(cmd=f"#eval {task_id} * {task_id}"))
    return f"Task {task_id}: {result.messages[0].data if not isinstance(result, LeanError) else 'Error'}"

# Pre-instantiate config before multiprocessing (downloads/initializes resources)
config = LeanREPLConfig(verbose=True)
with Pool() as p:
    print(p.starmap(worker, [(config, i) for i in range(5)]))
```

For more examples, check the [examples directory](https://github.com/augustepoiroux/LeanInteract/tree/main/examples).

### Core Principles

#### 1. Pre-instantiate Configuration

Always create your `LeanREPLConfig` instance **before** starting multiprocessing:

```python
from lean_interact import LeanREPLConfig, AutoLeanServer
import multiprocessing as mp

# ✅ CORRECT: Config created in main process
config = LeanREPLConfig()  # Pre-setup in main process

def worker(cfg):
    server = AutoLeanServer(cfg)  # Use pre-configured config
    # ... your work here
    pass

ctx = mp.get_context("spawn")
with ctx.Pool() as pool:
    pool.map(worker, [config] * 4)

# ❌ INCORRECT: Config created in each process
def worker():
    config = LeanREPLConfig()
    server = AutoLeanServer(config)
    # ... your work here
    pass

ctx = mp.get_context("spawn")
with ctx.Pool() as pool:
    pool.map(worker, range(4))
```

#### 2. One Server Per Process

Each process should have its own `LeanServer` or `AutoLeanServer` instance.

```python
def worker(config, task_data):
    # Each process gets its own server
    server = AutoLeanServer(config)

    for task in task_data:
        result = server.run(task)
        # Handle result

    return results
```

### Thread Safety

Within a single process, `LeanServer` and `AutoLeanServer` are thread-safe thanks to internal locking. All concurrent requests are processed sequentially. Across processes, servers are not shareable: each process must create its own instance.

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

### Memory Management

```python
from lean_interact import AutoLeanServer, LeanREPLConfig

# Configure memory limits for multi-process safety
config = LeanREPLConfig(memory_hard_limit_mb=8192)  # 8GB per server, works on Linux only

server = AutoLeanServer(
    config,
    max_total_memory=0.8,      # Restart when system uses >80% memory
    max_process_memory=0.8,    # Restart when process uses >80% of memory limit
    max_restart_attempts=5     # Allow up to 5 restart attempts per command
)
```

#### Memory Configuration Options

- `max_total_memory`: System-wide memory threshold (0.0-1.0)
- `max_process_memory`: Per-process memory threshold (0.0-1.0)
- `memory_hard_limit_mb`: Hard memory limit in MB (Linux only)
- `max_restart_attempts`: Maximum consecutive restart attempts
