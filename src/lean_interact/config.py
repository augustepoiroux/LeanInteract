import hashlib
import shutil
import subprocess
from dataclasses import dataclass
from os import PathLike
from pathlib import Path
from typing import Callable, Literal

from filelock import FileLock
from packaging.version import parse

from lean_interact.utils import (
    DEFAULT_CACHE_DIR,
    DEFAULT_REPL_GIT_URL,
    DEFAULT_REPL_VERSION,
    _GitUtilities,
    get_project_lean_version,
    logger,
)


@dataclass(frozen=True)
class LeanRequire:
    """Lean project dependency specification for lakefile.lean files."""

    name: str
    """The name of the dependency package."""

    git: str
    """The git URL of the dependency repository."""

    rev: str | None = None
    """The specific git revision (tag, branch, or commit hash) to use. If None, uses the default branch."""

    def __hash__(self):
        return hash((self.name, self.git, self.rev))


@dataclass(frozen=True)
class BaseProject:
    """Base class for Lean projects"""

    def _get_directory(self, cache_dir: str | PathLike, lean_version: str | None = None) -> Path:
        """Get the project directory."""
        raise NotImplementedError("Subclasses must implement this method")

    def _instantiate(
        self, cache_dir: str | PathLike, lean_version: str, lake_path: str | PathLike, verbose: bool = True
    ) -> None:
        """Instantiate the project."""
        raise NotImplementedError("Subclasses must implement this method")

    def _build_project(self, project_dir: Path, lake_path: str | PathLike, verbose: bool, update: bool = False) -> None:
        """Build the Lean project using lake."""
        stdout = None if verbose else subprocess.DEVNULL
        stderr = None if verbose else subprocess.DEVNULL
        try:
            # Run lake update if requested
            if update:
                subprocess.run([str(lake_path), "update"], cwd=project_dir, check=True, stdout=stdout, stderr=stderr)
            
            # Try to get cache first (non-fatal if it fails)
            cache_result = subprocess.run(
                [str(lake_path), "exe", "cache", "get"], cwd=project_dir, check=False, stdout=stdout, stderr=stderr
            )
            if cache_result.returncode != 0 and verbose:
                logger.info("Getting 'error: unknown executable cache' is expected if the project doesn't depend on Mathlib")

            # Build the project (this must succeed)
            subprocess.run([str(lake_path), "build"], cwd=project_dir, check=True, stdout=stdout, stderr=stderr)
            logger.debug("Successfully built project at %s", project_dir)

        except subprocess.CalledProcessError as e:
            logger.error("Failed to build the project: %s", e)
            raise


@dataclass(frozen=True)
class LocalProject(BaseProject):
    """Configuration for using an existing local Lean project directory."""

    directory: str | PathLike
    """Path to the local Lean project directory."""

    build: bool = True
    """Whether to build the project after instantiation. Set to False to skip building."""

    def _get_directory(self, cache_dir: str | PathLike, lean_version: str | None = None) -> Path:
        """Get the project directory."""
        return Path(self.directory)

    def _instantiate(
        self, cache_dir: str | PathLike, lean_version: str | None, lake_path: str | PathLike, verbose: bool = True
    ):
        """Instantiate the local project."""
        if not self.build:
            return

        directory = Path(self.directory)
        with FileLock(f"{directory}.lock"):
            self._build_project(directory, lake_path, verbose)


