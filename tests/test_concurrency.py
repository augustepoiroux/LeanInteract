import asyncio
import multiprocessing as mp
import os
from os import PathLike
import shutil
import tempfile
import threading
import time
import unittest
from unittest import mock

from filelock import FileLock, Timeout

from lean_interact import AutoLeanServer, LeanREPLConfig
from lean_interact.config import BaseTempProject
from lean_interact.interface import Command, CommandResponse
from lean_interact.server import LeanServer
from lean_interact.utils import DEFAULT_REPL_GIT_URL


# Helper function for testing config creation in a separate process
def create_config_process(cache_dir: str | PathLike, lean_version: str = "v4.18.0", verbose: bool = False):
    """Function that attempts to create a LeanREPLConfig instance."""
    try:
        # This should timeout if another process is already holding the lock
        LeanREPLConfig(lean_version=lean_version, cache_dir=str(cache_dir), verbose=verbose)
        return True
    except Exception:
        return False


# Function to access/modify a cache file with locking
def access_cache_file(file_path: str | PathLike, process_id: int, timeout: int = 1):
    """Function to simulate a process accessing and modifying a cache file."""
    try:
        lock_path = f"{file_path}.lock"
        with FileLock(lock_path, timeout=timeout):
            # Read the file
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()

                # Modify the file (simulate updating cache)
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(f"{content} - Modified by process {process_id}")
                time.sleep(timeout)
                return True
            except Exception as e:
                print(f"Error in access_cache_file: {e}")
                return False
    except Timeout:
        return False


