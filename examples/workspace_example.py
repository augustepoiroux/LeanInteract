#!/usr/bin/env python3
"""
Example demonst        # Example 2: Run commands with global session management
        print("\n2. Running commands with global session management...")
        try:
            # Run a command and add to global session cache
            result = workspace.run(
                Command(cmd="def test_value : Nat := 42"), 
                add_to_session_cache=True
            )
            print(f"Command result: {type(result).__name__}")
            
            # The environment is now available globally - any subsequent command
            # will automatically route to the correct server
            env_id = getattr(result, 'env', None) if hasattr(result, 'env') else None
            if env_id is not None:
                result2 = workspace.run(Command(cmd="#check test_value", env=env_id))
                print(f"Check result routed automatically: {type(result2).__name__}")

        except Exception as e:
            print(f"Error running commands: {e}")
            
        # Example 3: Demonstrate cross-file session sharing
        print("\n3. Cross-file session sharing...")
        try:
            # Create environment in one file
            result1 = workspace.run(
                Command(cmd="def shared_def : String := \"shared across files\""),
                add_to_session_cache=True
            )
            
            # Access same environment from different context - workspace routes automatically
            env_id = getattr(result1, 'env', None)
            if env_id is not None:
                result2 = workspace.run(Command(cmd="#check shared_def", env=env_id))
                print(f"Successfully shared environment across workspace: {type(result2).__name__}")
            
        except Exception as e:
            print(f"Error with cross-file sharing: {e}") of LeanWorkspace for project-level management.

This example shows how LeanWorkspace provides a higher-level abstraction for
working with multiple files in a Lean project, with automatic dependency
tracking and smart server restarts.
"""

from lean_interact import Command, FileCommand, LeanREPLConfig, LeanWorkspace, TempRequireProject


def main():
    """Demonstrate LeanWorkspace usage."""

    # Create a temporary project with mathlib
    project = TempRequireProject(lean_version="v4.8.0", require=["mathlib"])

    # Create config for the project
    config = LeanREPLConfig(project=project)

    # Create a workspace manager for the project
    with LeanWorkspace(config, cache_dependencies=True) as workspace:
        print("=== LeanWorkspace Example ===")

        # Example 1: Run a FileCommand to process a Lean file
        print("\n1. Processing a Lean file with FileCommand...")
        try:
            from pathlib import Path

            # Create a test file
            project_dir = Path(config.working_dir)
            test_file = project_dir / "Test.lean"
            test_file.write_text('def hello : String := "Hello from file!"')

            # Use FileCommand directly - this will trigger change detection
            result = workspace.run(FileCommand(path=str(test_file), declarations=True))
            print(f"FileCommand processed successfully: {type(result).__name__}")

        except Exception as e:
            print(f"Error with FileCommand: {e}")

        # Example 2: Run commands directly
        print("\n2. Running commands directly...")
        try:
            # Run a simple command - this goes to default server
            result = workspace.run(Command(cmd="def test_value : Nat := 42"))
            print(f"Command result: {type(result).__name__}")

            # Run another command that depends on the first
            env_id = getattr(result, "env", None) if hasattr(result, "env") else None
            result2 = workspace.run(Command(cmd="#check test_value", env=env_id))
            print(f"Check result: {type(result2).__name__}")

        except Exception as e:
            print(f"Error running commands: {e}")

        # Example 3: Get dependency information
        print("\n3. Dependency tracking...")
        try:
            deps = workspace.get_file_dependencies("Example.lean")
            print(f"Dependencies for Example.lean: {deps}")
        except Exception as e:
            print(f"Error getting dependencies: {e}")

        # Example 4: Session cache management
        print("\n4. Session cache management...")
        try:
            # Create an environment and add to cache
            result = workspace.run(
                Command(cmd="def cached_def : Nat := 123"),
                add_to_session_cache=True
            )
            
            # Remove from cache
            env_id = getattr(result, 'env', None)
            if env_id is not None and env_id < 0:  # Negative IDs are workspace session IDs
                workspace.remove_from_session_cache(env_id)
                print("Successfully managed session cache")
            
        except Exception as e:
            print(f"Error with session cache: {e}")

        # Example 5: Manual server management
        print("\n5. Server management...")
        try:
            # Get server instance for advanced usage
            server = workspace.get_server_for_file("Example.lean")
            print(f"Server for Example.lean: {type(server).__name__}")

            # Restart specific file server
            workspace.restart_file_server("Example.lean")
            print("Server restarted successfully")

        except Exception as e:
            print(f"Error managing servers: {e}")

        print("\n=== Example completed ===")


def demonstrate_comparison():
    """Show the difference between old approach and new LeanWorkspace approach."""

    print("\n=== Comparison: Old vs New Approach ===")

    project = TempRequireProject(lean_version="v4.8.0", require=["mathlib"])

    print("\n--- Old approach (per-file server management) ---")
    try:
        from lean_interact import AutoLeanServer, LeanREPLConfig

        config = LeanREPLConfig(project=project)

        # User has to manually manage servers for each file
        server1 = AutoLeanServer(config)
        server2 = AutoLeanServer(config)

        print("Created multiple servers manually")
        print("User responsible for:")
        print("- Tracking which server belongs to which file")
        print("- Restarting servers when dependencies change")
        print("- Managing memory across multiple servers")
        print("- Coordinating shared state")

        server1.kill()
        server2.kill()

    except Exception as e:
        print(f"Error in old approach: {e}")

    print("\n--- New approach (LeanWorkspace) ---")
    try:
        from lean_interact import LeanREPLConfig

        config = LeanREPLConfig(project=project)

        with LeanWorkspace(config) as workspace:
            print("Created workspace manager")
            print("Workspace automatically handles:")
            print("- One server per file with automatic creation")
            print("- Dependency tracking and smart restarts")
            print("- Global session cache for environments/proof states")
            print("- Intelligent routing based on session state")
            print("- Thread-safe operations")
            print("- Context management and cleanup")

            # Simple, intuitive API with global session management
            result = workspace.run(Command(cmd="def x := 42"), add_to_session_cache=True)
            print(f"API with global session management: {type(result).__name__}")
            
            # Automatic routing based on environment
            env_id = getattr(result, 'env', None)
            if env_id:
                result2 = workspace.run(Command(cmd="#check x", env=env_id))
                print(f"Automatic routing to correct server: {type(result2).__name__}")

    except Exception as e:
        print(f"Error in new approach: {e}")


if __name__ == "__main__":
    main()
    demonstrate_comparison()