@dataclass(frozen=True)
class GitProject(BaseProject):
    """Configuration for using an online git repository containing a Lean project."""

    url: str
    """The git URL of the repository to clone."""

    rev: str | None = None
    """The specific git revision (tag, branch, or commit hash) to checkout. If None, uses the default branch."""

    force_pull: bool = False
    """Whether to force pull the latest changes from the remote repository, overwriting local changes."""

    def _get_directory(self, cache_dir: str | PathLike, lean_version: str | None = None) -> Path:
        cache_dir = Path(cache_dir)
        repo_parts = self.url.split("/")
        if len(repo_parts) >= 2:
            owner = repo_parts[-2]
            repo = repo_parts[-1].replace(".git", "")
            return cache_dir / "git_projects" / owner / repo / (self.rev or "latest")
        else:
            # Fallback for malformed URLs
            repo_name = self.url.replace(".git", "").split("/")[-1]
            return cache_dir / "git_projects" / repo_name / (self.rev or "latest")

    def _instantiate(
        self, cache_dir: str | PathLike, lean_version: str | None, lake_path: str | PathLike, verbose: bool = True
    ):
        """Instantiate the git project."""
        project_dir = self._get_directory(cache_dir, lean_version)

        with FileLock(f"{project_dir}.lock"):
            try:
                if project_dir.exists():
                    self._update_existing_repo(project_dir, verbose)
                else:
                    self._clone_new_repo(project_dir, verbose)
                self._build_project(project_dir, lake_path, verbose)
            except Exception as e:
                logger.error("Failed to instantiate git project at %s: %s", project_dir, e)
                raise

    def _update_existing_repo(self, project_dir: Path, verbose: bool) -> None:
        """Update an existing git repository."""
        git_utils = _GitUtilities(project_dir)

        # Strategy: Only make network calls when absolutely necessary to avoid rate limiting
        network_calls_made = False

        # Handle force pull first if requested to ensure we have latest branches
        if self.force_pull:
            self._force_update_repo(git_utils, verbose)
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

    def _force_update_repo(self, git_utils: _GitUtilities, verbose: bool) -> None:
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

    def _clone_new_repo(self, project_dir: Path, verbose: bool) -> None:
        """Clone a new git repository."""
        from git import Repo

        try:
            Repo.clone_from(self.url, project_dir)
            logger.debug("Successfully cloned repository from %s", self.url)

            git_utils = _GitUtilities(project_dir)

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


@dataclass(frozen=True)
class BaseTempProject(BaseProject):
    """Base class for temporary Lean projects"""

    def _get_directory(self, cache_dir: str | PathLike, lean_version: str | None = None) -> Path:
        if lean_version is None:
            raise ValueError("`lean_version` cannot be `None`")
        cache_dir = Path(cache_dir)
        # create a unique hash to allow for caching
        hash_content = self._get_hash_content(lean_version)
        tmp_project_dir = cache_dir / "tmp_projects" / lean_version / hash_content
        tmp_project_dir.mkdir(parents=True, exist_ok=True)
        return tmp_project_dir

    def _instantiate(
        self, cache_dir: str | PathLike, lean_version: str, lake_path: str | PathLike, verbose: bool = True
    ):
        """Instantiate the temporary project."""
        stdout = None if verbose else subprocess.DEVNULL
        stderr = None if verbose else subprocess.DEVNULL

        tmp_project_dir = self._get_directory(cache_dir, lean_version)

        # Lock the temporary project directory during setup
        with FileLock(f"{tmp_project_dir}.lock"):
            # check if the Lean project already exists
            if not (tmp_project_dir / "lake-manifest.json").exists():
                # clean the content of the folder in case of a previous aborted build
                shutil.rmtree(tmp_project_dir, ignore_errors=True)
                tmp_project_dir.mkdir(parents=True, exist_ok=True)

                # initialize the Lean project
                cmd_init = [str(lake_path), f"+{lean_version}", "init", "dummy", "exe.lean"]
                if lean_version.startswith("v4") and int(lean_version.split(".")[1]) <= 7:
                    cmd_init = [str(lake_path), f"+{lean_version}", "init", "dummy", "exe"]

                try:
                    subprocess.run(cmd_init, cwd=tmp_project_dir, check=True, stdout=stdout, stderr=stderr)
                except subprocess.CalledProcessError as e:
                    logger.error("Failed to initialize Lean project: %s", e)
                    raise

                # Create or modify the lakefile
                self._modify_lakefile(tmp_project_dir, lean_version)

                logger.info("Preparing Lean environment with dependencies (may take a while the first time)...")

                # Use the inherited _build_project method with update=True
                try:
                    self._build_project(tmp_project_dir, lake_path, verbose, update=True)
                except subprocess.CalledProcessError as e:
                    logger.error("Failed during Lean project setup: %s", e)
                    # delete the project directory to avoid conflicts
                    shutil.rmtree(tmp_project_dir, ignore_errors=True)
                    raise

    def _get_hash_content(self, lean_version: str) -> str:
        """Return a unique hash for the project content."""
        raise NotImplementedError("Subclasses must implement this method")

    def _modify_lakefile(self, project_dir: str | PathLike, lean_version: str) -> None:
        """Modify the lakefile according to project needs."""
        raise NotImplementedError("Subclasses must implement this method")


