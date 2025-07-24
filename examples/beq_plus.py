# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "datasets",
#     "lean-interact",
#     "rich",
#     "tqdm",
#     "scikit-learn",
# ]
# ///
"""Module for verifying equivalence of Lean formalizations using BEqL and BEq+ metrics.

Citation:
```bibtex
@misc{poiroux2024improvingautoformalizationusingtype,
    title={Improving Autoformalization using Type Checking},
    author={Auguste Poiroux and Gail Weiss and Viktor Kunčak and Antoine Bosselut},
    year={2024},
    eprint={2406.07222},
    archivePrefix={arXiv},
    primaryClass={cs.CL},
    url={https://arxiv.org/abs/2406.07222},
}
```
"""

import json

from datasets import load_dataset
from rich.console import Console
from rich.syntax import Syntax
from rich.table import Table
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score
from tqdm import tqdm

from lean_interact import AutoLeanServer, Command, LeanREPLConfig
from lean_interact.interface import (
    CommandResponse,
    LeanError,
    Pos,
    message_intersects_code,
)
from lean_interact.project import TempRequireProject
from lean_interact.utils import (
    clean_last_theorem_string,
    indent_code,
    split_conclusion,
)

console = Console()
DEFAULT_TIMEOUT = 60


def extract_exact_proof(lean_output: CommandResponse, proof_start_line: int | None = None) -> str | None:
    # check only the messages intersecting the proof
    start = Pos(line=proof_start_line, column=0) if proof_start_line else None
    for message in lean_output.messages:
        if message_intersects_code(message, start, None):
            if message.severity == "error":
                return None
            if message.severity == "info" and message.data.startswith("Try this:"):
                return message.data.split("Try this:")[1].strip()
    return None


def check_proof_sub(
    server: AutoLeanServer,
    formal_code: str,
    context_env: int,
    formal_2_start_line: int,
    proof: str,
    timeout: int,
    indent_level: int = 2,
) -> str | None:
    """
    Runs Lean code appended with a given proof and checks its validity.

    Args:
        server: Instance of AutoLeanServer.
        formal_code: Concatenated Lean formalizations.
        context_env: Execution environment from the Lean server.
        formal_2_start_line: Starting line number of the second formalization.
        proof: Proof tactic string to run.
        timeout: Timeout in seconds for the Lean server execution.
        indent_level: Indentation level for the proof block.

    Returns:
        The proof string (or an extracted exact proof) if valid; None otherwise.
    """
    prepended = "\nintros\nsymm_saturate\n"
    try:
        lean_output = server.run(
            Command(
                cmd=formal_code + indent_code(prepended + proof, indent_level),
                env=context_env,
            ),
            timeout=timeout,
        )
        if isinstance(lean_output, LeanError):
            return None
        if proof == "sorry":
            if lean_output.lean_code_is_valid(start_pos=Pos(line=formal_2_start_line, column=0)):
                return proof
            return None

        if lean_output.lean_code_is_valid(start_pos=Pos(line=formal_2_start_line, column=0), allow_sorry=False):
            if proof == "exact?":
                return extract_exact_proof(lean_output, proof_start_line=formal_2_start_line)
            return proof
    except TimeoutError:
        pass
    except (ConnectionAbortedError, json.JSONDecodeError) as e:
        console.log(f"Error during proof checking: {e}")
    return None


def beql(
    formalization_1: str,
    formalization_2: str,
    src_header: str,
    repl_config: LeanREPLConfig,
    timeout_per_proof: int,
    verbose: bool = False,
) -> bool:
    """
    Checks equivalence of two formalizations using the BEq_L metric.

    Args:
        formalization_1: First Lean formalization as a string.
        formalization_2: Second Lean formalization as a string.
        src_header: Lean source header.
        repl_config: Configuration for the Lean REPL.
        timeout_per_proof: Timeout for each proof check in seconds.

    Returns:
        True if both directions of the equivalence hold; False otherwise.
    """
    server = AutoLeanServer(config=repl_config)
    context_run = server.run(Command(cmd=src_header), add_to_session_cache=True)
    assert isinstance(context_run, CommandResponse)
    context_env = context_run.env

    base_thm_name = "base_theorem"
    reformulated_thm_name = "reformulated_theorem"

    res = [False, False]
    for i, (base_thm, reform_thm) in enumerate(
        [(formalization_1, formalization_2), (formalization_2, formalization_1)]
    ):
        if verbose:
            console.print(f"=====\nChecking {'1 -> 2' if i == 0 else '2 -> 1'}")
        try:
            formal_1_code = clean_last_theorem_string(base_thm, base_thm_name, add_sorry=True) + "\n\n"
            formal_2_start_line = formal_1_code.count("\n") + 1
            formal_2_code = f"{clean_last_theorem_string(reform_thm, reformulated_thm_name, add_sorry=False)} := by"
        except ValueError:
            if verbose:
                console.print("Invalid theorems encountered, skipping this pair.")
            break

        formal_code = formal_1_code + formal_2_code
        # Preliminary check to ensure the formalization is well-typed.
        if check_proof_sub(server, formal_code, context_env, formal_2_start_line, "sorry", timeout_per_proof) is None:
            if verbose:
                console.print("Ill-typed formalization encountered, skipping this pair.")
            break

        proof_exact = check_proof_sub(
            server, formal_code, context_env, formal_2_start_line, "exact?", timeout_per_proof
        )
        if proof_exact and base_thm_name in proof_exact:
            res[i] = True
            if verbose:
                console.print("Proof exact")
                console.print(Syntax(proof_exact, "lean4"))
        else:
            break

    return res[0] and res[1]


