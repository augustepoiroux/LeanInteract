"""
**Module:** `lean_interact.interface`

This module provides the base classes and data models for interacting with the Lean REPL (Read-Eval-Print Loop).
It defines the request and response structures used for sending commands to the Lean server and receiving results.
These are aligned with the [Lean REPL's API](https://github.com/leanprover-community/repl/blob/8cca59562eabefce8494fb4600c4bbfa1c3b335b/REPL/JSON.lean).
"""

from collections import deque
from typing import Annotated, Generator, Literal

from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import Self


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


Name = list[str]

DataValue = bool | int | str | Name

Options = list[tuple[Name, DataValue]]


class CommandOptions(REPLBaseModel):
    """Common options for `Command` and `FileCommand`."""

    all_tactics: Annotated[bool | None, Field(alias="allTactics")] = None
    """If true, return all tactics used in the command with their associated information."""

    declarations: bool | None = None
    """If true, return detailed information about declarations in the command."""

    root_goals: Annotated[bool | None, Field(alias="rootGoals")] = None
    """If true, return root goals, i.e. initial goals of all declarations in the command, even if they already have a proof."""

    infotree: str | None = None
    """Return syntax information. Should be "full", "tactics", "original", or "substantive". Anything else is ignored."""

    incrementality: bool | None = None
    """If true, enable incremental optimization for the command."""

    set_options: Annotated[Options | None, Field(alias="setOptions")] = None
    """Options to be set before executing the command (i.e. `set_option` commands in Lean)."""


class Command(BaseREPLQuery, CommandOptions):
    """Command to be executed in the REPL."""

    cmd: Annotated[str, Field(min_length=1)]
    """The command to be executed."""

    env: int | None = None
    """The environment to be used. If `env = None`, starts a new session (in which you can use `import`).
       If `env` is set, the command is executed in the given environment.
    """


class FileCommand(BaseREPLQuery, CommandOptions):
    """Command for file operations in the REPL."""

    path: Annotated[str, Field(min_length=1)]
    """The path of the file to be operated on."""

    env: int | None = None
    """The environment to be used. If `env = None`, starts a new session (in which you can use `import`).
       If `env` is set, the command is executed in the given environment.
    """


class ProofStep(BaseREPLQuery):
    """Proof step in the REPL."""

    proof_state: Annotated[int, Field(alias="proofState")]
    """The proof state to start from."""

    tactic: Annotated[str, Field(min_length=1)]
    """The tactic to be applied."""


class PickleEnvironment(BaseREPLQuery):
    """Environment for pickling in the REPL."""

    env: int
    """The environment to be pickled."""

    pickle_to: Annotated[str, Field(min_length=1, alias="pickleTo")]
    """The path to save the pickle file."""


class UnpickleEnvironment(BaseREPLQuery):
    """Environment for unpickling in the REPL."""

    unpickle_env_from: Annotated[str, Field(min_length=1, alias="unpickleEnvFrom")]
    """The path to the pickle file."""


class PickleProofState(BaseREPLQuery):
    """Proof state for pickling in the REPL."""

    proof_state: Annotated[int, Field(alias="proofState")]
    """The proof state to be pickled."""

    pickle_to: Annotated[str, Field(min_length=1, alias="pickleTo")]
    """The path to save the pickle file."""


class UnpickleProofState(BaseREPLQuery):
    """Environment for unpickling in the REPL."""

    unpickle_proof_state_from: Annotated[str, Field(min_length=1, alias="unpickleProofStateFrom")]
    """The path to the pickle file containing the proof state to be unpickled."""

    env: int | None = None
    """The environment to be used as a context for unpickling."""


# Intermediate classes


class Pos(REPLBaseModel):
    """Position in the Lean code."""

    line: int
    """The line number of the position."""

    column: int
    """The column number of the position."""

    def __le__(self, other: "Pos") -> bool:
        if self.line < other.line:
            return True
        if self.line == other.line:
            return self.column <= other.column
        return False

    def __lt__(self, other: "Pos") -> bool:
        return self <= other and not self == other


