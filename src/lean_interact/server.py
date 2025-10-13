"""
**Module:** `lean_interact.server`

This module provides the `LeanServer` and `AutoLeanServer` classes, which are used to interact with the Lean REPL (Read-Eval-Print Loop).
The `LeanServer` class is a simple wrapper around the Lean REPL, while the `AutoLeanServer` class adds automatic memory management and session caching features.
"""

import asyncio
import gc
import json
import os
import platform
import subprocess
import threading
from copy import deepcopy
from time import sleep
from typing import overload

import psutil

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
from lean_interact.sessioncache import BaseSessionCache, PickleSessionCache
from lean_interact.utils import _limit_memory, get_total_memory_usage, logger

DEFAULT_TIMEOUT: int | None = None


class LeanServer:
    config: LeanREPLConfig
    _proc: subprocess.Popen | None
    _lock: threading.Lock

    def __init__(self, config: LeanREPLConfig):
        """
        This class is a Python wrapper for the Lean REPL. Please refer to the \
        [documentation](https://augustepoiroux.github.io/LeanInteract/stable/user-guide/basic-usage/) for usage examples.

        Warning:
            Instantiate a single config before starting multiprocessing. Then instantiate one `LeanServer`
            per process by passing the config instance to the constructor. This will ensure that the REPL is already set up
            for your specific environment and avoid concurrency conflicts.

        Args:
            config: The configuration for the Lean server.
        """
        self.config = config
        assert self.config.is_setup(), "The Lean environment has not been set up properly."
        self._proc = None
        self._lock = threading.Lock()
        self.start()

    @property
    def lean_version(self) -> str | None:
        """Get the Lean version used by the Lean REPL server."""
        return self.config.lean_version

    def start(self) -> None:
        """Start the Lean REPL server process. This is called automatically in the constructor."""

        self._proc = subprocess.Popen(
            [
                str(self.config.lake_path),
                "env",
                str(os.path.join(self.config._cache_repl_dir, ".lake", "build", "bin", "repl")),
            ],
            cwd=self.config.working_dir,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            text=True,
            bufsize=1,
            start_new_session=True,
            preexec_fn=None
            if platform.system() != "Linux"
            else lambda: _limit_memory(self.config.memory_hard_limit_mb),
        )
        if not self.is_alive():
            stdout, stderr = self.get_stdout_stderr()
            raise ChildProcessError(f"The Lean server could not be started:\nstdout: {stdout}\nstderr: {stderr}")

    def get_stdout_stderr(self) -> tuple[str, str]:
        """Get the stdout and stderr output from the Lean REPL.

        Returns:
            A tuple containing the stdout and stderr output.
        """
        stdout = self._proc.stdout.read() if self._proc and self._proc.stdout else ""
        stderr = self._proc.stderr.read() if self._proc and self._proc.stderr else ""
        return stdout, stderr

    def _sendline(self, line: str) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        self._proc.stdin.write(line + "\n")
        self._proc.stdin.flush()

    def is_alive(self) -> bool:
        """Check if the Lean REPL server process is running."""
        return self._proc is not None and self._proc.poll() is None

    def kill(self) -> None:
        """Kill the Lean REPL server process and its children."""
        if self._proc:
            try:
                proc = psutil.Process(self._proc.pid)
                # Terminate the process tree
                children = proc.children(recursive=True)
                for child in children:
                    try:
                        child.terminate()
                    except Exception:
                        pass
                proc.terminate()
                _, alive = psutil.wait_procs([proc] + children, timeout=1)
                for p in alive:
                    try:
                        p.kill()
                    except Exception:
                        pass
            except Exception:
                pass
            finally:
                try:
                    self._proc.wait(timeout=1)  # Ensure the process is properly reaped
                except Exception:
                    pass
            if self._proc.stdin:
                self._proc.stdin.close()
            if self._proc.stdout:
                self._proc.stdout.close()
            if self._proc.stderr:
                self._proc.stderr.close()
            self._proc = None
        gc.collect()

    def restart(self) -> None:
        """Restart the Lean REPL server."""
        self.kill()
        self.start()

    def __del__(self):
        self.kill()

    def get_memory_usage(self) -> float:
        """
        Get the memory usage of the Lean REPL server process in MB.

        Returns:
            Memory usage in MB.
        """
        if self._proc is None:
            return 0.0
        try:
            proc = psutil.Process(self._proc.pid)
            return get_total_memory_usage(proc) / (1024**2)  # Convert bytes to MB
        except psutil.NoSuchProcess:
            return 0.0

    def _execute_cmd_in_repl(self, json_query: str, verbose: bool, timeout: float | None) -> str:
        """Send JSON queries to the Lean REPL and wait for the standard delimiter.

        Args:
            json_query: The JSON query to send to the Lean REPL.
            verbose: Whether to print verbose output.
            timeout: The timeout for the query in seconds.

        Returns:
            The raw output from the Lean REPL.

        Raises:
            TimeoutError: If the Lean REPL does not respond within the specified timeout.
            BrokenPipeError: If the Lean REPL closes unexpectedly.
            AssertionError: If the Lean REPL process is not properly initialized.
        """
        assert self._proc is not None and self._proc.stdin is not None and self._proc.stdout is not None
        with self._lock:
            if verbose:
                logger.info("Sending query: %s", json_query)
            self._proc.stdin.write(json_query + "\n\n")
            self._proc.stdin.flush()

            output: str = ""

            def reader():
                # Read until delimiter "\n\n" or timeout
                nonlocal output
                assert self._proc is not None and self._proc.stdout is not None
                while True:
                    line = self._proc.stdout.readline()
                    if not line:
                        break  # EOF
                    output += line
                    if output.endswith("\n\n"):
                        break

            t = threading.Thread(target=reader)
            t.start()
            t.join(timeout)
            if t.is_alive():
                self.kill()
                raise TimeoutError(f"The Lean server did not respond in time ({timeout=}) and is now killed.")
            if output.strip():
                return output
            raise BrokenPipeError("The Lean server returned no output.")

    def _parse_repl_output(self, raw_output: str, verbose: bool) -> dict:
        """Parse JSON response.

        Args:
            raw_output: The raw output from the Lean REPL.
            verbose: Whether to print verbose output.

        Returns:
            Parsed JSON response as a dictionary.

        Raises:
            json.JSONDecodeError: If the raw output is not valid JSON.
        """
        if verbose:
            logger.info("Server output: `%s`", raw_output)
        try:
            return json.loads(raw_output)
        except json.JSONDecodeError as e:
            raise json.JSONDecodeError(
                msg=f"Could not parse the Lean server output: `{repr(raw_output)}`.", doc=e.doc, pos=e.pos
            ) from e

    def run_dict(self, request: dict, verbose: bool = False, timeout: float | None = DEFAULT_TIMEOUT) -> dict:
        """
        Run a Lean REPL dictionary request and return the Lean server output as a dictionary.

        Info:
            When working with custom REPL implementations that might have incompatible interfaces with
            LeanInteract's standard commands, you can use the `run_dict` method to communicate directly
            with the REPL using the raw JSON protocol. This method bypasses the command-specific parsing
            and validation, allowing you to work with custom REPL interfaces.

        Examples:
            ```python
            # Using run_dict to send a raw command to the REPL
            result = server.run_dict({"cmd": "your Lean code here"})
            ```

        Args:
            request: The Lean REPL request to execute. Must be a dictionary.
            verbose: Whether to print additional information during the verification process.
            timeout: The timeout for the request in seconds

        Returns:
            The output of the Lean server as a dictionary.

        Raises:
            TimeoutError: If the Lean server does not respond within the specified timeout.
            ConnectionAbortedError: If the Lean server closes unexpectedly.
            ChildProcessError: If the Lean server is not running.
            JsonDecodeError: If the Lean server output is not valid JSON.
        """
        if not self.is_alive():
            stdout, stderr = self.get_stdout_stderr()
            raise ChildProcessError(
                f"The Lean server is not running.\n{'-' * 50}\nstdout:\n{stdout}\n{'-' * 50}\nstderr:\n{stderr}\n{'-' * 50}"
            )

        json_query = json.dumps(request, ensure_ascii=False)
        try:
            raw_output = self._execute_cmd_in_repl(json_query, verbose, timeout)
        except TimeoutError as e:
            self.kill()
            raise TimeoutError(f"The Lean server did not respond in time ({timeout=}) and is now killed.") from e
        except BrokenPipeError as e:
            stdout, stderr = self.get_stdout_stderr()
            self.kill()
            raise ConnectionAbortedError(
                f"The Lean server closed unexpectedly."
                f"\n{'-' * 50}\nstdout:\n{stdout}\n{'-' * 50}\nstderr:\n{stderr}\n{'-' * 50}"
                f"If stdout and stderr are empty or obscure, here is a list of possible reasons (not exhaustive):\n"
                "- Not enough memory and/or compute available\n"
                "- The cached Lean REPL is corrupted. In this case, clear the cache using the `clear-lean-cache` command.\n"
                "- An uncaught exception in the Lean REPL"
            ) from e

        return self._parse_repl_output(raw_output, verbose)

    def _augment_request(self, request: BaseREPLQuery) -> BaseREPLQuery:
        if isinstance(request, (Command, FileCommand)):
            if self.config.enable_incremental_optimization:
                request = request.model_copy(update={"incrementality": True})
            if self.config.enable_parallel_elaboration:
                set_options = list(request.set_options) if request.set_options is not None else []
                set_options.append((["Elab", "async"], True))
                request = request.model_copy(update={"set_options": set_options})
        return request

    # Type hints for IDE and static analysis
    @overload
    def run(
        self,
        request: Command | FileCommand | PickleEnvironment | UnpickleEnvironment,
        *,
        verbose: bool = False,
        timeout: float | None = DEFAULT_TIMEOUT,
    ) -> CommandResponse | LeanError: ...

    @overload
    def run(
        self,
        request: ProofStep | PickleProofState | UnpickleProofState,
        *,
        verbose: bool = False,
        timeout: float | None = DEFAULT_TIMEOUT,
    ) -> ProofStepResponse | LeanError: ...

    def run(
        self, request: BaseREPLQuery, *, verbose: bool = False, timeout: float | None = DEFAULT_TIMEOUT, **kwargs
    ) -> BaseREPLResponse | LeanError:
        """
        Run a Lean REPL request.

        Note:
            **Thread-safe:** Uses a `threading.Lock` to ensure only one operation runs at a time.

        Args:
            request: The Lean REPL request to execute. Must be one of the following types:
                `Command`, `FileCommand`, `ProofStep`, `PickleEnvironment`, `PickleProofState`,
                `UnpickleEnvironment`, or `UnpickleProofState`
            verbose: Whether to print additional information
            timeout: The timeout for the request in seconds

        Returns:
            Depending on the request type, the response will be one of the following:
                `CommandResponse`, `ProofStepResponse`, or `LeanError`
        """
        request = self._augment_request(request)
        request_dict = request.model_dump(exclude_none=True, by_alias=True)
        result_dict = self.run_dict(request=request_dict, verbose=verbose, timeout=timeout, **kwargs)

        if set(result_dict.keys()) == {"message"}:
            return LeanError.model_validate(result_dict)

        if isinstance(request, (Command, FileCommand, PickleEnvironment, UnpickleEnvironment)):
            return CommandResponse.model_validate(result_dict)
        elif isinstance(request, (ProofStep, PickleProofState, UnpickleProofState)):
            return ProofStepResponse.model_validate(result_dict)
        else:
            return BaseREPLResponse.model_validate(result_dict)

    # Type hints for IDE and static analysis
    @overload
    async def async_run(
        self,
        request: Command | FileCommand | PickleEnvironment | UnpickleEnvironment,
        *,
        verbose: bool = False,
        timeout: float | None = DEFAULT_TIMEOUT,
    ) -> CommandResponse | LeanError: ...

    @overload
    async def async_run(
        self,
        request: ProofStep | PickleProofState | UnpickleProofState,
        *,
        verbose: bool = False,
        timeout: float | None = DEFAULT_TIMEOUT,
    ) -> ProofStepResponse | LeanError: ...

    async def async_run(
        self, request: BaseREPLQuery, *, verbose: bool = False, timeout: float | None = DEFAULT_TIMEOUT, **kwargs
    ) -> BaseREPLResponse | LeanError:
        """
        Asynchronous version of `run()`. Runs the blocking `run()` in a thread pool.

        Note:
            **Thread-safe:** Uses a `threading.Lock` to ensure only one operation runs at a time.

        Args:
            request: The Lean REPL request to execute. Must be one of the following types:
                `Command`, `FileCommand`, `ProofStep`, `PickleEnvironment`, `PickleProofState`,
                `UnpickleEnvironment`, or `UnpickleProofState`
            verbose: Whether to print additional information
            timeout: The timeout for the request in seconds

        Returns:
            Depending on the request type, the response will be one of the following:
                `CommandResponse`, `ProofStepResponse`, or `LeanError`
        """
        return await asyncio.to_thread(self.run, request, verbose=verbose, timeout=timeout, **kwargs)  # type: ignore