def beq_plus(
    formalization_1: str,
    formalization_2: str,
    src_header: str,
    repl_config: LeanREPLConfig,
    timeout_per_proof: int,
    verbose: bool = False,
) -> bool:
    """
    Checks equivalence of two formalizations using the BEq+ metric.

    Args:
        formalization_1: First Lean formalization as a string.
        formalization_2: Second Lean formalization as a string.
        src_header: Lean source header.
        repl_config: Configuration for the Lean REPL.
        timeout_per_proof: Timeout for each proof check in seconds.

    Returns:
        True if both directions of the equivalence hold; False otherwise.
    """
    server = AutoLeanServer(config=repl_config)
    context_run = server.run(Command(cmd=src_header), add_to_session_cache=True)
    assert isinstance(context_run, CommandResponse)
    context_env = context_run.env

    base_thm_name = "base_theorem"
    reformulated_thm_name = "reformulated_theorem"

    def prove_all(tactics: list[str]) -> str:
        prove_independent = " ; ".join([f"(all_goals try {t})" for t in tactics])
        prove_combined = "all_goals (" + " ; ".join([f"(try {t})" for t in tactics]) + ")"
        return "all_goals intros\nfirst | (" + prove_independent + ") | (" + prove_combined + ")"

    solver_tactics_apply = ["tauto", "simp_all_arith!", "noncomm_ring", "exact?"]
    solver_tactics_have = ["tauto", "simp_all_arith!", "exact? using this"]
    proof_all_apply = prove_all(solver_tactics_apply)
    proof_all_have = prove_all(solver_tactics_have)

    res = [False, False]
    for i, (base_thm, reform_thm) in enumerate(
        [(formalization_1, formalization_2), (formalization_2, formalization_1)]
    ):
        if verbose:
            console.print(f"=====\nChecking {'1 -> 2' if i == 0 else '2 -> 1'}")
        try:
            formal_1_code = clean_last_theorem_string(base_thm, base_thm_name, add_sorry=True) + "\n\n"
            formal_2_start_line = formal_1_code.count("\n") + 1
            formal_2_code = f"{clean_last_theorem_string(reform_thm, reformulated_thm_name, add_sorry=False)} := by"
        except ValueError:
            if verbose:
                console.print("Invalid theorem encountered, skipping this pair.")
            break

        formal_code = formal_1_code + formal_2_code
        if check_proof_sub(server, formal_code, context_env, formal_2_start_line, "sorry", timeout_per_proof) is None:
            if verbose:
                console.print("Ill-typed formalization encountered, skipping this pair.")
            break

        # 1. Use BEqL
        proof_exact = check_proof_sub(
            server, formal_code, context_env, formal_2_start_line, "exact?", timeout_per_proof
        )
        if proof_exact and base_thm_name in proof_exact:
            res[i] = True
            if verbose:
                console.print("Proof exact")
                console.print(Syntax(proof_exact, "lean4"))
            continue

        # 2. try to apply the base theorem directly
        proof_apply = check_proof_sub(
            server,
            formal_code,
            context_env,
            formal_2_start_line,
            f"apply {base_thm_name}\n" + proof_all_apply,
            timeout_per_proof,
        )
        if proof_apply:
            res[i] = True
            if verbose:
                console.print("Proof apply")
                console.print(Syntax(proof_apply, "lean4"))
            continue

        # 3. try to add the conclusion of the base theorem as hypothesis
        # sanity check: if we can prove `reform_thm` using a tactic in `solver_tactics_have` without introducing the hypothesis,
        # then we should skip this `have` step as it may introduce a false positive
        # drawback of `have` strategy: variable names/types must match exactly
        provable_without_have = False
        try:
            res_without_have = server.run(
                Command(cmd=formal_code + proof_all_have, env=context_env), timeout=timeout_per_proof
            )
            if isinstance(res_without_have, CommandResponse):
                provable_without_have = res_without_have.lean_code_is_valid(allow_sorry=False)
        except TimeoutError:
            pass
        except (ConnectionAbortedError, json.JSONDecodeError) as e:
            console.log(f"Error during proof checking: {e}")

        if not provable_without_have:
            idx_conclusion = split_conclusion(formal_1_code)
            if idx_conclusion:
                idx_end_conclusion = formal_1_code.rfind(":=")
                conclusion = formal_1_code[idx_conclusion:idx_end_conclusion].strip()
                have_stmt_proof = (
                    f"have {conclusion} := by\n"
                    + indent_code(f"apply_rules [{base_thm_name}]\n" + proof_all_apply, 2)
                    + "\n"
                )
                proof_have = check_proof_sub(
                    server,
                    formal_code,
                    context_env,
                    formal_2_start_line,
                    have_stmt_proof + proof_all_have,
                    timeout_per_proof,
                )
                if proof_have:
                    res[i] = True
                    if verbose:
                        console.print("Proof have")
                        console.print(Syntax(proof_have, "lean4"))
                    continue

        # 4. try to apply the base theorem with some tolerance on the differences in the conclusion
        for max_step in range(0, 5):
            proof_convert = check_proof_sub(
                server,
                formal_code,
                context_env,
                formal_2_start_line,
                f"convert (config := .unfoldSameFun) {base_thm_name} using {max_step}\n" + proof_all_apply,
                timeout_per_proof,
            )
            if proof_convert:
                res[i] = True
                if verbose:
                    console.print("Proof convert")
                    console.print(Syntax(proof_convert, "lean4"))
                break

        if not res[i]:
            break

    return res[0] and res[1]


