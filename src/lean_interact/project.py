"""
**Module:** `lean_interact.project`

This module provides classes for managing Lean projects, including local directories and git repositories.
It supports automatic building and dependency management using `lake`, and can be used to create temporary projects
with specific configurations.
It is useful for setting up Lean environments for development, testing, or running benchmarks without manual setup.
"""

import hashlib
import shutil
import subprocess
from dataclasses import dataclass, field
from os import PathLike
from pathlib import Path
from typing import Literal

from filelock import FileLock

from lean_interact.utils import (
    DEFAULT_CACHE_DIR,
    _GitUtilities,
    check_lake,
    get_project_lean_version,
    logger,
)


@dataclass(frozen=True, kw_only=True)
class BaseProject:
    """Base class for Lean projects"""

    directory: str | PathLike | None

    lake_path: str | PathLike = "lake"
    """The path to the lake executable. Default is "lake", which assumes it is in the system PATH."""

    auto_build: bool = True
    """Whether to automatically build the project after instantiation."""

    def __post_init__(self):
        if self.auto_build:
            self.build()

    def get_directory(self) -> str:
        """Get the directory of the Lean project."""
        if self.directory is None:
            raise ValueError("`directory` must be set")
        return str(Path(self.directory).resolve())

    def get_lean_version(self) -> str:
        """The Lean version used by this project."""
        version = get_project_lean_version(Path(self.get_directory()))
        if version is None:
            raise ValueError("Unable to determine Lean version")
        return version

    def build(self, verbose: bool = True, update: bool = False, _lock: bool = True) -> None:
        """Build the Lean project using lake.
        Args:
            verbose: Whether to print building information to the console.
            update: Whether to run `lake update` before building.
            _lock: (internal parameter) Whether to acquire a file lock (should be False if already locked by caller).
        """
        directory = Path(self.get_directory())
        check_lake(self.lake_path)

        def _do_build():
            stdout = None if verbose else subprocess.DEVNULL
            stderr = None if verbose else subprocess.DEVNULL
            try:
                # Run lake update if requested
                if update:
                    subprocess.run(
                        [str(self.lake_path), "update"], cwd=directory, check=True, stdout=stdout, stderr=stderr
                    )

                # Try to get cache first (non-fatal if it fails)
                cache_result = subprocess.run(
                    [str(self.lake_path), "exe", "cache", "get"],
                    cwd=directory,
                    check=False,
                    stdout=stdout,
                    stderr=stderr,
                )
                if cache_result.returncode != 0 and verbose:
                    logger.info(
                        "Getting 'error: unknown executable cache' is expected if the project doesn't depend on Mathlib"
                    )

                # Build the project (this must succeed)
                subprocess.run([str(self.lake_path), "build"], cwd=directory, check=True, stdout=stdout, stderr=stderr)
                logger.debug("Successfully built project at %s", directory)

            except subprocess.CalledProcessError as e:
                logger.error("Failed to build the project: %s", e)
                raise

        if _lock:
            with FileLock(f"{directory}.lock"):
                _do_build()
        else:
            _do_build()