class Message(REPLBaseModel):
    """Message in the REPL."""

    start_pos: Annotated[Pos, Field(alias="pos")]
    """The starting position of the message."""

    end_pos: Annotated[Pos | None, Field(alias="endPos")] = None
    """The ending position of the message."""

    severity: Literal["error", "warning", "info", "trace"]
    """The severity of the message. Possible values: `error`, `warning`, `info`, `trace`."""

    data: str
    """The data associated with the message."""


class Sorry(REPLBaseModel):
    """Sorry message in the REPL."""

    start_pos: Annotated[Pos | None, Field(alias="pos")] = None
    """The starting position of the sorry message."""

    end_pos: Annotated[Pos | None, Field(alias="endPos")] = None
    """The ending position of the sorry message."""

    goal: str
    """The proof goal at the sorry location."""

    proof_state: Annotated[int | None, Field(alias="proofState")] = None
    """The proof state associated to the sorry."""


class Tactic(REPLBaseModel):
    """Tactic in the REPL."""

    start_pos: Annotated[Pos, Field(alias="pos")]
    """The starting position of the tactic."""

    end_pos: Annotated[Pos, Field(alias="endPos")]
    """The ending position of the tactic."""

    goals: str
    """The goals associated with the tactic."""

    tactic: str
    """The applied tactic."""

    proof_state: Annotated[int | None, Field(alias="proofState")] = None
    """The proof state associated with the tactic."""

    used_constants: Annotated[list[str], Field(default_factory=list, alias="usedConstants")]
    """The constants used in the tactic."""


def message_intersects_code(msg: Message | Sorry, start_pos: Pos | None, end_pos: Pos | None) -> bool:
    res = True
    if start_pos is not None and msg.end_pos is not None:
        res = res and msg.end_pos.line >= start_pos.line
    if end_pos is not None and msg.start_pos is not None:
        res = res and msg.start_pos.line <= end_pos.line
    return res


class Range(REPLBaseModel):
    """Range of a Syntax object."""

    synthetic: bool
    """Whether the syntax is synthetic or not."""

    start: Pos
    """The starting position of the syntax."""

    finish: Pos
    """The ending position of the syntax."""

    def __eq__(self, other):
        return self.start == other.start and self.finish == other.finish


class Syntax(REPLBaseModel):
    """Lean Syntax object."""

    pp: str | None
    """The pretty-printed string of the syntax."""

    range: Range
    """The range of the syntax."""

    kind: str
    """The kind of the syntax.."""

    arg_kinds: list[str] = Field(default_factory=list, alias="argKinds")
    """The kinds of the arguments of the syntax."""


class BaseNode(REPLBaseModel):
    """Base for the nodes of the InfoTree."""

    stx: Syntax
    """The syntax object of the node."""


class TacticNode(BaseNode):
    """A tactic node of the InfoTree."""

    name: str | None
    """The name of the tactic, if available."""

    goals_before: list[str] = Field(default_factory=list, alias="goalsBefore")
    """Goals before tactic application."""

    goals_after: list[str] = Field(default_factory=list, alias="goalsAfter")
    """Goals after tactic application."""


class CommandNode(BaseNode):
    """A command node of the InfoTree."""

    elaborator: str
    """The elaborator used to elaborate the command."""


class TermNode(BaseNode):
    """A term node of the InfoTree."""

    is_binder: bool = Field(alias="isBinder")
    """Whether the node is a binder or not."""

    expr: str
    """The expression string of the term node."""

    expected_type: str | None = Field(default=None, alias="expectedType")
    """The expected type of the term node, if available."""

    elaborator: str | None
    """The elaborator used for the term node, if available."""


Node = TacticNode | CommandNode | TermNode | None
"""A node of the InfoTree, which can be a TacticNode, CommandNode, TermNode, or None."""


