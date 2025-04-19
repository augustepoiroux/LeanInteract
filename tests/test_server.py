import os
import tempfile
import time
import unittest
import unittest.mock
from queue import Queue
from threading import Thread
from typing import cast

import pexpect
import psutil

from lean_interact.config import (
    GitProject,
    LeanREPLConfig,
    LeanRequire,
    LocalProject,
    TempRequireProject,
)
from lean_interact.interface import (
    Command,
    CommandResponse,
    FileCommand,
    LeanError,
    Message,
    PickleEnvironment,
    PickleProofState,
    Pos,
    ProofStep,
    ProofStepResponse,
    Sorry,
    UnpickleEnvironment,
    UnpickleProofState,
)
from lean_interact.server import (
    DEFAULT_TIMEOUT,
    AutoLeanServer,
    LeanServer,
    _SessionState,
)


class TestLeanServer(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        # Pre-run configs for all available versions to get the cache
        lean_versions = LeanREPLConfig(verbose=True).get_available_lean_versions()
        for version in ["v4.7.0", "v4.14.0", lean_versions[-1]]:
            LeanREPLConfig(lean_version=version, verbose=True)

        # prepare Mathlib for the last version
        LeanREPLConfig(lean_version="v4.7.0", project=TempRequireProject("mathlib"), verbose=True)
        LeanREPLConfig(lean_version=lean_versions[-1], project=TempRequireProject("mathlib"), verbose=True)

    def test_init_with_lean_version(self):
        lean_versions = LeanREPLConfig(verbose=True).get_available_lean_versions()
        for version in ["v4.7.0", "v4.14.0", lean_versions[-1]]:
            server = AutoLeanServer(config=LeanREPLConfig(lean_version=version, verbose=True))
            self.assertEqual(server.lean_version, version)
            self.assertEqual(
                server.run(Command(cmd="#eval Lean.versionString")),
                CommandResponse(
                    messages=[
                        Message(
                            start_pos=Pos(line=1, column=0),
                            end_pos=Pos(line=1, column=5),
                            severity="info",
                            data=f'"{version[1:]}"',
                        )
                    ],
                    env=0,
                ),
            )

    def test_init_with_require(self):
        lean_versions = LeanREPLConfig(verbose=True).get_available_lean_versions()
        latest_version = lean_versions[-1]
        require = [
            LeanRequire(name="mathlib", git="https://github.com/leanprover-community/mathlib4.git", rev=latest_version)
        ]
        server = AutoLeanServer(LeanREPLConfig(project=TempRequireProject("mathlib"), verbose=True))
        project = cast(TempRequireProject, server.config.project)
        self.assertEqual(server.lean_version, latest_version)
        self.assertEqual(project._normalize_require(latest_version), require)

    def test_init_with_project_dir_fail(self):
        project_dir = "/tmp/path/to/project"
        with self.assertRaises(FileNotFoundError):
            AutoLeanServer(LeanREPLConfig(project=LocalProject(project_dir), lean_version="v4.7.0", verbose=True))

    def test_init_with_project_dir(self):
        base_config = LeanREPLConfig(project=TempRequireProject("mathlib"), verbose=True)
        new_config = LeanREPLConfig(project=LocalProject(base_config._working_dir), verbose=True)
        server = AutoLeanServer(new_config)
        server.run(Command(cmd="#eval Lean.versionString"))

    def test_init_with_git_project(self):
        git_url = "https://github.com/yangky11/lean4-example"
        config = LeanREPLConfig(project=GitProject(git_url), verbose=True)
        server = AutoLeanServer(config=config)
        server.run(Command(cmd="#eval Lean.versionString"))

    def test_run_code_simple(self):
        server = AutoLeanServer(config=LeanREPLConfig(verbose=True))
        result = server.run(Command(cmd="def x := 42"))
        self.assertEqual(result, CommandResponse(env=0))

    def test_run_code_with_env(self):
        server = AutoLeanServer(config=LeanREPLConfig(verbose=True))
        result1 = server.run(Command(cmd="def x := 1"), add_to_session_cache=True)
        self.assertEqual(result1, CommandResponse(env=-1))
        assert not isinstance(result1, LeanError)
        env_id = result1.env
        result2 = server.run(Command(cmd="def y := x + 1", env=env_id))
        self.assertEqual(result2, CommandResponse(env=1))

    def test_run_tactic(self):
        server = AutoLeanServer(config=LeanREPLConfig(verbose=True))
        result = server.run(Command(cmd="theorem zero_eq_zero : 0 = 0 := sorry"), add_to_session_cache=True)
        self.assertEqual(
            result,
            CommandResponse(
                env=-1,
                messages=[
                    Message(
                        start_pos=Pos(line=1, column=8),
                        end_pos=Pos(line=1, column=20),
                        severity="warning",
                        data="declaration uses 'sorry'",
                    )
                ],
                sorries=[
                    Sorry(
                        proof_state=0, start_pos=Pos(line=1, column=32), end_pos=Pos(line=1, column=37), goal="⊢ 0 = 0"
                    )
                ],
            ),
        )
        tactic_result = server.run(ProofStep(tactic="rfl", proof_state=0))
        self.assertEqual(tactic_result, ProofStepResponse(proof_state=1, goals=[], proof_status="Completed"))

    def test_run_file_nonexistent(self):
        server = AutoLeanServer(config=LeanREPLConfig(verbose=True))
        output = server.run(FileCommand(path="nonexistent_file.lean"))
        self.assertEqual(
            output, LeanError(message="no such file or directory (error code: 2)\n  file: nonexistent_file.lean")
        )

    def test_is_alive(self):
        server = AutoLeanServer(config=LeanREPLConfig(verbose=True))
        self.assertTrue(server.is_alive())
        server.kill()
        self.assertFalse(server.is_alive())

    def test_restart(self):
        server = AutoLeanServer(config=LeanREPLConfig(verbose=True))
        old_proc = server._proc
        server.restart()
        self.assertNotEqual(server._proc, old_proc)
        self.assertTrue(server.is_alive())

    def test_clear_session_cache(self):
        server = AutoLeanServer(config=LeanREPLConfig(verbose=True))
        server.run(Command(cmd="def x := 1"), add_to_session_cache=True)
        server.clear_session_cache()
        self.assertEqual(len(server._restart_persistent_session_cache), 0)

    def test_init_with_invalid_rev(self):
        with self.assertRaises(Exception):
            AutoLeanServer(config=LeanREPLConfig(lean_version="invalid_rev", verbose=True))

    def test_extremely_long_command(self):
        server = AutoLeanServer(config=LeanREPLConfig(verbose=True))
        result = server.run(Command(cmd="def " + "a" * 10000 + " : 1 + 1 = 2 := sorry"), add_to_session_cache=True)
        self.assertEqual(
            result,
            CommandResponse(
                env=-1,
                sorries=[
                    Sorry(
                        proof_state=0,
                        start_pos=Pos(line=1, column=10020),
                        end_pos=Pos(line=1, column=10025),
                        goal="⊢ 1 + 1 = 2",
                    )
                ],
                messages=[
                    Message(
                        severity="warning",
                        start_pos=Pos(line=1, column=4),
                        end_pos=Pos(line=1, column=10004),
                        data="declaration uses 'sorry'",
                    )
                ],
            ),
        )
        result = server.run(ProofStep(tactic="rfl", proof_state=0))
        self.assertEqual(result, ProofStepResponse(proof_state=1, goals=[], proof_status="Completed"))

    def test_lean_version(self):
        server = AutoLeanServer(config=LeanREPLConfig(lean_version="v4.14.0", verbose=True))
        result = server.run(Command(cmd="#eval Lean.versionString"))
        self.assertEqual(
            result,
            CommandResponse(
                env=0,
                messages=[
                    Message(
                        data='"4.14.0"',
                        end_pos=Pos(line=1, column=5),
                        start_pos=Pos(line=1, column=0),
                        severity="info",
                    )
                ],
            ),
        )

    def test_mathlib(self):
        server = AutoLeanServer(config=LeanREPLConfig(project=TempRequireProject("mathlib"), verbose=True))
        result = server.run(Command(cmd="import Mathlib"), add_to_session_cache=True)
        self.assertEqual(result, CommandResponse(env=-1))
        result = server.run(
            Command(
                cmd="theorem exercise_1_1a\n  (x : ℝ) (y : ℚ) (n : ℕ) (h : Odd n) :\n  ( Irrational x ) -> Irrational ( x + y ) := sorry",
                env=-1,
            ),
            add_to_session_cache=True,
        )
        self.assertEqual(
            result,
            CommandResponse(
                env=-2,
                sorries=[
                    Sorry(
                        proof_state=0,
                        start_pos=Pos(line=3, column=46),
                        end_pos=Pos(line=3, column=51),
                        goal="x : ℝ\ny : ℚ\nn : ℕ\nh : Odd n\n⊢ Irrational x → Irrational (x + ↑y)",
                    )
                ],
                messages=[
                    Message(
                        data="declaration uses 'sorry'",
                        end_pos=Pos(line=1, column=21),
                        start_pos=Pos(line=1, column=8),
                        severity="warning",
                    )
                ],
            ),
        )
        result = server.run(ProofStep(tactic="apply irrational_add_rat_iff.mpr", proof_state=0))
        self.assertEqual(result, ProofStepResponse(proof_state=1, goals=[], proof_status="Completed"))

    def test_restart_with_env(self):
        server = AutoLeanServer(config=LeanREPLConfig(verbose=True))
        result = server.run(Command(cmd="def x := 1"), add_to_session_cache=True)
        assert not isinstance(result, LeanError)
        env_id = result.env
        self.assertEqual(env_id, -1)
        server.restart()
        result = server.run(Command(cmd="noncomputable def y := x + 1", env=env_id))
        self.assertEqual(result, CommandResponse(env=1))
        self.assertEqual(list(server._restart_persistent_session_cache.keys()), [env_id])

    def test_process_request_memory_restart(self):
        server = AutoLeanServer(config=LeanREPLConfig(verbose=True), max_total_memory=0.01, max_restart_attempts=2)
        # Mock psutil.virtual_memory().percent to be high
        with unittest.mock.patch("psutil.virtual_memory") as mock_virtual_memory:
            mock_virtual_memory.return_value.percent = 99.0
            with unittest.mock.patch("time.sleep", return_value=None):
                with self.assertRaises(MemoryError):
                    server.run(Command(cmd="test"), verbose=False)
        self.assertFalse(server.is_alive())

    @unittest.mock.patch("lean_interact.server.LeanServer.run_dict")
    def test_process_request_with_negative_env_id(self, mock_super):
        server = AutoLeanServer(config=LeanREPLConfig(verbose=True))
        # Prepare restart_persistent_session_cache
        server._restart_persistent_session_cache[-1] = _SessionState(-1, 10, "", False)
        with unittest.mock.patch.object(server, "_get_repl_state_id", return_value=10):
            mock_super.return_value = {"env": 10}
            result = server.run(Command(cmd="test", env=-1))
            mock_super.assert_called_with(request={"cmd": "test", "env": 10}, verbose=False, timeout=DEFAULT_TIMEOUT)
            self.assertEqual(result, CommandResponse(env=10))

    @unittest.mock.patch("lean_interact.server.LeanServer.run_dict")
    def test_process_request_with_negative_proof_state_id(self, mock_super):
        server = AutoLeanServer(config=LeanREPLConfig(verbose=True))
        # Prepare restart_persistent_session_cache
        server._restart_persistent_session_cache[-2] = _SessionState(-2, 20, "", True)
        with unittest.mock.patch.object(server, "_get_repl_state_id", return_value=20):
            mock_super.return_value = {"proofState": 20, "goals": [], "proofStatus": "Completed"}
            result = server.run(ProofStep(proof_state=-2, tactic="test"))
            mock_super.assert_called_with(
                request={"proofState": 20, "tactic": "test"}, verbose=False, timeout=DEFAULT_TIMEOUT
            )
            self.assertEqual(result, ProofStepResponse(proof_state=20, goals=[], proof_status="Completed"))

    @unittest.mock.patch("lean_interact.server.LeanServer.run_dict", return_value={})
    @unittest.mock.patch("lean_interact.server.psutil.virtual_memory")
    def test_process_request_server_restart(self, mock_virtual_memory, mock_process_request):
        server = AutoLeanServer(config=LeanREPLConfig(verbose=True))
        server.kill()
        self.assertFalse(server.is_alive())
        mock_virtual_memory.return_value.percent = 0.0
        server.run(Command(cmd="test"), verbose=False)
        self.assertTrue(server.is_alive())

    @unittest.mock.patch("lean_interact.server.LeanServer.run_dict")
    def test_process_request_timeout_recovery(self, mock_process_request):
        # Simulate a timeout exception
        mock_process_request.side_effect = TimeoutError("Simulated timeout")

        server = AutoLeanServer(config=LeanREPLConfig(verbose=True))
        with self.assertRaises(TimeoutError):
            server.run(Command(cmd="test"), timeout=1)

        # Verify that the server did not attempt to restart
        self.assertTrue(server.is_alive())
        mock_process_request.assert_called_once()

    # @unittest.mock.patch("lean_interact.server.LeanServer._process_request")
    # def test_process_request_eof_recovery(self, mock_process_request):
    #     # Simulate a ConnectionAbortedError exception indicating server crash
    #     mock_process_request.side_effect = ConnectionAbortedError("Simulated server crash")

    #     max_restart_attempts = 2
    #     server = AutoLeanServer(config=LeanREPLConfig(), max_restart_attempts=max_restart_attempts)
    #     with self.assertRaises(ConnectionAbortedError):
    #         server._process_request({"cmd": "test"})

    #     # Verify that the server attempted to restart max_restart_attempts times
    #     self.assertFalse(server.is_alive())
    #     self.assertEqual(mock_process_request.call_count, max_restart_attempts + 1)

    @unittest.mock.patch("lean_interact.server.psutil.virtual_memory")
    def test_process_request_memory_overload_recovery(self, mock_virtual_memory):
        # Simulate high memory usage
        mock_virtual_memory.return_value.percent = 95.0

        max_restart_attempts = 2
        server = AutoLeanServer(
            config=LeanREPLConfig(), max_total_memory=0.8, max_restart_attempts=max_restart_attempts
        )
        with self.assertRaises(MemoryError):
            server.run(Command(cmd="test"))

        # Verify that the server is not alive after exceeding max restart attempts
        self.assertFalse(server.is_alive())

    def test_autoleanserver_recovery_after_timeout(self):
        server = AutoLeanServer(config=LeanREPLConfig(verbose=True))

        # Mock the expect_exact method to raise a timeout exception
        def raise_timeout_error(*args, **kwargs):
            raise pexpect.exceptions.TIMEOUT("")

        with unittest.mock.patch.object(server._proc, "expect_exact", side_effect=raise_timeout_error):
            with self.assertRaises(TimeoutError):
                server.run(Command(cmd="def x := y"))

        # Send a new command to verify auto-recovery
        result = server.run(Command(cmd="def z := 3"))
        self.assertEqual(result, CommandResponse(env=0))

    def test_leanserver_killed_after_timeout(self):
        server = LeanServer(config=LeanREPLConfig(verbose=True))

        # Mock the expect_exact method to raise a timeout exception
        def raise_timeout_error(*args, **kwargs):
            raise pexpect.exceptions.TIMEOUT("")

        with unittest.mock.patch.object(server._proc, "expect_exact", side_effect=raise_timeout_error):
            with self.assertRaises(TimeoutError):
                server.run(Command(cmd="def a := b"))

        # Ensure the server is killed after the timeout
        # self.assertFalse(server.is_alive())
        with self.assertRaises(ChildProcessError):
            server.run(Command(cmd="def z := 3"))

    # def test_run_proof(self):
    #     server = AutoLeanServer(config=LeanREPLConfig(verbose=True))
    #     result = server.run(
    #         Command(cmd="theorem test_run_proof : (x : Nat) -> x = x := sorry", add_to_session_cache=True)
    #     )
    #     self.assertEqual(result.get("env"), -1)

    #     proof_result = server.run_proof("intro x\nrfl", proof_state=0)
    #     self.assertDictEqual(proof_result, {"proofState": 1, "goals": []})

    def test_run_proof_equivalence(self):
        server = AutoLeanServer(config=LeanREPLConfig(verbose=True))
        result = server.run(
            Command(cmd="theorem test_run_proof_seq : (x : Nat) -> x = x := sorry"), add_to_session_cache=True
        )
        assert not isinstance(result, LeanError)
        self.assertEqual(result.env, -1)

        step1 = server.run(ProofStep(tactic="intro x", proof_state=0))
        assert not isinstance(step1, LeanError)
        step2 = server.run(ProofStep(tactic="rfl", proof_state=step1.proof_state))
        self.assertEqual(step2, ProofStepResponse(proof_state=2, goals=[], proof_status="Completed"))

    def test_infotree(self):
        """Test infotree with all possible values"""
        server = AutoLeanServer(config=LeanREPLConfig(verbose=True))

        # Test infotree with all possible values
        for infotree_value in ["full", "tactics", "original", "substantive"]:
            result = server.run(Command(cmd="theorem infotree_test : 0 = 0 := by rfl", infotree=infotree_value))
            self.assertIsInstance(result, CommandResponse)
            assert isinstance(result, CommandResponse)
            self.assertIsNotNone(result.infotree)

        # Test with an invalid infotree value
        result = server.run(Command(cmd="theorem infotree_test : 0 = 0 := by rfl", infotree="invalid"))
        self.assertIsInstance(result, CommandResponse)
        assert isinstance(result, CommandResponse)
        self.assertIsNone(result.infotree)

    def test_run_multiple_commands(self):
        # Test this issue: https://github.com/leanprover-community/repl/issues/77
        server = AutoLeanServer(config=LeanREPLConfig(memory_hard_limit_mb=4096, verbose=True))

        with self.assertRaises(ConnectionAbortedError):
            for i in range(1000):
                cmd = Command(cmd=f"theorem womp{i} (a{i} b c : Nat) : (a{i} + b) + c = c + a{i} + b := by sorry")
                server.run(cmd)

    def test_run_lots_of_commands(self):
        # Test this issue: https://github.com/leanprover-community/repl/issues/77
        server = LeanServer(LeanREPLConfig(verbose=True))

        init_env = server.run(Command(cmd="#eval 1"))
        assert not isinstance(init_env, LeanError)
        for i in range(1000):
            cmd = Command(
                cmd=f"theorem womp{i} (a{i} b c : Nat) : (a{i} + b) + c = c + a{i} + b := by sorry", env=init_env.env
            )
            result = server.run(cmd)
            self.assertIsInstance(result, CommandResponse)

    def test_bug_increasing_memory(self):
        mem_limit = 512
        server = AutoLeanServer(config=LeanREPLConfig(memory_hard_limit_mb=mem_limit, verbose=True))

        # Get initial memory usage
        assert server._proc is not None
        server_process = psutil.Process(server._proc.pid)
        time.sleep(1)  # Give the process time to start
        start_mem = server_process.memory_info().rss / (1024 * 1024)  # Convert to MB

        # Run code in separate thread to allow memory monitoring
        result_queue = Queue()

        def run_code_thread():
            try:
                # execute a known "fast infinite memory increasing" code
                result = server.run(
                    Command(
                        cmd="theorem dummy {x : ∀ α, X α} {ι : Type _} {x₁ : ι → ∀ α, X α} {x₂ : ι → ∀ α, X α} (x₃ : ι → ∀ α, X α) {x₄ : ι → ∀ α, X α} {x₅ : ι → ∀ α, X α} {x₆ : ι → ∀ α, X α} {x₇ : ι → ∀ α, X α} {x₈ : ι → ∀ α, X α} {x₉ : ι → ∀ α, X α} {x₀ : ι → ∀ α, X α} {x₁₀ : ι → ∀ α, X α} {x₁₁ : ι → ∀ α, X α} {x₁₂ : ι → ∀ α, X α} (x₁₃ : ι → ∀ α, X α) (x₁₄ : ι → ∀ α, X α) (x₁₅ : ι → ∀ α, X α) {x₁₆ : ι → ∀ α, X α} {x₁₇ : ι → ∀ α, X α} {x₁₈ : ι → ∀ α, X α} {x₁₉ : ι → ∀ α, X α} {x₂₀ : ι → ∀ α, X α} (x₂₁ : ι → ∀ α, X α) (x₂₂ : ι → ∀ α, X α) (x₂₃ : ι → ∀ α, X α) (x₂₄ : ι → ∀ α, X α) (x₂₅ : ι → ∀ α, X α) (x₂₆ : ι → ∀ α, X α) (x₂₇ : ι → ∀ α, X α) (x₂₈ : ι → ∀ α, X α) (x₂₉ : ι → ∀ α, X α) (x₃₀ : ι → ∀ α, X α) {x₃₁ : ι → ∀ α, X α} {x₃₂ : ι → ∀ α, X α} (x₃₃ : ι → ∀ α, X α) (x₃₄ : ι → ∀ α, X α) (x₃₅ : ι → ∀ α, X α) (x₃ sorry",
                    ),
                    timeout=10,
                )
                result_queue.put(("success", result))
            except TimeoutError as e:
                result_queue.put(("timeout", e))
            except ConnectionAbortedError as e:
                result_queue.put(("connection_aborted", e))  # out of memory
            except Exception as e:
                result_queue.put(("error", e))

        # Start code execution thread
        thread = Thread(target=run_code_thread)
        thread.start()

        # Monitor memory usage
        max_mem = start_mem
        while thread.is_alive():
            try:
                current_mem = server_process.memory_info().rss / (1024 * 1024)
                max_mem = max(max_mem, current_mem)
                if current_mem > mem_limit:
                    server.kill()
                    raise MemoryError(f"Memory usage exceeded limit: {current_mem:.1f}MB > {mem_limit}MB")
                time.sleep(1)
            except psutil.NoSuchProcess:
                break

        # Get result
        status, result = result_queue.get()
        if status == "error":
            raise result

        # Assert memory stayed within limits
        self.assertLess(max_mem, mem_limit, f"Memory usage peaked at {max_mem:.1f}MB, exceeding {mem_limit}MB limit")

    def test_pickle_unpickle_environment(self):
        server = AutoLeanServer(config=LeanREPLConfig(verbose=True))

        # Create an environment with a definition
        result = server.run(Command(cmd="def x := 42"), add_to_session_cache=True)
        self.assertEqual(result, CommandResponse(env=-1))
        assert isinstance(result, CommandResponse)
        env_id = result.env

        # Pickle the environment
        temp_pickle_file = tempfile.mkstemp(suffix=".olean")[1]
        pickle_result = server.run(PickleEnvironment(env=env_id, pickle_to=temp_pickle_file))
        self.assertIsInstance(pickle_result, CommandResponse)

        # Create a new server
        new_server = AutoLeanServer(config=LeanREPLConfig(verbose=True))

        # Unpickle the environment in the new server
        unpickle_result = new_server.run(UnpickleEnvironment(unpickle_env_from=temp_pickle_file))
        assert isinstance(unpickle_result, CommandResponse)
        unpickled_env_id = unpickle_result.env

        # TODO: there is a bug with the REPL pickling process which transforms `def` into `noncomputable def`

        # Test that the unpickled environment contains the original definition
        result = new_server.run(Command(cmd="noncomputable def y := x + 1", env=unpickled_env_id))
        self.assertEqual(result, CommandResponse(env=1))

        # # Test evaluation works with the unpickled environment
        # eval_result = new_server.run(Command(cmd="#eval x", env=1))
        # assert isinstance(eval_result, CommandResponse)
        # self.assertIn(
        #     Message(
        #         severity="info",
        #         data="43",
        #         start_pos=Pos(line=1, column=0),
        #         end_pos=Pos(line=1, column=5),
        #     ),
        #     eval_result.messages,
        # )

        # delete the temp file
        os.remove(temp_pickle_file)

    def test_pickle_unpickle_proof_state(self):
        server = AutoLeanServer(config=LeanREPLConfig(verbose=True))

        # Create a theorem with a proof state
        result = server.run(Command(cmd="theorem test_pickle : 0 = 0 := sorry"), add_to_session_cache=True)
        assert isinstance(result, CommandResponse)
        self.assertEqual(len(result.sorries), 1)
        proof_state_id = result.sorries[0].proof_state
        assert isinstance(proof_state_id, int)

        # Pickle the proof state
        temp_pickle_file = tempfile.mkstemp(suffix=".olean")[1]
        pickle_result = server.run(PickleProofState(proof_state=proof_state_id, pickle_to=temp_pickle_file))
        self.assertIsInstance(pickle_result, ProofStepResponse)

        # Create a new server
        new_server = AutoLeanServer(config=LeanREPLConfig(verbose=True))

        # Unpickle the proof state in the new server
        unpickle_result = new_server.run(UnpickleProofState(unpickle_proof_state_from=temp_pickle_file))
        assert isinstance(unpickle_result, ProofStepResponse)
        unpickled_proof_state_id = unpickle_result.proof_state

        # Test that we can continue the proof from the unpickled proof state
        tactic_result = new_server.run(ProofStep(tactic="rfl", proof_state=unpickled_proof_state_id))
        self.assertEqual(tactic_result, ProofStepResponse(proof_state=1, goals=[], proof_status="Completed"))

    def test_pickle_fails_with_invalid_env(self):
        server = AutoLeanServer(config=LeanREPLConfig(verbose=True))

        # Try to pickle a non-existent environment
        temp_pickle_file = tempfile.mkstemp(suffix=".olean")[1]
        result = server.run(PickleEnvironment(env=999, pickle_to=temp_pickle_file))
        assert isinstance(result, LeanError)
        self.assertEqual("unknown environment.", result.message.lower())

        # delete the temp file
        os.remove(temp_pickle_file)

    def test_unpickle_fails_with_invalid_data(self):
        server = AutoLeanServer(config=LeanREPLConfig(verbose=True))
        print("Unpickle test")
        # Try to unpickle invalid data
        temp_pickle_file = tempfile.mkstemp(suffix=".olean")[1]

        # Try to unpickle invalid data
        with self.assertRaises(ConnectionAbortedError):
            server.run(UnpickleEnvironment(unpickle_env_from=temp_pickle_file))
        with self.assertRaises(ConnectionAbortedError):
            server.run(UnpickleProofState(unpickle_proof_state_from=temp_pickle_file))

        # delete the temp file
        os.remove(temp_pickle_file)

    def test_pickle_unpickle_with_complex_environment(self):
        server = AutoLeanServer(config=LeanREPLConfig(verbose=True))

        # Create a more complex environment with multiple definitions and imports
        cmds = [
            "import Lean",
            "def add_one (n : Nat) : Nat := n + 1",
            "def double (n : Nat) : Nat := n * 2",
            "def compute (n : Nat) : Nat := double (add_one n)",
        ]

        env_id = None
        for cmd in cmds:
            result = server.run(Command(cmd=cmd, env=env_id), add_to_session_cache=True)
            assert isinstance(result, CommandResponse)
            env_id = result.env
        assert env_id is not None

        # Verify the environment works
        eval_result = server.run(Command(cmd="#eval compute 5", env=env_id))
        assert isinstance(eval_result, CommandResponse)
        self.assertIn(
            Message(
                severity="info",
                data="12",
                start_pos=Pos(line=1, column=0),
                end_pos=Pos(line=1, column=5),
            ),
            eval_result.messages,
        )

        # Pickle the environment
        temp_pickle_file = tempfile.mkstemp(suffix=".olean")[1]
        pickle_result = server.run(PickleEnvironment(env=env_id, pickle_to=temp_pickle_file))
        self.assertIsInstance(pickle_result, CommandResponse)

        # Create a new server and unpickle
        new_server = AutoLeanServer(config=LeanREPLConfig(verbose=True))
        unpickle_result = new_server.run(UnpickleEnvironment(unpickle_env_from=temp_pickle_file))
        assert isinstance(unpickle_result, CommandResponse)
        unpickled_env_id = unpickle_result.env

        # TODO: there is a bug with the REPL pickling process which transforms `def` into `noncomputable def`

        # # Test that the functions still work in the unpickled environment
        # eval_result = new_server.run(Command(cmd="#eval compute 10", env=unpickled_env_id))
        # assert isinstance(eval_result, CommandResponse)
        # self.assertIn(
        #     Message(
        #         severity="info",
        #         data="22",
        #         start_pos=Pos(line=1, column=0),
        #         end_pos=Pos(line=1, column=5),
        #     ),
        #     eval_result.messages,
        # )

        # delete the temp file
        os.remove(temp_pickle_file)


if __name__ == "__main__":
    unittest.main()
