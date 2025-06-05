from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import wraps
from typing import Any, Callable, cast

from mcp.server.fastmcp import Context, FastMCP

from lean_interact.config import BaseProject, GitProject, LeanREPLConfig, LocalProject, TempRequireProject
from lean_interact.interface import (
    Command,
    CommandResponse,
    FileCommand,
    LeanError,
    ProofStep,
    ProofStepResponse,
)
from lean_interact.server import AutoLeanServer
from lean_interact.utils import DEFAULT_REPL_VERSION


@dataclass
class MCPServerLifespanContext:
    repl_config: LeanREPLConfig | None = None
    repl_server: AutoLeanServer | None = None


@asynccontextmanager
async def app_lifespan(_: FastMCP) -> AsyncIterator[MCPServerLifespanContext]:
    yield MCPServerLifespanContext()


def require_lean_environment(func: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator that checks if the Lean environment is configured."""

    @wraps(func)
    async def wrapper(ctx: Context, *args: Any, **kwargs: Any) -> dict[str, Any]:
        context: MCPServerLifespanContext = ctx.request_context.lifespan_context
        if not context.repl_server:
            return {
                "error": "No Lean environment configured",
                "message": "Please configure a Lean environment first using configure_lean_environment",
                "details": "No Lean server instance is available.",
            }
        return await func(ctx, *args, **kwargs)

    return wrapper


mcp = FastMCP(
    "LeanInteractMCP",
    description="Lean Interact MCP Server",
    dependencies=["lean-interact"],
    lifespan=app_lifespan,
)


@mcp.tool()
@require_lean_environment
async def execute_lean_command(
    ctx: Context,
    cmd: str,
    env: int | None = None,
    all_tactics: bool | None = None,
    root_goals: bool | None = None,
    infotree: str | None = None,
) -> dict[str, Any]:
    context: MCPServerLifespanContext = ctx.request_context.lifespan_context
    request = Command(cmd=cmd, env=env, all_tactics=all_tactics, root_goals=root_goals, infotree=infotree)
    try:
        # The decorator ensures repl_server is not None at this point
        response: CommandResponse | LeanError = await context.repl_server.async_run(request)  # type: ignore
        return response.model_dump(exclude_none=True, by_alias=True)
    except TimeoutError as e:
        return {"error": e.__class__.__name__, "message": str(e), "details": "Lean server command execution timed out."}
    except ConnectionAbortedError as e:
        return {"error": e.__class__.__name__, "message": str(e), "details": "Lean server communication error."}
    except Exception as e:  # pylint: disable=broad-except
        # Catch all unexpected errors to return a proper error response to the client
        print(f"Unexpected error in execute_lean_command: {type(e).__name__} - {e}")
        return {
            "error": type(e).__name__,
            "message": str(e),
            "details": "An unexpected error occurred while processing the command.",
        }


@mcp.tool()
@require_lean_environment
async def execute_file_command(
    ctx: Context,
    path: str,
    all_tactics: bool | None = None,
    root_goals: bool | None = None,
    infotree: str | None = None,
) -> dict[str, Any]:
    context: MCPServerLifespanContext = ctx.request_context.lifespan_context
    request = FileCommand(path=path, all_tactics=all_tactics, root_goals=root_goals, infotree=infotree)
    try:
        # The decorator ensures repl_server is not None at this point
        response: CommandResponse | LeanError = await context.repl_server.async_run(request)  # type: ignore
        return response.model_dump(exclude_none=True, by_alias=True)
    except (TimeoutError, ConnectionAbortedError) as e:
        return {"error": e.__class__.__name__, "message": str(e), "details": "Lean server communication error."}
    except Exception as e:  # pylint: disable=broad-except
        # Catch all unexpected errors to return a proper error response to the client
        print(f"Unexpected error in execute_file_command: {type(e).__name__} - {e}")
        return {
            "error": type(e).__name__,
            "message": str(e),
            "details": "An unexpected error occurred while processing the file command.",
        }


@mcp.tool()
@require_lean_environment
async def execute_proof_step(ctx: Context, proof_state: int, tactic: str) -> dict[str, Any]:
    context: MCPServerLifespanContext = ctx.request_context.lifespan_context
    request = ProofStep(proof_state=proof_state, tactic=tactic)
    try:
        # The decorator ensures repl_server is not None at this point
        response: ProofStepResponse | LeanError = await context.repl_server.async_run(request)  # type: ignore
        return response.model_dump(exclude_none=True, by_alias=True)
    except (TimeoutError, ConnectionAbortedError) as e:
        return {"error": e.__class__.__name__, "message": str(e), "details": "Lean server communication error."}
    except Exception as e:  # pylint: disable=broad-except
        # Catch all unexpected errors to return a proper error response to the client
        print(f"Unexpected error in execute_proof_step: {type(e).__name__} - {e}")
        return {
            "error": type(e).__name__,
            "message": str(e),
            "details": "An unexpected error occurred while processing the proof step.",
        }


@mcp.tool()
async def configure_lean_environment(
    ctx: Context,
    lean_version: str | None = None,
    project_type: str | None = None,
    project_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context: MCPServerLifespanContext = ctx.request_context.lifespan_context

    # Initialize config arguments with defaults
    final_config_args = {}

    # Use current context config values if they exist
    if context.repl_config:
        if lean_version is None and hasattr(context.repl_config, "lean_version"):
            final_config_args["lean_version"] = context.repl_config.lean_version

    # Override with any explicitly provided values
    if lean_version is not None:
        final_config_args["lean_version"] = lean_version

    final_config_args["verbose"] = True

    # Handle project configuration
    project: BaseProject | None = None
    if project_type:
        if project_config is None:
            project_config = {}  # Default to empty dict to simplify access

        if project_type == "local":
            if "path" not in project_config:
                return {"error": "project_config for 'local' must contain 'path'."}
            project = LocalProject(directory=project_config["path"], build=project_config.get("build", True))
        elif project_type == "git":
            if "url" not in project_config:
                return {"error": "project_config for 'git' must contain 'url'."}
            project = GitProject(url=project_config["url"], rev=project_config.get("rev"))
        elif project_type == "temp_mathlib":
            project = TempRequireProject(require="mathlib")
        elif project_type == "temp_require":  # More generic temp require
            if "require_str" not in project_config and "require_list" not in project_config:
                return {"error": "project_config for 'temp_require' must contain 'require_str' or 'require_list'."}
            require_arg = project_config.get("require_str") or project_config.get("require_list")
            if require_arg is None:
                return {
                    "error": "project_config for 'temp_require' must have a non-null 'require_str' or 'require_list'."
                }
            project = TempRequireProject(require=require_arg)
        elif project_type == "none":
            project = None
        else:
            return {"error": f"Unsupported project_type: {project_type}"}
        final_config_args["project"] = project
    elif context.repl_config and context.repl_config.project is not None:
        final_config_args["project"] = context.repl_config.project

    try:
        print(f"Attempting to create new LeanREPLConfig with args: {final_config_args}")
        new_repl_config = LeanREPLConfig(**final_config_args)
        print(
            f"New LeanREPLConfig created: Lean Version={new_repl_config.lean_version}, Project={new_repl_config.project}"
        )
    except Exception as e:  # pylint: disable=broad-except
        print(f"Error creating new LeanREPLConfig: {e}")
        return {"error": "Failed to create LeanREPLConfig", "details": str(e)}

    print("Shutting down old Lean server (if any)...")
    if context.repl_server:
        context.repl_server.kill()
        print("Old Lean server shut down.")
    else:
        print("No existing Lean server found in context.")

    try:
        print("Initializing new AutoLeanServer with new config...")
        new_lean_server = AutoLeanServer(new_repl_config)
        print("New AutoLeanServer initialized.")
    except Exception as e:  # pylint: disable=broad-except
        print(f"Error creating new AutoLeanServer: {e}")
        return {"error": "Failed to create new AutoLeanServer", "details": str(e)}

    # Update the context with the new configuration and server
    context.repl_server = new_lean_server
    context.repl_config = new_repl_config

    return {
        "status": "Lean environment configured successfully.",
        "new_config_details": {
            "lean_version": new_repl_config.lean_version,
            "repl_rev": new_repl_config.repl_rev,
            "project_type": project_type if project_type else ("existing" if new_repl_config.project else "none"),
            "project_details": str(new_repl_config.project),  # Basic string representation
            "verbose": new_repl_config.verbose,
            "memory_hard_limit_mb": new_repl_config.memory_hard_limit_mb,
        },
    }


def main() -> None:
    mcp.run()
