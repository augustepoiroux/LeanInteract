from collections import deque
from typing import Annotated, Generator, Literal

from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import Self

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


class Range(BaseModel):
    """Range of a Syntax object.
    Attributes:
        start: The starting position of the syntax.
        finish: The ending position of the syntax.
        synthetic: Boolean whether the syntax is synthetic or not.
    """

    synthetic: bool
    start: Pos
    finish: Pos

    def __eq__(self, other):
        return self.start == other.start and self.finish == other.finish


class Syntax(BaseModel):
    """Lean Syntax object.
    Attributes:
        pp: Pretty-printed string of the syntax.
        range: Range of the syntax.
        kind: SyntaxNodeKind for the syntax.
        arg_kinds: SyntaxNodeKinds for the children of the syntax.
    """

    pp: str | None
    range: Range
    kind: str
    arg_kinds: list[str] = Field(default_factory=list, alias="argKinds")


class BaseNode(BaseModel):
    """Base for the nodes of the InfoTree.
    Attributes:
        stx: Syntax object of the node.
    """

    stx: Syntax


class TacticNode(BaseNode):
    """A tactic node of the InfoTree.
    Attributes:
        stx: Syntax object of the node.
        name: Optional name of the tactic.
        goals_before: Goals before tactic application.
        goals_after: Goals after tactic application.
    """

    name: str | None
    goals_before: list[str] = Field(default_factory=list, alias="goalsBefore")
    goals_after: list[str] = Field(default_factory=list, alias="goalsAfter")


class CommandNode(BaseNode):
    """A command node of the InfoTree.
    Attributes:
        stx: Syntax object of the node.
        elaborator: The elaborator used to elaborate the command.
    """

    elaborator: str


class TermNode(BaseNode):
    """A term node of the InfoTree.
    Attributes:
        stx: Syntax object of the node.
        is_binder: Whether the node is a binder or not.
        expr: Expression string.
        expected_type: Expected type.
        elaborator: Optionally, the elaborator used.
    """

    is_binder: bool = Field(alias="isBinder")
    expr: str
    expected_type: str | None = Field(default=None, alias="expectedType")
    elaborator: str | None


Node = TacticNode | CommandNode | TermNode | None


class InfoTree(BaseModel):
    """An InfoTree representation of the Lean code.
    Attributes:
        node: The root node of the InfoTree.
        kind: The kind of the InfoTree.
        children: Children of the InfoTree.
    """

    node: Node
    kind: Literal[
        "TacticInfo",
        "TermInfo",
        "PartialTermInfo",
        "CommandInfo",
        "MacroExpansionInfo",
        "OptionInfo",
        "FieldInfo",
        "CompletionInfo",
        "UserWidgetInfo",
        "CustomInfo",
        "FVarAliasInfo",
        "FieldRedeclInfo",
        "ChoiceInfo",
        "DelabTermInfo",
    ]
    children: list[Self] = Field(default_factory=list)

    def dfs_walk(self) -> Generator[Self, None, None]:
        """
        Walk the InfoTree using Depth-First-Search.
        Returns:
            Yields the subsequent InfoTree.
        """
        # Had to do this iteratively, because recursively is slow and exceeds recursion depth
        stack = deque([self])

        while stack:
            first = stack.popleft()
            yield first
            stack.extendleft(first.children)

    def leaves(self) -> Generator[Self, None, None]:
        """
        Get the InfoTree leaves of the Depth-First-Search
        Returns:
            Yield the leaves of the InfoTree.
        """
        for tree in self.dfs_walk():
            if not tree.children:
                yield tree

    def commands(self) -> Generator[Self, None, None]:
        """
        Get all InfoTrees that represent commands
        Returns:
            Yields the command nodes of the InfoTree.
        """
        for tree in self.dfs_walk():
            if tree.kind != "CommandInfo":
                continue
            assert isinstance(tree.node, CommandNode)
            yield tree

    def variables(self) -> Generator[Self, None, None]:
        """
        Get children corresponding to variable expressions.
        Returns:
            Yields the variable nodes of the InfoTree.
        """
        for tree in self.commands():
            if tree.node.elaborator != "Lean.Elab.Command.elabVariable":  # type: ignore
                continue
            yield tree

    def theorems(self) -> Generator[Self, None, None]:
        """
        Get children corresponding to theorems (including lemmas).
        Returns:
             Yields the theorems of the InfoTree.
        """
        for tree in self.commands():
            if tree.node.stx.kind != "Lean.Parser.Command.declaration":  # type: ignore
                continue
            if tree.node.stx.arg_kinds[-1] != "Lean.Parser.Command.theorem":  # type: ignore
                continue
            yield tree

    def docs(self) -> Generator[Self, None, None]:
        """
        Get children corresponding to DocStrings.
        Returns:
             Yields the InfoTree nodes representing Docstrings.
        """
        for tree in self.commands():
            if tree.node.elaborator != "Lean.Elab.Command.elabModuleDoc":  # type: ignore
                continue
            yield tree

    def namespaces(self) -> Generator[Self, None, None]:
        """
        Get children corresponding to namespaces.
        Returns:
             Yields the InfoTree nodes for namespaces.
        """
        for tree in self.commands():
            if tree.node.elaborator != "Lean.Elab.Command.elabNamespace":  # type: ignore
                continue
            yield tree

    def pp_up_to(self, end_pos: Pos) -> str:
        """
        Get the pretty-printed string of the InfoTree up to a given position.
        """
        if self.node is None:
            raise ValueError("InfoTree node is None, cannot pretty-print!")
        if end_pos > self.node.stx.range.finish or end_pos < self.node.stx.range.start:
            raise ValueError("end_pos has to be in bounds!")
        if self.node.stx.pp is None:
            raise ValueError("InfoTree node has no pretty-printed string!")
        lines = self.node.stx.pp.splitlines(keepends=True)
        result = []
        for line_idx in range(end_pos.line + 1 - self.node.stx.range.start.line):
            line = lines[line_idx]
            if line_idx == end_pos.line - self.node.stx.range.start.line:
                line = line[: end_pos.column]
            result.append(line)
        return "".join(result)

    def theorem_for_sorry(self, sorry: Sorry) -> Self | None:
        """
        Get the theorem InfoTree for a given sorry, if found in this tree.
        Args:
            sorry: The sorry to search a theorem for
        Returns:
            The found InfoTree, if found, else None
        """
        found = None
        for tree in self.theorems():
            thm_range = tree.node.stx.range  # type: ignore
            # Sorry inside
            if sorry.start_pos is None or sorry.end_pos is None:
                continue
            if sorry.start_pos < thm_range.start or sorry.end_pos > thm_range.finish:
                continue
            assert found is None
            found = tree
        return found


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
    infotree: list[InfoTree] | None = None


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
