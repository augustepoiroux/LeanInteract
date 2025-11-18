# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "datasets",
#     "lean-interact",
#     "rich",
#     "tqdm",
# ]
# ///
"""
This module shows how to type-check / compile Lean4 snippets, leveraging automatic incremental state reuse.
"""

import json
from typing import Any

from datasets import load_dataset
from rich.console import Console
from tqdm import tqdm

from lean_interact import AutoLeanServer, LeanREPLConfig
from lean_interact.interface import Command, CommandResponse
from lean_interact.project import TempRequireProject

console = Console()
DEFAULT_TIMEOUT = 60


def type_check_sequential(dataset: list[dict[str, Any]], repl_config: LeanREPLConfig) -> list[bool]:
    """
    Type-checks each formalization sequentially.

    Args:
        dataset: A list of dictionaries with keys 'lean4_src_header' and 'lean4_formalization'.
        repl_config: Configuration for the Lean REPL.

    Returns:
        A list of booleans indicating if each formalization is valid.
    """
    server = AutoLeanServer(repl_config)
    successes = [False for _ in dataset]
    for idx, row in enumerate(tqdm(dataset)):
        src_header = row["lean4_src_header"]
        formalization = row["lean4_formalization"]
        try:
            server_output = server.run(
                Command(cmd=src_header + "\n" + formalization + " sorry"), timeout=DEFAULT_TIMEOUT
            )
            if isinstance(server_output, CommandResponse):
                successes[idx] = server_output.lean_code_is_valid()
        except (TimeoutError, ConnectionAbortedError, json.JSONDecodeError) as e:
            console.log(f"Error while type checking entry {idx}: {e}")
    return successes


if __name__ == "__main__":
    proofnetsharp = load_dataset("PAug/ProofNetSharp", split="valid")
    config = LeanREPLConfig(project=TempRequireProject(lean_version="v4.16.0-rc2", require="mathlib"), verbose=True)

    type_check_results = type_check_sequential(proofnetsharp, config)
    assert len(type_check_results) == len(proofnetsharp)

    if any(not well_typed for well_typed in type_check_results):
        console.log("Failures:")
        for i, well_typed in enumerate(type_check_results):
            if not well_typed:
                console.log(proofnetsharp[i])
    else:
        console.log("All formalizations are well-typed!")
