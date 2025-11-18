"""
**Module:** `lean_interact.sessioncache`

This module implements the session cache classes responsible for storing and retrieving Lean proof states and environments.
Session cache is used internally by the `AutoLeanServer` class.
It enables efficient resumption of proofs and environments after server restarts, timeouts, and automated recover from crashes.
Additionally, `ReplaySessionCache` and `PickleSessionCache` are thread-safe and can be used to share session states between multiple `AutoLeanServer` instances within the same process.
While by default `AutoLeanServer` instantiates a fresh `ReplaySessionCache` instance, you can also use a custom one.
It can be useful to implement more advanced caching strategies, shareable cache across processes / compute nodes, ...

Examples:
    ```python
    from lean_interact.sessioncache import PickleSessionCache, ReplaySessionCache
    from lean_interact.server import AutoLeanServer

    # Create a session cache
    replay_cache = ReplaySessionCache()
    pickle_cache = PickleSessionCache(working_dir="./cache")

    # Create Lean servers with a given cache
    server = AutoLeanServer(config=..., session_cache=replay_cache)
    legacy = AutoLeanServer(config=..., session_cache=pickle_cache)
    ```
"""

import hashlib
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from os import PathLike
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING, Iterator, cast
from uuid import uuid4
from weakref import WeakKeyDictionary

if TYPE_CHECKING:
    from lean_interact.server import LeanServer

from filelock import FileLock

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

ReplayableRequest = Command | FileCommand | ProofStep | UnpickleEnvironment | UnpickleProofState


@dataclass(kw_only=True)
class SessionState:
    session_id: int
    is_proof_state: bool
    repl_ids: dict[str, int | None] = field(default_factory=dict)


class BaseSessionCache(ABC):
    def __init__(self):
        self._lock = RLock()
        self._server_keys: WeakKeyDictionary["LeanServer", str] = WeakKeyDictionary()

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

    @abstractmethod
    def get_repl_id(self, session_state_id: int, lean_server: "LeanServer") -> int | None: ...

    def _get_server_key(self, lean_server: "LeanServer") -> str:
        with self._lock:
            key = self._server_keys.get(lean_server)
            if key is None:
                key = uuid4().hex
                self._server_keys[lean_server] = key
            return key


@dataclass(kw_only=True)
class ReplaySessionState(SessionState):
    request: BaseREPLQuery
    _materializing_servers: set[str] = field(default_factory=set, repr=False)


class ReplaySessionCache(BaseSessionCache):
    """Automatically replays cached Lean commands to restore proof states and environments when needed.

    Args:
        lazy: When `True` (default) cached states are re-materialized on demand the next time
            they are requested. When `False`, `reload()` eagerly replays every cached command for
            the target `LeanServer`, which can reduce latency after restarts at the cost of
            upfront work.
    """

    def __init__(self, lazy: bool = True):
        super().__init__()
        self._cache: dict[int, ReplaySessionState] = {}
        self._state_counter = 0
        self._lazy = lazy

    def _get_state_repl_id(self, state: SessionState, lean_server: "LeanServer") -> int | None:
        with self._lock:
            return state.repl_ids.get(self._get_server_key(lean_server))

    def _set_state_repl_id(self, state: SessionState, lean_server: "LeanServer", repl_id: int | None) -> None:
        with self._lock:
            state.repl_ids[self._get_server_key(lean_server)] = repl_id

    def _materialize_state(
        self,
        lean_server: "LeanServer",
        state: ReplaySessionState,
        *,
        timeout: int | float | None = None,
        verbose: bool = False,
    ) -> None:
        with self._lock:
            if self._get_state_repl_id(state, lean_server) is not None:
                return
            server_key = self._get_server_key(lean_server)
            if server_key in state._materializing_servers:
                raise RuntimeError(f"Session state {state.session_id} is already being materialized.")
            request_for_server = cast(ReplayableRequest, state.request)
            state._materializing_servers.add(server_key)
        try:
            response = lean_server.run(request_for_server, verbose=verbose, timeout=timeout)
        finally:
            with self._lock:
                state._materializing_servers.discard(server_key)

        if isinstance(response, LeanError):
            raise ValueError(
                f"Could not replay the cached state. The Lean server returned an error: {response.message}"
            )
        if state.is_proof_state:
            if not isinstance(response, ProofStepResponse):
                raise ValueError(
                    "Could not replay the cached proof state. The Lean server returned an unexpected response."
                )
            self._set_state_repl_id(state, lean_server, response.proof_state)
        else:
            if not isinstance(response, CommandResponse):
                raise ValueError(
                    "Could not replay the cached environment. The Lean server returned an unexpected response."
                )
            self._set_state_repl_id(state, lean_server, response.env)

    def add(
        self,
        lean_server: "LeanServer",
        request: BaseREPLQuery,
        response: BaseREPLResponse,
        verbose: bool = False,
    ) -> int:
        if isinstance(response, ProofStepResponse):
            repl_id = response.proof_state
            is_proof_state = True
        elif isinstance(response, CommandResponse):
            repl_id = response.env
            is_proof_state = False
        else:
            raise NotImplementedError(
                f"Cannot store the session state for unsupported response of type {type(response).__name__}."
            )

        request_copy = request.model_copy(deep=True)
        with self._lock:
            self._state_counter -= 1
            session_id = self._state_counter
            self._cache[session_id] = ReplaySessionState(
                session_id=session_id,
                is_proof_state=is_proof_state,
                request=request_copy,
            )
        self._set_state_repl_id(self._cache[session_id], lean_server, repl_id)
        return session_id

    def remove(self, session_state_id: int, verbose: bool = False) -> None:
        with self._lock:
            self._cache.pop(session_state_id, None)

    def reload(
        self,
        lean_server: "LeanServer",
        timeout_per_state: int | float | None,
        verbose: bool = False,
    ) -> None:
        with self._lock:
            states = list(self._cache.values())
        for state in states:
            self._set_state_repl_id(state, lean_server, None)
            if not self._lazy:
                self._materialize_state(
                    lean_server,
                    state,
                    timeout=timeout_per_state,
                    verbose=verbose,
                )

    def is_empty(self) -> bool:
        with self._lock:
            return len(self._cache) == 0

    def clear(self, verbose: bool = False) -> None:
        with self._lock:
            self._cache.clear()

    def __iter__(self) -> Iterator[ReplaySessionState]:
        with self._lock:
            return iter(list(self._cache.values()))

    def __contains__(self, session_id: int) -> bool:
        with self._lock:
            return session_id in self._cache

    def __getitem__(self, session_id: int) -> ReplaySessionState:
        with self._lock:
            return self._cache[session_id]

    def keys(self) -> list[int]:
        with self._lock:
            return list(self._cache.keys())

    def get_repl_id(self, session_state_id: int, lean_server: "LeanServer") -> int | None:
        state = self.__getitem__(session_state_id)
        repl_id = self._get_state_repl_id(state, lean_server)
        if repl_id is None:
            self._materialize_state(lean_server, state)
            repl_id = self._get_state_repl_id(state, lean_server)
        return repl_id