class AutoLeanServer(LeanServer):
    def __init__(
        self,
        config: LeanREPLConfig,
        max_total_memory: float = 0.8,
        max_process_memory: float | None = 0.8,
        max_restart_attempts: int = 5,
        session_cache: BaseSessionCache | None = None,
    ):
        """
        This class is a Python wrapper for the Lean REPL. `AutoLeanServer` differs from `LeanServer` by automatically \
        restarting when it runs out of memory to clear Lean environment states. \
        It also automatically recovers from timeouts. \
        An exponential backoff strategy is used to restart the server, making this class slightly more friendly for multiprocessing
        than `LeanServer` when multiple instances are competing for resources. \
        Please refer to the [documentation](https://augustepoiroux.github.io/LeanInteract/stable/user-guide/basic-usage/) for usage examples.

        Note:
            A session cache is implemented to keep user-selected environment / proof states across these automatic restarts. \
            Use the `add_to_session_cache` parameter in the different class methods to add the command to \
            the session cache. `AutoLeanServer` works best when only a few states are cached simultaneously. \
            You can use `remove_from_session_cache` and `clear_session_cache` to clear the session cache. \
            Cached state indices are negative integers starting from -1 to not conflict with the positive integers used by the Lean REPL.

        Note:
            The session cache is specific to each `AutoLeanServer` instance and is cleared when the instance is deleted. \
            If you want truly persistent states, you can use the `pickle` and `unpickle` methods to save and load states to disk.

        Warning:
            Instantiate a single config before starting multiprocessing. Then instantiate one `LeanServer`
            per process by passing the config instance to the constructor. This will ensure that the REPL is already set up
            for your specific environment and avoid concurrency conflicts.

        Args:
            config: The configuration for the Lean server.
            max_total_memory: The maximum proportion of system-wide memory usage (across all processes) before triggering a Lean server restart. This is a soft limit ranging from 0.0 to 1.0, with default 0.8 (80%). When system memory exceeds this threshold, the server restarts to free memory. Particularly useful in multiprocessing environments to prevent simultaneous crashes.
            max_process_memory: The maximum proportion of the memory hard limit (set in `LeanREPLConfig.memory_hard_limit_mb`) that the Lean server process can use before restarting. This soft limit ranges from 0.0 to 1.0, with default 0.8 (80%). Only applied if a hard limit is configured in `LeanREPLConfig`.
            max_restart_attempts: The maximum number of consecutive restart attempts allowed before raising a `MemoryError` exception. Default is 5. The server uses exponential backoff between restart attempts.
            session_cache: The session cache to use, if specified.
        """
        session_cache = (
            session_cache if session_cache is not None else PickleSessionCache(working_dir=config.working_dir)
        )
        self._session_cache: BaseSessionCache = session_cache
        self._max_total_memory = max_total_memory
        self._max_process_memory = max_process_memory
        self._max_restart_attempts = max_restart_attempts
        super().__init__(config=config)

    def _get_repl_state_id(self, state_id: int | None) -> int | None:
        if state_id is None:
            return None
        if state_id in self._session_cache:
            return self._session_cache[state_id].repl_id
        return state_id

    def restart(self, verbose: bool = False) -> None:
        """
        Restart the Lean REPL server and reload the session cache.

        Args:
            verbose: Whether to print additional information during the restart process.
        """
        super().restart()
        self._session_cache.reload(self, timeout_per_state=DEFAULT_TIMEOUT, verbose=verbose)

    def remove_from_session_cache(self, session_state_id: int) -> None:
        """
        Remove an environment from the session cache.

        Args:
            session_state_id: The session state id to remove.
        """
        self._session_cache.remove(session_state_id)

    def clear_session_cache(self, force: bool = False) -> None:
        """
        Clear the session cache.

        Args:
            force: Whether to directly clear the session cache. \
                `force=False` will only clear the session cache the next time the server runs out of memory while \
                still allowing you to add new content in the session cache in the meantime.
        """
        self._session_cache.clear()
        if force:
            self.restart()

    def __del__(self):
        # delete the session cache
        self._session_cache.clear()
        super().__del__()

    def _run_dict_backoff(self, request: dict, verbose: bool, timeout: float | None, restart_counter: int = 0) -> dict:
        if (psutil.virtual_memory().percent >= 100 * self._max_total_memory) or (
            self.is_alive()
            and self._proc is not None
            and self.config.memory_hard_limit_mb is not None
            and self._max_process_memory is not None
            and get_total_memory_usage(psutil.Process(self._proc.pid))
            >= self._max_process_memory * self.config.memory_hard_limit_mb * 1024**2
        ):
            self.kill()
            if restart_counter >= self._max_restart_attempts:
                raise MemoryError(
                    f"Memory usage is too high. We attempted to restart the Lean server {self._max_restart_attempts} times without success."
                )
            if verbose:
                logger.info("Memory usage is too high. Reloading the Lean server...")
            sleep(2**restart_counter)
            return self._run_dict_backoff(
                request=request, verbose=verbose, timeout=timeout, restart_counter=restart_counter + 1
            )

        if not self.is_alive():
            self.start()
            self._session_cache.reload(self, timeout_per_state=DEFAULT_TIMEOUT, verbose=verbose)

        # Replace the negative environment / proof state ids with the corresponding REPL ids
        if request.get("env", 0) < 0:
            request = deepcopy(request)
            request["env"] = self._get_repl_state_id(request["env"])
        if request.get("proofState", 0) < 0:
            request = deepcopy(request)
            request["proofState"] = self._get_repl_state_id(request["proofState"])

        return super().run_dict(request=request, verbose=verbose, timeout=timeout)

    def run_dict(self, request: dict, verbose: bool = False, timeout: float | None = DEFAULT_TIMEOUT) -> dict:
        """
        Warning:
            This method is not available with automated memory management. Please use `run`, or use `run_dict` from the `LeanServer` class.

        Raises:
            NotImplementedError: This method is not available with automated memory management.
                Please use `run`, or use `run_dict` from the `LeanServer` class.
        """
        raise NotImplementedError(
            "This method is not available with automated memory management. Please use `run`, or use `run_dict` from the `LeanServer` class."
        )

    # Type hints for IDE and static analysis
    @overload
    def run(
        self,
        request: Command | FileCommand | PickleEnvironment | UnpickleEnvironment,
        *,
        verbose: bool = False,
        timeout: float | None = DEFAULT_TIMEOUT,
        add_to_session_cache: bool = False,
    ) -> CommandResponse | LeanError: ...

    @overload
    def run(
        self,
        request: ProofStep | PickleProofState | UnpickleProofState,
        *,
        verbose: bool = False,
        timeout: float | None = DEFAULT_TIMEOUT,
        add_to_session_cache: bool = False,
    ) -> ProofStepResponse | LeanError: ...

    def run(
        self,
        request: BaseREPLQuery,
        *,
        verbose: bool = False,
        timeout: float | None = DEFAULT_TIMEOUT,
        add_to_session_cache: bool = False,
    ) -> BaseREPLResponse | LeanError:
        """
        Run a Lean REPL request with optional session caching.

        Args:
            request: The Lean REPL request to execute. Must be one of the following types:
                `Command`, `File`, `ProofStep`, `PickleEnvironment`, `PickleProofState`,
                `UnpickleEnvironment`, or `UnpickleProofState`
            verbose: Whether to print additional information
            timeout: The timeout for the request in seconds

        Returns:
            Depending on the request type, the response will be one of the following:
                `CommandResponse`, `ProofStepResponse`, or `LeanError`
        """
        request = self._augment_request(request)
        request_dict = request.model_dump(exclude_none=True, by_alias=True)
        result_dict = self._run_dict_backoff(request=request_dict, verbose=verbose, timeout=timeout)

        if set(result_dict.keys()) == {"message"} or result_dict == {}:
            response = LeanError.model_validate(result_dict)
        elif isinstance(request, (Command, FileCommand, PickleEnvironment, UnpickleEnvironment)):
            response = CommandResponse.model_validate(result_dict)
            if add_to_session_cache:
                new_env_id = self._session_cache.add(self, request, response, verbose=verbose)
                response = response.model_copy(update={"env": new_env_id})
        elif isinstance(request, (ProofStep, PickleProofState, UnpickleProofState)):
            response = ProofStepResponse.model_validate(result_dict)
            if add_to_session_cache:
                new_proof_state_id = self._session_cache.add(self, request, response, verbose=verbose)
                response = response.model_copy(update={"proofState": new_proof_state_id})
        else:
            response = BaseREPLResponse.model_validate(result_dict)

        return response

    # Type hints for IDE and static analysis
    @overload
    async def async_run(
        self,
        request: Command | FileCommand | PickleEnvironment | UnpickleEnvironment,
        *,
        verbose: bool = False,
        timeout: float | None = DEFAULT_TIMEOUT,
        add_to_session_cache: bool = False,
    ) -> CommandResponse | LeanError: ...

    @overload
    async def async_run(
        self,
        request: ProofStep | PickleProofState | UnpickleProofState,
        *,
        verbose: bool = False,
        timeout: float | None = DEFAULT_TIMEOUT,
        add_to_session_cache: bool = False,
    ) -> ProofStepResponse | LeanError: ...

    async def async_run(
        self,
        request: BaseREPLQuery,
        *,
        verbose: bool = False,
        timeout: float | None = DEFAULT_TIMEOUT,
        add_to_session_cache: bool = False,
    ) -> BaseREPLResponse | LeanError:
        """
        Asynchronous version of `run()` for AutoLeanServer. Runs the blocking `run()` in a thread pool.

        Args:
            request: The Lean REPL request to execute. Must be one of the following types:
                `Command`, `FileCommand`, `ProofStep`, `PickleEnvironment`, `PickleProofState`,
                `UnpickleEnvironment`, or `UnpickleProofState`
            verbose: Whether to print additional information
            timeout: The timeout for the request in seconds
            add_to_session_cache: Whether to add the command to the session cache. \
                If `True`, the command will be added to the session cache and the response will be updated with the new environment or proof state id.

        Returns:
            Depending on the request type, the response will be one of the following:
                `CommandResponse`, `ProofStepResponse`, or `LeanError`
        """
        return await asyncio.to_thread(
            self.run,
            request,  # type: ignore
            verbose=verbose,
            timeout=timeout,
            add_to_session_cache=add_to_session_cache,
        )
