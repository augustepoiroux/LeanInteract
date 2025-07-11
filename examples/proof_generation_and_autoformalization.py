# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "datasets",
#     "lean-interact",
#     "rich",
#     "tqdm",
#     "jsonlines",
#     "litellm",
#     "diskcache",
#     "vllm",
#     "setuptools",
# ]
# ///
"""
This module provides functions to run a LLM to prove theorems in Lean 4.
"""

import json
import multiprocessing as mp
import os
from collections import Counter
from datetime import datetime
from multiprocessing import Pool
from typing import Literal

import jsonlines
import litellm
from datasets import load_dataset
from litellm import completion
from litellm.caching.caching import Cache, LiteLLMCacheType
from rich.console import Console
from rich.syntax import Syntax
from tqdm import tqdm
from vllm import LLM, SamplingParams

from lean_interact import (
    AutoLeanServer,
    Command,
    LeanREPLConfig,
    TempRequireProject,
)
from lean_interact.interface import LeanError
from lean_interact.utils import (
    clean_last_theorem_string,
    indent_code,
    remove_lean_comments,
)

console = Console()
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
litellm.cache = Cache(type=LiteLLMCacheType.DISK, disk_cache_dir=os.path.join(ROOT_DIR, ".cache/litellm"))

os.environ["TOKENIZERS_PARALLELISM"] = "false"


def load_minif2f_dataset(split: Literal["train", "validation", "test"] = "validation") -> list[dict]:
    """
    Loads the minif2f dataset from Harmonic AI (https://github.com/harmonic-ai/datasets/tree/main/minif2f).
    """
    json_file_link = f"https://raw.githubusercontent.com/harmonic-ai/datasets/main/minif2f/{split}.json"
    dataset = load_dataset("json", data_files=json_file_link, split="train")
    processed_dataset = []
    for item in dataset:
        header = "import Mathlib\nopen BigOperators Real Nat Topology\n"
        processed_dataset.append(
            {
                "id": item["id"],
                "header": header.strip(),
                "formal": clean_last_theorem_string(item["formal"]) + " :=",
                "natural": item["natural"],
                "nl_proof": None,
            },
        )
    return processed_dataset


def load_proofnetsharp_dataset(split: Literal["valid", "test"] = "valid") -> list[dict]:
    """
    Loads the ProofNet# dataset.
    """
    dataset = load_dataset("PAug/ProofNetSharp", split=split)
    # Create header for each theorem
    processed_dataset = []
    for item in dataset:
        processed_dataset.append(
            {
                "id": item["id"],
                "header": item["lean4_src_header"].strip(),
                "formal": clean_last_theorem_string(item["lean4_formalization"]) + " :=",
                "natural": item["nl_statement"],
                "nl_proof": item["nl_proof"],
            }
        )
    return processed_dataset


def check_context_proofs(args: tuple[int, LeanREPLConfig, int, tuple[str, str, list[str]]]) -> tuple[int, str | None]:
    """
    Filter function to check if at least one proof is valid for a given context and declaration to prove.
    """
    idx, repl_config, timeout_per_proof, context_proofs = args
    context_code, formalization_code, proofs = context_proofs

    server = AutoLeanServer(repl_config)
    # using the cache accelerates the verification process by at least one order of magnitude
    # it also drastically reduces the memory usage
    context_res = server.run(Command(cmd=context_code), add_to_session_cache=True)
    assert not isinstance(context_res, LeanError)
    context_env = context_res.env

    for proof in proofs:
        try:
            lean_output = server.run(
                Command(cmd=formalization_code + proof, env=context_env), timeout=timeout_per_proof
            )
            if not isinstance(lean_output, LeanError) and lean_output.lean_code_is_valid(allow_sorry=False):
                return idx, proof
        except (TimeoutError, ConnectionAbortedError, json.JSONDecodeError):
            pass

    return idx, None


