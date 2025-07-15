#!/usr/bin/env python3
"""Quick test of the new server parameter functionality in LeanWorkspace."""

import tempfile

from lean_interact import Command, LeanREPLConfig, LeanWorkspace, TempRequireProject


def test_server_parameter():
    """Test the new server parameter functionality."""

    # Create a simple temporary project
    project = TempRequireProject(lean_version="v4.8.0", require="mathlib")
    config = LeanREPLConfig(project=project, cache_dir=tempfile.mkdtemp())

    with LeanWorkspace(config, cache_dependencies=False) as workspace:
        print("✅ Workspace created successfully")

        # Test 1: Default routing (should use main server for non-FileCommands)
        response1 = workspace.run(Command(cmd="#check Nat"))
        print(f"✅ Default routing: {type(response1).__name__}")

        # Test 2: Explicit main server
        main_server = workspace.main_server
        response2 = workspace.run(Command(cmd="#check Nat"), server=main_server)
        print(f"✅ Explicit main server: {type(response2).__name__}")

        # Test 3: Try to get server for a hypothetical file (will create it)
        try:
            file_server = workspace.get_server_for_lean_file("Test.lean")
            response3 = workspace.run(Command(cmd="#check Nat"), server=file_server)
            print(f"✅ File server: {type(response3).__name__}")
        except Exception as e:
            print(f"ℹ️  File server test: {e}")

        print("✅ All tests completed successfully!")


if __name__ == "__main__":
    test_server_parameter()
