import asyncio
import unittest
from unittest.mock import patch, AsyncMock, MagicMock

# Attempt to import LeanMCPServer and related components
try:
    from lean_interact.mcp_server import LeanMCPServer
    from lean_interact.config import LeanREPLConfig, LocalProject, GitProject, TempRequireProject, BaseProject # Added project types
    from lean_interact.interface import CommandResponse, LeanError, Command
    from lean_interact.server import AutoLeanServer
    from lean_interact.utils import DEFAULT_REPL_VERSION # Added for default repl_rev
    MCP_SERVER_AVAILABLE = True
except ImportError:
    MCP_SERVER_AVAILABLE = False
    # Define placeholders if not available, so linters/type checkers don't complain in skipIf block
    class AutoLeanServer: pass
    class Command: pass
    class LeanMCPServer: pass
    class LeanREPLConfig: pass
    class CommandResponse: pass
    class LeanError: pass
    class LocalProject: pass
    class GitProject: pass
    class TempRequireProject: pass
    class BaseProject: pass
    DEFAULT_REPL_VERSION = "main"


# Conditional skip for tests if mcp_server components are not found
# This helps if tests are run in an environment where mcp_server might not be fully set up yet in early dev stages
# Or if its dependencies (like mcp-sdk) are missing.
@unittest.skipIf(not MCP_SERVER_AVAILABLE, "LeanMCPServer or its dependencies not available")
class TestLeanMCPServerInitialization(unittest.TestCase):

    def test_server_instantiation(self):
        """Test that LeanMCPServer can be instantiated."""
        try:
            # Mock LeanREPLConfig to avoid actual setup during instantiation for this basic test
            with patch('lean_interact.mcp_server.LeanREPLConfig', autospec=True) as MockLeanREPLConfig:
                mock_config_instance = MockLeanREPLConfig.return_value
                mock_config_instance.lean_version = "v4.0.0-test" # Example attribute
                mock_config_instance.working_dir = "/tmp/test_lean"
                mock_config_instance.verbose = False

                server = LeanMCPServer(config=mock_config_instance)
                self.assertIsNotNone(server, "Server should be instantiated.")
                self.assertIsNotNone(server.mcp, "Server should have an MCP FastMCP instance.")
                # self.assertEqual(server.mcp.title, "Lean Interact MCP Server") # Removed due to AttributeError
        except Exception as e:
            self.fail(f"LeanMCPServer instantiation failed: {e}")

