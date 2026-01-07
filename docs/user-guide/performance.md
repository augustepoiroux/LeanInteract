# Performance & Parallelization

LeanInteract provides **three complementary performance layers** that can be combined:

1. **Incremental elaboration**: reuse previous elaboration results instead of starting from scratch.
2. **Parallel elaboration**: use `Elab.async` so Lean elaborates independent parts in parallel.
3. **External parallelization**: run multiple Lean servers concurrently to process many commands in parallel.

All three can be enabled together for maximum throughput: fast single commands (incremental + parallel elaboration) and high aggregate throughput across many commands (external parallelization).

By default, **incremental elaboration** and **parallel elaboration** are enabled in [`LeanREPLConfig`](../api/config.md#lean_interact.config.LeanREPLConfig). **External parallelization** can be achieved using [`LeanServerPool`](../api/pool.md#lean_interact.pool.LeanServerPool) or via a custom multiprocessing/threading setup (see [Parallelization Guide](#parallelization-guide-multiple-commands) below).

## Incremental Elaboration

Incremental elaboration is a free performance boost that reduces latency and memory by automatically reusing elaboration results from prior commands executed on the same [`LeanServer`](../api/server.md#lean_interact.server.LeanServer).

### How it works

In Lean, incremental elaboration allows reusing the elaboration state of a prior command when elaborating a new command that shares a common prefix.
For example, if a command has already been elaborated:

```lean
import Mathlib
def foo : Nat := 42
```

and the next command to elaborate is:

```lean
import Mathlib
def bar : Nat := 56
```

then Lean can reuse the elaboration state after `import Mathlib` from the first command instead of starting from scratch, effectively loading Mathlib only once.

LeanInteract **automatically finds the best incremental state** to reuse for each new command. For VS Code users, this corresponds to how Lean4's built-in language server reuses elaboration states when editing files (indicated by the vertical orange loading bar in the gutter).

LeanInteract extends this mechanism by searching through **all prior commands** in the history, not just the most recent one. The optimal reuse point is found using a trie-based data structure, which in practice has negligible overhead in both memory and CPU usage.

### Properties

- Write commands in any order without manually worrying about managing command states.
- The trie-based history lookup ensures that the best reuse point is found efficiently, independent of the number of prior commands.
- In the worst case, memory and CPU usage will be similar to non-incremental elaboration (if no reuse is possible).
- Particularly useful when checking batches of file edits or multiple similar commands.

### How to use it

Incremental elaboration is **enabled by default** and requires no special setup:

1. Create a [`LeanREPLConfig`](../api/config.md#lean_interact.config.LeanREPLConfig) with default settings (or explicitly set [`enable_incremental_optimization`](../api/config.md#lean_interact.config.LeanREPLConfig.enable_incremental_optimization) to `True`).
2. Send commands to the same [`LeanServer`](../api/server.md#lean_interact.server.LeanServer) instance as usual, incremental elaboration is applied automatically.

**Recommendation:** Send full commands or file contents rather than splitting the code into small chunks. LeanInteract will automatically find the best reuse points, making manual state management unnecessary.

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
    Imports are cached in incremental mode, meaning that if the content of one of the imported files has changed, it will not be taken into account unless the server is restarted.

This feature can be disabled by setting [`enable_incremental_optimization`](../api/config.md#lean_interact.config.LeanREPLConfig.enable_incremental_optimization) to `False` in [`LeanREPLConfig`](../api/config.md#lean_interact.config.LeanREPLConfig).

## Parallel Elaboration

Lean can elaborate different parts of a command or file in parallel. LeanInteract automatically enables this feature by setting `Elab.async` to `true` to each request.

To disable parallel elaboration, set [`enable_parallel_elaboration`](../api/config.md#lean_interact.config.LeanREPLConfig.enable_parallel_elaboration) to `False` in [`LeanREPLConfig`](../api/config.md#lean_interact.config.LeanREPLConfig).

!!! note
    This feature is only available for Lean >= v4.19.0

---

## Parallelization Guide (Multiple Commands)

LeanInteract is designed for efficient parallelization, allowing to leverage multiple CPU cores for parallel theorem proving and verification tasks.

This section covers **external parallelization**: running multiple Lean servers concurrently (in threads, processes, or workers) to process many commands in parallel. This is complementary to the within-command optimizations above and can be combined with them for maximum throughput.

**Recommended approach:** Use [`LeanServerPool`](../api/pool.md#lean_interact.pool.LeanServerPool) for most use cases. It manages a pool of Lean servers and efficiently distributes commands among them with minimal boilerplate.

### Using LeanServerPool

[`LeanServerPool`](../api/pool.md#lean_interact.pool.LeanServerPool) provides a simple, high-level interface for parallel command execution, with automatic worker management and load balancing.

```python
from lean_interact import LeanREPLConfig, LeanServerPool, Command

# Pre-instantiate config (downloads/builds dependencies once)
config = LeanREPLConfig(verbose=True)

# Create a batch of commands
commands = [Command(cmd=f"#eval {i} * {i}") for i in range(100)]

# Run them in parallel with progress tracking
with LeanServerPool(config, num_workers=4) as pool:
    results = pool.run_batch(commands, timeout_per_cmd=60, show_progress=True)
```

[extract_mathlib_decls.py](https://github.com/augustepoiroux/LeanInteract/blob/main/examples/extract_mathlib_decls.py) in the examples directory demonstrates how to use [`LeanServerPool`](../api/pool.md#lean_interact.pool.LeanServerPool) to extract declarations from Mathlib in parallel.

!!! note
    Exceptions raised during command execution in `run_batch` and `async_run_batch` are captured and returned as results along with successful results. This allows processing all results without interruption. Check the type of each result to handle errors accordingly.

### Custom Multiprocessing Setup

For more control, here are guidelines for setting up a custom parallelization pipeline.

#### Recommended Practices

1. **Pre-instantiate** [`LeanREPLConfig`](../api/config.md#lean_interact.config.LeanREPLConfig) before parallelization, then pass it to each worker
2. **Use [`AutoLeanServer`](../api/server.md#lean_interact.server.AutoLeanServer)**
3. **Configure memory limits** to prevent single-command blowups
4. **Set appropriate timeouts** for long-running operations

```python
from multiprocessing import Pool
from lean_interact import AutoLeanServer, Command, LeanREPLConfig
from lean_interact.interface import LeanError

def worker(config: LeanREPLConfig, task_id: int):
    """Worker function that runs in each process"""
    server = AutoLeanServer(config)
    result = server.run(Command(cmd=f"#eval {task_id} * {task_id}"), timeout=60)
    return f"Task {task_id}: {result.messages[0].data if not isinstance(result, LeanError) else 'Error'}"

# Pre-instantiate config before parallelization (downloads/initializes resources)
config = LeanREPLConfig(verbose=True, memory_hard_limit_mb=8192)  # 8GB limit per server (Linux only)
with Pool() as p:
    print(p.starmap(worker, [(config, i) for i in range(5)]))
```

[proof_generation_and_autoformalization.py](https://github.com/augustepoiroux/LeanInteract/blob/main/examples/proof_generation_and_autoformalization.py) in the [examples directory](https://github.com/augustepoiroux/LeanInteract/tree/main/examples) demonstrates a custom multiprocessing setup for proof generation and autoformalization tasks. It regroups proof attempts per problem to minimize redundant elaboration work thanks to incremental elaboration and aborts early if a valid proof is found.

!!! tip "Multithreading vs Multiprocessing"
    Since [`LeanServer`](../api/server.md#lean_interact.server.LeanServer) and [`AutoLeanServer`](../api/server.md#lean_interact.server.AutoLeanServer) spawn a separate subprocess for the Lean REPL, the Python process itself is mostly waiting on I/O. Therefore, **multithreading** or **asyncio** (within a single process) is often sufficient and more lightweight than multiprocessing for running multiple servers. This approach also makes session cache sharing easier, as all servers can share the same [`ReplaySessionCache`](../api/sessioncache.md#lean_interact.sessioncache.ReplaySessionCache) instance.

#### Pre-instantiating Configuration

We recommend creating [`LeanREPLConfig`](../api/config.md#lean_interact.config.LeanREPLConfig) before starting parallelization.

Creating a [`LeanREPLConfig`](../api/config.md#lean_interact.config.LeanREPLConfig) involves setting up the Lean environment, resolving dependencies, and building the project, operations that can be time-consuming, especially on first run.

While **it is safe** to create multiple configurations concurrently (file locks prevent corruption), it is **inefficient**. Workers will serialize during the setup phase as they contend for locks.

Best practices:

   1. **Instantiate config in the main process** (downloads/builds once)
   2. **Pass it to workers** (configs are picklable)

#### [`LeanServer`](../api/server.md#lean_interact.server.LeanServer) vs [`AutoLeanServer`](../api/server.md#lean_interact.server.AutoLeanServer)

We recommend using [`AutoLeanServer`](../api/server.md#lean_interact.server.AutoLeanServer). It is specifically designed for parallel environments with automated restart on fatal Lean errors, timeouts, and when memory limits are reached. On automated restarts, only commands run with `add_to_session_cache=True` (attribute of the [`AutoLeanServer.run`](../api/server.md#lean_interact.server.AutoLeanServer.run) method) will be preserved.

#### Thread Safety

Within a single process:

- [`LeanServer`](../api/server.md#lean_interact.server.LeanServer) and [`AutoLeanServer`](../api/server.md#lean_interact.server.AutoLeanServer) are **thread-safe** (internal locking ensures concurrent requests are handled safely)
- [`ReplaySessionCache`](../api/sessioncache.md#lean_interact.sessioncache.ReplaySessionCache) is **thread-safe** (multiple servers in different threads can share the same cache instance)

Across processes:

- Each process **must create its own server instance** (servers are not shareable across process boundaries)
- Each process **must have its own cache instance** (caches cannot be shared across processes)

#### Memory Management

[`AutoLeanServer`](../api/server.md#lean_interact.server.AutoLeanServer) provides automatic memory management with configurable thresholds to prevent system overload:

```python
from lean_interact import AutoLeanServer, LeanREPLConfig

# Configure memory limits
config = LeanREPLConfig(memory_hard_limit_mb=8192)  # 8GB hard limit per server (Linux only)

server = AutoLeanServer(
    config,
    max_total_memory=0.8,      # Restart when system uses >80% memory
    max_process_memory=0.8,    # Restart when process uses >80% of memory limit
    max_restart_attempts=5     # Allow up to 5 restart attempts per command
)
```

Memory configuration options:

- [`memory_hard_limit_mb`](../api/config.md#lean_interact.config.LeanREPLConfig.memory_hard_limit_mb): Hard memory limit in MB (Linux only). Sets an OS-level limit on the Lean process memory usage. Empirically, some slow-downs and memory overheads have been observed when this parameter is set. It is recommended to set this limit above 8GB.
- [`max_total_memory`](../api/server.md#lean_interact.server.AutoLeanServer): System-wide memory threshold (0.0-1.0)
- [`max_process_memory`](../api/server.md#lean_interact.server.AutoLeanServer): Per-process memory threshold (0.0-1.0)
- [`max_restart_attempts`](../api/server.md#lean_interact.server.AutoLeanServer): Maximum consecutive restart attempts