@dataclass(frozen=True, kw_only=True)
class LocalProject(BaseProject):
    """Configuration for using an existing local Lean project directory.

    Examples:
        ```python
        # Use an existing local project
        project = LocalProject(
            directory="/path/to/my/lean/project",
            auto_build=True  # Build the project automatically
        )

        config = LeanREPLConfig(project=project)
        ```
    """

    directory: str | PathLike
    """Path to the local Lean project directory."""

    def __post_init__(self):
        if self.directory is None:
            raise ValueError("`LocalProject` requires `directory` to be specified")
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class GitProject(BaseProject):
    """Configuration for using an online git repository containing a Lean project.

    Examples:
        ```python
        # Clone and use a Git repository
        project = GitProject(
            url="https://github.com/user/lean-project",
            rev="main",  # Optional: specific branch/tag/commit
            directory="/custom/cache/dir",  # Optional: custom directory
            force_pull=False  # Optional: force update on each use
        )

        config = LeanREPLConfig(project=project)
        ```
    """

    url: str
    """The git URL of the repository to clone."""

    directory: str | PathLike | None = field(default=None)
    """The directory where the git project will be cloned.
    If None, a unique path inside the default LeanInteract cache directory will be used."""

    rev: str | None = None
    """The specific git revision (tag, branch, or commit hash) to checkout. If None, uses the default branch."""

    force_pull: bool = False
    """Whether to force pull the latest changes from the remote repository, overwriting local changes."""

    def __post_init__(self):
        if self.directory is None:
            repo_parts = self.url.split("/")
            if len(repo_parts) >= 2:
                owner = repo_parts[-2]
                repo = repo_parts[-1].replace(".git", "")
                object.__setattr__(
                    self, "directory", DEFAULT_CACHE_DIR / "git_projects" / owner / repo / (self.rev or "latest")
                )
            else:
                # Fallback for malformed URLs
                repo_name = self.url.replace(".git", "").split("/")[-1]
                object.__setattr__(
                    self, "directory", DEFAULT_CACHE_DIR / "git_projects" / repo_name / (self.rev or "latest")
                )

        directory = Path(self.get_directory())
        with FileLock(f"{directory}.lock"):
            try:
                if directory.exists():
                    self._update_existing_repo()
                else:
                    self._clone_new_repo()
                self.build(_lock=False)
            except Exception as e:
                logger.error("Failed to instantiate git project at %s: %s", directory, e)
                raise

    def _update_existing_repo(self) -> None:
        """Update an existing git repository."""
        git_utils = _GitUtilities(self.get_directory())

        # Strategy: Only make network calls when absolutely necessary to avoid rate limiting
        network_calls_made = False

        # Handle force pull first if requested to ensure we have latest branches
        if self.force_pull:
            self._force_update_repo(git_utils)
            network_calls_made = True

        # Checkout the specified revision if provided
        if self.rev:
            # First try to checkout without network calls
            if not git_utils.safe_checkout(self.rev):
                logger.debug("Revision '%s' not found locally, fetching from remote", self.rev)
                if git_utils.safe_fetch():
                    network_calls_made = True
                    if not git_utils.safe_checkout(self.rev):
                        raise ValueError(f"Could not checkout revision '{self.rev}' after fetching")
                else:
                    raise ValueError(f"Could not fetch from remote to get revision '{self.rev}'")
        else:
            # Only pull for non-specific revisions and only if we haven't made network calls yet
            if not network_calls_made:
                if git_utils.safe_pull():
                    network_calls_made = True
                    logger.debug("Pulled latest changes for default branch")
                else:
                    logger.warning("Failed to pull from remote, continuing with current state")

        # Update submodules only if we made other network calls or if explicitly requested
        if network_calls_made or self.force_pull:
            if not git_utils.update_submodules():
                logger.warning("Failed to update submodules")
        else:
            logger.debug("Skipping submodule update to minimize network calls")

    def _force_update_repo(self, git_utils: _GitUtilities) -> None:
        """Perform a force update of the repository with single fetch call."""
        # Single fetch call for force update
        if not git_utils.safe_fetch():
            raise RuntimeError("Failed to fetch from remote during force update")

        logger.debug("Force update: successfully fetched latest changes from remote")

        # Determine target branch for reset
        target_branch = None
        if self.rev and git_utils.branch_exists_locally(self.rev):
            target_branch = self.rev
        elif not self.rev:
            target_branch = git_utils.get_current_branch_name()

        # Perform hard reset if we have a valid remote branch
        if target_branch and git_utils.remote_ref_exists(f"origin/{target_branch}"):
            if git_utils.safe_reset_hard(f"origin/{target_branch}"):
                logger.info("Force updated git project to match remote branch %s", target_branch)
            else:
                logger.warning("Failed to reset to remote branch %s", target_branch)
        else:
            logger.info("Force pull: fetched all refs, but no matching remote branch for reset.")

        if not git_utils.update_submodules():
            logger.warning("Failed to update submodules after force update")

    def _clone_new_repo(self) -> None:
        """Clone a new git repository."""
        from git import Repo

        try:
            Repo.clone_from(self.url, self.get_directory())
            logger.debug("Successfully cloned repository from %s", self.url)

            git_utils = _GitUtilities(self.get_directory())

            # Checkout specific revision if provided
            if self.rev:
                if not git_utils.safe_checkout(self.rev):
                    raise ValueError(f"Could not checkout revision '{self.rev}' after cloning")

            # Initialize and update submodules
            if not git_utils.update_submodules():
                logger.warning("Failed to update submodules after cloning")

        except Exception as e:
            logger.error("Failed to clone repository from %s: %s", self.url, e)
            raise


