from abc import ABC, abstractmethod
from dataclasses import dataclass
from os import PathLike
import os
from typing import Iterator, Any
from filelock import FileLock
import hashlib
from lean_interact.interface import PickleProofState, PickleEnvironment, LeanError


@dataclass
class SessionState:
    session_id: int
    repl_id: int
    pickle_file: str
    is_proof_state: bool


class BaseSessionCache(ABC):
    @abstractmethod
    def __init__(self):
        pass

    @abstractmethod
    def add(self, server, hash_key: str, repl_id: int, is_proof_state: bool = False, verbose: bool = False) -> int:
        """Add a new item into the session cache.

        Will either be a request or a proof state.

        Returns an identifier session_state_id, that can be used to access or remove the item."""
        pass

    @abstractmethod
    def remove(self, session_state_id: int, verbose: bool = False) -> None:
        """Remove an item from the session cache."""
        pass

    @abstractmethod
    def clear(self, verbose: bool = False) -> None:
        pass

    @abstractmethod
    def __iter__(self) -> Iterator[SessionState]:
        pass

    @abstractmethod
    def __contains__(self, item: Any) -> bool:
        pass

    @abstractmethod
    def __getitem__(self, item: Any) -> SessionState:
        pass


class DictSessionCache(BaseSessionCache):
    """A session cache based on the local file storage.

    Will maintain a separate session cache per server."""
    def __init__(self, working_dir: str | PathLike):
        self._cache: dict[int, SessionState] = {}
        self._state_counter = 0
        self._working_dir = working_dir

    def add(self, server, hash_key: str, repl_id: int, is_proof_state: bool = False, verbose: bool = False) -> None:
        self._state_counter -= 1
        process_id = os.getpid()  # use process id to avoid conflicts in multiprocessing
        pickle_file = os.path.join(
            self._working_dir,
            f"session_cache/{hashlib.sha256(hash_key.encode()).hexdigest()}_{process_id}.olean",
        )
        os.makedirs(os.path.dirname(pickle_file), exist_ok=True)
        if is_proof_state:
            request = PickleProofState(proof_state=repl_id, pickle_to=pickle_file)
        else:
            request = PickleEnvironment(env=repl_id, pickle_to=pickle_file)

        # Use file lock when accessing the pickle file to prevent cache invalidation
        # from concurrent access
        with FileLock(f"{pickle_file}.lock", timeout=60):
            result = server.run(request, verbose=verbose)
            if isinstance(result, LeanError):
                raise ValueError(
                    f"Could not store the result in the session cache. The Lean server returned an error: {result.message}"
                )

            self._cache[self._state_counter] = SessionState(
                session_id=self._state_counter,
                repl_id=repl_id,
                pickle_file=pickle_file,
                is_proof_state=is_proof_state,
            )

    def remove(self, session_state_id: int, verbose: bool = False) -> None:
        if (state_cache := self._cache.pop(session_state_id, None)) is not None:
            pickle_file = state_cache.pickle_file
            with FileLock(f"{pickle_file}.lock", timeout=60):
                if os.path.exists(pickle_file):
                    os.remove(pickle_file)

    def clear(self, verbose: bool = False) -> None:
        for state_data in self:
            self.remove(session_state_id=state_data.session_id)
        assert not self._cache

    def __iter__(self) -> Iterator[SessionState]:
        return iter(self._cache.values())

    def __contains__(self, item: Any) -> bool:
        return item in self._cache

    def __getitem__(self, item: Any) -> SessionState:
        return self._cache[item]