class TestFileLocks(unittest.TestCase):
    """Tests for file locking functionality."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        # Clean up temporary directory
        if os.path.exists(self.temp_dir):
            try:
                shutil.rmtree(self.temp_dir)
            except PermissionError:
                pass

    def test_config_repl_setup_lock(self):
        """Test that the REPL setup lock prevents concurrent access."""
        # Create a temporary cache directory
        cache_dir = os.path.join(self.temp_dir, "cache")
        os.makedirs(cache_dir, exist_ok=True)

        # Prepare the lock file path that would be used by LeanREPLConfig
        repo_name = "/".join(DEFAULT_REPL_GIT_URL.split("/")[-2:]).replace(".git", "")
        cache_clean_repl_dir = os.path.join(cache_dir, repo_name, "repl_clean_copy")
        os.makedirs(os.path.dirname(cache_clean_repl_dir), exist_ok=True)
        lock_file = f"{cache_clean_repl_dir}.lock"

        # Acquire the lock that would be used by LeanREPLConfig
        with FileLock(lock_file, timeout=0.1):
            # Start a process that tries to create a LeanREPLConfig, which should try to acquire the same lock
            ctx = mp.get_context("spawn")

            p = ctx.Process(target=create_config_process, args=(cache_dir,))
            p.start()
            p.join(timeout=30)

            # The process should have exited with a timeout exception
            self.assertNotEqual(p.exitcode, 0, "Process should have failed to acquire the lock")

    def test_temporary_project_lock(self):
        """Test that the temporary project lock prevents concurrent access."""

        # Create a temp project instance with a simple hash
        class SimpleTestProject(BaseTempProject):
            def _get_hash_content(self, lean_version: str) -> str:
                """Return a fixed hash."""
                return "test_hash"

            def _modify_lakefile(self, project_dir: str | PathLike, lean_version: str) -> None:
                """Do nothing."""
                pass

        test_project = SimpleTestProject()

        # Get the project directory and lock path
        cache_dir = os.path.join(self.temp_dir, "cache")
        os.makedirs(cache_dir, exist_ok=True)
        project_dir = test_project._get_directory(str(cache_dir), "v4.18.0")
        lock_file = f"{project_dir}.lock"

        # Hold the lock to simulate another process using it
        with FileLock(lock_file, timeout=0.1):
            # Try to instantiate the project which should try to acquire the same lock
            with self.assertRaises(Exception):
                # Use a short timeout to avoid test hanging
                with mock.patch("lean_interact.config.FileLock", return_value=FileLock(lock_file, timeout=0.1)):
                    test_project._instantiate(cache_dir, "v4.18.0", verbose=False)


def _worker(idx, result_queue, config: LeanREPLConfig):
    try:
        # Each process gets its own server instance
        server = AutoLeanServer(config)
        # Each process runs a simple Lean command
        cmd = Command(cmd=f"def x{idx} := {idx}")
        result = server.run(cmd)
        # Return result type and env id
        if isinstance(result, CommandResponse):
            result_queue.put((idx, True, result.env))
        else:
            result_queue.put((idx, False, str(result)))
    except Exception as e:
        result_queue.put((idx, False, str(e)))


class TestAutoLeanServerConcurrency(unittest.TestCase):
    """Realistic concurrent use-cases for AutoLeanServer and LeanREPLConfig (no mocks)."""

    @classmethod
    def setUpClass(cls):
        # Use a dedicated cache dir for concurrency tests
        cls.cache_dir = tempfile.mkdtemp(prefix="lean_concurrency_cache_")
        # Pre-instantiate config to avoid race in REPL setup
        cls.config = LeanREPLConfig(cache_dir=cls.cache_dir, verbose=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.cache_dir, ignore_errors=True)

    def test_concurrent_autoleanserver(self):
        """Test concurrent use of AutoLeanServer."""
        num_proc = 4
        ctx = mp.get_context("spawn")
        result_queue = ctx.Queue()
        procs = [ctx.Process(target=_worker, args=(i, result_queue, self.config)) for i in range(num_proc)]
        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=60)
        results = [result_queue.get(timeout=5) for _ in range(num_proc)]
        self.assertTrue(all(success for (_, success, _) in results), f"Failures: {results}")
        env_ids = [env for (_, _, env) in results]
        self.assertEqual(len(env_ids), num_proc)


class TestAsyncRun(unittest.TestCase):
    """Tests for the async_run methods of LeanServer and AutoLeanServer, including concurrency."""

    @classmethod
    def setUpClass(cls):
        cls.config = LeanREPLConfig(verbose=True)

    def test_async_run_eval_leansrv(self):
        server = LeanServer(self.config)
        cmd = Command(cmd="#eval 1 + 1")
        result = asyncio.run(server.async_run(cmd))
        # Should be a CommandResponse and contain a message with '2'
        self.assertIsInstance(result, CommandResponse)
        assert isinstance(result, CommandResponse)
        self.assertTrue(any("2" in m.data for m in result.messages))

    def test_async_run_eval_autoleansrv(self):
        server = AutoLeanServer(self.config)
        cmd = Command(cmd="#eval 2 + 2")
        result = asyncio.run(server.async_run(cmd))
        self.assertIsInstance(result, CommandResponse)
        assert isinstance(result, CommandResponse)
        self.assertTrue(any("4" in m.data for m in result.messages))

    def test_async_run_concurrent_multiple_servers(self):
        n_server, n_cmd = 10, 10
        config = LeanREPLConfig(verbose=True)
        servers = [AutoLeanServer(config) for _ in range(n_server)]
        cmds = [Command(cmd=f"#eval {i} * {i}") for i in range(n_cmd)]

        async def run_all():
            tasks = [srv.async_run(cmd) for srv, cmd in zip(servers, cmds)]
            return await asyncio.gather(*tasks)

        results = asyncio.run(run_all())

        # Collect expected outputs
        expected_outputs = {str(i * i) for i in range(n_server)}
        actual_outputs = set()
        for result in results:
            self.assertIsInstance(result, CommandResponse)
            assert isinstance(result, CommandResponse)
            for n_cmd in result.messages:
                actual_outputs.add(n_cmd.data)
        self.assertEqual(actual_outputs, expected_outputs)

    def test_async_run_concurrent_autoleansrv(self):
        n = 10
        server = AutoLeanServer(self.config)
        cmds = [Command(cmd=f"#eval {i} + {i}") for i in range(n)]

        async def run_all():
            tasks = [server.async_run(cmd) for cmd in cmds]
            return await asyncio.gather(*tasks)

        results = asyncio.run(run_all())

        # Collect expected outputs
        expected_outputs = [str(i + i) for i in range(n)]
        actual_outputs = []
        for result in results:
            self.assertIsInstance(result, CommandResponse)
            assert isinstance(result, CommandResponse)
            # Find all numbers in all messages
            for m in result.messages:
                actual_outputs.append(m.data)
        self.assertEqual(actual_outputs, expected_outputs)

    def test_async_run_concurrent_state_modification_leansrv(self):
        """Test that concurrent async_run calls don't interfere with state in LeanServer."""
        server = LeanServer(self.config)

        # First command defines a global variable
        cmd1 = Command(cmd="def test_value : Nat := 42")
        # Second command uses that variable
        cmd2 = Command(cmd="#eval test_value", env=0)

        async def run_in_sequence():
            # Run first, then check if second can access the state
            result1 = await server.async_run(cmd1)
            result2 = await server.async_run(cmd2)
            return result1, result2

        results = asyncio.run(run_in_sequence())

        self.assertIsInstance(results[0], CommandResponse)
        self.assertIsInstance(results[1], CommandResponse)
        assert isinstance(results[1], CommandResponse)
        # Check that the second command correctly got the value 42
        self.assertTrue(any("42" in m.data for m in results[1].messages))

    def test_async_run_concurrent_state_modification_autoleansrv(self):
        """Test that concurrent async_run calls don't interfere with state in AutoLeanServer."""
        server = AutoLeanServer(self.config)

        # First command defines a global variable
        cmd1 = Command(cmd="def test_auto_value : Nat := 100")
        # Second command uses that variable
        cmd2 = Command(cmd="#eval test_auto_value", env=0)

        async def run_in_sequence():
            # Run first, then check if second can access the state
            result1 = await server.async_run(cmd1, add_to_session_cache=True)
            result2 = await server.async_run(cmd2)
            return result1, result2

        results = asyncio.run(run_in_sequence())

        self.assertIsInstance(results[0], CommandResponse)
        self.assertIsInstance(results[1], CommandResponse)
        assert isinstance(results[1], CommandResponse)
        # Check that the second command correctly got the value 100
        self.assertTrue(any("100" in m.data for m in results[1].messages))

    def test_async_run_interleaved_state_safety(self):
        """Test that interleaved async_run calls maintain proper state isolation."""
        server = LeanServer(self.config)

        # These commands need to execute in sequence to work properly
        cmds = [
            Command(cmd="def x := 1"),
            Command(cmd="def y := x + 1", env=0),
            Command(cmd="def z := y + 1", env=1),
            Command(cmd="#eval z", env=2),
        ]

        async def run_all_sequentially():
            results = []
            for cmd in cmds:
                results.append(await server.async_run(cmd))
            return results

        results = asyncio.run(run_all_sequentially())
        for result in results:
            self.assertIsInstance(result, CommandResponse)

        # The final result should be 3
        self.assertTrue(any("3" in m.data for m in results[-1].messages))

    def test_async_run_parallel_state_safety(self):
        """Test that parallel async_run calls are properly synchronized."""
        n = 5
        server = LeanServer(self.config)

        # Create a sequence of dependent definitions
        # If the lock doesn't work, some definitions might not be available
        # when subsequent commands try to use them
        cmds = []
        for i in range(n):
            if i == 0:
                cmds.append(Command(cmd=f"def a{i} := {i}"))
            else:
                cmds.append(Command(cmd=f"def a{i} := a{i - 1} + 1", env=i - 1))

        # Final command that uses all definitions
        final_cmd = Command(cmd="#eval " + " + ".join(f"a{i}" for i in range(n)), env=n - 1)

        async def run_with_dependencies():
            # Run all definitions first
            for cmd in cmds:
                await server.async_run(cmd)
            # Then evaluate the final expression
            return await server.async_run(final_cmd)

        result = asyncio.run(run_with_dependencies())

        # The sum should be 0 + 1 + 2 + 3 + 4 = 10
        self.assertIsInstance(result, CommandResponse)
        assert isinstance(result, CommandResponse)
        self.assertTrue(any("10" in m.data for m in result.messages))

    def test_run_and_async_run_concurrent_safety(self):
        """Test that synchronous run and asynchronous async_run calls don't interfere with each other."""
        server = LeanServer(self.config)
        async_results = []
        sync_results = []

        # This will be run in a separate thread
        def sync_task():
            for i in range(3):
                cmd = Command(cmd=f"def sync_test_{i} := {i * 10}")
                result = server.run(cmd)
                sync_results.append((result, i))

        # This will run the async commands
        async def async_task():
            for i in range(3):
                cmd = Command(cmd=f"def async_test_{i} := {i * 100}")
                result = await server.async_run(cmd)
                async_results.append((result, i))
            return "done"

        # Start thread for synchronous calls
        thread = threading.Thread(target=sync_task)
        thread.start()

        # Run async commands
        asyncio.run(async_task())

        # Wait for sync thread to complete
        thread.join()

        # Verify all calls succeeded
        self.assertEqual(len(sync_results), 3)
        self.assertEqual(len(async_results), 3)

        for result in sync_results + async_results:
            self.assertIsInstance(result[0], CommandResponse)

        # Test that all definitions are accessible
        for i in range(3):
            # Check sync definitions
            result, idx = sync_results[i]
            sync_eval = server.run(Command(cmd=f"#eval sync_test_{idx}", env=result.env))
            assert isinstance(sync_eval, CommandResponse)
            self.assertTrue(any(msg.data == str(idx * 10) for msg in sync_eval.messages))

            # Check async definitions
            result, idx = async_results[i]
            async_eval = server.run(Command(cmd=f"#eval async_test_{idx}", env=result.env))
            assert isinstance(async_eval, CommandResponse)
            self.assertTrue(any(msg.data == str(idx * 100) for msg in async_eval.messages))

    def test_run_thread_safety(self):
        """Test that multiple threads using run() are properly synchronized."""
        server = LeanServer(self.config)
        num_threads = 3
        results = []

        # Use a barrier to start all threads at the same time
        barrier = threading.Barrier(num_threads)

        def thread_task(idx):
            barrier.wait()
            # Run a simple Lean command
            cmd = Command(cmd=f"def thread_test_{idx} := {idx}")
            result = server.run(cmd)
            results.append((result, idx))

        # Create and start threads
        threads = []
        for i in range(num_threads):
            thread = threading.Thread(target=thread_task, args=(i,))
            threads.append(thread)
            thread.start()

        # Wait for all threads to finish
        for thread in threads:
            thread.join()

        # Verify all commands succeeded
        self.assertEqual(len(results), num_threads)
        for result in results:
            self.assertIsInstance(result[0], CommandResponse)

        # Verify the definitions are accessible
        for i in range(num_threads):
            result, idx = results[i]
            eval_result = server.run(Command(cmd=f"#eval thread_test_{idx}", env=result.env))
            assert isinstance(eval_result, CommandResponse)
            self.assertTrue(any(msg.data == str(idx) for msg in eval_result.messages))


if __name__ == "__main__":
    unittest.main()
