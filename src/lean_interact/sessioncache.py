"""
**Module:** `lean_interact.sessioncache`

This module implements the session cache classes responsible for storing and retrieving Lean proof states and environments.
Session cache is used internally by the `AutoLeanServer` class.
It enables efficient resumption of proofs and environments after server restarts, timeouts, and automated recover from crashes.
While by default `AutoLeanServer` instantiates a fresh `PickleSessionCache` instance, you can also use a custom one.
It can be useful to share a session cache between multiple `AutoLeanServer` instances, or to use a custom session cache implementation.

Examples:
    ```python
    from lean_interact.sessioncache import PickleSessionCache
    from lean_interact.server import AutoLeanServer

    # Create a session cache
    cache = PickleSessionCache(working_dir="./cache")

    # Create a Lean server with the cache
    server = AutoLeanServer(config=..., session_cache=cache)
    ```
"""

import hashlib
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from os import PathLike
from pathlib import Path
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:
    from lean_interact.server import LeanServer

from filelock import FileLock

from lean_interact.interface import (
    BaseREPLQuery,
    BaseREPLResponse,
    CommandResponse,
    LeanError,
    PickleEnvironment,
    PickleProofState,
    ProofStepResponse,
    UnpickleEnvironment,
    UnpickleProofState,
)


@dataclass
class SessionState:
    session_id: int
    repl_id: int
    is_proof_state: bool


class BaseSessionCache(ABC):
    @abstractmethod
    def __init__(self):
        """Initialize the session cache."""

    @abstractmethod
    def add(
        self, lean_server: "LeanServer", request: BaseREPLQuery, response: BaseREPLResponse, verbose: bool = False
    ) -> int:
        """Add a new item into the session cache.

        Args:
            lean_server: The Lean server to use.
            request: The request to send to the Lean server.
            response: The response from the Lean server.
            verbose: Whether to print verbose output.

        Returns:
            An identifier session_state_id, that can be used to access or remove the item.
        """

    @abstractmethod
    def remove(self, session_state_id: int, verbose: bool = False) -> None:
        """Remove an item from the session cache.

        Args:
            session_state_id: The identifier of the item to remove.
            verbose: Whether to print verbose output.
        """

    @abstractmethod
    def reload(self, lean_server: "LeanServer", timeout_per_state: int | float | None, verbose: bool = False) -> None:
        """Reload the session cache.
        This is useful when the Lean server has been restarted and the session cache
        needs to be reloaded.

        Args:
            lean_server: The Lean server to use.
            timeout_per_state: The timeout for each state in seconds.
            verbose: Whether to print verbose output.
        """

    @abstractmethod
    def is_empty(self) -> bool:
        """Check if the session cache is empty."""

    @abstractmethod
    def clear(self, verbose: bool = False) -> None:
        """Clear the session cache by removing all items.

        Args:
            verbose: Whether to print verbose output.
        """

    @abstractmethod
    def __iter__(self) -> Iterator[SessionState]: ...

    @abstractmethod
    def __contains__(self, session_id: int) -> bool: ...

    @abstractmethod
    def __getitem__(self, session_id: int) -> SessionState: ...

    @abstractmethod
    def keys(self) -> list[int]:
        """Get all keys (session state IDs) currently in the cache.

        Returns:
            A list of all session state IDs.
        """


@dataclass
class PickleSessionState(SessionState):
    pickle_file: str


class PickleSessionCache(BaseSessionCache):
    """A session cache based on the local file storage and the REPL pickle feature."""

    def __init__(self, working_dir: str | PathLike):
        self._cache: dict[int, PickleSessionState] = {}
        self._state_counter = 0
        self._working_dir = Path(working_dir)

    def add(
        self, lean_server: "LeanServer", request: BaseREPLQuery, response: BaseREPLResponse, verbose: bool = False
    ) -> int:
        self._state_counter -= 1
        process_id = os.getpid()  # use process id to avoid conflicts in multiprocessing
        hash_key = f"request_{type(request).__name__}_{id(request)}"
        pickle_file = (
            self._working_dir / "session_cache" / f"{hashlib.sha256(hash_key.encode()).hexdigest()}_{process_id}.olean"
        )
        pickle_file.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(response, ProofStepResponse):
            repl_id = response.proof_state
            is_proof_state = True
            request = PickleProofState(proof_state=response.proof_state, pickle_to=str(pickle_file))
        elif isinstance(response, CommandResponse):
            repl_id = response.env
            is_proof_state = False
            request = PickleEnvironment(env=response.env, pickle_to=str(pickle_file))
        else:
            raise NotImplementedError(
                f"Cannot pickle the session state for unsupported request of type {type(request).__name__}."
            )

        # Use file lock when accessing the pickle file to prevent cache invalidation
        # from concurrent access
        with FileLock(f"{pickle_file}.lock", timeout=60):
            response_pickle = lean_server.run(request, verbose=verbose)
            if isinstance(response_pickle, LeanError):
                raise ValueError(
                    f"Could not store the result in the session cache. The Lean server returned an error: {response_pickle.message}"
                )

            self._cache[self._state_counter] = PickleSessionState(
                session_id=self._state_counter,
                repl_id=repl_id,
                pickle_file=str(pickle_file),
                is_proof_state=is_proof_state,
            )
        return self._state_counter

    def remove(self, session_state_id: int, verbose: bool = False) -> None:
        if (state_cache := self._cache.pop(session_state_id, None)) is not None:
            pickle_file = state_cache.pickle_file
            with FileLock(f"{pickle_file}.lock", timeout=60):
                if os.path.exists(pickle_file):
                    os.remove(pickle_file)

    def reload(self, lean_server: "LeanServer", timeout_per_state: int | float | None, verbose: bool = False) -> None:
        for state_data in self:
            # Use file lock when accessing the pickle file to prevent cache invalidation
            # from multiple concurrent processes
            with FileLock(
                f"{state_data.pickle_file}.lock", timeout=float(timeout_per_state) if timeout_per_state else -1
            ):
                if state_data.is_proof_state:
                    cmd = UnpickleProofState(unpickle_proof_state_from=state_data.pickle_file, env=state_data.repl_id)
                else:
                    cmd = UnpickleEnvironment(unpickle_env_from=state_data.pickle_file)
                result = lean_server.run(
                    cmd,
                    verbose=verbose,
                    timeout=timeout_per_state,
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

    def is_empty(self) -> bool:
        return len(self._cache) == 0

    def clear(self, verbose: bool = False) -> None:
        for state_data in list(self):
            self.remove(session_state_id=state_data.session_id, verbose=verbose)
        assert not self._cache, f"Cache is not empty after clearing: {self._cache}"

    def __iter__(self) -> Iterator[PickleSessionState]:
        return iter(self._cache.values())

    def __contains__(self, session_id: int) -> bool:
        return session_id in self._cache

    def __getitem__(self, session_id: int) -> PickleSessionState:
        return self._cache[session_id]

    def keys(self) -> list[int]:
        return list(self._cache.keys())
