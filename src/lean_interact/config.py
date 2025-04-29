import hashlib
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Literal

from filelock import FileLock
from git import GitCommandError, Repo

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

    def _get_directory(self, cache_dir: str, lean_version: str | None = None) -> str:
        """Get the project directory."""
        raise NotImplementedError("Subclasses must implement this method")

    def _instantiate(self, cache_dir: str, lean_version: str, verbose: bool = True) -> None:
        """Instantiate the project."""
        raise NotImplementedError("Subclasses must implement this method")


@dataclass(frozen=True)
class LocalProject(BaseProject):
    """Use an existing local Lean project directory"""

    directory: str

    def _get_directory(self, cache_dir: str, lean_version: str | None = None) -> str:
        """Get the project directory."""
        return self.directory

    def _instantiate(self, cache_dir: str, lean_version: str, verbose: bool = True):
        """Instantiate the local project."""
        stdout = None if verbose else subprocess.DEVNULL
        stderr = None if verbose else subprocess.DEVNULL

        with FileLock(f"{self.directory}.lock"):
            try:
                subprocess.run(["lake", "exe", "cache", "get"], cwd=self.directory, check=False, stdout=stdout, stderr=stderr)
                subprocess.run(["lake", "build"], cwd=self.directory, check=True, stdout=stdout, stderr=stderr)
            except subprocess.CalledProcessError as e:
                logger.error("Failed to build local project: %s", e)
                raise


@dataclass(frozen=True)
class GitProject(BaseProject):
    """Use an online git repository with a Lean project"""

    url: str
    rev: str | None = None

    def _get_directory(self, cache_dir: str, lean_version: str | None = None) -> str:
        repo_parts = self.url.split("/")
        if len(repo_parts) >= 2:
            owner = repo_parts[-2]
            repo = repo_parts[-1].replace(".git", "")
            return os.path.join(cache_dir, "git_projects", owner, repo, self.rev or "latest")
        else:
            # Fallback for malformed URLs
            repo_name = self.url.replace(".git", "").split("/")[-1]
            return os.path.join(cache_dir, "git_projects", repo_name, self.rev or "latest")

    def _instantiate(self, cache_dir: str, lean_version: str, verbose: bool = True):
        """Instantiate the git project."""
        stdout = None if verbose else subprocess.DEVNULL
        stderr = None if verbose else subprocess.DEVNULL

        project_dir = self._get_directory(cache_dir)

        with FileLock(f"{project_dir}.lock"):
            # check if the git repository is already cloned
            repo = Repo(project_dir) if os.path.exists(project_dir) else Repo.clone_from(self.url, project_dir)

            if self.rev:
                repo.git.checkout(self.rev)
            else:
                repo.git.pull()

            repo.submodule_update(init=True, recursive=True)

            try:
                subprocess.run(["lake", "exe", "cache", "get"], cwd=project_dir, check=False, stdout=stdout, stderr=stderr)
                subprocess.run(["lake", "build"], cwd=project_dir, check=True, stdout=stdout, stderr=stderr)
            except subprocess.CalledProcessError as e:
                logger.error("Failed to build the git project: %s", e)
                raise


@dataclass(frozen=True)
class BaseTempProject(BaseProject):
    """Base class for temporary Lean projects"""

    def _get_directory(self, cache_dir: str, lean_version: str | None = None) -> str:
        if lean_version is None:
            raise ValueError("`lean_version` cannot be `None`")
        # create a unique hash to allow for caching
        hash_content = self._get_hash_content(lean_version)
        tmp_project_dir = os.path.join(cache_dir, "tmp_projects", lean_version, hash_content)
        os.makedirs(tmp_project_dir, exist_ok=True)
        return tmp_project_dir

    def _instantiate(self, cache_dir: str, lean_version: str, verbose: bool = True):
        """Instantiate the temporary project."""
        stdout = None if verbose else subprocess.DEVNULL
        stderr = None if verbose else subprocess.DEVNULL

        tmp_project_dir = self._get_directory(cache_dir, lean_version)

        # Lock the temporary project directory during setup
        with FileLock(f"{tmp_project_dir}.lock"):
            # check if the Lean project already exists
            if not os.path.exists(os.path.join(tmp_project_dir, "lake-manifest.json")):
                # clean the content of the folder in case of a previous aborted build
                shutil.rmtree(tmp_project_dir, ignore_errors=True)
                os.makedirs(tmp_project_dir, exist_ok=True)

                # initialize the Lean project
                cmd_init = ["lake", f"+{lean_version}", "init", "dummy", "exe.lean"]
                if lean_version.startswith("v4") and int(lean_version.split(".")[1]) <= 7:
                    cmd_init = ["lake", f"+{lean_version}", "init", "dummy", "exe"]

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
                    subprocess.run(["lake", "update"], cwd=tmp_project_dir, check=True, stdout=stdout, stderr=stderr)
                    # in case mathlib is used as a dependency, we try to get the cache
                    subprocess.run(
                        ["lake", "exe", "cache", "get"], cwd=tmp_project_dir, check=False, stdout=stdout, stderr=stderr
                    )
                    subprocess.run(["lake", "build"], cwd=tmp_project_dir, check=True, stdout=stdout, stderr=stderr)
                except subprocess.CalledProcessError as e:
                    logger.error("Failed during Lean project setup: %s", e)
                    # delete the project directory to avoid conflicts
                    shutil.rmtree(tmp_project_dir, ignore_errors=True)
                    raise

    def _get_hash_content(self, lean_version: str) -> str:
        """Return a unique hash for the project content."""
        raise NotImplementedError("Subclasses must implement this method")

    def _modify_lakefile(self, project_dir: str, lean_version: str) -> None:
        """Modify the lakefile according to project needs."""
        raise NotImplementedError("Subclasses must implement this method")


