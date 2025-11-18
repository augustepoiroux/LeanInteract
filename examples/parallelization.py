# /// script
# requires-python = ">=3.10"
# dependencies = ["lean-interact", "joblib"]
# ///
"""
Example demonstrating multi-processing and multi-threading with LeanInteract.

This example shows the correct pattern for using LeanInteract with multiple processes:
1. Pre-instantiate the config before starting multiprocessing
2. Use spawn context for cross-platform compatibility
3. Each process gets its own server instance

Run this example with: python examples/parallelization.py
"""

import concurrent.futures
import multiprocessing as mp
import time
from contextlib import contextmanager

from joblib import Parallel, delayed  # type: ignore

from lean_interact import AutoLeanServer, LeanREPLConfig
from lean_interact.interface import Command, LeanError


def worker(config: LeanREPLConfig, task_id: int) -> str:
    """Worker function that runs in each process"""
    try:
        # Each process gets its own server instance
        server = AutoLeanServer(config)
        result = server.run(
            Command(
                cmd="""
def fib : Nat → Nat
  | 0 => 0
  | 1 => 1
  | n + 2 => fib (n + 1) + fib n
#eval fib 32
"""
            )
        )
        if isinstance(result, LeanError):
            return f"Task {task_id}: LeanError - {result}"
        return f"Task {task_id}: {result.messages[0].data}"
    except Exception as e:
        return f"Task {task_id}: Exception - {e}"


def setup() -> tuple[LeanREPLConfig, list[int]]:
    print("Setting up LeanREPLConfig (may take a few minutes the first time)...")
    config = LeanREPLConfig(verbose=True)
    print("Config setup complete.")

    # Dummy tasks
    tasks = list(range(8))

    return config, tasks


@contextmanager
def timed_section(title: str, *, summary_prefix: str | None = None):
    print("\n\n" + "=" * 40)
    print(title)
    start_time = time.time()
    try:
        yield
    finally:
        elapsed = time.time() - start_time
        label = summary_prefix or title
        print(f"{label} took {elapsed:.2f} seconds.")


def print_results(results: list[str]) -> None:
    """Utility function to print results"""
    print("\nResults:")
    print("-" * 40)
    for result in results:
        print(result)


def sequential_baseline(config: LeanREPLConfig, tasks: list[int]) -> None:
    """Run tasks sequentially for baseline comparison"""
    with timed_section("Sequential Baseline", summary_prefix="Sequential processing"):
        results = []
        for task_id in tasks:
            result = worker(config, task_id)
            results.append(result)
    print_results(results)


def multiprocessing_example(config: LeanREPLConfig, tasks: list[int]) -> None:
    """Demonstrate multiprocessing with LeanInteract"""
    with timed_section("Multi-processing Example", summary_prefix="Multi-processing"):
        ctx = mp.get_context("spawn")
        with ctx.Pool(processes=min(4, len(tasks))) as pool:
            results = pool.starmap(worker, [(config, task_id) for task_id in tasks])
    print_results(results)


def multithreading_example(config: LeanREPLConfig, tasks: list[int]) -> None:
    """Demonstrate multithreading with LeanInteract"""
    with timed_section("Multi-threading Example", summary_prefix="Multi-threading"):
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(tasks))) as executor:
            future_to_task = {executor.submit(worker, config, task_id): task_id for task_id in tasks}
            for future in concurrent.futures.as_completed(future_to_task):
                results.append(future.result())
    print_results(results)


def joblib_parallel_example(config: LeanREPLConfig, tasks: list[int]) -> None:
    """Demonstrate joblib-based parallel execution with LeanInteract"""
    with timed_section("Joblib Parallel Example", summary_prefix="Joblib parallel processing"):
        results = Parallel(n_jobs=min(4, len(tasks)))(delayed(worker)(config, task_id) for task_id in tasks)
    print_results(results)


if __name__ == "__main__":
    config, tasks = setup()

    multiprocessing_example(config, tasks)
    joblib_parallel_example(config, tasks)
    multithreading_example(config, tasks)
    sequential_baseline(config, tasks)
