import gc
import hashlib
import json
import os
from copy import deepcopy
from dataclasses import dataclass
from time import sleep
from typing import overload

import pexpect
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
from lean_interact.utils import _limit_memory, get_total_memory_usage, logger

DEFAULT_TIMEOUT: int | None = None


class LeanServer:
    config: LeanREPLConfig
    _proc: pexpect.spawn | None

    def __init__(self, config: LeanREPLConfig):
        """
        This class is a Python wrapper for the Lean REPL. Please refer to the \
        [Lean REPL documentation](https://github.com/leanprover-community/repl) to learn more about the Lean REPL commands.

        \u26a0 Multiprocessing: instantiate one config before starting multiprocessing. Then instantiate one `LeanServer`
        per process by passing the config instance to the constructor. This will ensure that the REPL is already set up
        for your specific environment and avoid concurrency conflicts.

        Args:
            config: The configuration for the Lean server.
        """
        self.config = config
        assert self.config.is_setup(), "The Lean environment has not been set up properly."
        self._proc = None
        self.start()

    @property
    def lean_version(self) -> str | None:
        return self.config.lean_version

    def start(self) -> None:
        self._proc = pexpect.spawn(
            "/bin/bash",
            cwd=self.config._working_dir,
            encoding="utf-8",
            codec_errors="replace",
            echo=False,
            preexec_fn=lambda: _limit_memory(self.config.memory_hard_limit_mb),
        )
        self._proc.delaybeforesend = None
        # `stty -icanon` is required to handle arbitrary long inputs in the Lean REPL
        self._proc.sendline("stty -icanon")
        self._proc.sendline(f"lake env {self.config._cache_repl_dir}/.lake/build/bin/repl || exit")

    def is_alive(self) -> bool:
        return hasattr(self, "_proc") and self._proc is not None and self._proc.isalive()

    def kill(self) -> None:
        if hasattr(self, "_proc") and self._proc:
            self._proc.terminate(force=True)
            del self._proc
        gc.collect()

    def restart(self) -> None:
        self.kill()
        self.start()

    def __del__(self):
        self.kill()

    def _execute_cmd_in_repl(self, json_query: str, verbose: bool, timeout: float | None) -> str:
        """Send JSON queries to the Lean REPL and wait for the standard delimiter."""
        assert self._proc is not None
        if verbose:
            logger.info("Sending query: %s", json_query)
        self._proc.send(json_query + "\n\n")
        self._proc.expect_exact("\r\n\r\n", timeout=timeout)
        return self._proc.before or ""

    def _parse_repl_output(self, raw_output: str, verbose: bool) -> dict:
        """Clean up raw REPL output and parse JSON response."""
        if verbose:
            logger.info("Server raw output: `%s", raw_output)
        output = raw_output.replace("\r\n", "\n")
        output = output[output.find('{"') :] if '{"' in output else ""
        if verbose:
            logger.info("Server cleaned output: `%s", output)
        try:
            return json.loads(output)
        except json.JSONDecodeError as e:
            raise json.JSONDecodeError(
                msg=f"Could not parse the Lean server output: `{repr(output)}`.", doc=e.doc, pos=e.pos
            ) from e

    def run_dict(self, request: dict, verbose: bool = False, timeout: float | None = DEFAULT_TIMEOUT) -> dict:
        """
        Run a Lean REPL dictionary request and return the Lean server output as a dictionary.
        Args:
            request: The Lean REPL request to execute. Must be a dictionary.
            verbose: Whether to print additional information during the verification process.
            timeout: The timeout for the request in seconds
        Returns:
            The output of the Lean server as a dictionary.
        """
        if not self.is_alive():
            raise ChildProcessError("The Lean server is not running.")

        json_query = json.dumps(request, ensure_ascii=False)
        try:
            raw_output = self._execute_cmd_in_repl(json_query, verbose, timeout)
        except pexpect.exceptions.TIMEOUT as e:
            self.kill()
            raise TimeoutError(f"The Lean server did not respond in time ({timeout=}) and is now killed.") from e
        except pexpect.exceptions.EOF as e:
            self.kill()
            raise ConnectionAbortedError(
                "The Lean server closed unexpectedly. Possible reasons (not exhaustive):\n"
                "- An uncaught exception in the Lean REPL (for example, an unexistent file has been requested)\n"
                "- Not enough memory and/or compute available\n"
                "- The cached Lean REPL is corrupted. In this case, clear the cache"
                " using the `clear_cache` (`from pyleanrepl import clear_cache`) method."
            ) from e

        return self._parse_repl_output(raw_output, verbose)

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

        Args:
            request: The Lean REPL request to execute. Must be one of the following types:
                - `Command`
                - `File`
                - `ProofStep`
                - `PickleEnvironment`
                - `PickleProofState`
                - `UnpickleEnvironment`
                - `UnpickleProofState`
            verbose: Whether to print additional information
            timeout: The timeout for the request in seconds

        Returns:
            Depending on the request type, the response will be one of the following:
            - `CommandResponse`
            - `ProofStepResponse`
            - `LeanError`
        """
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


@dataclass
class _SessionState:
    session_id: int
    repl_id: int
    pickle_file: str
    is_proof_state: bool


class AutoLeanServer(LeanServer):
    def __init__(
        self,
        config: LeanREPLConfig,
        max_total_memory: float = 0.8,
        max_process_memory: float | None = 0.8,
        max_restart_attempts: int = 5,
    ):
        """
        This class is a Python wrapper for the Lean REPL. `AutoLeanServer` differs from `LeanServer` by automatically \
        restarting when it runs out of memory to clear Lean environment states. \
        It also automatically recovers from timeouts (). \
        An exponential backoff strategy is used to restart the server, making this class slightly more friendly for multiprocessing
        than `LeanServer` when multiple instances are competing for resources. \
        Please refer to the original [Lean REPL documentation](https://github.com/leanprover-community/repl) to learn more about the \
        Lean REPL commands.

        A session cache is implemented to keep user-selected environment / proof states across these automatic restarts. \
        Use the `add_to_session_cache` parameter in the different class methods to add the command to \
        the session cache. `AutoLeanServer` works best when only a few states are cached simultaneously. \
        You can use `remove_from_session_cache` and `clear_session_cache` to clear the session cache. \
        Cached state indices are negative integers starting from -1 to not conflict with the positive integers used by the Lean REPL.

        **Note:** the session cache is specific to each `AutoLeanServer` instance and is cleared when the instance is deleted. \
        If you want truly persistent states, you can use the `pickle` and `unpickle` methods to save and load states to disk.

        \u26a0 Multiprocessing: instantiate the config before starting multiprocessing. Then instantiate one `LeanServer`
        per process by passing the config instance to the constructor. This will ensure that the REPL is already set up
        for your specific environment and avoid concurrency conflicts.

        Args:
            config: The configuration for the Lean server.
            max_total_memory: The maximum proportion of system-wide memory usage (across all processes) before triggering a Lean server restart. This is a soft limit ranging from 0.0 to 1.0, with default 0.8 (80%). When system memory exceeds this threshold, the server restarts to free memory. Particularly useful in multiprocessing environments to prevent simultaneous crashes.
            max_process_memory: The maximum proportion of the memory hard limit (set in `LeanREPLConfig.memory_hard_limit_mb`) that the Lean server process can use before restarting. This soft limit ranges from 0.0 to 1.0, with default 0.8 (80%). Only applied if a hard limit is configured in `LeanREPLConfig`.
            max_restart_attempts: The maximum number of consecutive restart attempts allowed before raising a `MemoryError` exception. Default is 5. The server uses exponential backoff between restart attempts.
        """
        self._state_counter = 0
        self._restart_persistent_session_cache: dict[int, _SessionState] = {}
        self._max_total_memory = max_total_memory
        self._max_process_memory = max_process_memory
        self._max_restart_attempts = max_restart_attempts
        super().__init__(config=config)

    def _get_repl_state_id(self, state_id: int | None) -> int | None:
        if state_id is None:
            return None
        if state_id >= 0:
            return state_id
        return self._restart_persistent_session_cache[state_id].repl_id

    def _reload_session_cache(self, verbose: bool = False) -> None:
        """
        Reload the session cache. This method should be called only after a restart of the Lean REPL.
        """
        for state_data in self._restart_persistent_session_cache.values():
            if state_data.is_proof_state:
                cmd = UnpickleProofState(unpickle_proof_state_from=state_data.pickle_file, env=state_data.repl_id)
            else:
                cmd = UnpickleEnvironment(unpickle_env_from=state_data.pickle_file)
            result = self.run(
                cmd,
                verbose=verbose,
                timeout=DEFAULT_TIMEOUT,
                add_to_session_cache=False,
            )
            if isinstance(result, LeanError):
                raise ValueError(
                    f"Could not reload the session cache. The Lean server returned an error: {result.message}"
                )
            elif isinstance(result, CommandResponse):
                state_data.repl_id = result.env
            elif isinstance(result, ProofStepResponse):
                state_data.repl_id = result.proof_state
            else:
                raise ValueError(
                    f"Could not reload the session cache. The Lean server returned an unexpected response: {result}"
                )

    def restart(self, verbose: bool = False) -> None:
        super().restart()
        self._reload_session_cache(verbose=verbose)

    def remove_from_session_cache(self, session_state_id: int) -> None:
        """
        Remove an environment from the session cache.

        Args:
            env_id: The environment id to remove.
        """
        if (state_cache := self._restart_persistent_session_cache.pop(session_state_id, None)) is not None:
            os.remove(state_cache.pickle_file)

    def clear_session_cache(self, force: bool = False) -> None:
        """
        Clear the session cache.

        Args:
            force: Whether to directly clear the session cache. \
                `force=False` will only clear the session cache the next time the server runs out of memory while \
                still allowing you to add new content in the session cache in the meantime.
        """
        states_data = list(self._restart_persistent_session_cache.values())
        for state_data in states_data:
            self.remove_from_session_cache(session_state_id=state_data.session_id)
        self._restart_persistent_session_cache = {}
        if force:
            self.restart()

    def __del__(self):
        # delete the session cache
        for state_data in self._restart_persistent_session_cache.values():
            try:
                os.remove(state_data.pickle_file)
            except FileNotFoundError:
                pass

        super().__del__()

    def _store_session_cache(
        self, hash_key: str, repl_id: int, is_proof_state: bool = False, verbose: bool = False
    ) -> int:
        self._state_counter -= 1
        process_id = os.getpid()  # use process id to avoid conflicts in multiprocessing
        pickle_file = os.path.join(
            self.config._working_dir,
            f"session_cache/{hashlib.sha256(hash_key.encode()).hexdigest()}_{process_id}.olean",
        )
        os.makedirs(os.path.dirname(pickle_file), exist_ok=True)
        if is_proof_state:
            request = PickleProofState(proof_state=repl_id, pickle_to=pickle_file)
        else:
            request = PickleEnvironment(env=repl_id, pickle_to=pickle_file)

        result = self.run(request, verbose=verbose, timeout=DEFAULT_TIMEOUT)
        if isinstance(result, LeanError):
            raise ValueError(
                f"Could not store the result in the session cache. The Lean server returned an error: {result.message}"
            )

        self._restart_persistent_session_cache[self._state_counter] = _SessionState(
            session_id=self._state_counter,
            repl_id=repl_id,
            pickle_file=pickle_file,
            is_proof_state=is_proof_state,
        )
        return self._state_counter

    def _run_dict_backoff(self, request: dict, verbose: bool, timeout: float | None, restart_counter: int = 0) -> dict:
        if (psutil.virtual_memory().percent >= 100 * self._max_total_memory) or (
            self.is_alive()
            and self._proc is not None
            and self.config.memory_hard_limit_mb is not None
            and self._max_process_memory is not None
            and get_total_memory_usage(psutil.Process())
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
            self._reload_session_cache(verbose=verbose)

        # Replace the negative environment / proof state ids with the corresponding REPL ids
        if request.get("env", 0) < 0:
            request = deepcopy(request)
            request["env"] = self._get_repl_state_id(request["env"])
        if request.get("proofState", 0) < 0:
            request = deepcopy(request)
            request["proofState"] = self._get_repl_state_id(request["proofState"])

        return super().run_dict(request=request, verbose=verbose, timeout=timeout)

    def run_dict(self, request: dict, verbose: bool = False, timeout: float | None = DEFAULT_TIMEOUT) -> dict:
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
                - `Command`
                - `File`
                - `ProofStep`
                - `PickleEnvironment`
                - `PickleProofState`
                - `UnpickleEnvironment`
                - `UnpickleProofState`
            verbose: Whether to print additional information
            timeout: The timeout for the request in seconds

        Returns:
            Depending on the request type, the response will be one of the following:
            - `CommandResponse`
            - `ProofStepResponse`
            - `LeanError`
        """
        request_dict = request.model_dump(exclude_none=True, by_alias=True)
        result_dict = self._run_dict_backoff(request=request_dict, verbose=verbose, timeout=timeout)

        if set(result_dict.keys()) == {"message"} or result_dict == {}:
            result = LeanError.model_validate(result_dict)
        elif isinstance(request, (Command, FileCommand, PickleEnvironment, UnpickleEnvironment)):
            result = CommandResponse.model_validate(result_dict)
            if add_to_session_cache:
                env_id = result.env
                hash_key = f"request_{type(request).__name__}_{id(request)}"
                new_env_id = self._store_session_cache(
                    hash_key=hash_key, repl_id=env_id, is_proof_state=False, verbose=verbose
                )
                result = result.model_copy(update={"env": new_env_id})
        elif isinstance(request, (ProofStep, PickleProofState, UnpickleProofState)):
            result = ProofStepResponse.model_validate(result_dict)
            if add_to_session_cache:
                proof_state_id = result.proof_state
                hash_key = f"proofstep_{type(request).__name__}_{id(request)}"
                new_proof_state_id = self._store_session_cache(
                    hash_key=hash_key, repl_id=proof_state_id, is_proof_state=True, verbose=verbose
                )
                result = result.model_copy(update={"proofState": new_proof_state_id})
        else:
            result = BaseREPLResponse.model_validate(result_dict)

        return result