@dataclass(frozen=True)
class TemporaryProject(BaseTempProject):
    """Use custom lakefile.lean content to create a temporary Lean project"""

    content: str

    def _get_hash_content(self, lean_version: str) -> str:
        """Return a unique hash based on the content."""
        return hashlib.sha256(self.content.encode()).hexdigest()

    def _modify_lakefile(self, project_dir: str, lean_version: str) -> None:
        """Write the content to the lakefile."""
        with open(os.path.join(project_dir, "lakefile.lean"), "w", encoding="utf-8") as f:
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

    def _modify_lakefile(self, project_dir: str, lean_version: str) -> None:
        """Add requirements to the lakefile."""
        require = self._normalize_require(lean_version)
        with open(os.path.join(project_dir, "lakefile.lean"), "a", encoding="utf-8") as f:
            for req in require:
                f.write(f'\n\nrequire {req.name} from git\n  "{req.git}"' + (f' @ "{req.rev}"' if req.rev else ""))


class LeanREPLConfig:
    def __init__(
        self,
        lean_version: str | None = None,
        project: BaseProject | None = None,
        repl_rev: str = DEFAULT_REPL_VERSION,
        repl_git: str = DEFAULT_REPL_GIT_URL,
        cache_dir: str = DEFAULT_CACHE_DIR,
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
                The project you want to use. There are 4 options:
                - `None`: The project will only depend on Lean and its standard library.
                - `LocalProject`: An existing local Lean project.
                - `GitProject`: A git repository with a Lean project that will be cloned.
                - `TemporaryProject`: A temporary Lean project with a custom lakefile.lean that will be created.
                - `TempRequireProject`: A temporary Lean project with dependencies that will be created.
            repl_rev:
                The REPL version you want to use. It is not recommended to change this value unless you know what you are doing.
            repl_git:
                The git repository of the Lean REPL. It is not recommended to change this value unless you know what you are doing.
            cache_dir:
                The directory where the Lean REPL and temporary Lean projects with dependencies will be cached.
                Default is inside the package directory.
            memory_hard_limit_mb:
                The maximum memory usage in MB for the Lean server. Setting this value too low may lead to more command processing failures.
                Only available on Linux platforms.
                Default is `None`, which means no limit.
            verbose:
                Whether to print additional information during the setup process.
        """
        self.lean_version = lean_version
        self.project = project
        self.repl_git = repl_git
        self.repl_rev = repl_rev
        self.cache_dir = os.path.normpath(cache_dir)
        self.memory_hard_limit_mb = memory_hard_limit_mb

        self.verbose = verbose
        self._stdout = None if self.verbose else subprocess.DEVNULL
        self._stderr = None if self.verbose else subprocess.DEVNULL

        repo_parts = self.repl_git.split("/")
        if len(repo_parts) >= 2:
            owner = repo_parts[-2]
            repo = repo_parts[-1].replace(".git", "")
            self.repo_name = os.path.join(owner, repo)
        else:
            self.repo_name = self.repl_git.replace(".git", "")

        self.cache_clean_repl_dir = os.path.join(self.cache_dir, self.repo_name, "repl_clean_copy")

        # check if lake is installed
        if shutil.which("lake") is None:
            raise RuntimeError(
                "Lean 4 build system (`lake`) is not installed. You can try to run `install-lean` or find installation instructions here: https://leanprover-community.github.io/get_started.html"
            )

        self._setup_repl()

        assert isinstance(self.lean_version, str)

        if self.project is None:
            self._working_dir = self._cache_repl_dir
        else:
            self.project._instantiate(
                cache_dir=self.cache_dir,
                lean_version=self.lean_version,
                verbose=self.verbose,
            )
            self._working_dir = self.project._get_directory(cache_dir=self.cache_dir, lean_version=self.lean_version)

    def _setup_repl(self) -> None:
        assert isinstance(self.repl_rev, str)

        # Lock the clean REPL directory during setup to prevent race conditions
        with FileLock(f"{self.cache_clean_repl_dir}.lock", timeout=300):
            # check if the repl is already cloned
            if not os.path.exists(self.cache_clean_repl_dir):
                os.makedirs(self.cache_clean_repl_dir, exist_ok=True)
                Repo.clone_from(self.repl_git, self.cache_clean_repl_dir)

            repo = Repo(self.cache_clean_repl_dir)
            try:
                repo.git.checkout(self.repl_rev)
            except GitCommandError:
                repo.remote().pull()
                try:
                    repo.git.checkout(self.repl_rev)
                except GitCommandError as e:
                    raise ValueError(f"Lean REPL version `{self.repl_rev}` is not available.") from e

            # check if the Lean version is available in the repository
            lean_versions_sha = self._get_available_lean_versions_sha()
            lean_versions_sha_dict = dict(lean_versions_sha)
            if not lean_versions_sha:
                raise ValueError("No Lean versions are available in the Lean REPL repository.")
            if self.lean_version is None:
                if self.project is None or isinstance(self.project, (TemporaryProject, TempRequireProject)):
                    self.lean_version = lean_versions_sha[-1][0]
                elif isinstance(self.project, (LocalProject, GitProject)):
                    # get the Lean version from the project
                    inferred_ver = get_project_lean_version(self.project._get_directory(self.cache_dir))
                    self.lean_version = inferred_ver if inferred_ver else lean_versions_sha[-1][0]
            if self.lean_version not in lean_versions_sha_dict:
                raise ValueError(
                    f"Lean version `{self.lean_version}` is required but not available in the Lean REPL repository."
                )

        # check if the repl revision is already in the cache
        self._cache_repl_dir = os.path.join(self.cache_dir, self.repo_name, f"repl_{self.repl_rev}_{self.lean_version}")

        # Lock the version-specific REPL directory during setup
        with FileLock(f"{self._cache_repl_dir}.lock", timeout=300):  # 5 minute timeout for long-running operations
            if not os.path.exists(self._cache_repl_dir):
                # copy the repository to the version directory and checkout the required revision
                os.makedirs(self._cache_repl_dir, exist_ok=True)
                shutil.copytree(self.cache_clean_repl_dir, self._cache_repl_dir, dirs_exist_ok=True)
                cached_repo = Repo(self._cache_repl_dir)
                cached_repo.git.checkout(lean_versions_sha_dict[self.lean_version])

            # check that the lean version is correct
            assert self.lean_version == get_project_lean_version(self._cache_repl_dir), (
                f"An error occured while preparing the Lean REPL. The requested Lean version `{self.lean_version}` "
                f"does not match the fetched Lean version in the repository `{get_project_lean_version(self._cache_repl_dir)}`."
                f"Please open an issue on GitHub if you think this is a bug."
            )

            try:
                subprocess.run(
                    ["lake", "build"], cwd=self._cache_repl_dir, check=True, stdout=self._stdout, stderr=self._stderr
                )
            except subprocess.CalledProcessError as e:
                logger.error("Failed to build the REPL: %s", e)
                raise

    def _get_available_lean_versions_sha(self) -> list[tuple[str, str]]:
        """
        Get the available Lean versions for the selected REPL.
        """
        repo = Repo(self.cache_clean_repl_dir)
        return [
            (str(commit.message.strip()), commit.hexsha)
            for commit in repo.iter_commits(f"{self.repl_rev}...master")
            if str(commit.message.strip()).startswith("v4")
        ]

    def get_available_lean_versions(self) -> list[str]:
        """
        Get the available Lean versions for the selected REPL.
        """
        return [commit[0] for commit in self._get_available_lean_versions_sha()]

    @property
    def working_dir(self) -> str:
        """Get the working directory for the Lean environment."""
        return self._working_dir

    @property
    def cache_repl_dir(self) -> str:
        """Get the cache directory for the Lean REPL."""
        return self._cache_repl_dir

    def is_setup(self) -> bool:
        return hasattr(self, "_working_dir")