def examples_limitations(metric):
    repl_config = LeanREPLConfig(project=TempRequireProject(lean_version="v4.8.0", require="mathlib"), verbose=True)

    src_header = """import Mathlib

open Fintype Group Monoid
open Set Real Ideal Polynomial
open scoped BigOperators"""

    formalization_pairs = [
        (
            "theorem random_name_1 {G : Type*} [Group G] [Fintype G] (h : Fintype.card G % 2 = 0) :\n  ∃ a : G, a ≠ 1 ∧ a = a⁻¹ :=",
            "theorem random_name_2 {G : Type*} [Group G] [Fintype G] (hG2 : Even (card G)) :\n  ∃ (a : G), a ≠ 1 ∧ a = a⁻¹ :=",
        ),
        (
            "theorem sPpp {G : Type*} [Group G] [Fintype G] {p q : ℕ} (hp : Prime p) (hq : Prime q) (hG : card G = p*q) :  IsSimpleGroup G → False :=",
            "theorem sQqq (p q : ℕ) (hp : Nat.Prime p) (hq : Nat.Prime q) (G : Type _) [Group G] [Fintype G] (hG : Fintype.card G = p * q) : ¬ IsSimpleGroup G :=",
        ),
        (
            "theorem sPppp {f : ℝ → ℝ} (hf : ∀ x y, |f x - f y| ≤ |x - y| ^ 2) : ∃ c, f = λ x => c :=",
            "theorem sQqqq (f : ℝ → ℝ) (h : ∀ (t x : ℝ), |f t - f x| ≤ |t - x| ^ 2) (x : ℝ) (y : ℝ) : f x = f y :=",
        ),
        (
            "theorem dummy (n : ℕ) (hn : n % 2 = 1) : 8 ∣ n^2 - 1 :=",
            "theorem dummy {n : ℕ} (hn : Odd n) : 8 ∣ (n^2 - 1) :=",
        ),
        (
            "theorem dumssmy {G : Type*} [Group G] (x : G) : x ^ 2 = 1 ↔ orderOf x = 1 ∨ orderOf x = 2 :=",
            "theorem dumssfmy {G : Type*} [Group G] : ∀ (x : G), orderOf x = 1 ∨ orderOf x = 2 ↔ x ^ 2 = 1 :=",
        ),
        (
            "theorem sP : Infinite {p : Nat.Primes // p ≡ -1 [ZMOD 6]} :=",
            "theorem sQ : Set.Infinite {p : ℕ | Nat.Prime p ∧ p % 6 = 5} :=",
        ),
        (
            "theorem dummy83 : Irreducible (Polynomial.C (12 : ℚ) + Polynomial.C (6 : ℚ) * Polynomial.X + Polynomial.X ^ 3) :=",
            "theorem dummy84 : Irreducible (12 + 6 * X + X ^ 3 : Polynomial ℚ) :=",
        ),
        (
            "theorem dummy90 {p : ℕ} (hp : Nat.Prime p) (n : ℕ) (hn : 0 < n) : Irreducible (Polynomial.C (1 : ℚ) * Polynomial.X ^ n - Polynomial.C (p : ℚ)) :=",
            "theorem dummy91 (p : ℕ) (hp : Prime p) (n : ℕ) (hn : n > 0) : Irreducible (X ^ n - (p : Polynomial ℚ) : Polynomial ℚ) :=",
        ),
        (
            "theorem dummy64 {X X' : Type*} [TopologicalSpace X] [TopologicalSpace X'] (π₁ : X × X' → X) (π₂ : X × X' → X') (h₁ : π₁ = Prod.fst) (h₂ : π₂ = Prod.snd) : IsOpenMap π₁ ∧ IsOpenMap π₂ :=",
            "theorem dummy63 {X X' : Type*} [TopologicalSpace X] [TopologicalSpace X'] : (∀ U : Set (X × X'), IsOpen U → IsOpen (Prod.fst '' U)) ∧ (∀ U : Set (X × X'), IsOpen U → IsOpen (Prod.snd '' U)) :=",
        ),
        (
            "theorem sP {R : Type u_1} [Ring R] (h : ∀ (x : R), x ^ 3 = x) (x : R) (y : R) : x * y = y * x :=",
            "theorem sQ {R : Type*} [Ring R] (h : ∀ x : R, x ^ 3 = x) : Nonempty (CommRing R) :=",
        ),
        (
            "theorem dummy {x : ℝ} (r : ℚ) (hr : r ≠ 0) (hx : Irrational x) : Irrational (r + x) :=",
            "theorem dummy (x : ℝ) (y : ℚ) (hy : y ≠ 0) : ( Irrational x ) -> Irrational ( x + y ) :=",
        ),
    ]

    console.print(f"{metric.__name__} metric on examples:")
    counter_equivalent = 0
    for formalization_1, formalization_2 in formalization_pairs:
        console.print()
        console.rule()
        console.print("Comparing formalizations:")
        console.print(Syntax(formalization_1, "lean4"))
        console.print(Syntax(formalization_2, "lean4"))
        equivalent = metric(
            formalization_1,
            formalization_2,
            src_header,
            repl_config,
            timeout_per_proof=DEFAULT_TIMEOUT,
            verbose=True,
        )
        counter_equivalent += equivalent
        if equivalent:
            console.print("[green]Proved equivalent[/]")
        else:
            console.print("[red]Equivalence not proven[/]")
    console.print()
    console.print(f"Total proved equivalent: {counter_equivalent}/{len(formalization_pairs)}")


