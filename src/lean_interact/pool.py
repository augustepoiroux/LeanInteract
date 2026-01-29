"""
**Module:** `lean_interact.pool`

This module provides the `LeanServerPool` class, which manages a pool of `AutoLeanServer` instances
sharing a common `ReplaySessionCache`. This allows efficient distribution of Lean commands across
multiple persistent REPL processes.
"""

from __future__ import annotations

import asyncio
import multiprocessing as mp
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, overload

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
from lean_interact.server import DEFAULT_TIMEOUT, AutoLeanServer
from lean_interact.sessioncache import ReplaySessionCache


class LeanServerPool:
    """
    A pool of `AutoLeanServer` instances sharing a `ReplaySessionCache`.
    """

    def __init__(
        self,
        config: LeanREPLConfig,
        num_workers: int | None = None,
        max_total_memory: float = 0.8,
        max_process_memory: float | None = 0.8,
        max_restart_attempts: int = 5,
    ):
        """
        Initialize the Lean server pool.

        Args:
            config: The configuration for the Lean servers.
            num_workers: The number of workers to start. Defaults to `cpu_count() - 1`.
            max_total_memory: Passed to `AutoLeanServer`.
            max_process_memory: Passed to `AutoLeanServer`.
            max_restart_attempts: Passed to `AutoLeanServer`.
        """
        self.config = config
        self.num_workers = num_workers or max(1, mp.cpu_count() - 1)
        self.session_cache = ReplaySessionCache(lazy=True)

        self._lock = threading.Lock()
        self._workers: list[AutoLeanServer] = []
        self._free_workers: list[AutoLeanServer] = []
        self._workers_cond = threading.Condition(self._lock)
        self._async_cond: asyncio.Condition | None = None  # Lazy init

        def _create_server(_: int) -> AutoLeanServer:
            return AutoLeanServer(
                config=config,
                max_total_memory=max_total_memory,
                max_process_memory=max_process_memory,
                max_restart_attempts=max_restart_attempts,
                session_cache=self.session_cache,
            )

        with ThreadPoolExecutor(max_workers=self.num_workers) as executor:
            self._workers = list(executor.map(_create_server, range(self.num_workers)))

        self._free_workers = list(self._workers)

    def close(self) -> None:
        """Close all workers and the session cache."""
        with self._lock:
            # We work on a copy to avoid concurrent modification issues if any
            workers_to_kill = list(self._workers)
            self._workers.clear()
            self._free_workers.clear()

        def _kill_worker(w: AutoLeanServer) -> None:
            try:
                w.kill()
            except Exception:
                pass

        if workers_to_kill:
            with ThreadPoolExecutor(max_workers=len(workers_to_kill)) as executor:
                executor.map(_kill_worker, workers_to_kill)

    def __del__(self) -> None:
        self.close()

    def __enter__(self) -> LeanServerPool:
        return self

    async def __aenter__(self) -> LeanServerPool:
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.close()

    async def __aexit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.close()

    def _try_acquire_worker(self, required_session_id: int | None) -> AutoLeanServer | None:
        """
        Try to acquire a worker from the pool. Returns None if no workers are available.
        Must be called with self._lock or self._workers_cond held.
        """
        if not self._free_workers:
            return None

        # Scheduling strategy
        chosen_worker: AutoLeanServer | None = None

        if required_session_id is not None and required_session_id < 0:
            # Optimized search: find a worker that has the state materialized
            for i, w in enumerate(self._free_workers):
                try:
                    # pylint: disable=protected-access
                    state = self.session_cache._cache.get(required_session_id)
                    if state and self.session_cache._get_state_repl_id(state, w) is not None:
                        chosen_worker = w
                        self._free_workers.pop(i)
                        break
                except Exception:
                    pass

        if chosen_worker is None:
            # Fallback: take the most recently used (LIFO) or just the last one
            chosen_worker = self._free_workers.pop()

        return chosen_worker

    def _acquire_worker_sync(self, required_session_id: int | None = None) -> AutoLeanServer:
        """
        Acquire a worker from the pool, blocking if necessary.
        Tries to pick a worker that has `required_session_id` loaded.
        """
        with self._workers_cond:
            while True:
                worker = self._try_acquire_worker(required_session_id)
                if worker:
                    return worker
                self._workers_cond.wait()

    def _release_worker_sync(self, worker: AutoLeanServer) -> None:
        with self._workers_cond:
            self._free_workers.append(worker)
            self._workers_cond.notify()

    async def _acquire_worker_async(self, required_session_id: int | None = None) -> AutoLeanServer:
        return await asyncio.to_thread(self._acquire_worker_sync, required_session_id)

    async def _release_worker_async(self, worker: AutoLeanServer) -> None:
        return await asyncio.to_thread(self._release_worker_sync, worker)

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
        self,
        request: BaseREPLQuery,
        *,
        verbose: bool = False,
        timeout: float | None = DEFAULT_TIMEOUT,
    ) -> BaseREPLResponse | LeanError:
        """
        Run a command on an available worker.
        """
        # Extract desired env/proofState to optimize worker selection
        req_id: int | None = None
        if isinstance(request, Command):
            req_id = request.env
        elif isinstance(request, ProofStep):
            req_id = request.proof_state

        worker = self._acquire_worker_sync(req_id)
        try:
            return worker.run(request, verbose=verbose, timeout=timeout, add_to_session_cache=True)  # type: ignore
        finally:
            self._release_worker_sync(worker)

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
        self,
        request: BaseREPLQuery,
        *,
        verbose: bool = False,
        timeout: float | None = DEFAULT_TIMEOUT,
    ) -> BaseREPLResponse | LeanError:
        """
        Run a command asynchronously on an available worker.
        """
        req_id: int | None = None
        if isinstance(request, Command):
            req_id = request.env
        elif isinstance(request, ProofStep):
            req_id = request.proof_state

        worker = await self._acquire_worker_async(req_id)
        try:
            return await worker.async_run(request, verbose=verbose, timeout=timeout, add_to_session_cache=True)  # type: ignore
        finally:
            await self._release_worker_async(worker)

    def run_batch(
        self,
        requests: list[BaseREPLQuery],
        *,
        verbose: bool = False,
        timeout_per_cmd: float | None = DEFAULT_TIMEOUT,
        show_progress: bool = False,
    ) -> list[BaseREPLResponse | LeanError | Exception]:
        """
        Run a batch of commands on available workers.
        """
        with ThreadPoolExecutor(max_workers=self.num_workers) as executor:
            futures = [executor.submit(self.run, req, verbose=verbose, timeout=timeout_per_cmd) for req in requests]  # type: ignore
            results = [None] * len(futures)
            if show_progress:
                from tqdm import tqdm  # type: ignore

                for future in tqdm(as_completed(futures), total=len(futures), desc="Running batch"):
                    index = futures.index(future)
                    try:
                        results[index] = future.result()
                    except Exception as e:
                        results[index] = e
            else:
                for future in as_completed(futures):
                    index = futures.index(future)
                    try:
                        results[index] = future.result()
                    except Exception as e:
                        results[index] = e
            return results  # type: ignore

    async def async_run_batch(
        self,
        requests: list[BaseREPLQuery],
        *,
        verbose: bool = False,
        timeout_per_cmd: float | None = DEFAULT_TIMEOUT,
        show_progress: bool = False,
    ) -> list[BaseREPLResponse | LeanError | Exception]:
        """
        Run a batch of commands asynchronously on available workers.
        """
        tasks = [self.async_run(req, verbose=verbose, timeout=timeout_per_cmd) for req in requests]  # type: ignore
        futures = [asyncio.create_task(task) for task in tasks]
        results = [None] * len(futures)
        if show_progress:
            from tqdm.asyncio import tqdm  # type: ignore

            for future in tqdm(asyncio.as_completed(futures), total=len(futures), desc="Running batch"):
                index = futures.index(future)
                try:
                    results[index] = await future
                except Exception as e:
                    results[index] = e
        else:
            for future in asyncio.as_completed(futures):
                index = futures.index(future)
                try:
                    results[index] = await future
                except Exception as e:
                    results[index] = e
        return results  # type: ignore
