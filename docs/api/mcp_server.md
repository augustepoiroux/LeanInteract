# Lean Interact MCP Server

The LeanInteract library includes an MCP (Model Context Protocol) server that exposes its core functionalities, allowing language models and other MCP-compatible clients to interact with Lean 4 programmatically.

## Overview

The MCP server acts as a bridge between the Model Context Protocol and the underlying `LeanServer` or `AutoLeanServer` provided by LeanInteract. It allows clients to send requests to execute Lean commands, process files, manage proof states, and more, all through a standardized MCP interface.

## Running the Server

You can run the Lean Interact MCP server in a couple of ways:

1.  **Directly using Python**:
    If LeanInteract is installed in your environment, you can run the server module directly:
    ```bash
    python -m lean_interact.mcp_server
    ```
    This will start the server with a default `LeanREPLConfig`.

2.  **Using the MCP CLI tools**:
    The `mcp-sdk` provides command-line tools for development and running MCP servers. Navigate to the directory containing the `lean_interact` source (or your installed package's `mcp_server.py` file) and run:
    ```bash
    # For development with live reloading and inspection UI
    mcp dev path/to/lean_interact/mcp_server.py

    # To run the server
    mcp run path/to/lean_interact/mcp_server.py
    ```
    Replace `path/to/` with the actual path to `mcp_server.py`. If you have `lean-interact` installed as a package, this path might be inside your Python environment's `site-packages` directory.

## Configuration

The MCP server uses a `LeanREPLConfig` object to configure the underlying Lean environment (e.g., Lean version, project directory, memory limits).

When running `python -m lean_interact.mcp_server`, the server is started with a default `LeanREPLConfig` (verbose logging enabled, latest compatible Lean version). To use a custom configuration at startup:

1.  You can modify the `__main__` block in `src/lean_interact/mcp_server.py` to instantiate `LeanMCPServer` with your desired `LeanREPLConfig` object.
    ```python
    # Example in mcp_server.py's __main__
    if __name__ == '__main__':
        print("Configuring and starting Lean Interact MCP Server...")
        custom_config = LeanREPLConfig(lean_version="v4.7.0", verbose=True)
        mcp_server = LeanMCPServer(config=custom_config)
        mcp_server.run()
    ```

2.  If you are importing `LeanMCPServer` programmatically from another script, you can pass the desired `LeanREPLConfig` instance to its constructor.

The `GLOBAL_LEAN_CONFIG` mechanism in `mcp_server.py` allows the initial configuration to be set before the server's lifespan manager initializes the `AutoLeanServer`.

Furthermore, the Lean environment can be dynamically reconfigured after startup using the `configure_lean_environment` tool described below.

## Exposed Tools

The server exposes the following tools, which correspond to LeanInteract's functionalities:

*   **`execute_lean_command`**: Executes a Lean command string.
    *   `cmd: str`: The Lean command to execute.
    *   `env: Optional[int]`: Environment ID to use (for stateful interaction).
    *   `all_tactics: Optional[bool]`: Whether to return all tactics info.
    *   `root_goals: Optional[bool]`: Whether to return root goals.
    *   `infotree: Optional[str]`: Infotree mode ("full", "tactics", etc.).
    *   *Returns*: `dict` (JSON representation of `CommandResponse` or `LeanError`).

*   **`execute_file_command`**: Executes all commands in a specified Lean file.
    *   `path: str`: Path to the `.lean` file.
    *   `all_tactics: Optional[bool]`: (See above).
    *   `root_goals: Optional[bool]`: (See above).
    *   `infotree: Optional[str]`: (See above).
    *   *Returns*: `dict` (JSON representation of `CommandResponse` or `LeanError`).

*   **`execute_proof_step`**: Applies a tactic within a given proof state.
    *   `proof_state: int`: The ID of the proof state to operate on.
    *   `tactic: str`: The tactic string to apply.
    *   *Returns*: `dict` (JSON representation of `ProofStepResponse` or `LeanError`).

*   **`configure_lean_environment`**: Dynamically reconfigures the Lean environment and restarts the internal Lean server. This is useful for changing Lean versions, projects, or other settings without restarting the entire MCP server process.
    *   `lean_version: Optional[str]`: The desired Lean version string (e.g., "v4.7.0"). If `None`, the existing version is kept or a default is used.
    *   `repl_rev: Optional[str]`: The specific revision (commit hash or tag) of the Lean REPL to use. If `None`, a default revision for the Lean version is used.
    *   `memory_hard_limit_mb: Optional[int]`: A memory hard limit for the Lean process in Megabytes. If `None`, no limit is set or existing is kept.
    *   `verbose: Optional[bool]`: Enables or disables verbose logging for the Lean REPL interactions. If `None`, existing setting is kept or defaults to `True`.
    *   `project_type: Optional[str]`: Specifies the type of Lean project. Can be:
        *   `"local"`: Use an existing local Lean project. Requires `project_config` with `{"path": "/path/to/project"}`.
        *   `"git"`: Clone a Lean project from a Git repository. Requires `project_config` with `{"url": "repository_url", "rev": "optional_commit_hash_or_tag"}`.
        *   `"temp_mathlib"`: Create a temporary project with Mathlib as a dependency. `project_config` can be minimal or `None`.
        *   `"temp_require"`: Create a temporary project with specified dependencies. Requires `project_config` with `{"require_str": "dep"}` or `{"require_list": ["dep1", "dep2"]}`.
        *   `"none"`: Explicitly use no project (a bare Lean environment).
        *   If `None`, the existing project configuration is maintained if possible.
    *   `project_config: Optional[Dict[str, Any]]`: A dictionary containing configuration specific to the `project_type`.
        *   For `local`: `{"path": "your_project_directory", "build": True/False}` (build defaults to True).
        *   For `git`: `{"url": "git_url", "rev": "commit_hash_or_tag"}`.
        *   For `temp_require`: `{"require_str": "dep_name"}` or `{"require_list": ["dep1", "dep2"]}`.
    *   *Returns*: `dict` confirming success (e.g., `{"status": "Lean environment reconfigured successfully.", "new_config_details": {...}}`) or an error (e.g., `{"error": "description", "details": "..."}`).

All tools return a dictionary. In case of an error during processing (e.g., Lean process error, timeout), the dictionary will typically contain an "error" key with details.

## Interacting with the Server

Clients can interact with these tools using any MCP-compatible client library. The specifics of making calls (e.g., tool invocation requests) are defined by the Model Context Protocol. For detailed information on MCP client development and the protocol itself, please refer to the official [MCP documentation](https://modelcontextprotocol.io/).
