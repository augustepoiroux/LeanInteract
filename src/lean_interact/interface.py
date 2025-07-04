from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

# Classes and attributes are aligned with the Lean REPL: https://github.com/leanprover-community/repl/blob/2f0a3cb876b045cc0fe550ca3a625bc479816739/REPL/JSON.lean


class REPLBaseModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow", populate_by_name=True)

    def __repr__(self) -> str:
        """Return string representation showing only set attributes."""
        attrs = []
        for name in self.__pydantic_fields_set__:
            attrs.append(f"{name}={getattr(self, name)!r}")
        return f"{self.__class__.__name__}({', '.join(attrs)})"

    def __str__(self) -> str:
        """Return simplified string showing only set attributes."""
        return self.__repr__()


# Request


class BaseREPLQuery(REPLBaseModel):
    """Base class for all Lean requests."""


class CommandOptions(REPLBaseModel):
    """Options for commands.
    Attributes:
        all_tactics: If true, return all tactics used in the command with their associated information.
        root_goals: If true, return root goals, i.e. initial goals of all declarations in the command, even if they already have a proof.
        infotree: Return syntax information. Should be "full", "tactics", "original", or "substantive". Anything else is ignored.
    """

    all_tactics: Annotated[bool | None, Field(alias="allTactics")] = None
    root_goals: Annotated[bool | None, Field(alias="rootGoals")] = None
    infotree: str | None = None


class Command(BaseREPLQuery, CommandOptions):
    """Command to be executed in the REPL.
    Attributes:
        cmd: The command to be executed.
        env: The environment to be used (optional). If `env = None`, starts a new session (in which you can use `import`).
            If `env` is set, the command is executed in the given environment.
        all_tactics: If true, return all tactics used in the command with their associated information.
        root_goals: If true, return root goals, i.e. initial goals of all declarations in the command, even if they already have a proof.
        infotree: Return syntax information. Should be "full", "tactics", "original", or "substantive". Anything else is ignored.
    """

    cmd: Annotated[str, Field(min_length=1)]
    env: int | None = None


class FileCommand(BaseREPLQuery, CommandOptions):
    """Command for file operations in the REPL.
    Attributes:
        path: The path of the file to be operated on.
        env: The environment to be used (optional). If `env = None`, starts a new session (in which you can use `import`).
            If `env` is set, the command is executed in the given environment.
        all_tactics: If true, return all tactics used in the command with their associated information.
        root_goals: If true, return root goals, i.e. initial goals of all declarations in the command, even if they already have a proof.
        infotree: Return syntax information. Should be "full", "tactics", "original", or "substantive". Anything else is ignored.
    """

    path: Annotated[str, Field(min_length=1)]
    env: int | None = None


class ProofStep(BaseREPLQuery):
    """Proof step in the REPL.
    Attributes:
        proof_state: The proof state to start from.
        tactic: The tactic to be applied.
    """

    proof_state: Annotated[int, Field(alias="proofState")]
    tactic: Annotated[str, Field(min_length=1)]


class PickleEnvironment(BaseREPLQuery):
    """Environment for pickling in the REPL.
    Attributes:
        env: The environment to be used.
        pickle_to: The path to save the pickle file.
    """

    env: int
    pickle_to: Annotated[str, Field(min_length=1, alias="pickleTo")]


class UnpickleEnvironment(BaseREPLQuery):
    """Environment for unpickling in the REPL.
    Attributes:
        unpickle_env_from: The path to the pickle file.
    """

    unpickle_env_from: Annotated[str, Field(min_length=1, alias="unpickleEnvFrom")]


class PickleProofState(BaseREPLQuery):
    """Proof state for pickling in the REPL.
    Attributes:
        proof_state: The proof state to be pickled.
        pickle_to: The path to save the pickle file.
    """

    proof_state: Annotated[int, Field(alias="proofState")]
    pickle_to: Annotated[str, Field(min_length=1, alias="pickleTo")]


class UnpickleProofState(BaseREPLQuery):
    """Environment for unpickling in the REPL.
    Attributes:
        unpickle_proof_state_from: The path to the pickle file.
    """

    unpickle_proof_state_from: Annotated[str, Field(min_length=1, alias="unpickleProofStateFrom")]
    env: int | None = None


# Intermediate classes


class Pos(REPLBaseModel):
    line: int
    column: int

    def __le__(self, other: "Pos") -> bool:
        if self.line < other.line:
            return True
        if self.line == other.line:
            return self.column <= other.column
        return False

    def __lt__(self, other: "Pos") -> bool:
        return self <= other and not self == other


