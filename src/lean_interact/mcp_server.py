# LeanInteract imports
from lean_interact.config import LeanREPLConfig, LocalProject, GitProject, TempRequireProject, BaseProject
from lean_interact.server import AutoLeanServer
from lean_interact.interface import (
    Command,
    CommandResponse,
    FileCommand,
    ProofStep,
    ProofStepResponse,
    # PickleEnvironment, # Removed
    # UnpickleEnvironment, # Removed
    # PickleProofState, # Removed
    # UnpickleProofState, # Removed
    LeanError,
    REPLBaseModel,
)
from lean_interact.utils import DEFAULT_REPL_VERSION

# MCP and standard library imports
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Optional, Any, Union, Dict

from mcp.server.fastmcp import FastMCP

GLOBAL_LEAN_CONFIG: Optional[LeanREPLConfig] = None

@dataclass
class MCPServerLifespanContext:
    lean_server: AutoLeanServer

@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[MCPServerLifespanContext]:
    global GLOBAL_LEAN_CONFIG
    current_config: LeanREPLConfig
    if GLOBAL_LEAN_CONFIG is None:
        print("Warning: GLOBAL_LEAN_CONFIG not set prior to app_lifespan. Using default LeanREPLConfig(verbose=True).")
        current_config = LeanREPLConfig(verbose=True)
    else:
        current_config = GLOBAL_LEAN_CONFIG

    print(f"Initializing Lean Server for MCP with config: Lean Version={current_config.lean_version}, Working Dir={current_config.working_dir}, Verbose={current_config.verbose}")
    lean_server_instance = AutoLeanServer(current_config)
    print("Lean Server initialized successfully.")

    try:
        yield MCPServerLifespanContext(lean_server=lean_server_instance)
    finally:
        print("Shutting down Lean Server...")
        lean_server_instance.kill()
        print("Lean Server shut down.")