@dataclass(frozen=True)
class TemporaryProject(BaseTempProject):
    """Configuration for creating a temporary Lean project with custom lakefile content."""

    content: str
    """The content to write to the lakefile (either lakefile.lean or lakefile.toml format)."""

    lakefile_type: Literal["lean", "toml"] = "lean"
    """The type of lakefile to create. Either 'lean' for lakefile.lean or 'toml' for lakefile.toml."""

    def _get_hash_content(self, lean_version: str) -> str:
        """Return a unique hash based on the content."""
        return hashlib.sha256(self.content.encode()).hexdigest()

    def _modify_lakefile(self, project_dir: str | PathLike, lean_version: str) -> None:
        """Write the content to the lakefile."""
        project_dir = Path(project_dir)
        filename = "lakefile.lean" if self.lakefile_type == "lean" else "lakefile.toml"
        with (project_dir / filename).open("w", encoding="utf-8") as f:
            f.write(self.content)


@dataclass(frozen=True)
class TempRequireProject(BaseTempProject):
    """
    Configuration for setting up a temporary project with specific dependencies.

    As Mathlib is a common dependency, you can just set `require="mathlib"` and a compatible
    version of mathlib will be used. This feature has been developed mostly to be able to run
    benchmarks using Mathlib as a dependency (such as ProofNet# or MiniF2F) without having
    to manually set up a Lean project.
    """

    require: Literal["mathlib"] | LeanRequire | list[LeanRequire | Literal["mathlib"]]
    """
    The dependencies to include in the project. Can be:
    - "mathlib" for automatic Mathlib dependency matching the Lean version
    - A single LeanRequire object for a custom dependency
    - A list of dependencies (mix of "mathlib" and LeanRequire objects)
    """

    def _normalize_require(self, lean_version: str) -> list[LeanRequire]:
        """Normalize the require field to always be a list."""
        require = self.require
        if not isinstance(require, list):
            require = [require]

        normalized_require: list[LeanRequire] = []
        for req in require:
            if req == "mathlib":
                normalized_require.append(
                    LeanRequire("mathlib", "https://github.com/leanprover-community/mathlib4.git", lean_version)
                )
            elif isinstance(req, LeanRequire):
                normalized_require.append(req)
            else:
                raise ValueError(f"Invalid requirement type: {type(req)}")

        return sorted(normalized_require, key=lambda x: x.name)

    def _get_hash_content(self, lean_version: str) -> str:
        """Return a unique hash based on dependencies."""
        require = self._normalize_require(lean_version)
        return hashlib.sha256(str(require).encode()).hexdigest()

    def _modify_lakefile(self, project_dir: str | PathLike, lean_version: str) -> None:
        """Add requirements to the lakefile."""
        project_dir = Path(project_dir)
        require = self._normalize_require(lean_version)
        with (project_dir / "lakefile.lean").open("a", encoding="utf-8") as f:
            for req in require:
                f.write(f'\n\nrequire {req.name} from git\n  "{req.git}"' + (f' @ "{req.rev}"' if req.rev else ""))


