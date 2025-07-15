import tempfile
import unittest

from lean_interact import Command, FileCommand, LeanREPLConfig, LeanWorkspace, TempRequireProject


class TestLeanWorkspace(unittest.TestCase):
    """Test cases for LeanWorkspace functionality."""

    @classmethod
    def setUpClass(cls):
        """Set up test configuration."""
        cls.project = TempRequireProject(lean_version="v4.8.0", require=["mathlib"], directory=tempfile.mkdtemp())
        cls.config = LeanREPLConfig(project=cls.project)

    def test_workspace_creation(self):
        """Test basic workspace creation and cleanup."""
        workspace = LeanWorkspace(self.config, cache_dependencies=False)
        self.assertIsNotNone(workspace.config)
        # Test that internal attributes exist
        self.assertIsNotNone(workspace._file_servers)
        self.assertIsNotNone(workspace._workspace_lock)
        workspace.close()

    def test_context_manager(self):
        """Test workspace as context manager."""
        with LeanWorkspace(self.config, cache_dependencies=False) as workspace:
            self.assertIsNotNone(workspace)
            # Workspace should be properly initialized
            self.assertIsNotNone(workspace.config)

    def test_run_method_basic(self):
        """Test the new run method with different request types."""
        with LeanWorkspace(self.config, cache_dependencies=False) as workspace:
            # Test with Command
            result = workspace.run(Command(cmd="def test_value : Nat := 42"))

            from lean_interact.interface import LeanError

            self.assertNotIsInstance(result, LeanError)

            # Test with FileCommand
            from pathlib import Path

            project_dir = Path(self.config.working_dir)
            test_file = project_dir / "TestFile.lean"
            test_file.write_text('def file_def : String := "test"')

            result2 = workspace.run(FileCommand(path=str(test_file), declarations=True))
            self.assertNotIsInstance(result2, LeanError)

    def test_get_server_for_file(self):
        """Test server creation and retrieval."""
        with LeanWorkspace(self.config, cache_dependencies=False) as workspace:
            # Get server for a file
            server1 = workspace.get_server_for_file("File1.lean")
            server2 = workspace.get_server_for_file("File1.lean")  # Should be same instance
            server3 = workspace.get_server_for_file("File2.lean")  # Should be different

            # Same file should return same server
            self.assertIs(server1, server2)
            # Different files should have different servers
            self.assertIsNot(server1, server3)

    def test_dependency_tracking_disabled(self):
        """Test that dependency tracking can be disabled."""
        with LeanWorkspace(self.config, cache_dependencies=False) as workspace:
            # Should return empty set when caching is disabled
            deps = workspace.get_file_dependencies("Test.lean")
            self.assertEqual(deps, set())

    def test_server_type(self):
        """Test that workspace uses AutoLeanServer."""
        with LeanWorkspace(self.config, cache_dependencies=False) as workspace:
            server = workspace.get_server_for_file("Test.lean")
            from lean_interact.server import AutoLeanServer

            self.assertIsInstance(server, AutoLeanServer)

    def test_global_session_management(self):
        """Test global session cache and routing."""
        with LeanWorkspace(self.config, cache_dependencies=False) as workspace:
            # Run command with session caching
            result1 = workspace.run(Command(cmd="def global_test : Nat := 42"), add_to_session_cache=True)

            from lean_interact.interface import LeanError

            self.assertNotIsInstance(result1, LeanError)

            # Should get a negative session ID for workspace-managed sessions
            env_id = getattr(result1, "env", None)
            self.assertIsNotNone(env_id)
            if env_id is not None:
                self.assertLess(env_id, 0)  # Session IDs are negative

                # Use the environment in another command - should route automatically
                result2 = workspace.run(Command(cmd="#check global_test", env=env_id))
                self.assertNotIsInstance(result2, LeanError)

    def test_session_cache_management(self):
        """Test session cache management methods."""
        with LeanWorkspace(self.config, cache_dependencies=False) as workspace:
            # Add to session cache
            result = workspace.run(Command(cmd="def cache_test := 1"), add_to_session_cache=True)

            env_id = getattr(result, "env", None)
            if env_id is not None and env_id < 0:
                # Remove from cache should not raise
                workspace.remove_from_session_cache(env_id)

            # Clear cache should not raise
            workspace.clear_session_cache()


if __name__ == "__main__":
    unittest.main()