class LeanMCPServer:
    # Define methods without decorators first
    async def execute_lean_command(self, cmd: str, env: Optional[int] = None, all_tactics: Optional[bool] = None, root_goals: Optional[bool] = None, infotree: Optional[str] = None) -> dict[str, Any]:
        lean_s: AutoLeanServer = self.mcp.get_context().request_context.lifespan_context.lean_server
        request = Command(cmd=cmd, env=env, all_tactics=all_tactics, root_goals=root_goals, infotree=infotree)
        try:
            response: Union[CommandResponse, LeanError] = await lean_s.async_run(request)
            return response.model_dump(exclude_none=True, by_alias=True)
        except (TimeoutError, ConnectionAbortedError) as e:
            return {"error": e.__class__.__name__, "message": str(e), "details": "Lean server communication error."}
        except Exception as e:
            print(f"Unexpected error in execute_lean_command: {type(e).__name__} - {e}")
            return {"error": type(e).__name__, "message": str(e), "details": "An unexpected error occurred while processing the command."}

    async def execute_file_command(self, path: str, all_tactics: Optional[bool] = None, root_goals: Optional[bool] = None, infotree: Optional[str] = None) -> dict[str, Any]:
        lean_s: AutoLeanServer = self.mcp.get_context().request_context.lifespan_context.lean_server
        request = FileCommand(path=path, all_tactics=all_tactics, root_goals=root_goals, infotree=infotree)
        try:
            response: Union[CommandResponse, LeanError] = await lean_s.async_run(request)
            return response.model_dump(exclude_none=True, by_alias=True)
        except (TimeoutError, ConnectionAbortedError) as e:
            return {"error": e.__class__.__name__, "message": str(e), "details": "Lean server communication error."}
        except Exception as e:
            print(f"Unexpected error in execute_file_command: {type(e).__name__} - {e}")
            return {"error": type(e).__name__, "message": str(e), "details": "An unexpected error occurred while processing the file command."}

    async def execute_proof_step(self, proof_state: int, tactic: str) -> dict[str, Any]:
        lean_s: AutoLeanServer = self.mcp.get_context().request_context.lifespan_context.lean_server
        request = ProofStep(proof_state=proof_state, tactic=tactic)
        try:
            response: Union[ProofStepResponse, LeanError] = await lean_s.async_run(request)
            return response.model_dump(exclude_none=True, by_alias=True)
        except (TimeoutError, ConnectionAbortedError) as e:
            return {"error": e.__class__.__name__, "message": str(e), "details": "Lean server communication error."}
        except Exception as e:
            print(f"Unexpected error in execute_proof_step: {type(e).__name__} - {e}")
            return {"error": type(e).__name__, "message": str(e), "details": "An unexpected error occurred while processing the proof step."}

    async def configure_lean_environment(
        self,
        lean_version: Optional[str] = None,
        repl_rev: Optional[str] = None,
        memory_hard_limit_mb: Optional[int] = None,
        verbose: Optional[bool] = None,
        project_type: Optional[str] = None,
        project_config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        global GLOBAL_LEAN_CONFIG

        current_global_config_dict = {}
        if GLOBAL_LEAN_CONFIG:
            current_global_config_dict = {
                "lean_version": GLOBAL_LEAN_CONFIG.lean_version,
                "repl_rev": GLOBAL_LEAN_CONFIG.repl_rev,
                "memory_hard_limit_mb": GLOBAL_LEAN_CONFIG.memory_hard_limit_mb,
                "verbose": GLOBAL_LEAN_CONFIG.verbose,
            }

        new_config_values = {
            "lean_version": lean_version,
            "repl_rev": repl_rev,
            "memory_hard_limit_mb": memory_hard_limit_mb,
            "verbose": verbose,
        }

        # Prepare arguments for LeanREPLConfig, using new values if provided, else old, else defaults
        final_config_args = {}
        final_config_args["lean_version"] = new_config_values["lean_version"] if new_config_values["lean_version"] is not None else current_global_config_dict.get("lean_version")
        final_config_args["repl_rev"] = new_config_values["repl_rev"] if new_config_values["repl_rev"] is not None else current_global_config_dict.get("repl_rev", DEFAULT_REPL_VERSION)
        final_config_args["memory_hard_limit_mb"] = new_config_values["memory_hard_limit_mb"] if new_config_values["memory_hard_limit_mb"] is not None else current_global_config_dict.get("memory_hard_limit_mb")
        final_config_args["verbose"] = new_config_values["verbose"] if new_config_values["verbose"] is not None else current_global_config_dict.get("verbose", True)

        # Filter out None values so LeanREPLConfig can use its own defaults for those not explicitly set
        final_config_args = {k: v for k, v in final_config_args.items() if v is not None}

        project: Optional[BaseProject] = None
        if project_type:
            if project_config is None:
                project_config = {} # Default to empty dict to simplify access

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
            elif project_type == "temp_require": # More generic temp require
                 if "require_str" not in project_config and "require_list" not in project_config:
                     return {"error": "project_config for 'temp_require' must contain 'require_str' or 'require_list'."}
                 require_arg = project_config.get("require_str") or project_config.get("require_list")
                 project = TempRequireProject(require=require_arg)
            elif project_type == "none":
                project = None
            else:
                return {"error": f"Unsupported project_type: {project_type}"}
            final_config_args["project"] = project
        elif GLOBAL_LEAN_CONFIG and GLOBAL_LEAN_CONFIG.project is not None:
             final_config_args["project"] = GLOBAL_LEAN_CONFIG.project
        # If project_type is not specified and no global project, LeanREPLConfig will default project to None

        try:
            print(f"Attempting to create new LeanREPLConfig with args: {final_config_args}")
            new_repl_config = LeanREPLConfig(**final_config_args)
            print(f"New LeanREPLConfig created: Lean Version={new_repl_config.lean_version}, Project={new_repl_config.project}")
        except Exception as e:
            print(f"Error creating new LeanREPLConfig: {e}")
            return {"error": "Failed to create LeanREPLConfig", "details": str(e)}

        context: MCPServerLifespanContext = self.mcp.get_context().request_context.lifespan_context

        print(f"Shutting down old Lean server (if any)...")
        if hasattr(context, 'lean_server') and context.lean_server:
            context.lean_server.kill()
            print("Old Lean server shut down.")
        else:
            print("No existing Lean server found in context or context.lean_server is None.")

        try:
            print(f"Initializing new AutoLeanServer with new config...")
            new_lean_server = AutoLeanServer(new_repl_config)
            print("New AutoLeanServer initialized.")
        except Exception as e:
            print(f"Error creating new AutoLeanServer: {e}")
            return {"error": "Failed to create new AutoLeanServer", "details": str(e)}

        context.lean_server = new_lean_server
        GLOBAL_LEAN_CONFIG = new_repl_config

        return {"status": "Lean environment reconfigured successfully.", "new_config_details": {
            "lean_version": new_repl_config.lean_version,
            "repl_rev": new_repl_config.repl_rev,
            "project_type": project_type if project_type else ("existing" if new_repl_config.project else "none"),
            "project_details": str(new_repl_config.project), # Basic string representation
            "verbose": new_repl_config.verbose,
            "memory_hard_limit_mb": new_repl_config.memory_hard_limit_mb,
        }}

    def __init__(self, config: Optional[LeanREPLConfig] = None):
        global GLOBAL_LEAN_CONFIG
        if config:
            GLOBAL_LEAN_CONFIG = config
            print(f"LeanMCPServer initialized with provided config: Lean Version={config.lean_version}, Verbose={config.verbose}")
        elif GLOBAL_LEAN_CONFIG is None:
            print("No LeanREPLConfig provided to LeanMCPServer and no global config pre-set. Using default LeanREPLConfig(verbose=True).")
            GLOBAL_LEAN_CONFIG = LeanREPLConfig(verbose=True)
        else:
            print(f"LeanMCPServer initialized using pre-existing GLOBAL_LEAN_CONFIG: Lean Version={GLOBAL_LEAN_CONFIG.lean_version}, Verbose={GLOBAL_LEAN_CONFIG.verbose}")

        self.mcp = FastMCP(
            "LeanInteractMCP",
            lifespan=app_lifespan,
            title="Lean Interact MCP Server",
            description="An MCP server to interact with Lean 4 using the LeanInteract library.", # Updated description
            version="0.1.0"
        )

        # Register tools with the MCP instance
        self.mcp.tool(description="Executes a Lean command and returns the result.")(self.execute_lean_command)
        self.mcp.tool(description="Executes all commands in a Lean file and returns the result.")(self.execute_file_command)
        self.mcp.tool(description="Executes a single proof step (tactic) in a given proof state.")(self.execute_proof_step)
        self.mcp.tool(description="Reconfigures the Lean environment (version, project, etc.) and restarts the Lean server.")(self.configure_lean_environment)

    def run(self, **kwargs: Any) -> None:
        if GLOBAL_LEAN_CONFIG is None:
             print("CRITICAL WARNING: GLOBAL_LEAN_CONFIG is None at run time. Defaulting for safety.")
             GLOBAL_LEAN_CONFIG = LeanREPLConfig(verbose=True)
        print(f"Attempting to run MCP server with arguments: {kwargs}")
        self.mcp.run(**kwargs)

if __name__ == '__main__':
    print("Configuring and starting Lean Interact MCP Server...")
    # Example: Use default configuration
    mcp_server = LeanMCPServer()
    # Example: Run with default settings
    mcp_server.run()