class Message(REPLBaseModel):
    """Message in the REPL.
    Attributes:
        start_pos: The starting position of the message.
        end_pos: The ending position of the message.
        severity: The severity of the message.
        data: The data associated with the message.
    """

    start_pos: Annotated[Pos, Field(alias="pos")]
    end_pos: Annotated[Pos | None, Field(alias="endPos")] = None
    severity: Literal["error", "warning", "info", "trace"]
    data: str


class Sorry(REPLBaseModel):
    """Sorry message in the REPL.
    Attributes:
        start_pos: The starting position of the sorry message.
        end_pos: The ending position of the sorry message.
        goal: The proof goal at the sorry location.
        proof_state: The proof state associated to the sorry.
    """

    start_pos: Annotated[Pos | None, Field(alias="pos")] = None
    end_pos: Annotated[Pos | None, Field(alias="endPos")] = None
    goal: str
    proof_state: Annotated[int | None, Field(alias="proofState")] = None


class Tactic(REPLBaseModel):
    """Tactic in the REPL.
    Attributes:
        start_pos: The starting position of the tactic.
        end_pos: The ending position of the tactic.
        goals: The goals associated with the tactic.
        tactic: The applied tactic.
        proof_state: The proof state associated with the tactic.
        used_constants: The constants used in the tactic.
    """

    start_pos: Annotated[Pos, Field(alias="pos")]
    end_pos: Annotated[Pos, Field(alias="endPos")]
    goals: str
    tactic: str
    proof_state: Annotated[int | None, Field(alias="proofState")] = None
    used_constants: Annotated[list[str], Field(default_factory=list, alias="usedConstants")]


def message_intersects_code(msg: Message | Sorry, start_pos: Pos | None, end_pos: Pos | None) -> bool:
    res = True
    if start_pos is not None and msg.end_pos is not None:
        res = res and msg.end_pos.line >= start_pos.line
    if end_pos is not None and msg.start_pos is not None:
        res = res and msg.start_pos.line <= end_pos.line
    return res


# Response


class BaseREPLResponse(REPLBaseModel):
    """Base class for all Lean responses.
    Attributes:
        messages: List of messages in the response.
        sorries: List of sorries found in the submitted code.
    """

    messages: list[Message] = Field(default_factory=list)
    sorries: list[Sorry] = Field(default_factory=list)

    def __init__(self, **data):
        if self.__class__ == BaseREPLResponse:
            raise TypeError("BaseResponse cannot be instantiated directly")
        super().__init__(**data)

    def get_errors(self) -> list[Message]:
        """Return all error messages"""
        return [msg for msg in self.messages if msg.severity == "error"]

    def get_warnings(self) -> list[Message]:
        """Return all warning messages"""
        return [msg for msg in self.messages if msg.severity == "warning"]

    def has_errors(self) -> bool:
        """Check if response contains any error messages"""
        return any(msg.severity == "error" for msg in self.messages)

    def lean_code_is_valid(
        self,
        start_pos: Pos | None = None,
        end_pos: Pos | None = None,
        allow_sorry: bool = True,
    ) -> bool:
        """Check if the submitted code is valid Lean code."""
        # check only the messages intersecting the code
        errors = [
            message
            for message in self.messages
            if message_intersects_code(message, start_pos, end_pos) and message.severity == "error"
        ]
        sorries = [message for message in self.sorries if message_intersects_code(message, start_pos, end_pos)] + [
            message
            for message in self.messages
            if message_intersects_code(message, start_pos, end_pos) and message.data == "declaration uses 'sorry'"
        ]
        return not errors and (allow_sorry or not sorries)


class CommandResponse(BaseREPLResponse):
    """Response to a command in the REPL.
    Attributes:
        env: The environment state after running the code in the command
        tactics: List of tactics in the code. Returned only if `all_tactics` is true.
        infotree: The infotree of the code. Returned only if `infotree` is true.
        messages: List of messages in the response.
        sorries: List of sorries found in the submitted code.
    """

    env: int
    tactics: list[Tactic] = Field(default_factory=list)
    infotree: list | None = None


class ProofStepResponse(BaseREPLResponse):
    """Response to a proof step in the REPL.
    Attributes:
        proof_status: The proof status of the whole proof. Possible values: `Completed`, `Incomplete`, `Error`.
        proof_state: The proof state after the proof step.
        goals: List of goals after the proof step.
        traces: List of traces in the proof step.
        messages: List of messages in the response.
        sorries: List of sorries found in the submitted code.
    """

    proof_status: Annotated[str, Field(alias="proofStatus")]
    proof_state: Annotated[int, Field(alias="proofState")]
    goals: list[str] = Field(default_factory=list)
    traces: list[str] = Field(default_factory=list)


class LeanError(REPLBaseModel):
    message: str = ""
