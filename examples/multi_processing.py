# /// script
# requires-python = ">=3.10"
# dependencies = ["lean-interact"]
# ///
"""
Example demonstrating multi-processing with LeanInteract.

This example shows the correct pattern for using LeanInteract with multiple processes:
1. Pre-instantiate the config before starting multiprocessing
2. Use spawn context for cross-platform compatibility
3. Each process gets its own server instance

Run this example with: python examples/multiprocessing_example.py
"""

import multiprocessing as mp

from lean_interact import AutoLeanServer, LeanREPLConfig
from lean_interact.interface import Command, LeanError


def worker(config: LeanREPLConfig, task_id: int) -> str:
    """Worker function that runs in each process"""
    try:
        # Each process gets its own server instance
        server = AutoLeanServer(config)
        result = server.run(Command(cmd=f"#eval {task_id} * {task_id}"))
        if isinstance(result, LeanError):
            return f"Task {task_id}: LeanError - {result}"
        return f"Task {task_id}: {task_id}² = {result.messages[0].data}"
    except Exception as e:
        return f"Task {task_id}: Exception - {e}"


def main():
    """Main function demonstrating correct multiprocessing setup"""
    print("LeanInteract Multi-processing Example")
    print("=" * 40)

    # CRITICAL: Pre-instantiate config before multiprocessing as it downloads and initializes resources
    print("Setting up LeanREPLConfig (may take a few minutes the first time)...")
    config = LeanREPLConfig(verbose=True)
    print("Config setup complete.")

    # Dummy tasks
    tasks = range(1, 6)
    print(f"\nProcessing {len(tasks)} tasks in parallel...")

    ctx = mp.get_context("spawn")
    with ctx.Pool(processes=min(4, len(tasks))) as pool:
        results = pool.starmap(worker, [(config, task_id) for task_id in tasks])

    print("\nResults:")
    print("-" * 40)
    for result in results:
        print(result)


if __name__ == "__main__":
    main()
