"""Clone mathlib4 and extract all Lean declarations in parallel (per-file tasks).

Output: mathlib_declarations.jsonl (JSONL, one declaration per line).
        Can be parsed back using `DeclarationInfo.model_validate_json()` from `lean_interact.interface`.
"""

import json
import multiprocessing as mp
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from tqdm import tqdm

from lean_interact import LeanREPLConfig
from lean_interact.project import GitProject

MATHLIB_GIT = "https://github.com/leanprover-community/mathlib4.git"
MATHLIB_REV = "v4.24.0-rc1"  # or use a commit hash, branch name, etc.
NUM_PROCS = max((os.cpu_count() or 2) - 1, 1)  # Override with env var NUM_PROCS if desired


def find_lean_files(root: Path) -> list[Path]:
    excluded = {".git", ".lake", "build", "lake-packages"}
    return [p for p in root.rglob("*.lean") if p.name != "lakefile.lean" and not (set(p.parts) & excluded)]


def process_file(rel_path: str, config: LeanREPLConfig) -> list[dict]:
    """Extract declarations from a single .lean file (relative to project)."""
    from lean_interact.interface import CommandResponse, FileCommand, LeanError
    from lean_interact.server import LeanServer

    server = LeanServer(config)
    out: list[dict] = []
    try:
        res = server.run(FileCommand(path=rel_path, declarations=True))
        if isinstance(res, LeanError):
            return out
        assert isinstance(res, CommandResponse)
        for d in res.declarations:
            out.append({"file": rel_path, "decl": d.model_dump_json()})
    except Exception:
        # Skip files that fail to elaborate for any reason
        return out
    return out


def main() -> None:
    # Create the GitProject for mathlib (auto-builds)
    project = GitProject(url=MATHLIB_GIT, rev=MATHLIB_REV)
    config = LeanREPLConfig(project=project, verbose=True)
    project_dir = Path(project.get_directory())
    mathlib_root = project_dir / "Mathlib"
    search_root = mathlib_root if mathlib_root.exists() else project_dir

    print(f"Scanning Lean files under: {search_root}")
    files = find_lean_files(search_root)
    rel_paths = [str(p.relative_to(project_dir)) for p in files]
    print(f"Discovered {len(rel_paths)} .lean files")

    if not rel_paths:
        print("No .lean files found; exiting.")
        return

    num_jobs = max(1, int(os.environ.get("NUM_PROCS", NUM_PROCS)))
    print(f"Starting {num_jobs} workers over {len(rel_paths)} files…")

    # Simple tqdm progress that updates as each file finishes
    results: list[list[dict]] = []
    with tqdm(total=len(rel_paths), desc="Processing files", unit="file") as pbar:
        with ProcessPoolExecutor(max_workers=num_jobs, mp_context=mp.get_context("spawn")) as executor:
            futures = [executor.submit(process_file, rp, config) for rp in rel_paths]
            for fut in as_completed(futures):
                try:
                    results.append(fut.result())
                finally:
                    pbar.update(1)

    # Write output
    out_path = Path.cwd() / "mathlib_declarations.jsonl"
    total = 0
    with out_path.open("w", encoding="utf-8") as f:
        for lst in results:
            total += len(lst)
            for rec in lst:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"Wrote {total} declarations to {out_path}")


if __name__ == "__main__":
    main()