def check_proofs(
    context_proofs_list: list[tuple[str, str, list[str]]],
    repl_config: LeanREPLConfig,
    verbose: bool = False,
    nb_process: int | None = None,
    timeout: int = 120,
    timeout_per_proof: int = 60,
) -> list[str | None]:
    """Per context, check if at least one proof is valid.

    Args:
        context_proofs: List of (`context_code`, `formalization_code`, `proofs_list`) tuples. `formalization_code` must end by `:=`.
        verbose: Whether to print additional information during the verification process.
        nb_process: Number of processes to use for the verification. If None, the number of processes is set to the number of CPUs.
        timeout: Timeout in seconds per element in the list. Sometimes, even with timeout per proof, the verification process can get stuck on a single element.
            This parameter ensures that the verification process will finish in finite time.
        timeout_per_proof: Timeout in seconds per proof. This is used to avoid getting stuck on a single proof, but will not interrupt the overall verification process.
        lean_version: Version of Lean to use for the verification.
    """
    assert all([formalization_code.endswith(":=") for _, formalization_code, _ in context_proofs_list])

    # heuristic: sort the contexts by the total length of the proofs to better distribute the work among the processes
    idx_context_proofs = list(enumerate(context_proofs_list))
    idx_context_proofs = sorted(idx_context_proofs, key=lambda x: sum([len(proof) for proof in x[1][2]]), reverse=True)

    res: list[str | None] = [None for _ in context_proofs_list]
    with Pool(nb_process, maxtasksperchild=1) as p:
        iterator = p.imap_unordered(
            check_context_proofs,
            [(idx, repl_config, timeout_per_proof, context_proofs) for idx, context_proofs in idx_context_proofs],
            chunksize=1,
        )
        pbar = tqdm(total=len(context_proofs_list), desc="Checking proofs", disable=not verbose)
        for i, _ in enumerate(idx_context_proofs):
            try:
                idx, proofs_result = iterator.next(timeout)
                res[idx] = proofs_result
                pbar.update(1)
            except mp.TimeoutError:
                console.log(
                    f"Timeout during proof verification. {len(context_proofs_list) - i} elements from the list have been left unchecked."
                )
                p.terminate()
                p.join()
                break

    return res


def generate(prompts: list[str], gen_config: dict) -> list[list[str]]:
    """
    Generate proofs using litellm.

    Args:
        prompts: List of prompts to generate proofs for.
        gen_config: Generation parameters passed to litellm.

    Returns:
        List of lists of generated proofs, one list per prompt.
    """
    if gen_config["custom_llm_provider"] == "vllm":
        # Litellm vLLM local backend does not handle n > 1 generations properly,
        # so we fall back to calling vLLM directly
        sampling_params = SamplingParams(
            temperature=gen_config["temperature"],
            top_p=gen_config["top_p"],
            n=gen_config["n"],
            max_tokens=gen_config["max_tokens"],
            stop=gen_config["stop"],
        )
        llm = LLM(model=gen_config["model"], quantization="fp8", swap_space=24, max_num_seqs=96)
        raw_generated_outputs = llm.generate(prompts, sampling_params, use_tqdm=True)
        return [[o.text for o in output.outputs] for output in raw_generated_outputs]  # type: ignore

    else:
        all_proofs = []
        for prompt in tqdm(prompts, desc=f"Generating proofs with {gen_config['model']}"):
            try:
                response = completion(messages=[{"role": "user", "content": prompt}], **gen_config)
                print(response)
                all_proofs.append([choice.message.content for choice in response.choices])  # type: ignore
            except Exception as e:
                console.log(f"Error during generation: {e}")
                all_proofs.append([])
        return all_proofs