class LeanREPLConfig:
    def __init__(
        self,
        lean_version: str | None = None,
        project: BaseProject | None = None,
        repl_rev: str = DEFAULT_REPL_VERSION,
        repl_git: str = DEFAULT_REPL_GIT_URL,
        force_pull_repl: bool = False,
        cache_dir: str | PathLike = DEFAULT_CACHE_DIR,
        local_repl_path: str | PathLike | None = None,
        build_repl: bool = True,
        lake_path: str | PathLike = "lake",
        memory_hard_limit_mb: int | None = None,
        verbose: bool = False,
    ):
        """
        Initialize the Lean REPL configuration.

        Args:
            lean_version:
                The Lean version you want to use.
                Default is `None`, which means the latest version compatible with the project will be selected.
            project:
                The project you want to use. There are 5 options:
                - `None`: The REPL sessions will only depend on Lean and its standard library.
                - `LocalProject`: An existing local Lean project.
                - `GitProject`: A git repository with a Lean project that will be cloned.
                - `TemporaryProject`: A temporary Lean project with a custom lakefile that will be created.
                - `TempRequireProject`: A temporary Lean project with dependencies that will be created.
            repl_rev:
                The REPL version / git revision you want to use. It is not recommended to change this value unless you know what you are doing.
                It will first attempt to checkout `{repl_rev}_lean-toolchain-{lean_version}`, and fallback to `{repl_rev}` if it fails.
                Note: Ignored when `local_repl_path` is provided.
            repl_git:
                The git repository of the Lean REPL. It is not recommended to change this value unless you know what you are doing.
                Note: Ignored when `local_repl_path` is provided.
            force_pull_repl:
                If True, always pull the latest changes from the REPL git repository before checking out the revision.
                By default, it is `False` to limit hitting GitHub API rate limits.
            cache_dir:
                The directory where the Lean REPL and temporary Lean projects with dependencies will be cached.
                Default is inside the package directory.
            local_repl_path:
                A local path to the Lean REPL. This is useful if you want to use a local copy of the REPL.
                When provided, the REPL will not be downloaded from the git repository.
                This is particularly useful during REPL development.
            build_repl:
                Whether to build the local REPL before running it. This option is ignored when `local_repl_path` is not provided.
            lake_path:
                The path to the `lake` executable. This is the Lean 4 build system.
            memory_hard_limit_mb:
                The maximum memory usage in MB for the Lean server. Setting this value too low may lead to more command processing failures.
                Only available on Linux platforms.
                Default is `None`, which means no limit.
            verbose:
                Whether to print additional information during the setup process.
        """
        # Initialize basic configuration
        if lean_version:
            lean_version = lean_version.removeprefix("leanprover/lean4:")
            if not lean_version.startswith("v4"):
                raise ValueError("Unable to parse Lean version format!")
        self.lean_version = lean_version
        self.project = project
        self.repl_git = repl_git
        self.repl_rev = repl_rev
        self.force_pull_repl = force_pull_repl
        self.cache_dir = Path(cache_dir)
        self.local_repl_path = Path(local_repl_path) if local_repl_path else None
        self.build_repl = build_repl
        self.memory_hard_limit_mb = memory_hard_limit_mb
        self.lake_path = Path(lake_path)
        self.verbose = verbose
        self._timeout_lock = 300

        # Configure output streams based on verbosity
        self._stdout = None if self.verbose else subprocess.DEVNULL
        self._stderr = None if self.verbose else subprocess.DEVNULL

        # Set up repository information for Git-based setup
        if not self.local_repl_path:
            repo_parts = self.repl_git.split("/")
            if len(repo_parts) >= 2:
                owner = repo_parts[-2]
                repo = repo_parts[-1].replace(".git", "")
                self.repo_name = Path(owner) / repo
            else:
                self.repo_name = Path(self.repl_git.replace(".git", ""))
            self.cache_clean_repl_dir = self.cache_dir / self.repo_name / "repl_clean_copy"

        # Check if the specified lake executable is available
        if shutil.which(str(self.lake_path)) is None:
            raise RuntimeError(
                f"Lean 4 build system (`{self.lake_path}`) is not installed or not found in PATH. "
                "You can try to run `install-lean` or find installation instructions here: https://leanprover-community.github.io/get_started.html"
            )

        # If the project is not temporary, we first set up the project to infer the Lean version.
        if isinstance(self.project, (LocalProject, GitProject)):
            self.project._instantiate(
                cache_dir=self.cache_dir, lean_version=self.lean_version, lake_path=self.lake_path, verbose=self.verbose
            )
            project_lean_version = get_project_lean_version(self.project._get_directory(self.cache_dir))
            assert project_lean_version is not None, (
                f"Could not determine Lean version for project at {self.project._get_directory(self.cache_dir)}"
            )
            if self.lean_version is not None:
                assert project_lean_version == self.lean_version, (
                    f"Project Lean version `{project_lean_version}` does not match the requested Lean version `{self.lean_version}`."
                )
            self.lean_version = project_lean_version
            self._working_dir = self.project._get_directory(cache_dir=self.cache_dir, lean_version=self.lean_version)

        self._setup_repl()

        assert isinstance(self.lean_version, str)

        if self.project is None:
            self._working_dir = self._cache_repl_dir
        elif not isinstance(self.project, (LocalProject, GitProject)):
            self.project._instantiate(
                cache_dir=self.cache_dir,
                lean_version=self.lean_version,
                lake_path=self.lake_path,
                verbose=self.verbose,
            )
            self._working_dir = self.project._get_directory(cache_dir=self.cache_dir, lean_version=self.lean_version)

    def _setup_repl(self) -> None:
        """Set up the REPL either from a local path or from a Git repository."""
        if self.local_repl_path:
            self._prepare_local_repl()
            if self.build_repl:
                self._build_repl()
        else:
            self._prepare_git_repl()
            self._build_repl()

    def _prepare_local_repl(self) -> None:
        """Prepare a local REPL."""
        assert self.local_repl_path is not None

        if not self.local_repl_path.exists():
            raise ValueError(f"Local REPL path '{self.local_repl_path}' does not exist")

        # Get the Lean version from the local REPL
        local_lean_version = get_project_lean_version(self.local_repl_path)
        if not local_lean_version:
            logger.warning("Could not determine Lean version from local REPL at '%s'", self.local_repl_path)
        else:
            # If lean_version is specified, confirm compatibility
            if self.lean_version is not None and self.lean_version != local_lean_version:
                logger.warning(
                    "Requested Lean version '%s' does not match version in local REPL '%s'.",
                    self.lean_version,
                    local_lean_version,
                )

        if self.lean_version is None:
            self.lean_version = local_lean_version

        # Set the working REPL directory to the local path
        self._cache_repl_dir = self.local_repl_path

        if self.verbose:
            logger.info("Using local REPL at %s", self.local_repl_path)

    def _prepare_git_repl(self) -> None:
        """Prepare a Git-based REPL."""
        assert isinstance(self.repl_rev, str)

        def get_tag_name(lean_version: str) -> str:
            return f"{self.repl_rev}_lean-toolchain-{lean_version}"

        # First, ensure we have the clean repository
        with FileLock(f"{self.cache_clean_repl_dir}.lock", timeout=self._timeout_lock):
            # Initialize or update the clean repository
            self._setup_clean_repl_repo()
            git_utils = _GitUtilities(self.cache_clean_repl_dir)

            # Handle force pull first if requested to ensure we have latest branches
            if self.force_pull_repl:
                self._force_update_repl(git_utils)

            # Checkout the appropriate revision
            checkout_success = self._checkout_repl_revision(git_utils, get_tag_name)

            # If checkout failed and we haven't done a force update, try pulling and retrying
            if not checkout_success and not self.force_pull_repl:
                checkout_success = self._retry_checkout_after_pull(git_utils, get_tag_name)

            # Determine and validate Lean version
            self._validate_and_set_lean_version(get_tag_name)

            # Set up version-specific REPL directory
            self._setup_version_specific_repl_dir(get_tag_name)

    def _setup_clean_repl_repo(self) -> None:
        """Set up the clean REPL repository."""
        from git import Repo

        if not self.cache_clean_repl_dir.exists():
            self.cache_clean_repl_dir.mkdir(parents=True, exist_ok=True)
            try:
                Repo.clone_from(self.repl_git, self.cache_clean_repl_dir)
                logger.debug("Successfully cloned REPL repository from %s", self.repl_git)
            except Exception as e:
                logger.error("Failed to clone REPL repository from %s: %s", self.repl_git, e)
                raise

    def _force_update_repl(self, git_utils: _GitUtilities) -> None:
        """Perform force update of the REPL repository with fetch and reset."""
        # Fetch the latest changes
        if not git_utils.safe_fetch():
            logger.warning("Failed to fetch during force update")
            return

        logger.debug("Force update: successfully fetched latest changes from remote")

        # Determine target branch for reset
        target_branch = None
        if self.lean_version is not None:
            # If we have a lean version, try to find the corresponding tag first
            target_tag = f"{self.repl_rev}_lean-toolchain-{self.lean_version}"
            # For tags, we don't reset since tags don't change
            if git_utils.safe_checkout(target_tag):
                logger.debug("Force update: checked out target tag %s", target_tag)
                return
            # If tag doesn't exist, fall back to branch logic

        # Check if we're on a branch that has a remote counterpart
        current_branch = git_utils.get_current_branch_name()
        if current_branch and git_utils.remote_ref_exists(f"origin/{current_branch}"):
            target_branch = current_branch
        elif not self.lean_version:
            # If no lean version specified, use current branch or default
            target_branch = current_branch

        # Perform hard reset if we have a valid remote branch
        if target_branch and git_utils.remote_ref_exists(f"origin/{target_branch}"):
            if git_utils.safe_reset_hard(f"origin/{target_branch}"):
                logger.debug("Force updated REPL to match remote branch %s", target_branch)
            else:
                logger.warning("Failed to reset REPL to remote branch %s", target_branch)
        else:
            logger.debug("Force update: fetched all refs, but no matching remote branch for reset")

    def _checkout_repl_revision(self, git_utils: _GitUtilities, get_tag_name: Callable[[str], str]) -> bool:
        """Attempt to checkout the specified REPL revision."""
        checkout_success = False

        if self.lean_version is not None:
            # Try to find a tag with the format `{repl_rev}_lean-toolchain-{lean_version}`
            target_tag = get_tag_name(self.lean_version)
            checkout_success = git_utils.safe_checkout(target_tag)
            if checkout_success:
                logger.debug("Successfully checked out tag: %s", target_tag)
        else:
            checkout_success = git_utils.safe_checkout(self.repl_rev)
            if checkout_success:
                logger.debug("Successfully checked out revision: %s", self.repl_rev)

        return checkout_success

    def _retry_checkout_after_pull(self, git_utils: _GitUtilities, get_tag_name: Callable[[str], str]) -> bool:
        """Retry checkout after pulling latest changes - only if force_pull_repl is False."""
        # Only pull if not already done in force update
        if not self.force_pull_repl:
            if git_utils.safe_pull():
                logger.debug("Pulled latest changes to retry checkout")
            else:
                logger.warning("Failed to pull REPL repository, continuing with current state")

        # Retry checkout with updated repository
        checkout_success = False
        if self.lean_version is not None:
            checkout_success = git_utils.safe_checkout(get_tag_name(self.lean_version))

        # Fall back to base revision if needed
        if not checkout_success:
            if not git_utils.safe_checkout(self.repl_rev):
                raise ValueError(f"Lean REPL version `{self.repl_rev}` is not available.")
            checkout_success = True

        return checkout_success

    def _validate_and_set_lean_version(self, get_tag_name) -> None:
        """Validate and set the Lean version for the REPL."""
        # If we still don't have a lean_version, try to find the latest available
        if self.lean_version is None:
            # We need to temporarily store the repo directory location for the _get_available_lean_versions call
            self._cache_repl_dir = self.cache_clean_repl_dir
            if available_versions := self._get_available_lean_versions():
                # The versions are already sorted semantically, so take the last one
                self.lean_version = available_versions[-1][0]
                git_utils = _GitUtilities(self.cache_clean_repl_dir)
                git_utils.safe_checkout(get_tag_name(self.lean_version))

        # Verify we have a valid lean version
        repl_lean_version = get_project_lean_version(self.cache_clean_repl_dir)
        if not self.lean_version:
            self.lean_version = repl_lean_version
        if not repl_lean_version or self.lean_version != repl_lean_version:
            raise ValueError(
                f"An error occurred while preparing the Lean REPL. The requested Lean version `{self.lean_version}` "
                f"does not match the fetched Lean version in the repository `{repl_lean_version or 'unknown'}`."
                f"Please open an issue on GitHub if you think this is a bug."
            )
        assert isinstance(self.lean_version, str), "Lean version inference failed"

    def _setup_version_specific_repl_dir(self, get_tag_name) -> None:
        """Set up the version-specific REPL directory."""
        # Set up the version-specific REPL directory
        self._cache_repl_dir = self.cache_dir / self.repo_name / f"repl_{get_tag_name(self.lean_version)}"

        # Only update the version-specific REPL checkout if the revision changed since last time
        from git import Repo

        repo = Repo(self.cache_clean_repl_dir)
        clean_commit = repo.head.commit.hexsha
        last_synced_file = self._cache_repl_dir / ".last_synced_commit"

        # Acquire lock before checking and copying to avoid race conditions
        with FileLock(f"{self._cache_repl_dir}.lock", timeout=self._timeout_lock):
            last_synced_commit = self._read_last_synced_commit(last_synced_file)

            if (not self._cache_repl_dir.exists()) or (last_synced_commit != clean_commit):
                self._update_version_specific_cache(clean_commit, last_synced_file)

    def _read_last_synced_commit(self, last_synced_file: Path) -> str | None:
        """Read the last synced commit hash from file."""
        if self._cache_repl_dir.exists() and last_synced_file.exists():
            try:
                with open(last_synced_file, "r") as f:
                    return f.read().strip()
            except Exception as e:
                logger.warning("Could not read last synced commit file: %s", e)
        return None

    def _update_version_specific_cache(self, clean_commit: str, last_synced_file: Path) -> None:
        """Update the version-specific REPL cache directory."""
        # Remove the directory first to avoid stale files
        if self._cache_repl_dir.exists():
            try:
                shutil.rmtree(self._cache_repl_dir)
            except Exception as e:
                logger.error("Failed to remove old REPL cache directory: %s", e)
                raise

        try:
            self._cache_repl_dir.mkdir(parents=True, exist_ok=True)
            shutil.copytree(self.cache_clean_repl_dir, self._cache_repl_dir, dirs_exist_ok=True)
            with open(last_synced_file, "w") as f:
                f.write(clean_commit)
            logger.info("Updated version-specific REPL cache to commit %s", clean_commit)
        except Exception as e:
            logger.error("Failed to update REPL cache: %s", e)
            raise

    def _build_repl(self) -> None:
        """Build the REPL."""
        try:
            subprocess.run(
                [str(self.lake_path), "build"],
                cwd=self._cache_repl_dir,
                check=True,
                stdout=self._stdout,
                stderr=self._stderr,
            )
        except subprocess.CalledProcessError as e:
            logger.error("Failed to build the REPL at %s: %s", self._cache_repl_dir, e)
            raise

    def _get_available_lean_versions(self) -> list[tuple[str, str | None]]:
        """
        Get the available Lean versions for the selected REPL.

        Returns:
            A list of tuples (lean_version, tag_name) for available versions.
            For local REPL path, returns only the detected version with `None` as tag_name.
        """
        # If using local REPL, there's only one version available
        if self.local_repl_path:
            version = get_project_lean_version(self.local_repl_path)
            if version:
                return [(version, None)]
            return []

        # For Git-based REPL, get versions from tags
        from git import Repo

        repo = Repo(self.cache_clean_repl_dir)
        all_tags = [tag for tag in repo.tags if tag.name.startswith(f"{self.repl_rev}_lean-toolchain-")]
        if not all_tags:
            # The tag convention is not used, let's extract the only available version
            version = get_project_lean_version(self._cache_repl_dir)
            if version:
                return [(version, None)]
            return []
        else:
            # Extract versions and sort them semantically
            versions = [(tag.name.split("_lean-toolchain-")[-1], tag.name) for tag in all_tags]

            def version_key(version_tuple):
                v = version_tuple[0]
                if v.startswith("v"):
                    v = v[1:]
                return parse(v)

            return sorted(versions, key=version_key)

    def get_available_lean_versions(self) -> list[str]:
        """
        Get the available Lean versions for the selected REPL.
        """
        return [commit[0] for commit in self._get_available_lean_versions()]

    @property
    def working_dir(self) -> str:
        """Get the working directory for the Lean environment."""
        return str(self._working_dir)

    @property
    def cache_repl_dir(self) -> str:
        """Get the cache directory for the Lean REPL."""
        return str(self._cache_repl_dir)

    def is_setup(self) -> bool:
        """Check if the REPL is set up."""
        return hasattr(self, "_working_dir")
