import os
import platform
import shutil
import subprocess
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path
from queue import Queue
from threading import Thread
from typing import cast

import psutil

from lean_interact.config import LeanREPLConfig
from lean_interact.interface import (
    BinderView,
    Command,
    CommandResponse,
    DeclarationInfo,
    DeclBinders,
    DeclModifiers,
    DeclSignature,
    DeclType,
    DeclValue,
    FileCommand,
    LeanError,
    Message,
    PickleEnvironment,
    PickleProofState,
    Pos,
    ProofStep,
    ProofStepResponse,
    Range,
    ScopeInfo,
    Sorry,
    UnpickleEnvironment,
    UnpickleProofState,
)
from lean_interact.project import (
    GitProject,
    LeanRequire,
    LocalProject,
    TemporaryProject,
    TempRequireProject,
)
from lean_interact.server import DEFAULT_TIMEOUT, AutoLeanServer, LeanServer
from lean_interact.sessioncache import PickleSessionCache, PickleSessionState
from lean_interact.utils import get_total_memory_usage


class TestLeanServer(unittest.TestCase):
    maxDiff = None
    oldestVersion = "v4.8.0-rc1"

    @classmethod
    def setUpClass(cls):
        # Pre-run configs for all available versions to get the cache
        lean_versions = LeanREPLConfig(verbose=True).get_available_lean_versions()
        cls.mostRecentVersion = lean_versions[-1]
        for version in [cls.oldestVersion, "v4.14.0", lean_versions[-1]]:
            LeanREPLConfig(lean_version=version, verbose=True)

        # (Temporary) Skip mathlib setup on Windows to avoid long path issues in CI
        if platform.system() == "Windows":
            return

        # prepare Mathlib for the last version
        LeanREPLConfig(project=TempRequireProject(lean_version=cls.oldestVersion, require="mathlib"), verbose=True)
        LeanREPLConfig(project=TempRequireProject(lean_version=lean_versions[-1], require="mathlib"), verbose=True)

    def test_init_with_lean_version(self):
        lean_versions = LeanREPLConfig(verbose=True).get_available_lean_versions()
        for version in [self.oldestVersion, "v4.14.0", lean_versions[-1]]:
            server = AutoLeanServer(config=LeanREPLConfig(lean_version=version, verbose=True))
            self.assertEqual(server.lean_version, version)
            self.assertEqual(
                server.run(Command(cmd="#eval Lean.versionString"), verbose=True),
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
        # (Temporary) Skip mathlib tests on Windows to avoid long path issues in CI
        if platform.system() == "Windows":
            self.skipTest("(Temporary) Skipping test on Windows due to long path issues in the CI")

        lean_versions = LeanREPLConfig(verbose=True).get_available_lean_versions()
        latest_version = lean_versions[-1]
        require = [
            LeanRequire(name="mathlib", git="https://github.com/leanprover-community/mathlib4.git", rev=latest_version)
        ]
        server = AutoLeanServer(
            LeanREPLConfig(project=TempRequireProject(lean_version=latest_version, require="mathlib"), verbose=True)
        )
        project = cast(TempRequireProject, server.config.project)
        self.assertEqual(server.lean_version, latest_version)
        self.assertEqual(project._normalize_require(), require)

    def test_init_with_project_dir_fail(self):
        project_dir = os.path.join("tmp", "path", "to", "project")
        with self.assertRaises((FileNotFoundError, NotADirectoryError)):
            AutoLeanServer(
                LeanREPLConfig(
                    project=LocalProject(directory=project_dir), lean_version=self.oldestVersion, verbose=True
                )
            )

    def test_init_with_project_dir(self):
        # (Temporary) Skip mathlib tests on Windows to avoid long path issues in CI
        if platform.system() == "Windows":
            self.skipTest("(Temporary) Skipping test on Windows due to long path issues in the CI")

        base_config = LeanREPLConfig(
            project=TempRequireProject(lean_version=self.mostRecentVersion, require="mathlib"), verbose=True
        )
        new_config = LeanREPLConfig(project=LocalProject(directory=base_config.working_dir), verbose=True)
        server = AutoLeanServer(new_config)
        response = server.run(Command(cmd="#eval Lean.versionString"), verbose=True)
        self.assertIsInstance(response, CommandResponse)
        # Re-use the existing build
        with unittest.mock.patch("subprocess.run") as run_mock:
            run_mock.return_value = subprocess.CompletedProcess(
                args=["lake", "--version"], returncode=0, stdout="", stderr=""
            )
            new_config = LeanREPLConfig(
                project=LocalProject(directory=base_config.working_dir, auto_build=False), verbose=True
            )
            # it should be called only by the REPL (once to check Lake, once to build the REPL)
            self.assertEqual(run_mock.call_count, 2)
            server = AutoLeanServer(new_config)
            response = server.run(Command(cmd="#eval Lean.versionString"), verbose=True)
            self.assertIsInstance(response, CommandResponse)

    def test_init_with_official_repl(self):
        config = LeanREPLConfig(
            repl_rev="v4.24.0-rc1", repl_git="https://github.com/leanprover-community/repl", verbose=True
        )
        server = AutoLeanServer(config=config)
        self.assertEqual(server.lean_version, "v4.24.0-rc1")
        response = server.run(Command(cmd="#eval Lean.versionString"), verbose=True)
        self.assertIsInstance(response, CommandResponse)
        self.assertEqual(
            response,
            CommandResponse(
                messages=[
                    Message(
                        start_pos=Pos(line=1, column=0),
                        end_pos=Pos(line=1, column=5),
                        severity="info",
                        data='"4.24.0-rc1"',
                    )
                ],
                env=0,
            ),
        )

    def test_temp_project_creation(self):
        # Create a simple temporary project
        temp_content = """
import Lake
open Lake DSL

package "dummy" where
  version := v!"0.1.0"

@[default_target]
lean_exe "dummy" where
  root := `Main
"""
        project = TemporaryProject(content=temp_content, lean_version="v4.14.0")
        config = LeanREPLConfig(project=project, verbose=True)
        server = AutoLeanServer(config=config)
        response = server.run(Command(cmd="#eval Lean.versionString"), verbose=True)
        self.assertEqual(
            response,
            CommandResponse(
                messages=[
                    Message(
                        start_pos=Pos(line=1, column=0), end_pos=Pos(line=1, column=5), severity="info", data='"4.14.0"'
                    )
                ],
                env=0,
            ),
        )

    def test_init_with_git_project(self):
        if platform.system() == "Windows":
            self.skipTest("(Temporary) Skipping test on Windows due to long path issues in the CI")

        git_url = "https://github.com/yangky11/lean4-example"
        config = LeanREPLConfig(project=GitProject(url=git_url), verbose=True)
        server = AutoLeanServer(config=config)
        response = server.run(Command(cmd="#eval Lean.versionString"), verbose=True)
        assert config.lean_version is not None, "Error: Lean version could not be determined from the project"
        lean_version = config.lean_version[1:]
        self.assertEqual(
            response,
            CommandResponse(
                messages=[
                    Message(
                        start_pos=Pos(line=1, column=0),
                        end_pos=Pos(line=1, column=5),
                        severity="info",
                        data=f'"{lean_version}"',
                    )
                ],
                env=0,
            ),
        )

    def test_run_code_simple(self):
        server = AutoLeanServer(config=LeanREPLConfig(verbose=True))
        result = server.run(Command(cmd="def x := 42"), verbose=True)
        self.assertEqual(result, CommandResponse(env=0))

    def test_run_code_with_env(self):
        server = AutoLeanServer(config=LeanREPLConfig(verbose=True))
        result1 = server.run(Command(cmd="def x := 1"), add_to_session_cache=True, verbose=True)
        self.assertEqual(result1, CommandResponse(env=-1))
        assert not isinstance(result1, LeanError)
        env_id = result1.env
        result2 = server.run(Command(cmd="def y := x + 1", env=env_id), verbose=True)
        self.assertEqual(result2, CommandResponse(env=1))

    def test_run_tactic(self):
        server = AutoLeanServer(config=LeanREPLConfig(verbose=True))
        result = server.run(
            Command(cmd="theorem zero_eq_zero : 0 = 0 := sorry"), add_to_session_cache=True, verbose=True
        )
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
        tactic_result = server.run(ProofStep(tactic="rfl", proof_state=0), verbose=True)
        self.assertEqual(tactic_result, ProofStepResponse(proof_state=1, goals=[], proof_status="Completed"))

    def test_run_file_nonexistent(self):
        server = AutoLeanServer(config=LeanREPLConfig(verbose=True))
        output = server.run(FileCommand(path="nonexistent_file.lean"), verbose=True)
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
        server.run(Command(cmd="def x := 1"), add_to_session_cache=True, verbose=True)
        server.clear_session_cache()
        self.assertTrue(server._session_cache.is_empty())

    def test_init_with_invalid_rev(self):
        with self.assertRaises(Exception):
            AutoLeanServer(config=LeanREPLConfig(lean_version="invalid_rev", verbose=True))

    def test_extremely_long_command(self):
        server = AutoLeanServer(config=LeanREPLConfig(verbose=True))
        result = server.run(
            Command(cmd="def " + "a" * 10000 + " : 1 + 1 = 2 := sorry"), add_to_session_cache=True, verbose=True
        )
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
        result = server.run(ProofStep(tactic="rfl", proof_state=0), verbose=True)
        self.assertEqual(result, ProofStepResponse(proof_state=1, goals=[], proof_status="Completed"))

    def test_lean_version(self):
        server = AutoLeanServer(config=LeanREPLConfig(lean_version="v4.14.0", verbose=True))
        result = server.run(Command(cmd="#eval Lean.versionString"), verbose=True)
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
        if platform.system() == "Windows":
            self.skipTest("(Temporary) Skipping test on Windows due to long path issues in the CI")

        server = AutoLeanServer(
            config=LeanREPLConfig(
                project=TempRequireProject(lean_version=self.mostRecentVersion, require="mathlib"), verbose=True
            )
        )
        result = server.run(Command(cmd="import Mathlib"), add_to_session_cache=True, verbose=True)
        self.assertEqual(result, CommandResponse(env=-1))
        result = server.run(
            Command(
                cmd="theorem exercise_1_1a\n  (x : ℝ) (y : ℚ) (n : ℕ) (h : Odd n) :\n  ( Irrational x ) -> Irrational ( x + y ) := sorry",
                env=-1,
            ),
            add_to_session_cache=True,
            verbose=True,
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
        result = server.run(ProofStep(tactic="apply irrational_add_ratCast_iff.mpr", proof_state=0), verbose=True)
        self.assertEqual(result, ProofStepResponse(proof_state=1, goals=[], proof_status="Completed"))

    def test_restart_with_env(self):
        server = AutoLeanServer(config=LeanREPLConfig(verbose=True))
        result = server.run(Command(cmd="def x := 1"), add_to_session_cache=True, verbose=True)
        assert not isinstance(result, LeanError)
        env_id = result.env
        self.assertEqual(env_id, -1)
        server.restart()
        result = server.run(Command(cmd="noncomputable def y := x + 1", env=env_id), verbose=True)
        self.assertEqual(result, CommandResponse(env=1))
        self.assertEqual(list(server._session_cache.keys()), [env_id])

    def test_process_request_memory_restart(self):
        server = AutoLeanServer(config=LeanREPLConfig(verbose=True), max_total_memory=0.01, max_restart_attempts=2)
        # Mock psutil.virtual_memory().percent to be high
        with unittest.mock.patch("psutil.virtual_memory") as mock_virtual_memory:
            mock_virtual_memory.return_value.percent = 99.0
            with unittest.mock.patch("time.sleep", return_value=None):
                with self.assertRaises(MemoryError):
                    server.run(Command(cmd="test"), verbose=True)
        self.assertFalse(server.is_alive())

    @unittest.mock.patch("lean_interact.server.LeanServer.run_dict")
    def test_process_request_with_negative_env_id(self, mock_super):
        server = AutoLeanServer(config=LeanREPLConfig(verbose=True, enable_parallel_elaboration=False))
        # Prepare restart_persistent_session_cache
        assert isinstance(server._session_cache, PickleSessionCache)
        server._session_cache._cache[-1] = PickleSessionState(-1, 10, False, "")
        with unittest.mock.patch.object(server, "_get_repl_state_id", return_value=10):
            mock_super.return_value = {"env": 10}
            result = server.run(Command(cmd="test", env=-1))
            mock_super.assert_called_with(
                request={"cmd": "test", "env": 10, "incrementality": True}, verbose=False, timeout=DEFAULT_TIMEOUT
            )
            self.assertEqual(result, CommandResponse(env=10))

    @unittest.mock.patch("lean_interact.server.LeanServer.run_dict")
    def test_process_request_with_negative_proof_state_id(self, mock_super):
        server = AutoLeanServer(config=LeanREPLConfig(verbose=True))
        # Prepare restart_persistent_session_cache
        assert isinstance(server._session_cache, PickleSessionCache)
        server._session_cache._cache[-2] = PickleSessionState(-2, 20, True, "")
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
        server.run(Command(cmd="test"), verbose=True)
        self.assertTrue(server.is_alive())

    @unittest.mock.patch("lean_interact.server.LeanServer.run_dict")
    def test_process_request_timeout_recovery(self, mock_process_request):
        # Simulate a timeout exception
        mock_process_request.side_effect = TimeoutError("Simulated timeout")

        server = AutoLeanServer(config=LeanREPLConfig(verbose=True))
        with self.assertRaises(TimeoutError):
            server.run(Command(cmd="test"), timeout=1, verbose=True)

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
            server.run(Command(cmd="test"), verbose=True)

        # Verify that the server is not alive after exceeding max restart attempts
        self.assertFalse(server.is_alive())

    def test_autoleanserver_recovery_after_timeout(self):
        server = AutoLeanServer(config=LeanREPLConfig(verbose=True))

        with self.assertRaises(TimeoutError):
            server.run(Command(cmd="def x := y"), verbose=True, timeout=0)

        # Send a new command to verify auto-recovery
        result = server.run(Command(cmd="def z := 3"), verbose=True)
        self.assertEqual(result, CommandResponse(env=0))

    def test_leanserver_killed_after_timeout(self):
        server = LeanServer(config=LeanREPLConfig(verbose=True))

        with self.assertRaises(TimeoutError):
            server.run(Command(cmd="def a := b"), verbose=True, timeout=0)

        # Ensure the server is killed after the timeout
        self.assertFalse(server.is_alive())
        with self.assertRaises(ChildProcessError):
            server.run(Command(cmd="def z := 3"), verbose=True)

    def test_timeout_respected(self):
        if platform.system() == "Windows":
            self.skipTest("(Temporary) Skipping test on Windows due to long path issues in the CI")

        config = LeanREPLConfig(project=TempRequireProject(lean_version=self.mostRecentVersion, require="mathlib"))
        server = AutoLeanServer(config)

        response = server.run(
            Command(cmd="import Mathlib\nset_option maxHeartbeats 0\nset_option maxRecDepth 100000"),
            add_to_session_cache=True,
        )
        assert isinstance(response, CommandResponse)
        root_env = response.env

        # check that the next command takes less than 3 seconds
        start = time.time()
        with self.assertRaises(TimeoutError):
            server.run(
                Command(
                    cmd="def fib : Nat → Nat\n  | 0 => 0\n  | 1 => 1\n  | n + 2 => fib (n + 1) + fib n\n\n#eval fib 40",
                    env=root_env,
                ),
                timeout=2,
            )
        self.assertLess(time.time() - start, 3)

    # def test_run_proof(self):
    #     server = AutoLeanServer(config=LeanREPLConfig(verbose=True))
    #     result = server.run(
    #         Command(cmd="theorem test_run_proof : (x : Nat) -> x = x := sorry", add_to_session_cache=True, verbose=True)
    #     )
    #     self.assertEqual(result.get("env"), -1)

    #     proof_result = server.run_proof("intro x\nrfl", proof_state=0)
    #     self.assertDictEqual(proof_result, {"proofState": 1, "goals": []})

    def test_run_proof_equivalence(self):
        server = AutoLeanServer(config=LeanREPLConfig(verbose=True))
        result = server.run(
            Command(cmd="theorem test_run_proof_seq : (x : Nat) -> x = x := sorry"),
            add_to_session_cache=True,
            verbose=True,
        )
        assert not isinstance(result, LeanError)
        self.assertEqual(result.env, -1)

        step1 = server.run(ProofStep(tactic="intro x", proof_state=0), verbose=True)
        assert not isinstance(step1, LeanError)
        step2 = server.run(ProofStep(tactic="rfl", proof_state=step1.proof_state), verbose=True)
        self.assertEqual(step2, ProofStepResponse(proof_state=2, goals=[], proof_status="Completed"))

    def test_declaration_info(self):
        server = AutoLeanServer(config=LeanREPLConfig(verbose=True))
        result = server.run(Command(cmd="def x := 42", declarations=True), verbose=True)
        self.assertEqual(
            result,
            CommandResponse(
                declarations=[
                    DeclarationInfo(
                        pp="def x := 42",
                        range=Range(synthetic=False, start=Pos(line=1, column=0), finish=Pos(line=1, column=11)),
                        scope=ScopeInfo(
                            var_decls=[],
                            include_vars=[],
                            omit_vars=[],
                            level_names=[],
                            curr_namespace="[anonymous]",
                            open_decl=[],
                        ),
                        name="x",
                        full_name="x",
                        kind="definition",
                        modifiers=DeclModifiers(
                            doc_string=None,
                            visibility="regular",
                            compute_kind="regular",
                            rec_kind="default",
                            is_protected=False,
                            is_unsafe=False,
                            attributes=[],
                        ),
                        signature=DeclSignature(
                            pp="",
                            constants=[],
                            range=Range(synthetic=True, start=Pos(line=1, column=0), finish=Pos(line=1, column=0)),
                        ),
                        binders=None,
                        type=None,
                        value=DeclValue(
                            pp=":= 42",
                            constants=[],
                            range=Range(synthetic=False, start=Pos(line=1, column=6), finish=Pos(line=1, column=11)),
                        ),
                    )
                ],
                env=0,
            ),
        )

        result = server.run(
            Command(cmd="variable (p : Prop)\ntheorem test (h : p) : 0 = 0 := by rfl", declarations=True), verbose=True
        )
        print(result)
        self.assertEqual(
            result,
            CommandResponse(
                messages=[
                    Message(
                        end_pos=Pos(column=15, line=2),
                        severity="warning",
                        data="unused variable `h`\n\nNote: This linter can be disabled with `set_option linter.unusedVariables false`",
                        start_pos=Pos(column=14, line=2),
                    )
                ],
                env=1,
                declarations=[
                    DeclarationInfo(
                        pp="theorem test (h : p) : 0 = 0 := by rfl",
                        type=DeclType(
                            pp="0 = 0",
                            range=Range(synthetic=False, finish=Pos(column=28, line=2), start=Pos(column=23, line=2)),
                            constants=[],
                        ),
                        full_name="test",
                        binders=DeclBinders(
                            pp="(h : p)",
                            groups=["(h : p)"],
                            map=[BinderView(id="h", type="p", binderInfo="default")],
                            range=Range(synthetic=False, finish=Pos(column=20, line=2), start=Pos(column=13, line=2)),
                        ),
                        kind="theorem",
                        range=Range(synthetic=False, finish=Pos(column=38, line=2), start=Pos(column=0, line=2)),
                        modifiers=DeclModifiers(
                            doc_string=None,
                            is_unsafe=False,
                            is_protected=False,
                            rec_kind="default",
                            attributes=[],
                            visibility="regular",
                            compute_kind="regular",
                        ),
                        signature=DeclSignature(
                            pp="(h : p) : 0 = 0",
                            range=Range(synthetic=False, finish=Pos(column=28, line=2), start=Pos(column=13, line=2)),
                            constants=["h", "p"],
                        ),
                        scope=ScopeInfo(
                            level_names=[],
                            open_decl=[],
                            curr_namespace="[anonymous]",
                            omit_vars=[],
                            var_decls=["variable (p : Prop)"],
                            include_vars=[],
                        ),
                        name="test",
                        value=DeclValue(
                            pp=":= by rfl",
                            range=Range(synthetic=False, finish=Pos(column=38, line=2), start=Pos(column=29, line=2)),
                            constants=[],
                        ),
                    )
                ],
            ),
        )

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

    def test_infotree_theorems(self):
        """Test infotree theorems for full infotrees"""
        server = AutoLeanServer(config=LeanREPLConfig(verbose=True))

        result = server.run(Command(cmd="theorem infotree_test : 0 = 0 := by rfl", infotree="full"))
        self.assertIsInstance(result, CommandResponse)
        assert isinstance(result, CommandResponse)
        self.assertIsNotNone(result.infotree)
        assert result.infotree is not None
        assert len(list(result.infotree[0].commands())) == 1
        assert len(list(result.infotree[0].theorems())) == 1

    def test_infotree_variables(self):
        """Test infotree theorems for full infotrees"""
        server = AutoLeanServer(config=LeanREPLConfig(verbose=True))

        result = server.run(
            Command(cmd="variable (p : Prop)\ntheorem infotree_test (h : p) : 0 = 0 := by rfl", infotree="full")
        )
        self.assertIsInstance(result, CommandResponse)
        assert isinstance(result, CommandResponse)
        self.assertIsNotNone(result.infotree)
        assert result.infotree is not None
        assert len(list(result.infotree[0].variables())) == 1
        assert len(list(result.infotree[1].theorems())) == 1

    def test_infotree_sorry(self):
        """Test infotree theorems for full infotrees"""
        server = AutoLeanServer(config=LeanREPLConfig(verbose=True))

        result = server.run(Command(cmd="theorem infotree_test : 0 = 0 := by sorry", infotree="full"))
        self.assertIsInstance(result, CommandResponse)
        assert isinstance(result, CommandResponse)
        assert len(result.sorries) == 1
        sorry = result.sorries[0]
        self.assertIsNotNone(result.infotree)
        assert result.infotree is not None
        assert len(list(result.infotree[0].theorems())) == 1
        self.assertIsNotNone(result.infotree[0].theorem_for_sorry(sorry))

    def test_run_multiple_commands(self):
        if platform.system() != "Linux":
            self.skipTest("This test is only relevant on Linux")

        # Check that the following issue is now solved: https://github.com/leanprover-community/repl/issues/77
        server = AutoLeanServer(config=LeanREPLConfig(memory_hard_limit_mb=4096, verbose=True))

        for i in range(1000):
            cmd = Command(cmd=f"theorem womp{i} (a{i} b c : Nat) : (a{i} + b) + c = c + a{i} + b := by sorry")
            server.run(cmd)

    def test_run_lots_of_commands(self):
        # Test this issue: https://github.com/leanprover-community/repl/issues/77
        server = LeanServer(LeanREPLConfig(verbose=True))

        init_env = server.run(Command(cmd="#eval 1"), verbose=True)
        assert not isinstance(init_env, LeanError)
        for i in range(1000):
            cmd = Command(
                cmd=f"theorem womp{i} (a{i} b c : Nat) : (a{i} + b) + c = c + a{i} + b := by sorry", env=init_env.env
            )
            result = server.run(cmd)
            self.assertIsInstance(result, CommandResponse)

    def test_bug_increasing_memory(self):
        if platform.system() != "Linux":
            self.skipTest("This test is only relevant on Linux")

        mem_limit = 512
        server = AutoLeanServer(config=LeanREPLConfig(memory_hard_limit_mb=mem_limit, verbose=True))

        # Get initial memory usage
        assert server._proc is not None
        server_process = psutil.Process(server._proc.pid)
        start_mem = get_total_memory_usage(server_process) / (1024 * 1024)  # Convert to MB

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
                    verbose=True,
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
                current_mem = get_total_memory_usage(server_process) / (1024 * 1024)
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
        result = server.run(Command(cmd="def x := 42"), add_to_session_cache=True, verbose=True)
        self.assertEqual(result, CommandResponse(env=-1))
        assert isinstance(result, CommandResponse)
        env_id = result.env

        # Pickle the environment
        temp_pickle = tempfile.NamedTemporaryFile(suffix=".olean", delete=False)
        temp_pickle.close()  # Close the file to allow writing

        pickle_result = server.run(PickleEnvironment(env=env_id, pickle_to=temp_pickle.name), verbose=True)
        self.assertIsInstance(pickle_result, CommandResponse)

        # Create a new server
        new_server = AutoLeanServer(config=LeanREPLConfig(verbose=True))

        # Unpickle the environment in the new server
        unpickle_result = new_server.run(UnpickleEnvironment(unpickle_env_from=temp_pickle.name), verbose=True)
        assert isinstance(unpickle_result, CommandResponse)
        unpickled_env_id = unpickle_result.env

        # TODO: there is a bug with the REPL pickling process which transforms `def` into `noncomputable def`

        # Test that the unpickled environment contains the original definition
        result = new_server.run(Command(cmd="noncomputable def y := x + 1", env=unpickled_env_id), verbose=True)
        self.assertEqual(result, CommandResponse(env=1))

        # # Test evaluation works with the unpickled environment
        # eval_result = new_server.run(Command(cmd="#eval x", env=1), verbose=True)
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
        try:
            os.remove(temp_pickle.name)
        except (FileNotFoundError, PermissionError):
            pass

    def test_pickle_unpickle_proof_state(self):
        server = AutoLeanServer(config=LeanREPLConfig(verbose=True))

        # Create a theorem with a proof state
        result = server.run(
            Command(cmd="theorem test_pickle : 0 = 0 := sorry"), add_to_session_cache=True, verbose=True
        )
        assert isinstance(result, CommandResponse)
        self.assertEqual(len(result.sorries), 1)
        proof_state_id = result.sorries[0].proof_state
        assert isinstance(proof_state_id, int)

        # Pickle the proof state
        temp_pickle = tempfile.NamedTemporaryFile(suffix=".olean", delete=False)
        temp_pickle.close()  # Close the file to allow writing

        pickle_result = server.run(
            PickleProofState(proof_state=proof_state_id, pickle_to=temp_pickle.name), verbose=True
        )
        self.assertIsInstance(pickle_result, ProofStepResponse)

        # Create a new server
        new_server = AutoLeanServer(config=LeanREPLConfig(verbose=True))

        # Unpickle the proof state in the new server
        unpickle_result = new_server.run(UnpickleProofState(unpickle_proof_state_from=temp_pickle.name), verbose=True)
        assert isinstance(unpickle_result, ProofStepResponse)
        unpickled_proof_state_id = unpickle_result.proof_state

        # Test that we can continue the proof from the unpickled proof state
        tactic_result = new_server.run(ProofStep(tactic="rfl", proof_state=unpickled_proof_state_id), verbose=True)
        self.assertEqual(tactic_result, ProofStepResponse(proof_state=1, goals=[], proof_status="Completed"))

        # Delete the temp file
        try:
            os.remove(temp_pickle.name)
        except (FileNotFoundError, PermissionError):
            pass

    def test_pickle_fails_with_invalid_env(self):
        server = AutoLeanServer(config=LeanREPLConfig(verbose=True))

        # Try to pickle a non-existent environment
        temp_pickle = tempfile.NamedTemporaryFile(suffix=".olean", delete=False)
        temp_pickle.close()  # Close the file to allow writing

        result = server.run(PickleEnvironment(env=999, pickle_to=temp_pickle.name), verbose=True)
        assert isinstance(result, LeanError)
        self.assertEqual("unknown environment.", result.message.lower())

        # delete the temp file
        try:
            os.remove(temp_pickle.name)
        except (FileNotFoundError, PermissionError):
            pass

    def test_unpickle_fails_with_invalid_data(self):
        server = AutoLeanServer(config=LeanREPLConfig(verbose=True))
        # Try to unpickle invalid data
        temp_pickle = tempfile.NamedTemporaryFile(suffix=".olean", delete=False)
        temp_pickle.close()  # Close the file to allow writing

        # Try to unpickle invalid data
        with self.assertRaises(ConnectionAbortedError):
            server.run(UnpickleEnvironment(unpickle_env_from=temp_pickle.name), verbose=True)
        with self.assertRaises(ConnectionAbortedError):
            server.run(UnpickleProofState(unpickle_proof_state_from=temp_pickle.name), verbose=True)

        # delete the temp file
        try:
            os.remove(temp_pickle.name)
        except (FileNotFoundError, PermissionError):
            pass

    def test_pickle_unpickle_with_complex_environment(self):
        server = AutoLeanServer(config=LeanREPLConfig(verbose=True))

        # Create a more complex environment with multiple definitions and imports
        cmds = [
            "def add_one (n : Nat) : Nat := n + 1",
            "def double (n : Nat) : Nat := n * 2",
            "def compute (n : Nat) : Nat := double (add_one n)",
        ]

        env_id = None
        for cmd in cmds:
            result = server.run(Command(cmd=cmd, env=env_id), add_to_session_cache=True, verbose=True)
            assert isinstance(result, CommandResponse)
            env_id = result.env
        assert env_id is not None

        # Verify the environment works
        eval_result = server.run(Command(cmd="#eval compute 5", env=env_id), verbose=True)
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
        temp_pickle = tempfile.NamedTemporaryFile(suffix=".olean", delete=False)
        temp_pickle.close()  # Close the file to allow writing

        pickle_result = server.run(PickleEnvironment(env=env_id, pickle_to=temp_pickle.name), verbose=True)
        self.assertIsInstance(pickle_result, CommandResponse)

        # Create a new server and unpickle
        new_server = AutoLeanServer(config=LeanREPLConfig(verbose=True))
        unpickle_result = new_server.run(UnpickleEnvironment(unpickle_env_from=temp_pickle.name), verbose=True)
        assert isinstance(unpickle_result, CommandResponse)
        unpickled_env_id = unpickle_result.env

        # TODO: there is a bug with the REPL pickling process which transforms `def` into `noncomputable def`

        # # Test that the functions still work in the unpickled environment
        # eval_result = new_server.run(Command(cmd="#eval compute 10", env=unpickled_env_id), verbose=True)
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
        try:
            os.remove(temp_pickle.name)
        except (FileNotFoundError, PermissionError):
            pass

    def test_separate_cache_dirs(self):
        """Test that projects manage their own cache directories independently."""
        # Create temporary directories
        repl_cache = Path(tempfile.mkdtemp(prefix="test_repl_cache")).resolve()
        project_cache = Path(tempfile.mkdtemp(prefix="test_project_cache")).resolve()

        try:
            # Create config with REPL cache directory
            config = LeanREPLConfig(cache_dir=repl_cache, lean_version="v4.18.0", verbose=True)
            self.assertEqual(config.cache_dir.resolve(), repl_cache)

            # Test with a project that has its own directory
            project_config = LeanREPLConfig(
                cache_dir=repl_cache,
                project=TempRequireProject(require=[], lean_version="v4.18.0", directory=project_cache),
                verbose=True,
            )

            # REPL still uses its own cache
            self.assertEqual(project_config.cache_dir.resolve(), repl_cache)
            # Project uses its specified directory
            self.assertEqual(Path(project_config.working_dir).resolve(), project_cache)

        finally:
            # Clean up
            shutil.rmtree(repl_cache, ignore_errors=True)
            shutil.rmtree(project_cache, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