class InfoTree(REPLBaseModel):
    """An InfoTree representation of the Lean code."""

    node: Node
    """The root node of the InfoTree, which can be a TacticNode, CommandNode, TermNode, or None."""

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
    """The kind of the InfoTree."""

    children: list[Self] = Field(default_factory=list)
    """Children of the InfoTree, which are also InfoTrees."""

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


class DocString(REPLBaseModel):
    content: str
    range: Range


class DeclModifiers(REPLBaseModel):
    doc_string: Annotated[DocString | None, Field(default=None, alias="docString")]
    visibility: Literal["regular", "private", "protected", "public"] = "regular"
    compute_kind: Annotated[Literal["regular", "meta", "noncomputable"], Field(default="regular", alias="computeKind")]
    rec_kind: Annotated[Literal["default", "partial", "nonrec"], Field(default="default", alias="recKind")]
    is_protected: Annotated[bool, Field(default=False, alias="isProtected")]
    is_unsafe: Annotated[bool, Field(default=False, alias="isUnsafe")]
    attributes: list[str] = Field(default_factory=list)


class DeclSignature(REPLBaseModel):
    pp: str
    constants: list[str]
    range: Range


class BinderView(REPLBaseModel):
    id: str
    type: str
    binderInfo: str


class DeclBinders(REPLBaseModel):
    pp: str
    groups: list[str]
    map: list[BinderView]
    range: Range


class DeclType(REPLBaseModel):
    pp: str
    constants: list[str]
    range: Range


class DeclValue(REPLBaseModel):
    pp: str
    constants: list[str]
    range: Range


class OpenDecl(REPLBaseModel):
    simple: dict[str, str | list[str]] | None = None
    rename: dict[str, str] | None = None


class ScopeInfo(REPLBaseModel):
    var_decls: Annotated[list[str], Field(default_factory=list, alias="varDecls")]
    include_vars: Annotated[list[str], Field(default_factory=list, alias="includeVars")]
    omit_vars: Annotated[list[str], Field(default_factory=list, alias="omitVars")]
    level_names: Annotated[list[str], Field(default_factory=list, alias="levelNames")]
    curr_namespace: Annotated[str, Field(alias="currNamespace")]
    open_decl: Annotated[list[OpenDecl], Field(default_factory=list, alias="openDecl")]


class DeclarationInfo(REPLBaseModel):
    pp: str
    range: Range
    scope: ScopeInfo
    name: str
    full_name: Annotated[str, Field(alias="fullName")]
    kind: str
    modifiers: DeclModifiers
    signature: DeclSignature
    binders: DeclBinders | None = None
    type: DeclType | None = None
    value: DeclValue | None = None


# Response


class BaseREPLResponse(REPLBaseModel):
    """Base class for all Lean responses."""

    messages: list[Message] = Field(default_factory=list)
    """List of messages in the response."""

    sorries: list[Sorry] = Field(default_factory=list)
    """List of sorries found in the submitted code."""

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
    """Response to a command in the REPL."""

    env: int
    """The new environment state after running the code in the command."""

    tactics: list[Tactic] = Field(default_factory=list)
    """List of tactics in the code. Returned only if `all_tactics` is true."""

    declarations: list[DeclarationInfo] = Field(default_factory=list)
    """List of declarations in the code. Returned only if `declarations` is true."""

    infotree: list[InfoTree] | None = None
    """The infotree of the code. Returned only if `infotree` is true."""


class ProofStepResponse(BaseREPLResponse):
    """Response to a proof step in the REPL."""

    proof_status: Annotated[str, Field(alias="proofStatus")]
    """The proof status of the whole proof. Possible values: `Completed`, `Incomplete`, `Error`.
    It may contain additional information, e.g. `Incomplete: contains sorry`."""

    proof_state: Annotated[int, Field(alias="proofState")]
    """The proof state after the proof step."""

    goals: list[str] = Field(default_factory=list)
    """List of goals after the proof step."""

    traces: list[str] = Field(default_factory=list)
    """List of traces in the proof step."""


class LeanError(REPLBaseModel):
    """Represents an error in the Lean REPL."""

    message: str = ""
    """The error message."""