@dataclass(frozen=True, kw_only=True)
class BaseTempProject(BaseProject):
    """Base class for temporary Lean projects"""

    lean_version: str
    """The Lean version to use for this project."""

    directory: str | PathLike | None = field(default=None)
    """The directory where temporary Lean projects will be cached.
    If None, a unique path inside the default LeanInteract cache directory will be used."""

    verbose: bool = True
    """Whether to print additional information during the setup process."""

    def __post_init__(self):
        if self.directory is None:
            # create a unique hash for caching
            hash_content = self._get_hash_content()
            directory = DEFAULT_CACHE_DIR
            tmp_project_dir = directory / "tmp_projects" / self.lean_version / hash_content
            tmp_project_dir.mkdir(parents=True, exist_ok=True)
            object.__setattr__(self, "directory", tmp_project_dir)
        directory = Path(self.get_directory())

        stdout = None if self.verbose else subprocess.DEVNULL
        stderr = None if self.verbose else subprocess.DEVNULL

        # Lock the temporary project directory during setup
        with FileLock(f"{directory}.lock"):
            # check if the Lean project already exists
            if not (directory / "lake-manifest.json").exists():
                # clean the content of the folder in case of a previous aborted build
                shutil.rmtree(directory, ignore_errors=True)
                directory.mkdir(parents=True, exist_ok=True)

                # initialize the Lean project
                cmd_init = [str(self.lake_path), f"+{self.lean_version}", "init", "dummy", "exe.lean"]
                if self.lean_version.startswith("v4") and int(self.lean_version.split(".")[1]) <= 7:
                    cmd_init = [str(self.lake_path), f"+{self.lean_version}", "init", "dummy", "exe"]

                try:
                    subprocess.run(cmd_init, cwd=directory, check=True, stdout=stdout, stderr=stderr)
                except subprocess.CalledProcessError as e:
                    logger.error("Failed to initialize Lean project: %s", e)
                    raise

                # Create or modify the lakefile
                self._modify_lakefile()

                logger.info("Preparing Lean environment with dependencies (may take a while the first time)...")

                # Use the inherited _build_project method with update=True
                try:
                    self.build(verbose=self.verbose, update=True, _lock=False)
                except subprocess.CalledProcessError as e:
                    logger.error("Failed during Lean project setup: %s", e)
                    # delete the project directory to avoid conflicts
                    shutil.rmtree(directory, ignore_errors=True)
                    raise

    def _get_hash_content(self) -> str:
        """Return a unique hash for the project content."""
        raise NotImplementedError("Subclasses must implement this method")

    def _modify_lakefile(self) -> None:
        """Modify the lakefile according to project needs."""
        raise NotImplementedError("Subclasses must implement this method")


