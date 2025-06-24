import hashlib
import shutil
import subprocess
from dataclasses import dataclass
from os import PathLike
from pathlib import Path
from typing import Literal

from filelock import FileLock
from packaging.version import parse

from lean_interact.utils import (
    DEFAULT_CACHE_DIR,
    DEFAULT_REPL_GIT_URL,
    DEFAULT_REPL_VERSION,
    get_project_lean_version,
    logger,
)


@dataclass(frozen=True)
class LeanRequire:
    """Lean project dependency"""

    name: str
    git: str
    rev: str | None = None

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


@dataclass(frozen=True)
class LocalProject(BaseProject):
    """Use an existing local Lean project directory"""

    directory: str | PathLike
    build: bool = True

    def _get_directory(self, cache_dir: str | PathLike, lean_version: str | None = None) -> Path:
        """Get the project directory."""
        return Path(self.directory)

    def _instantiate(
        self, cache_dir: str | PathLike, lean_version: str | None, lake_path: str | PathLike, verbose: bool = True
    ):
        """Instantiate the local project."""
        if not self.build:
            return
        stdout = None if verbose else subprocess.DEVNULL
        stderr = None if verbose else subprocess.DEVNULL

        directory = Path(self.directory)
        with FileLock(f"{directory}.lock"):
            try:
                subprocess.run(
                    [str(lake_path), "exe", "cache", "get"], cwd=directory, check=False, stdout=stdout, stderr=stderr
                )
                subprocess.run([str(lake_path), "build"], cwd=directory, check=True, stdout=stdout, stderr=stderr)
            except subprocess.CalledProcessError as e:
                logger.error("Failed to build local project: %s", e)
                raise


@dataclass(frozen=True)
class GitProject(BaseProject):
    """Use an online git repository with a Lean project"""

    url: str
    rev: str | None = None

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

        from git import Repo

        stdout = None if verbose else subprocess.DEVNULL
        stderr = None if verbose else subprocess.DEVNULL
        project_dir = self._get_directory(cache_dir, lean_version)
        with FileLock(f"{project_dir}.lock"):
            # check if the git repository is already cloned
            repo = Repo(project_dir) if project_dir.exists() else Repo.clone_from(self.url, project_dir)

            if self.rev:
                repo.git.checkout(self.rev)
            else:
                repo.git.pull()

            repo.submodule_update(init=True, recursive=True)

            try:
                subprocess.run(
                    [str(lake_path), "exe", "cache", "get"], cwd=project_dir, check=False, stdout=stdout, stderr=stderr
                )
                subprocess.run([str(lake_path), "build"], cwd=project_dir, check=True, stdout=stdout, stderr=stderr)
            except subprocess.CalledProcessError as e:
                logger.error("Failed to build the git project: %s", e)
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

                # Run lake commands with appropriate platform handling
                try:
                    subprocess.run(
                        [str(lake_path), "update"], cwd=tmp_project_dir, check=True, stdout=stdout, stderr=stderr
                    )
                    # in case mathlib is used as a dependency, we try to get the cache
                    subprocess.run(
                        [str(lake_path), "exe", "cache", "get"],
                        cwd=tmp_project_dir,
                        check=False,
                        stdout=stdout,
                        stderr=stderr,
                    )
                    subprocess.run(
                        [str(lake_path), "build"], cwd=tmp_project_dir, check=True, stdout=stdout, stderr=stderr
                    )
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
    """Use custom lakefile.lean / lakefile.toml content to create a temporary Lean project"""

    content: str
    lakefile_type: Literal["lean", "toml"] = "lean"

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
    Set up a temporary project with dependencies.
    As Mathlib is a common dependency, you can just set `require="mathlib"` and a compatible version of mathlib will be used.
    This feature has been developed mostly to be able to run benchmarks using Mathlib as a dependency
    (such as [ProofNet#](https://huggingface.co/datasets/PAug/ProofNetSharp) or
    [MiniF2F](https://github.com/yangky11/miniF2F-lean4)) without having to manually set up a Lean project.
    """

    require: Literal["mathlib"] | LeanRequire | list[LeanRequire | Literal["mathlib"]]

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
        self.lean_version = lean_version
        self.project = project
        self.repl_git = repl_git
        self.repl_rev = repl_rev
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
        from git import GitCommandError, Repo

        assert isinstance(self.repl_rev, str)

        def get_tag_name(lean_version: str) -> str:
            return f"{self.repl_rev}_lean-toolchain-{lean_version}"

        # First, ensure we have the clean repository
        with FileLock(f"{self.cache_clean_repl_dir}.lock", timeout=self._timeout_lock):
            # Check if the repl is already cloned
            if not self.cache_clean_repl_dir.exists():
                self.cache_clean_repl_dir.mkdir(parents=True, exist_ok=True)
                Repo.clone_from(self.repl_git, self.cache_clean_repl_dir)

            repo = Repo(self.cache_clean_repl_dir)

            def try_checkout(rev):
                try:
                    repo.git.checkout(rev)
                    return True
                except GitCommandError:
                    return False

            checkout_success = False
            if self.lean_version is not None:
                # Try to find a tag with the format `{repl_rev}_lean-toolchain-{lean_version}`
                target_tag = get_tag_name(self.lean_version)
                checkout_success = try_checkout(target_tag)
            else:
                checkout_success = try_checkout(self.repl_rev)

            # If checkout fails, pull once and retry
            if not checkout_success:
                repo.remote().pull()

                if self.lean_version is not None:
                    checkout_success = try_checkout(get_tag_name(self.lean_version))

                # Fall back to base revision if needed
                if not checkout_success:
                    try:
                        repo.git.checkout(self.repl_rev)
                        checkout_success = True
                    except GitCommandError as e:
                        raise ValueError(f"Lean REPL version `{self.repl_rev}` is not available.") from e

            # If we still don't have a lean_version, try to find the latest available
            if self.lean_version is None:
                # Get all available versions and use the latest one
                # We need to temporarily store the repo directory location for the _get_available_lean_versions call
                self._cache_repl_dir = self.cache_clean_repl_dir
                if available_versions := self._get_available_lean_versions():
                    # The versions are already sorted semantically, so take the last one
                    self.lean_version = available_versions[-1][0]
                    try_checkout(get_tag_name(self.lean_version))

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

            # Set up the version-specific REPL directory
            self._cache_repl_dir = self.cache_dir / self.repo_name / f"repl_{get_tag_name(self.lean_version)}"

            # Prepare the version-specific REPL checkout
            if not self._cache_repl_dir.exists():
                with FileLock(f"{self._cache_repl_dir}.lock", timeout=self._timeout_lock):
                    self._cache_repl_dir.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(self.cache_clean_repl_dir, self._cache_repl_dir, dirs_exist_ok=True)

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
