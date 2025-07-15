import asyncio
import hashlib
import subprocess
import threading
from pathlib import Path
from typing import overload

import networkx as nx
from filelock import FileLock

from lean_interact.config import LeanREPLConfig
from lean_interact.interface import (
    BaseREPLQuery,
    BaseREPLResponse,
    Command,
    CommandResponse,
    FileCommand,
    LeanError,
    PickleEnvironment,
    PickleProofState,
    ProofStep,
    ProofStepResponse,
    UnpickleEnvironment,
    UnpickleProofState,
)
from lean_interact.server import AutoLeanServer, LeanServer
from lean_interact.sessioncache import PickleSessionCache
from lean_interact.utils import logger


class LeanWorkspace:
    """
    High-level workspace manager that provides global session management across multiple Lean files.

    **IMPORTANT**: Only one LeanWorkspace instance should be active per project directory.
    The constructor will raise RuntimeError if another instance is already active.

    Key features:
    - **File-based server management**: One AutoLeanServer per file with automatic creation
    - **Global session cache**: Environments and proof states shared across the entire workspace
    - **Intelligent routing**: Commands automatically routed to correct server based on session state
    - **Change detection**: Hash-based change detection with dependency-aware server restarts
    - **Thread-safe operations**: All operations use threading.Lock for thread safety within process
    - **Async support**: Both sync and async interfaces available (run() and async_run())

    The workspace maintains a global session cache where environments and proof states get
    negative session IDs. These can be used across different files and commands will be
    automatically routed to the server that created the session state.

    Context Manager Usage:
    The context manager (__enter__/__exit__) ensures proper cleanup of all resources:
    - Automatically closes all Lean server processes
    - Releases the workspace file lock
    - Clears session caches and internal state

    While not strictly required, using the context manager is recommended for proper resource management.

    Usage:
        ```python
        config = LeanREPLConfig(project=project)

        # Recommended: use as context manager for automatic cleanup
        with LeanWorkspace(config) as workspace:
            # FileCommands are automatically routed to the correct file server
            result1 = workspace.run(FileCommand(path="File1.lean", declarations=True))

            # Commands with session caching get global session IDs
            result2 = workspace.run(Command(cmd="def x := 1"), add_to_session_cache=True)

            # Subsequent commands route automatically to correct server
            env_id = result2.env  # Negative ID for workspace session
            result3 = workspace.run(Command(cmd="#check x", env=env_id))

            # Use a specific server explicitly
            main_server = workspace.main_server
            result4 = workspace.run(Command(cmd="def y := 2"), server=main_server)

            # Get server for a specific file
            file_server = workspace.get_server_for_lean_file("MyFile.lean")
            result5 = workspace.run(Command(cmd="def z := 3"), server=file_server)

        # Alternative: manual management (remember to call close())
        workspace = LeanWorkspace(config)
        try:
            # ... work with workspace ...
        finally:
            workspace.close()  # Important for cleanup
        ```
    """

    def __init__(self, config: LeanREPLConfig, cache_dependencies: bool = True, **server_kwargs):
        """
        Args:
            config: The Lean REPL configuration to use
            cache_dependencies: Whether to cache dependency graph and use for smart restarts
            **server_kwargs: Additional arguments passed to server constructors

        Raises:
            RuntimeError: If another LeanWorkspace is already active for this project
        """
        self.config = config
        self.cache_dependencies = cache_dependencies
        self.server_kwargs = server_kwargs

        # Prevent multiple LeanWorkspace instances per project
        self._workspace_lock_file = Path(self.config.working_dir) / ".lean_workspace.lock"
        try:
            self._workspace_file_lock = FileLock(str(self._workspace_lock_file))
            self._workspace_file_lock.acquire(timeout=0.1)
        except Exception:
            raise RuntimeError(
                f"Another LeanWorkspace is already active for project {self.config.working_dir}. "
                "Only one LeanWorkspace instance should be used per project."
            )

        # Track servers per file
        self._file_servers: dict[str, AutoLeanServer] = {}

        # Create a default main server for commands without specific file context
        self._main_server: AutoLeanServer = AutoLeanServer(self.config, **self.server_kwargs)

        # Content-based change detection
        self._file_content_hashes: dict[str, str] = {}
        self._needs_restart: dict[str, bool] = {}

        # Global session cache for workspace-wide environments and proof states
        self._session_cache: PickleSessionCache = PickleSessionCache(working_dir=config.working_dir)

        # Map session IDs to the server that manages them
        self._session_server_map: dict[int, str] = {}  # session_id -> filename

        # Dependency tracking
        self._dependency_graph: nx.DiGraph | None = None
        self._dependency_graph_mtime: float = 0.0

        # Main lock for workspace operations
        self._workspace_lock = threading.Lock()

        # Cache directory for workspace metadata
        self._cache_dir = Path(self.config.working_dir) / ".cache" / "lean_workspace"
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def _compute_file_hash(self, file_path: Path) -> str:
        """Compute SHA256 hash of file content."""
        if not file_path.exists():
            return ""

        try:
            with open(file_path, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()
        except Exception:
            return ""

    def _get_project_files(self) -> set[str]:
        """Get all .lean files in the project directory."""
        project_dir = Path(self.config.working_dir)
        lean_files = set()

        for lean_file in project_dir.rglob("*.lean"):
            try:
                rel_path = lean_file.relative_to(project_dir)
                lean_files.add(str(rel_path))
            except ValueError:
                # Skip files outside project directory
                continue

        return lean_files

    def _check_project_changes(self) -> None:
        """
        Check for changes in any file in the project and update restart flags.
        This checks both file content changes and new/deleted files.
        """
        current_files = self._get_project_files()
        project_dir = Path(self.config.working_dir)

        # Check for new files or deleted files
        previous_files = set(self._file_content_hashes.keys())

        # Files that were deleted
        deleted_files = previous_files - current_files
        for deleted_file in deleted_files:
            if deleted_file in self._file_content_hashes:
                del self._file_content_hashes[deleted_file]
            if deleted_file in self._needs_restart:
                del self._needs_restart[deleted_file]

        # Check for content changes in existing files and new files
        changed_files = set()
        for file_path in current_files:
            abs_path = project_dir / file_path
            current_hash = self._compute_file_hash(abs_path)

            if file_path not in self._file_content_hashes:
                # New file
                self._file_content_hashes[file_path] = current_hash
                changed_files.add(file_path)
            elif self._file_content_hashes[file_path] != current_hash:
                # File content changed
                self._file_content_hashes[file_path] = current_hash
                changed_files.add(file_path)

        # If any files changed, mark dependent files for restart
        if changed_files:
            self._mark_dependent_files_for_restart(changed_files)

    def _mark_dependent_files_for_restart(self, changed_files: set[str]) -> None:
        """Mark files that depend on changed files for restart."""
        if not self.cache_dependencies or self._dependency_graph is None:
            # Without dependency graph, mark all servers for restart
            for filename in self._file_servers.keys():
                self._needs_restart[filename] = True
            return

        # Mark changed files for restart
        for changed_file in changed_files:
            if changed_file in self._file_servers:
                self._needs_restart[changed_file] = True

        # Mark files that depend on changed files for restart
        for file_path in self._file_servers.keys():
            dependencies = self._get_file_dependencies(file_path)
            if dependencies.intersection(changed_files):
                self._needs_restart[file_path] = True

    def _get_server_for_file(self, filename: str) -> AutoLeanServer:
        """Get or create a server for the specified file."""
        with self._workspace_lock:
            if filename not in self._file_servers:
                self._file_servers[filename] = AutoLeanServer(self.config, **self.server_kwargs)
                # Initialize restart flag
                self._needs_restart[filename] = False

        return self._file_servers[filename]

    def _extract_dependency_graph(self) -> nx.DiGraph:
        """
        Extract the module dependency graph using the import-graph tool.

        Returns:
            A directed graph where edges point from importers to imported modules.
        """
        project_dir = Path(self.config.working_dir)
        lean_version = self.config.lean_version or "v4.8.0"

        # Use file locking to prevent concurrent dependency graph extraction
        lock_path = str(self._cache_dir / "dependency_graph.lock")
        with FileLock(lock_path):
            # Check if we need to rebuild the dependency graph
            graph_file = project_dir / "import_graph.dot"
            if (
                graph_file.exists()
                and self._dependency_graph is not None
                and graph_file.stat().st_mtime <= self._dependency_graph_mtime
            ):
                return self._dependency_graph

            # Prepare paths for import-graph tool
            graph_project_dir = (self._cache_dir / "import-graph").resolve()
            repo_url = "https://github.com/leanprover-community/import-graph.git"
            import_graph_exe = graph_project_dir / ".lake" / "build" / "bin" / "graph"

            # Clone or update the import-graph repo
            if not graph_project_dir.exists():
                logger.info("Cloning import-graph tool...")
                try:
                    subprocess.run(["git", "clone", repo_url, str(graph_project_dir)], check=True)
                except subprocess.CalledProcessError as e:
                    raise RuntimeError(f"Failed to clone import-graph: {e}")

                # Checkout the correct Lean version/tag
                try:
                    subprocess.run(["git", "checkout", lean_version], cwd=str(graph_project_dir), check=True)
                except subprocess.CalledProcessError:
                    # If version checkout fails, try to use main/master
                    logger.warning(f"Failed to checkout {lean_version}, using default branch")
                    pass

                logger.info("Building import-graph tool...")
                try:
                    subprocess.run(["lake", "build"], cwd=graph_project_dir, check=True)
                except subprocess.CalledProcessError as e:
                    raise RuntimeError(f"Failed to build import-graph: {e}")

            if not import_graph_exe.exists():
                raise FileNotFoundError(f"import-graph executable not found after build in {graph_project_dir}")

            # Run the import-graph tool on the project
            logger.info("Extracting dependency graph...")
            try:
                subprocess.run(["lake", "env", str(import_graph_exe)], cwd=str(project_dir), check=True)
            except subprocess.CalledProcessError as e:
                raise RuntimeError(f"Failed to run import-graph: {e}")

            # Load the generated graph
            if not graph_file.exists():
                raise FileNotFoundError(
                    f"Dependency graph file {graph_file} does not exist after running import-graph."
                )

            with open(graph_file) as f:
                # Use nx_pydot to read the DOT file and convert to DiGraph
                graph = nx.DiGraph(nx.drawing.nx_pydot.read_dot(f))

            self._dependency_graph = graph
            self._dependency_graph_mtime = graph_file.stat().st_mtime

            return graph

    def _get_file_dependencies(self, file_path: str) -> set[str]:
        """
        Get all files that the given file depends on (directly and transitively).

        Args:
            file_path: Path to the file (relative to project root)

        Returns:
            Set of file paths that this file depends on
        """
        if not self.cache_dependencies or self._dependency_graph is None:
            return set()

        # Convert file path to module name (remove .lean extension, replace / with .)
        module_name = str(Path(file_path).with_suffix("")).replace("/", ".")

        if module_name not in self._dependency_graph:
            return set()

        # Get all ancestors (dependencies) in the graph
        dependencies = nx.ancestors(self._dependency_graph, module_name)

        # Convert back to file paths
        dep_files = set()
        for dep in dependencies:
            # Convert module name back to file path
            dep_file = dep.replace(".", "/") + ".lean"
            dep_files.add(dep_file)

        return dep_files

    def _get_session_server(self, state_id: int | None) -> str | None:
        """Get the filename of the server managing a session state."""
        if state_id is None or state_id >= 0:
            return None  # Positive IDs are managed by individual servers
        return self._session_server_map.get(state_id)

    def _route_to_session_server(self, request: BaseREPLQuery) -> str:
        """
        Determine which server should handle a request based on its env/proofState.

        Returns:
            The filename of the server that should handle this request
        """
        # Check if request has environment or proof state references
        env_id = getattr(request, "env", None)
        proof_state_id = getattr(request, "proofState", None)

        # For negative session IDs, route to the server that created them
        if env_id is not None and env_id < 0:
            server_filename = self._get_session_server(env_id)
            if server_filename:
                return server_filename

        if proof_state_id is not None and proof_state_id < 0:
            server_filename = self._get_session_server(proof_state_id)
            if server_filename:
                return server_filename

        # Default to "default" server for commands without session state
        return "default"

    def _add_to_workspace_session_cache(
        self,
        server_filename: str,
        server: LeanServer,
        request: BaseREPLQuery,
        response: BaseREPLResponse,
        verbose: bool = False,
    ) -> BaseREPLResponse:
        """Add successful response to workspace session cache and track server mapping."""
        # Only cache CommandResponse and ProofStepResponse
        if isinstance(response, (CommandResponse, ProofStepResponse)):
            session_id = self._session_cache.add(server, request, response, verbose=verbose)
            self._session_server_map[session_id] = server_filename

            # Update response with session ID
            if isinstance(response, CommandResponse):
                return response.model_copy(update={"env": session_id})
            else:  # ProofStepResponse
                return response.model_copy(update={"proofState": session_id})

        return response

    def _resolve_session_ids(self, request: BaseREPLQuery, target_server: LeanServer) -> BaseREPLQuery:
        """Resolve negative session IDs to actual server IDs."""
        from copy import deepcopy

        # Check if we need to resolve any session IDs
        env_id = getattr(request, "env", None)
        proof_state_id = getattr(request, "proofState", None)

        if (env_id is not None and env_id < 0) or (proof_state_id is not None and proof_state_id < 0):
            request = deepcopy(request)

            # Resolve environment ID
            if env_id is not None and env_id < 0:
                if env_id in self._session_cache:
                    # Reload session state in target server if needed
                    session_data = self._session_cache[env_id]
                    # This would require extending the session cache to support cross-server replay
                    # For now, we'll use the original server ID
                    actual_env_id = session_data.repl_id
                    request = request.model_copy(update={"env": actual_env_id})

            # Resolve proof state ID
            if proof_state_id is not None and proof_state_id < 0:
                if proof_state_id in self._session_cache:
                    session_data = self._session_cache[proof_state_id]
                    actual_proof_state_id = session_data.repl_id
                    request = request.model_copy(update={"proofState": actual_proof_state_id})

        return request

    def _check_and_restart_if_needed(self, filename: str) -> None:
        """Check if file needs restart and restart server if needed."""
        if filename in self._needs_restart and self._needs_restart[filename]:
            logger.info(f"Restarting server for {filename} due to detected changes")
            self.restart_file_server(filename)
            self._needs_restart[filename] = False

    def restart_file_server(self, filename: str) -> None:
        """
        Restart the server for a specific file.

        Args:
            filename: The file whose server should be restarted
        """
        with self._workspace_lock:
            if filename in self._file_servers:
                self._file_servers[filename].restart()
                # Clear restart flag
                self._needs_restart[filename] = False

    def restart_all_servers(self) -> None:
        """Restart all file servers (e.g., when project dependencies change)."""
        with self._workspace_lock:
            for filename in list(self._file_servers.keys()):
                self.restart_file_server(filename)

    def invalidate_dependency_cache(self) -> None:
        """
        Invalidate the cached dependency graph and file state, forcing rebuild on next use.
        """
        with self._workspace_lock:
            self._dependency_graph = None
            self._dependency_graph_mtime = 0.0
            self._file_content_hashes.clear()
            self._needs_restart.clear()
            # Also clear session cache as it may reference old server states
            self._session_cache.clear()
            self._session_server_map.clear()

    def remove_from_session_cache(self, session_state_id: int) -> None:
        """
        Remove an environment or proof state from the workspace session cache.

        Args:
            session_state_id: The session state ID to remove
        """
        with self._workspace_lock:
            self._session_cache.remove(session_state_id)
            if session_state_id in self._session_server_map:
                del self._session_server_map[session_state_id]

    def clear_session_cache(self) -> None:
        """
        Clear the entire workspace session cache.
        This removes all cached environments and proof states.
        """
        with self._workspace_lock:
            self._session_cache.clear()
            self._session_server_map.clear()

    def get_file_dependencies(self, filename: str) -> set[str]:
        """
        Get the dependencies of a specific file.

        Args:
            filename: The file to get dependencies for

        Returns:
            Set of file paths that this file depends on
        """
        if self.cache_dependencies and self._dependency_graph is None:
            try:
                self._extract_dependency_graph()
            except Exception as e:
                logger.warning(f"Failed to extract dependency graph: {e}")
                return set()

        return self._get_file_dependencies(filename)

    def get_server_for_file(self, filename: str) -> AutoLeanServer:
        """
        Get the server instance for a specific file (for advanced usage).

        Args:
            filename: The file to get the server for

        Returns:
            The server instance managing this file
        """
        return self._get_server_for_file(filename)

    def get_server_for_lean_file(self, file_path: str) -> AutoLeanServer:
        """
        Get the server associated with a specific Lean file.

        Args:
            file_path: Path to the Lean file (can be absolute or relative to project)

        Returns:
            The AutoLeanServer instance managing this file

        Raises:
            ValueError: If the file path is invalid or outside the project
        """
        # Normalize the file path to be relative to project directory
        project_dir = Path(self.config.working_dir)
        file_path_obj = Path(file_path)

        try:
            # Try to get relative path from project directory
            if file_path_obj.is_absolute():
                filename = str(file_path_obj.relative_to(project_dir))
            else:
                # Check if relative path exists within project
                abs_path = project_dir / file_path_obj
                if abs_path.exists():
                    filename = str(file_path_obj)
                else:
                    raise ValueError(f"File {file_path} does not exist in project")
        except ValueError as e:
            if "does not start with" in str(e):
                raise ValueError(f"File {file_path} is outside the project directory {project_dir}")
            raise

        return self._get_server_for_file(filename)

    @property
    def main_server(self) -> AutoLeanServer:
        """
        Get the main server for general commands not associated with specific files.

        Returns:
            The main AutoLeanServer instance
        """
        return self._main_server

    # Type hints for IDE and static analysis
    @overload
    def run(
        self,
        request: Command | FileCommand | PickleEnvironment | UnpickleEnvironment,
        *,
        verbose: bool = False,
        timeout: float | None = None,
        add_to_session_cache: bool = False,
        server: LeanServer | None = None,
    ) -> CommandResponse | LeanError: ...

    @overload
    def run(
        self,
        request: ProofStep | PickleProofState | UnpickleProofState,
        *,
        verbose: bool = False,
        timeout: float | None = None,
        add_to_session_cache: bool = False,
        server: LeanServer | None = None,
    ) -> ProofStepResponse | LeanError: ...

    def run(
        self,
        request: BaseREPLQuery,
        *,
        verbose: bool = False,
        timeout: float | None = None,
        add_to_session_cache: bool = False,
        server: LeanServer | None = None,
        **kwargs,
    ) -> BaseREPLResponse | LeanError:
        """
        Run a Lean REPL request with intelligent routing and global session management.

        For FileCommands: Checks for project-wide changes and restarts servers if needed.
        For other commands: Routes based on environment/proof state references or uses specified server.

        Args:
            request: The Lean REPL request to execute
            verbose: Whether to print additional information
            timeout: The timeout for the request in seconds
            add_to_session_cache: Whether to add the result to global session cache
            server: Specific server to use. If None, routing is determined automatically:
                   - FileCommands: routed to the server for that file
                   - Other commands: routed based on session state, or main server if no state
            **kwargs: Additional arguments passed to server.run()

        Returns:
            The response from the Lean server
        """
        # If server is explicitly provided, use it directly
        if server is not None:
            filename = "explicit_server"  # Used for session cache mapping
            target_server = server

            # Still resolve session IDs if needed
            if not isinstance(request, FileCommand):
                request = self._resolve_session_ids(request, target_server)
        else:
            # Use automatic routing logic
            if isinstance(request, FileCommand):
                # Check for changes across the entire project before running FileCommand
                self._check_project_changes()

                # Initialize dependency graph if caching is enabled
                if self.cache_dependencies and self._dependency_graph is None:
                    try:
                        self._extract_dependency_graph()
                    except Exception as e:
                        logger.warning(
                            f"Failed to extract dependency graph: {e}. Continuing without dependency caching."
                        )
                        self.cache_dependencies = False

                # Extract filename from the file path
                project_dir = Path(self.config.working_dir)
                file_path = Path(request.path)

                try:
                    # Try to get relative path from project directory
                    filename = str(file_path.relative_to(project_dir))
                except ValueError:
                    # If path is not relative to project dir, use the filename only
                    filename = file_path.name

                # Check if we need to restart due to changes
                self._check_and_restart_if_needed(filename)

                # Get server for the file
                target_server = self._get_server_for_file(filename)
            else:
                # For non-FileCommands, route based on session state
                filename = self._route_to_session_server(request)

                # If routing returns "default", use the main server
                if filename == "default":
                    target_server = self._main_server
                    filename = "main"
                else:
                    target_server = self._get_server_for_file(filename)

                # Resolve session IDs to server-specific IDs
                request = self._resolve_session_ids(request, target_server)

        # Run the command - server handles its own thread safety
        response = target_server.run(
            request,  # type: ignore[arg-type]
            verbose=verbose,
            timeout=timeout,
            add_to_session_cache=False,  # We manage session cache at workspace level
            **kwargs,
        )

        # Add to workspace session cache if requested and not an error
        if add_to_session_cache and not isinstance(response, LeanError):
            response = self._add_to_workspace_session_cache(filename, target_server, request, response, verbose=verbose)

        return response

    # Type hints for async version - mirror AutoLeanServer interface
    @overload
    async def async_run(
        self,
        request: Command | FileCommand | PickleEnvironment | UnpickleEnvironment,
        *,
        verbose: bool = False,
        timeout: float | None = None,
        add_to_session_cache: bool = False,
        server: LeanServer | None = None,
    ) -> CommandResponse | LeanError: ...

    @overload
    async def async_run(
        self,
        request: ProofStep | PickleProofState | UnpickleProofState,
        *,
        verbose: bool = False,
        timeout: float | None = None,
        add_to_session_cache: bool = False,
        server: LeanServer | None = None,
    ) -> ProofStepResponse | LeanError: ...

    async def async_run(
        self,
        request: BaseREPLQuery,
        *,
        verbose: bool = False,
        timeout: float | None = None,
        add_to_session_cache: bool = False,
        server: LeanServer | None = None,
        **kwargs,
    ) -> BaseREPLResponse | LeanError:
        """
        Async version of run() method with identical behavior.

        See run() documentation for details on routing and session management.
        """
        return await asyncio.to_thread(
            self.run,
            request,  # type: ignore[arg-type]
            verbose=verbose,
            timeout=timeout,
            add_to_session_cache=add_to_session_cache,
            server=server,
            **kwargs,
        )

    def close(self) -> None:
        """Clean up all servers and resources."""
        with self._workspace_lock:
            # Clear session cache first
            self._session_cache.clear()
            self._session_server_map.clear()

            # Then close all servers
            for server in self._file_servers.values():
                try:
                    server.kill()
                except Exception as e:
                    logger.warning(f"Error closing file server: {e}")

            # Close the main server
            try:
                self._main_server.kill()
            except Exception as e:
                logger.warning(f"Error closing main server: {e}")

            self._file_servers.clear()
            self._file_content_hashes.clear()
            self._needs_restart.clear()

        # Release the workspace file lock
        try:
            if hasattr(self, "_workspace_file_lock"):
                self._workspace_file_lock.release()
        except Exception as e:
            logger.warning(f"Error releasing workspace lock: {e}")

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