def proofnetverif(metric, n_samples=100):
    repl_config = LeanREPLConfig(project=TempRequireProject(lean_version="v4.8.0", require="mathlib"), verbose=True)

    dataset = load_dataset("PAug/ProofNetVerif", split="valid")
    dataset = dataset.shuffle(seed=42).select(range(n_samples))

    metric_results = []
    for example in tqdm(dataset, desc=f"`{metric.__name__}` metric on ProofNetVerif dataset"):
        metric_results.append(
            metric(
                example["lean4_formalization"],
                example["lean4_prediction"],
                example["lean4_src_header"],
                repl_config,
                timeout_per_proof=DEFAULT_TIMEOUT,
                verbose=False,
            )
        )

    # Compute metrics
    y_true = dataset["correct"]
    y_pred = metric_results
    table = Table("Metric", "Value", title=f"`{metric.__name__}` metric results on ProofNetVerif")
    table.add_row("Accuracy", f"{accuracy_score(y_true, y_pred):.2%}")
    table.add_row("Precision", f"{precision_score(y_true, y_pred):.2%}")
    table.add_row("Recall", f"{recall_score(y_true, y_pred):.2%}")
    table.add_row("F1 Score", f"{f1_score(y_true, y_pred):.2%}")
    console.print(table)


if __name__ == "__main__":
    # metric_fun = beql
    metric_fun = beq_plus

    examples_limitations(metric_fun)
    # proofnetverif(metric_fun)

    # To run the metrics faster on a dataset, we recommend using a parallelized version.
    # Be careful with memory usage, as it can quickly become a bottleneck
