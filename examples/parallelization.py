# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "lean-interact",
#   "joblib",
# ]
# ///
"""
Example demonstrating multi-processing and multi-threading with LeanInteract.

This example shows the correct pattern for using LeanInteract with multiple processes:
1. Pre-instantiate the config before starting multiprocessing
2. Use spawn context for cross-platform compatibility
3. Each process gets its own server instance

Run this example with: python examples/parallelization.py
"""

import asyncio
import concurrent.futures
import multiprocessing as mp
import time
from contextlib import contextmanager

from joblib import Parallel, delayed  # type: ignore

from lean_interact import AutoLeanServer, LeanREPLConfig, LeanServerPool
from lean_interact.interface import Command, LeanError

# Common command for all examples
CMD = """
def fib : Nat → Nat
  | 0 => 0
  | 1 => 1
  | n + 2 => fib (n + 1) + fib n
#eval {task_id}
#eval fib 32
"""


def process_result(result) -> str:
    """Helper to process the result from a Lean command."""
    if isinstance(result, LeanError):
        return f"LeanError - {result}"
    if isinstance(result, Exception):
        return f"Exception - {result}"
    return " | ".join(msg.data for msg in result.messages)


def worker(config: LeanREPLConfig, code: str) -> str:
    """Worker function that runs in each process"""
    try:
        # Each process gets its own server instance
        server = AutoLeanServer(config)
        result = server.run(Command(cmd=code))
        return process_result(result)
    except Exception as e:
        return f"Exception - {e}"


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


def sequential_baseline(config: LeanREPLConfig, lean_codes: list[str]) -> None:
    """Run tasks sequentially for baseline comparison"""
    with timed_section("Sequential Baseline", summary_prefix="Sequential processing"):
        results = []
        for code in lean_codes:
            result = worker(config, code)
            results.append(result)
    print_results(results)


def multiprocessing_example(config: LeanREPLConfig, lean_codes: list[str], n_jobs: int) -> None:
    """Demonstrate multiprocessing with LeanInteract"""
    with timed_section("Multi-processing Example", summary_prefix="Multi-processing"):
        ctx = mp.get_context("spawn")
        with ctx.Pool(processes=n_jobs) as pool:
            results = pool.starmap(worker, [(config, code) for code in lean_codes])
    print_results(results)


def multithreading_example(config: LeanREPLConfig, lean_codes: list[str], n_jobs: int) -> None:
    """Demonstrate multithreading with LeanInteract"""
    with timed_section("Multi-threading Example", summary_prefix="Multi-threading"):
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=n_jobs) as executor:
            future_to_code = {executor.submit(worker, config, code): code for code in lean_codes}
            for future in concurrent.futures.as_completed(future_to_code):
                results.append(future.result())
    print_results(results)


def joblib_parallel_example(config: LeanREPLConfig, lean_codes: list[str], n_jobs: int) -> None:
    """Demonstrate joblib-based parallel execution with LeanInteract"""
    with timed_section("Joblib Parallel Example", summary_prefix="Joblib parallel processing"):
        results = Parallel(n_jobs=n_jobs)(delayed(worker)(config, code) for code in lean_codes)
    print_results(results)


def asyncio_example(config: LeanREPLConfig, lean_codes: list[str], n_jobs: int) -> None:
    """Demonstrate asyncio with LeanInteract"""

    async def run_tasks():
        semaphore = asyncio.Semaphore(min(n_jobs, len(lean_codes)))

        async def run_one(code: str) -> str:
            try:
                server = AutoLeanServer(config)
                async with semaphore:
                    result = await server.async_run(Command(cmd=code))
                return process_result(result)
            except Exception as e:
                return f"Exception - {e}"

        return await asyncio.gather(*(run_one(code) for code in lean_codes))

    with timed_section("Asyncio Example", summary_prefix="Asyncio processing"):
        results = asyncio.run(run_tasks())
    print_results(results)


def lean_server_pool_example(config: LeanREPLConfig, lean_codes: list[str], n_jobs: int) -> None:
    """Demonstrate LeanServerPool with LeanInteract"""
    with timed_section("LeanServerPool Example", summary_prefix="LeanServerPool processing"):
        with LeanServerPool(config, num_workers=n_jobs) as pool:
            results = pool.run_batch([Command(cmd=code) for code in lean_codes])
            results = [process_result(r) for r in results]
    print_results(results)


if __name__ == "__main__":
    print("Setting up LeanREPLConfig (may take a few minutes the first time)...")
    config = LeanREPLConfig(verbose=True)
    lean_codes = [CMD.format(task_id=i) for i in range(8)]
    n_jobs = min(4, len(lean_codes))
    print("Config setup complete.")

    multiprocessing_example(config=config, lean_codes=lean_codes, n_jobs=n_jobs)
    joblib_parallel_example(config=config, lean_codes=lean_codes, n_jobs=n_jobs)
    multithreading_example(config=config, lean_codes=lean_codes, n_jobs=n_jobs)
    asyncio_example(config=config, lean_codes=lean_codes, n_jobs=n_jobs)
    lean_server_pool_example(config=config, lean_codes=lean_codes, n_jobs=n_jobs)
    sequential_baseline(config=config, lean_codes=lean_codes)