@dataclass(kw_only=True)
class PickleSessionState(SessionState):
    pickle_file: str


class PickleSessionCache(BaseSessionCache):
    """A session cache based on the local file storage and the REPL pickle feature.

    Warning:
        Pickled Lean states are not fully reliable yet and are not always reloaded correctly. Prefer
        `ReplaySessionCache` unless you explicitly need serialized states on disk.
    """

    def __init__(self, working_dir: str | PathLike):
        super().__init__()
        self._cache: dict[int, PickleSessionState] = {}
        self._state_counter = 0
        self._working_dir = Path(working_dir)

    def _set_state_repl_id(self, state: SessionState, lean_server: "LeanServer", repl_id: int | None) -> None:
        with self._lock:
            state.repl_ids[self._get_server_key(lean_server)] = repl_id

    def _get_state_repl_id(self, state: SessionState, lean_server: "LeanServer") -> int | None:
        with self._lock:
            return state.repl_ids.get(self._get_server_key(lean_server))

    def add(
        self, lean_server: "LeanServer", request: BaseREPLQuery, response: BaseREPLResponse, verbose: bool = False
    ) -> int:
        with self._lock:
            self._state_counter -= 1
            session_id = self._state_counter
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

            with self._lock:
                self._cache[session_id] = PickleSessionState(
                    session_id=session_id,
                    pickle_file=str(pickle_file),
                    is_proof_state=is_proof_state,
                )
            self._set_state_repl_id(self._cache[session_id], lean_server, repl_id)
        return session_id

    def remove(self, session_state_id: int, verbose: bool = False) -> None:
        with self._lock:
            state_cache = self._cache.pop(session_state_id, None)
        if state_cache is not None:
            pickle_file = state_cache.pickle_file
            with FileLock(f"{pickle_file}.lock", timeout=60):
                if os.path.exists(pickle_file):
                    os.remove(pickle_file)

    def reload(self, lean_server: "LeanServer", timeout_per_state: int | float | None, verbose: bool = False) -> None:
        with self._lock:
            state_snapshot = list(self._cache.values())
        for state_data in state_snapshot:
            # Use file lock when accessing the pickle file to prevent cache invalidation
            # from multiple concurrent processes
            with FileLock(
                f"{state_data.pickle_file}.lock", timeout=float(timeout_per_state) if timeout_per_state else -1
            ):
                if state_data.is_proof_state:
                    cmd = UnpickleProofState(
                        unpickle_proof_state_from=state_data.pickle_file,
                        env=self._get_state_repl_id(state_data, lean_server),
                    )
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
                    self._set_state_repl_id(state_data, lean_server, result.env)
                elif isinstance(result, ProofStepResponse):
                    self._set_state_repl_id(state_data, lean_server, result.proof_state)
                else:
                    raise ValueError(
                        f"Could not reload the session cache. The Lean server returned an unexpected response: {result}"
                    )

    def is_empty(self) -> bool:
        with self._lock:
            return len(self._cache) == 0

    def clear(self, verbose: bool = False) -> None:
        with self._lock:
            state_snapshot = list(self._cache.values())
        for state_data in state_snapshot:
            self.remove(session_state_id=state_data.session_id, verbose=verbose)
        with self._lock:
            assert not self._cache, f"Cache is not empty after clearing: {self._cache}"

    def __iter__(self) -> Iterator[PickleSessionState]:
        with self._lock:
            return iter(list(self._cache.values()))

    def __contains__(self, session_id: int) -> bool:
        with self._lock:
            return session_id in self._cache

    def __getitem__(self, session_id: int) -> PickleSessionState:
        with self._lock:
            return self._cache[session_id]

    def keys(self) -> list[int]:
        with self._lock:
            return list(self._cache.keys())

    def get_repl_id(self, session_state_id: int, lean_server: "LeanServer") -> int | None:
        state = self.__getitem__(session_state_id)
        return self._get_state_repl_id(state, lean_server)