def run_proof_generation_pipeline(
    dataset_name: str,
    split: str,
    use_nl_proof_hint: bool,
    gen_config: dict,
    lean_version: str,
    verbose: bool = True,
):
    """
    Run the complete proof generation and checking pipeline.

    Args:
        dataset_name: Name of the dataset (`minif2f` or `proofnetsharp`).
        split: Split of the dataset.
        use_nl_proof_hint: Whether to use natural language proof to guide proof generation. This task is also known as "proof autoformalization".
        model: Model to use for generation.
        nb_proof_attempts: Number of proof attempts to generate per theorem.
        lean_version: Version of Lean to use.
        verbose: Whether to print additional information.
    """
    model = gen_config["model"]

    # 1. Prepare the dataset
    console.print(f"[bold]Preparing {dataset_name} dataset ({split} split)[/bold]")
    if dataset_name == "minif2f":
        dataset = load_minif2f_dataset(split)  # type: ignore
    elif dataset_name == "proofnetsharp":
        dataset = load_proofnetsharp_dataset(split)  # type: ignore
    else:
        raise ValueError(f"Unknown dataset: {dataset_name}")
    console.print(f"Loaded {len(dataset)} theorems")

    # 2. Create prompts
    prompts = []
    theorem_ids = []
    for i, theorem_data in enumerate(dataset):
        prompt = (
            f"Complete the following Lean 4 code:\n\n```lean4\n{theorem_data['header']}\n\n{theorem_data['formal']} by"
        )
        if use_nl_proof_hint and theorem_data["nl_proof"] is not None:
            prompt += "\n" + indent_code(f"/-\n{theorem_data['nl_proof']}\n-/")
        prompts.append(prompt)
        theorem_ids.append(i)

    console.print(f"Created {len(prompts)} prompts")

    # 3. Generate proofs
    outputs = generate(prompts, gen_config)

    # 4. Process outputs
    context_proofs_list = []
    for output, theorem_id in zip(outputs, theorem_ids):
        theorem_data = dataset[theorem_id]

        # Format generated proofs
        proofs = [remove_lean_comments(proof) for proof in output]  # removing comments as they sometimes cause issues
        proofs = [f"by\n{proof}" for proof in proofs]

        # Sort the proofs by their frequency and length while keeping only unique proofs
        proofs = sorted(proofs, key=len)
        proofs_freq = Counter(proofs)
        proofs = list(proofs_freq.keys())

        context_proofs_list.append((theorem_data["header"], theorem_data["formal"], proofs))

    # 5. Check proofs
    console.print(f"[bold]Checking proofs using Lean {lean_version}[/bold]")
    repl_config = LeanREPLConfig(project=TempRequireProject(lean_version=lean_version, require="mathlib"))
    proof_results = check_proofs(context_proofs_list, repl_config, verbose=verbose)

    # 6. Prepare results
    results = {}
    for theorem_id, proof, (_, _, proof_attempts) in zip(theorem_ids, proof_results, context_proofs_list):
        results[theorem_id] = {
            "id": theorem_id,
            "header": dataset[theorem_id]["header"],
            "formal": dataset[theorem_id]["formal"],
            "proof": proof,
            "success": proof is not None,
            "proof_attempts": proof_attempts,
        }

    # 7. Save results
    os.makedirs(os.path.join(ROOT_DIR, "results"), exist_ok=True)
    result_file = os.path.join(
        ROOT_DIR,
        "results",
        f"{dataset_name}_{split}_{model.split('/')[-1].replace('-', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl",
    )
    with jsonlines.open(result_file, "w") as writer:
        for theorem_id, result in results.items():
            writer.write(result)

    # 8. Display summary
    nb_theorems = len(results)
    nb_proven = sum(1 for result in results.values() if result["success"])
    console.print()
    console.rule("[bold]Results Summary[/bold]")
    console.print(f"Dataset: [bold]{dataset_name} ({split})[/bold]")
    console.print(f"Model: [bold]{model}[/bold]")
    console.print(f"Proven theorems: {nb_proven}/{nb_theorems} ({nb_proven / nb_theorems:.2%})")
    console.print(f"Results saved to: {result_file}")

    # 9. Sanity checks of the generated proofs
    console.print()
    console.rule("[bold]Successful generated proofs[/bold]")
    for theorem_id, result in results.items():
        if result["success"]:
            console.print(f"[bold]Theorem {theorem_id}[/bold]")
            console.print(Syntax(result["header"] + "\n" + result["formal"] + " " + result["proof"], "lean4"))
            if input("Continue? (y/n)") == "n":
                break


def default_gpt4o_config() -> dict:
    return {
        "model": "gpt-4o",
        "temperature": 1.0,
        "max_tokens": 1024,
        "n": 32,
        "top_p": 0.95,
        "stop": ["```"],
        "caching": True,
    }


def default_deepseekprover1_5() -> dict:
    return {
        "model": "deepseek-ai/DeepSeek-Prover-V1.5-RL",
        "custom_llm_provider": "vllm",
        "temperature": 1.0,
        "max_tokens": 1024,
        "n": 32,
        "top_p": 0.95,
        "stop": ["```"],
        "caching": True,
    }


def default_goedelprover() -> dict:
    return {
        "model": "Goedel-LM/Goedel-Prover-SFT",
        "custom_llm_provider": "vllm",
        "temperature": 1.0,
        "max_tokens": 1024,
        "n": 32,
        "top_p": 0.95,
        "stop": ["```"],
        "caching": True,
    }


if __name__ == "__main__":
    ## For DeepSeek Prover V1.5 and Goedel Prover, make sure to run this script on a GPU with at least 24GB of VRAM.

    gen_config = default_goedelprover()

    # MiniF2F benchmark
    run_proof_generation_pipeline(
        dataset_name="minif2f",
        split="validation",
        use_nl_proof_hint=False,
        gen_config=gen_config,
        lean_version="v4.8.0",
        verbose=True,
    )

    # ProofNet# benchmark
    run_proof_generation_pipeline(
        dataset_name="proofnetsharp",
        split="valid",
        use_nl_proof_hint=False,  # Set to True for proof autoformalization (only available for ProofNet#)
        gen_config=gen_config,
        lean_version="v4.8.0",
        verbose=True,
    )
