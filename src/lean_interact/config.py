"""
**Module:** `lean_interact.config`

This module provides the `LeanREPLConfig` class, which is used to configure the Lean REPL (Read-Eval-Print Loop) used
by the Lean servers in `lean_interact.server`.
"""

import shutil
import subprocess
from os import PathLike
from pathlib import Path
from typing import Callable

from filelock import FileLock
from packaging.version import parse

from lean_interact.project import BaseProject
from lean_interact.utils import (
    DEFAULT_CACHE_DIR,
    DEFAULT_REPL_GIT_URL,
    DEFAULT_REPL_VERSION,
    _GitUtilities,
    check_lake,
    get_project_lean_version,
    logger,
    parse_lean_version,
)


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
        enable_incremental_optimization: bool = True,
        enable_parallel_elaboration: bool = True,
        verbose: bool = False,
    ):
        """
        Initialize the Lean REPL configuration.

        Args:
            lean_version:
                The Lean version you want to use. Should only be set when `project` is `None`.
                When `project` is provided, the Lean version will be inferred from the project.
                Default is `None`, which means the latest available version will be selected if `project` is `None`.
            project:
                The project you want to use. Options:
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
                The directory where the Lean REPL will be cached.
                Default is inside the package directory.
            local_repl_path:
                A local path to the Lean REPL. This is useful if you want to use a local copy of the REPL.
                When provided, the REPL will not be downloaded from the git repository.
                This is particularly useful during REPL development.
            build_repl:
                Whether to build the local REPL before running it. This option is ignored when `local_repl_path` is not provided.
            lake_path:
                The path to the lake executable. Default is "lake", which assumes it is in the system PATH.
            memory_hard_limit_mb:
                The maximum memory usage in MB for the Lean server. Setting this value too low may lead to more command processing failures.
                Only available on Linux platforms.
                Default is `None`, which means no limit.
            enable_incremental_optimization:
                Whether to enable incremental optimization for all commands in the Lean REPL. This can significantly speed up processing
                and decrease memory usage of commands by automatically reusing partial computations from previous commands.
                Only available for Lean >= v4.8.0-rc1. Default is `True`.
            enable_parallel_elaboration:
                Whether to enable parallel elaboration in the Lean REPL. This can significantly speed up processing
                of commands, especially in large files. Only available for Lean >= v4.19.0. Default is `True`.
            verbose:
                Whether to print additional information during the setup process.

        Examples:
            ```python
            # Basic configuration with default settings
            config = LeanREPLConfig(verbose=True)

            # Configuration with specific Lean version
            config = LeanREPLConfig(lean_version="v4.19.0", verbose=True)

            # Configuration with memory limits
            config = LeanREPLConfig(memory_hard_limit_mb=2000)

            # Configuration with custom REPL version and repository
            config = LeanREPLConfig(
                repl_rev="v4.21.0-rc3",
                repl_git="https://github.com/leanprover-community/repl"
            )

            # Working with projects
            config = LeanREPLConfig(
                project=LocalProject(directory="/path/to/project"),
                verbose=True
            )
            ```
        """
        if project is not None and lean_version is not None:
            raise ValueError(
                "lean_version should only be set when project is None. When a project is provided, the Lean version is inferred from the project."
            )

        # Initialize basic configuration
        if lean_version:
            lean_version = parse_lean_version(lean_version)
            if lean_version is None:
                raise ValueError(f"Unable to parse Lean version format: `{lean_version}`")
        self.lean_version = lean_version
        self.project = project
        self.repl_git = repl_git
        self.repl_rev = repl_rev
        self.force_pull_repl = force_pull_repl
        self.cache_dir = Path(cache_dir)
        self.local_repl_path = Path(local_repl_path) if local_repl_path else None
        self.build_repl = build_repl
        self.memory_hard_limit_mb = memory_hard_limit_mb
        self.enable_incremental_optimization = enable_incremental_optimization
        self.enable_parallel_elaboration = enable_parallel_elaboration
        self.lake_path = Path(lake_path)
        self.verbose = verbose
        self._timeout_lock = 300

        if self.project is not None:
            self.lean_version = self.project.get_lean_version()
            if self.project.directory is None:
                raise ValueError("Project directory cannot be None")

        self._setup_repl()

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

        repo_parts = self.repl_git.split("/")
        if len(repo_parts) >= 2:
            owner = repo_parts[-2]
            repo = repo_parts[-1].replace(".git", "")
            self.repo_name = Path(owner) / repo
        else:
            self.repo_name = Path(self.repl_git.replace(".git", ""))
        self.cache_clean_repl_dir = self.cache_dir / self.repo_name / "repl_clean_copy"

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
        check_lake(self.lake_path)

        try:
            # Capture build output so failures can be diagnosed
            res = subprocess.run(
                [str(self.lake_path), "build"],
                cwd=self._cache_repl_dir,
                stdout=None if self.verbose else subprocess.PIPE,
                stderr=None if self.verbose else subprocess.PIPE,
                text=True,
            )
        except FileNotFoundError as e:
            raise RuntimeError(
                f"Lean 4 build system executable not found at `{self.lake_path}`. "
                "You can try to run `install-lean` or follow: https://leanprover-community.github.io/get_started.html"
            ) from e

        if res.returncode != 0:
            out = res.stdout or ""
            err = res.stderr or ""
            raise RuntimeError(
                f"Failed to build the REPL at {self._cache_repl_dir}"
                f"\n{'-' * 50}\nstdout:\n{out}\n{'-' * 50}\nstderr:\n{err}\n{'-' * 50}"
            )

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
    def cache_repl_dir(self) -> str:
        """Get the cache directory for the Lean REPL."""
        return str(self._cache_repl_dir)

    @property
    def working_dir(self) -> str:
        """Get the working directory, where the commands are executed."""
        if self.project is not None:
            return str(self.project.get_directory())
        return str(self._cache_repl_dir)

    def is_setup(self) -> bool:
        """Check if the Lean environment has been set up."""
        return hasattr(self, "_cache_repl_dir") and self._cache_repl_dir is not None
