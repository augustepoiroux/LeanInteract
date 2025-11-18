# Performance & Parallelization

LeanInteract provides **three complementary performance layers** that can be combined:

1. **Within-command speedups (inside a single Lean request)**
     - **Incremental elaboration**: reuse previous elaboration results instead of starting from scratch.
     - **Parallel elaboration**: use `Elab.async` so Lean elaborates independent parts in parallel.
2. **Across-command speedups (multiple commands / tasks)**
     - **External parallelization**: run several Lean servers in parallel, typically via `AutoLeanServer`.

All three can be enabled together for maximum throughput: fast single commands (incremental + parallel elaboration) and high aggregate throughput across many commands (external parallelization).
By default, **incremental elaboration** and **parallel elaboration** are enabled in `LeanREPLConfig`. **External parallelization** can be implemented in various ways, thus no default is provided.

## Incremental Elaboration

Incremental elaboration is a free performance boost that reduces latency and memory by automatically reusing elaboration results from prior commands executed on the same `LeanServer`.

### How it works

In Lean, incremental elaboration allows reusing the elaboration state of a prior command when elaborating a new command that shares a common prefix.
For example, if you have already elaborated:

```lean
import Mathlib
def foo : Nat := 42
```

and now want to elaborate:

```lean
import Mathlib
def bar : Nat := 56
```

then Lean can reuse the elaboration state after `import Mathlib` from the first command instead of starting from scratch, effectively loading Mathlib only once.

Incremental elaboration therefore **automatically finds the best incremental state from the previous command** to reuse for the new command. For VS Code users, this corresponds to how Lean4's built-in language server reuses elaboration states when editing files (vertical orange loading bar in the gutter).

LeanInteract generalizes this mechanism further by extending the search for the best incremental state to reuse to **all prior commands** in the history, not just the most recent one. The optimal incremental state is found using a Trie-based data structure, which in practice has no noticeable overhead in both memory and CPU usage.

### Properties

- Write commands in any order without manually worrying about managing command states.
- The Trie-based history lookup ensures that the best reuse point is found efficiently, independent of the number of prior commands.
- In the worst case, memory and CPU usage will be similar to non-incremental elaboration (if no reuse is possible).
- Particularly useful when checking batches of file edits or multiple similar commands.

### How to use it

- Create your `LeanREPLConfig` with default settings (or ensure `enable_incremental_optimization=True`).
- Simply send commands to the same `LeanServer` instance as usual, incremental elaboration will be automatically applied.
- **Recommendation:** Instead of splitting your code into small chunks like in a REPL, you should send full commands or file contents. LeanInteract will find the best reuse points automatically.

### Example

Below is a small script that measures the elapsed time of two "heavy" commands, but the second command benefits from incremental reuse:

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

You can disable this feature by setting `enable_incremental_optimization=False` in `LeanREPLConfig`.

## Parallel Elaboration

When supported (Lean >= v4.19.0), Lean can elaborate different parts of a command/file in parallel. LeanInteract auto-enables this by adding `set_option Elab.async true` to each request.
You can disable it if needed by setting `enable_parallel_elaboration=False` in `LeanREPLConfig`.

!!! note
    Only available for Lean >= v4.19.0

---

## Parallelization Guide (multiple commands)

LeanInteract is designed with parallelization in mind, allowing you to leverage multiple CPU cores for parallel theorem proving and verification tasks.

This section focuses on **external parallelization**: running multiple Lean servers (usually via `AutoLeanServer`) in parallel threads, processes or workers. This is complementary to the within-command optimizations above and can be combined with them.

We recommend using `AutoLeanServer`. It is specifically designed for parallel environments with automated restart on fatal Lean errors, timeouts, and when memory limits are reached. On automated restarts, only commands run with `add_to_session_cache=True` (attribute of the `AutoLeanServer.run` method) will be preserved.

`AutoLeanServer` is still experimental, feedback and issues are welcome.

### Best Practices Summary

1. **Always pre-instantiate** `LeanREPLConfig` before parallelization
2. **One lean server per process/thread**
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

# Pre-instantiate config before parallelization (downloads/initializes resources)
config = LeanREPLConfig(verbose=True)
with Pool() as p:
    print(p.starmap(worker, [(config, i) for i in range(5)]))
```

For more examples, check the [examples directory](https://github.com/augustepoiroux/LeanInteract/tree/main/examples).

### Core Principles

#### 1. Pre-instantiate Configuration

Always create your `LeanREPLConfig` instance **before** starting parallelization:

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

#### 2. One Server Per Process/Thread

Each process or thread should have its own `LeanServer` or `AutoLeanServer` instance.

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

Similarly, `ReplaySessionCache` is thread-safe within a process, meaning multiple `AutoLeanServer` in different threads can safely share the same cache instance. However, across processes, each must have its own cache instance.

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
