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
This module provides functions to type-check Lean formalizations
using sequential and optimized batch methods.
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


def type_check_sequential_optimized(dataset: list[dict[str, Any]], repl_config: LeanREPLConfig) -> list[bool]:
    """
    Optimized type-checking by batching formalizations with a common context.

    Args:
        dataset: A list of dictionaries with keys 'lean4_src_header' and 'lean4_formalization'.
        repl_config: Configuration for the Lean REPL.

    Returns:
        A list of booleans indicating if each formalization is valid.
    """
    # Group by common src header
    formalizations_idx = list(enumerate(dataset))
    formalizations_grouped: dict[str, list] = {}
    for idx, row in formalizations_idx:
        header = row["lean4_src_header"]
        formalizations_grouped.setdefault(header, []).append((idx, row["lean4_formalization"]))

    def type_check_group(src_header: str, group: list) -> list[int]:
        server = AutoLeanServer(repl_config)
        context_res = server.run(Command(cmd=src_header), add_to_session_cache=True)
        if not isinstance(context_res, CommandResponse):
            console.log(f"Error while loading context for header '{src_header}': {context_res}")
            return []
        context_env = context_res.env
        valid_indices = []
        for idx, formalization in group:
            try:
                server_output = server.run(
                    Command(cmd=formalization + " sorry", env=context_env), timeout=DEFAULT_TIMEOUT
                )
                if isinstance(server_output, CommandResponse) and server_output.lean_code_is_valid():
                    valid_indices.append(idx)
            except (TimeoutError, ConnectionAbortedError, json.JSONDecodeError) as e:
                console.log(f"Error in group with header '{src_header}': {e}")
        return valid_indices

    res: list[bool] = [False for _ in dataset]
    for idx, group in enumerate(tqdm(formalizations_grouped.items())):
        src_header, group = group
        valid_indices = type_check_group(src_header, group)
        for idx in valid_indices:
            res[idx] = True
    return res


if __name__ == "__main__":
    proofnetsharp = load_dataset("PAug/ProofNetSharp", split="valid")
    config = LeanREPLConfig(project=TempRequireProject(lean_version="v4.16.0-rc2", require="mathlib"), verbose=True)

    # type_check_results = type_check_sequential(proofnetsharp, config)
    type_check_results = type_check_sequential_optimized(proofnetsharp, config)

    assert len(type_check_results) == len(proofnetsharp)

    if any(not well_typed for well_typed in type_check_results):
        console.log("Failures:")
        for i, well_typed in enumerate(type_check_results):
            if not well_typed:
                console.log(proofnetsharp[i])
    else:
        console.log("All formalizations are well-typed!")