@dataclass(frozen=True, kw_only=True)
class TemporaryProject(BaseTempProject):
    """Configuration for creating a temporary Lean project with custom lakefile content.

    Examples:
        ```python
        # Create a temporary project with custom lakefile
        project = TemporaryProject(
            lean_version="v4.19.0",
            content=\"\"\"
        import Lake
        open Lake DSL

        package "my_temp_project" where
        version := v!"0.1.0"

        require mathlib from git
        "https://github.com/leanprover-community/mathlib4.git" @ "v4.19.0"
        \"\"\",
            lakefile_type="lean"  # or "toml"
        )

        config = LeanREPLConfig(project=project)
        ```
    """

    content: str
    """The content to write to the lakefile (either lakefile.lean or lakefile.toml format)."""

    lakefile_type: Literal["lean", "toml"] = "lean"
    """The type of lakefile to create. Either 'lean' for lakefile.lean or 'toml' for lakefile.toml."""

    def _get_hash_content(self) -> str:
        """Return a unique hash based on the content."""
        return hashlib.sha256(self.content.encode()).hexdigest()

    def _modify_lakefile(self) -> None:
        """Write the content to the lakefile."""
        project_dir = Path(self.get_directory())
        filename = "lakefile.lean" if self.lakefile_type == "lean" else "lakefile.toml"
        with (project_dir / filename).open("w", encoding="utf-8") as f:
            f.write(self.content)


@dataclass(frozen=True)
class LeanRequire:
    """Lean project dependency specification for `lakefile.lean` files."""

    name: str
    """The name of the dependency package."""

    git: str
    """The git URL of the dependency repository."""

    rev: str | None = None
    """The specific git revision (tag, branch, or commit hash) to use. If None, uses the default branch."""

    def __hash__(self):
        return hash((self.name, self.git, self.rev))


@dataclass(frozen=True, kw_only=True)
class TempRequireProject(BaseTempProject):
    """
    Configuration for setting up a temporary project with specific dependencies.

    As Mathlib is a common dependency, you can just set `require="mathlib"` and a compatible
    version of mathlib will be used. This feature has been developed mostly to be able to run
    benchmarks using Mathlib as a dependency (such as ProofNet# or MiniF2F) without having
    to manually set up a Lean project.

    Examples:
        ```python
        # Create a temporary project with Mathlib
        project = TempRequireProject(
            lean_version="v4.19.0",
            require="mathlib"  # Shortcut for Mathlib
        )

        # Or with custom dependencies
        project = TempRequireProject(
            lean_version="v4.19.0",
            require=[
                LeanRequire("mathlib", "https://github.com/leanprover-community/mathlib4.git", "v4.19.0"),
                LeanRequire("my_lib", "https://github.com/user/my-lib.git", "v1.0.0")
            ]
        )

        config = LeanREPLConfig(project=project)
        ```
    """

    require: Literal["mathlib"] | LeanRequire | list[LeanRequire | Literal["mathlib"]]
    """
    The dependencies to include in the project. Can be:

    - "mathlib" for automatic Mathlib dependency matching the Lean version
    - A single LeanRequire object for a custom dependency
    - A list of dependencies (mix of "mathlib" and LeanRequire objects)
    """

    def _normalize_require(self) -> list[LeanRequire]:
        """Normalize the require field to always be a list."""
        require = self.require
        if not isinstance(require, list):
            require = [require]

        normalized_require: list[LeanRequire] = []
        for req in require:
            if req == "mathlib":
                normalized_require.append(
                    LeanRequire("mathlib", "https://github.com/leanprover-community/mathlib4.git", self.lean_version)
                )
            elif isinstance(req, LeanRequire):
                normalized_require.append(req)
            else:
                raise ValueError(f"Invalid requirement type: {type(req)}")

        return sorted(normalized_require, key=lambda x: x.name)

    def _get_hash_content(self) -> str:
        """Return a unique hash based on dependencies."""
        require = self._normalize_require()
        return hashlib.sha256(str(require).encode()).hexdigest()

    def _modify_lakefile(self) -> None:
        """Add requirements to the lakefile."""
        project_dir = Path(self.get_directory())
        require = self._normalize_require()
        with (project_dir / "lakefile.lean").open("a", encoding="utf-8") as f:
            for req in require:
                f.write(f'\n\nrequire {req.name} from git\n  "{req.git}"' + (f' @ "{req.rev}"' if req.rev else ""))