@unittest.skipIf(not MCP_SERVER_AVAILABLE, "LeanMCPServer or its dependencies not available")
class TestMCPTools(unittest.IsolatedAsyncioTestCase): # Use IsolatedAsyncioTestCase for async tests

    def setUp(self):
        # Patch LeanREPLConfig globally for this test class to simplify server instantiation
        # Ensure that the mcp_server module (where LeanREPLConfig is used) is the target of the patch
        self.mock_lean_repl_config_patch = patch('lean_interact.mcp_server.LeanREPLConfig', autospec=True)
        self.MockLeanREPLConfig = self.mock_lean_repl_config_patch.start()

        self.mock_config_instance = self.MockLeanREPLConfig.return_value
        self.mock_config_instance.lean_version = "v4.0.0-test"
        # self.mock_config_instance.working_dir = "/tmp/test_lean" # Not a direct LeanREPLConfig constructor arg, but an attribute after init
        self.mock_config_instance.verbose = False
        self.mock_config_instance.repl_rev = DEFAULT_REPL_VERSION # Add missing attribute
        self.mock_config_instance.memory_hard_limit_mb = None # Add missing attribute
        self.mock_config_instance.project = None # Explicitly set for clarity

        # Patch AutoLeanServer used within app_lifespan (indirectly by tools)
        self.mock_auto_lean_server_patch = patch('lean_interact.mcp_server.AutoLeanServer', spec=AutoLeanServer)
        self.MockAutoLeanServer = self.mock_auto_lean_server_patch.start()
        self.mock_auto_lean_server_instance = self.MockAutoLeanServer.return_value

        self.server = LeanMCPServer(config=self.mock_config_instance)

        # Mock the context chain for self.mcp.get_context()
        # This is crucial for the tools to find the mocked lean_server
        self.mock_mcp_context = MagicMock()
        mock_request_context = MagicMock()
        mock_lifespan_context = MagicMock()

        # This is where the actual mock_auto_lean_server_instance should be placed
        mock_lifespan_context.lean_server = self.mock_auto_lean_server_instance
        mock_request_context.lifespan_context = mock_lifespan_context
        self.mock_mcp_context.request_context = mock_request_context

        self.get_context_patch = patch.object(self.server.mcp, 'get_context', return_value=self.mock_mcp_context)
        self.mock_get_context = self.get_context_patch.start()

    def tearDown(self):
        self.get_context_patch.stop()
        self.mock_auto_lean_server_patch.stop()
        self.mock_lean_repl_config_patch.stop()

    async def test_execute_lean_command_success(self):
        """Test successful execution of execute_lean_command tool."""
        mock_response_data = {
            "env": 1,
            "messages": [{
                "data": "Processed",
                "severity": "info",
                "pos": {"line": 1, "column": 0} # Added pos field
            }]
        }
        mock_lean_response = CommandResponse(**mock_response_data)
        self.mock_auto_lean_server_instance.async_run = AsyncMock(return_value=mock_lean_response)

        cmd_text = "theorem t: True := by trivial"
        result = await self.server.execute_lean_command(cmd=cmd_text, env=0)

        self.mock_auto_lean_server_instance.async_run.assert_called_once()
        called_arg = self.mock_auto_lean_server_instance.async_run.call_args[0][0]
        self.assertIsInstance(called_arg, Command)
        self.assertEqual(called_arg.cmd, cmd_text)
        self.assertEqual(called_arg.env, 0)

        expected_dict = mock_lean_response.model_dump(exclude_none=True, by_alias=True)
        self.assertEqual(result, expected_dict)

    async def test_execute_lean_command_lean_error_response(self):
        """Test execute_lean_command when Lean returns a LeanError."""
        mock_error_data = {"message": "Lean compilation error"}
        mock_lean_error = LeanError(**mock_error_data)
        self.mock_auto_lean_server_instance.async_run = AsyncMock(return_value=mock_lean_error)

        result = await self.server.execute_lean_command(cmd="broken command")

        self.mock_auto_lean_server_instance.async_run.assert_called_once()
        expected_dict = mock_lean_error.model_dump(exclude_none=True, by_alias=True)
        self.assertEqual(result, expected_dict)

    async def test_execute_lean_command_timeout_exception(self):
        """Test execute_lean_command when a TimeoutError occurs during Lean interaction."""
        self.mock_auto_lean_server_instance.async_run = AsyncMock(side_effect=TimeoutError("Lean timed out"))

        result = await self.server.execute_lean_command(cmd="long_running_command")

        self.mock_auto_lean_server_instance.async_run.assert_called_once()
        self.assertIn("error", result)
        self.assertEqual(result["error"], "TimeoutError")
        self.assertEqual(result["message"], "Lean timed out")
        self.assertEqual(result["details"], "Lean server communication error.")

    async def test_execute_lean_command_unexpected_exception(self):
        """Test execute_lean_command when an unexpected error occurs."""
        self.mock_auto_lean_server_instance.async_run = AsyncMock(side_effect=ValueError("Unexpected issue"))

        result = await self.server.execute_lean_command(cmd="command_causing_value_error")

        self.mock_auto_lean_server_instance.async_run.assert_called_once()
        self.assertIn("error", result)
        self.assertEqual(result["error"], "ValueError")
        self.assertEqual(result["message"], "Unexpected issue")
        self.assertEqual(result["details"], "An unexpected error occurred while processing the command.")

    async def test_configure_lean_environment_simple(self):
        """Test successful reconfiguration with a new Lean version."""
        new_lean_version = "v4.8.0"

        # Configure the mock that will be returned by LeanREPLConfig()
        mock_created_repl_config = MagicMock(spec=LeanREPLConfig)
        mock_created_repl_config.lean_version = new_lean_version
        mock_created_repl_config.repl_rev = DEFAULT_REPL_VERSION # This is what it would be called with
        mock_created_repl_config.project = None # Expected default from this call
        mock_created_repl_config.verbose = self.mock_config_instance.verbose # Expected from global/default
        mock_created_repl_config.memory_hard_limit_mb = self.mock_config_instance.memory_hard_limit_mb # Expected from global/default
        self.MockLeanREPLConfig.return_value = mock_created_repl_config

        # Mock the new AutoLeanServer instance
        mock_new_auto_lean_server = AsyncMock(spec=AutoLeanServer)
        self.MockAutoLeanServer.return_value = mock_new_auto_lean_server

        result = await self.server.configure_lean_environment(lean_version=new_lean_version)

        self.assertEqual(result["status"], "Lean environment reconfigured successfully.")
        self.assertEqual(result["new_config_details"]["lean_version"], new_lean_version)

        # verbose comes from global mock config (self.mock_config_instance.verbose = False)
        self.MockLeanREPLConfig.assert_called_once_with(lean_version=new_lean_version, repl_rev=DEFAULT_REPL_VERSION, verbose=False)
        self.mock_auto_lean_server_instance.kill.assert_called_once() # Old server killed
        self.MockAutoLeanServer.assert_called_once_with(mock_created_repl_config) # New server created with new config
        self.assertEqual(self.mock_mcp_context.request_context.lifespan_context.lean_server, mock_new_auto_lean_server) # Context updated

    async def test_configure_lean_environment_with_local_project(self):
        """Test reconfiguration with a local project."""
        project_path = "/test/project"

        mock_created_repl_config = MagicMock(spec=LeanREPLConfig)
        # These attributes are for the print statement and return dict after successful creation
        mock_created_repl_config.lean_version = self.mock_config_instance.lean_version
        mock_created_repl_config.repl_rev = self.mock_config_instance.repl_rev
        mock_created_repl_config.project = LocalProject(directory=project_path, build=False)
        mock_created_repl_config.verbose = self.mock_config_instance.verbose
        mock_created_repl_config.memory_hard_limit_mb = self.mock_config_instance.memory_hard_limit_mb
        self.MockLeanREPLConfig.return_value = mock_created_repl_config

        mock_new_auto_lean_server = AsyncMock(spec=AutoLeanServer)
        self.MockAutoLeanServer.return_value = mock_new_auto_lean_server

        result = await self.server.configure_lean_environment(
            project_type="local",
            project_config={"path": project_path, "build": False}
        )
        self.assertEqual(result["status"], "Lean environment reconfigured successfully.")

        # Check that LeanREPLConfig was called with a LocalProject instance
        called_args, called_kwargs = self.MockLeanREPLConfig.call_args
        self.assertIn("project", called_kwargs)
        self.assertIsInstance(called_kwargs["project"], LocalProject)
        self.assertEqual(called_kwargs["project"].directory, project_path)
        self.assertFalse(called_kwargs["project"].build) # Check build flag
        # Check that other args were picked from global mock config
        self.assertEqual(called_kwargs.get('lean_version'), self.mock_config_instance.lean_version)
        self.assertEqual(called_kwargs.get('verbose'), self.mock_config_instance.verbose)


    async def test_configure_lean_environment_config_creation_fails(self):
        """Test handling when LeanREPLConfig creation fails."""
        self.MockLeanREPLConfig.side_effect = ValueError("Config creation error")

        result = await self.server.configure_lean_environment(lean_version="bad-version")

        self.assertIn("error", result)
        self.assertEqual(result["error"], "Failed to create LeanREPLConfig")
        self.assertEqual(result["details"], "Config creation error")

    async def test_configure_lean_environment_server_creation_fails(self):
        """Test handling when AutoLeanServer creation fails after config is made."""
        mock_created_repl_config = MagicMock(spec=LeanREPLConfig)
        # Setup attributes for the print statement after successful LeanREPLConfig creation
        mock_created_repl_config.lean_version = "v4.7.0"
        mock_created_repl_config.repl_rev = DEFAULT_REPL_VERSION
        mock_created_repl_config.project = None
        mock_created_repl_config.verbose = self.mock_config_instance.verbose
        mock_created_repl_config.memory_hard_limit_mb = self.mock_config_instance.memory_hard_limit_mb
        self.MockLeanREPLConfig.return_value = mock_created_repl_config

        self.MockAutoLeanServer.side_effect = RuntimeError("Server creation error")

        result = await self.server.configure_lean_environment(lean_version="v4.7.0")

        self.assertIn("error", result)
        self.assertEqual(result["error"], "Failed to create new AutoLeanServer") # This is what we test
        self.assertEqual(result["details"], "Server creation error")
        self.mock_auto_lean_server_instance.kill.assert_called_once() # Old server should still be killed

    async def test_configure_lean_environment_invalid_project_config(self):
        """Test error handling for invalid project_config."""
        result = await self.server.configure_lean_environment(
            project_type="local",
            project_config={} # Missing 'path'
        )
        self.assertIn("error", result)
        self.assertEqual(result["error"], "project_config for 'local' must contain 'path'.")

# It's good practice to have a main for running tests via `python tests/test_mcp_server.py`
if __name__ == '__main__':
    unittest.main()
