"""MCP (Model Context Protocol) server exposing FMU assembly capabilities.

The server is built on top of an :class:`~fmu_manipulation_toolbox.assistant.bridge.AssemblyBridge`
implementation, so the very same tools can drive either the live Container
Builder GUI or a headless assembly.

The FastMCP SDK comes with the optional ``mcp`` extra; it is therefore imported
lazily by :func:`build_server` so that importing this package keeps working
without it.
"""

import functools
import inspect
import json
import logging
import os
from typing import Any, Literal

from . import analysis
from .bridge import AssemblyBridge
from .knowledge import (
    FMI_CONVENTIONS, USAGE_GUIDE, analyze_assembly_prompt, build_container_prompt,
    container_options_reference, diagnose_assembly_prompt, inspect_fmu_prompt,
)
from .paths import PathPolicy
from .tools import Toolbox, is_actionable, ports_page

logger = logging.getLogger("fmu_manipulation_toolbox")

#: Default interface the HTTP transport binds to. Loopback only.
DEFAULT_HOST = "127.0.0.1"
#: Default TCP port for the HTTP transport.
DEFAULT_PORT = 8765
#: Environment variable overriding :data:`DEFAULT_PORT`.
PORT_ENV_VAR = "FMUCONTAINER_MCP_PORT"

#: How long a tool waits for the backend to apply one operation, in seconds.
#: Generous on purpose: the backend may be a GUI busy with a modal dialog.
DEFAULT_TIMEOUT = 60.0
#: Environment variable overriding :data:`DEFAULT_TIMEOUT`.
TIMEOUT_ENV_VAR = "FMUCONTAINER_MCP_TIMEOUT"
#: Building a container is orders of magnitude slower than editing it (it
#: unzips, rewrites and re-zips every embedded FMU), so build operations get a
#: proportionally longer budget rather than a second knob to tune.
BUILD_TIMEOUT_FACTOR = 10


class McpUnavailableError(RuntimeError):
    """Raised when the optional ``fastmcp`` dependency cannot be imported."""


def resolve_port() -> int:
    """Return the TCP port to listen on, honouring :data:`PORT_ENV_VAR`.

    Called when the server starts rather than when the module is imported, so
    a malformed value cannot break an unrelated ``import`` of the package.

    Raises:
        ValueError: If the environment variable is set to something that is
            not a valid TCP port.
    """
    raw = os.environ.get(PORT_ENV_VAR)
    if raw is None:
        return DEFAULT_PORT
    try:
        port = int(raw)
    except ValueError:
        raise ValueError(
            f"{PORT_ENV_VAR} must be a TCP port number, got '{raw}'."
        ) from None
    if not 1 <= port <= 65535:
        raise ValueError(f"{PORT_ENV_VAR} must be between 1 and 65535, got {port}.")
    return port


def resolve_timeout() -> float:
    """Return the per-operation timeout, honouring :data:`TIMEOUT_ENV_VAR`.

    A fixed 60 s budget is wrong in both directions: too short for a large
    assembly on a slow machine, too long for an interactive session where the
    user would rather be told quickly that the GUI is not answering. Hence the
    knob — resolved at startup, like the port, so a malformed value surfaces
    where it can be reported.

    Raises:
        ValueError: If the environment variable is not a positive number.
    """
    raw = os.environ.get(TIMEOUT_ENV_VAR)
    if raw is None:
        return DEFAULT_TIMEOUT
    try:
        timeout = float(raw)
    except ValueError:
        raise ValueError(
            f"{TIMEOUT_ENV_VAR} must be a number of seconds, got '{raw}'."
        ) from None
    if timeout <= 0:
        raise ValueError(f"{TIMEOUT_ENV_VAR} must be positive, got {timeout}.")
    return timeout



# ---------------------------------------------------------------------------
# Error reporting
# ---------------------------------------------------------------------------

def _schema_node(schema: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    """Follow `$ref` and pick the object branch of `anyOf` (optional fields) in a JSON schema."""
    while True:
        if "$ref" in node:
            node = schema.get("$defs", {}).get(node["$ref"].rsplit("/", 1)[-1], {})
        elif "anyOf" in node:
            node = next((branch for branch in node["anyOf"]
                         if "properties" in branch or "$ref" in branch), {})
        else:
            return node


def _allowed_keys(schema: dict[str, Any], path: list[str]) -> list[str]:
    """Keys accepted at `path` (e.g. `["options"]`) of a tool input schema."""
    node = _schema_node(schema, schema)
    for key in path:
        node = _schema_node(schema, node.get("properties", {}).get(key, {}))
    return sorted(node.get("properties", {}))


def describe_argument_errors(tool: str, errors: list[dict[str, Any]], schema: dict[str, Any]) -> str:
    """Turn Pydantic argument errors into one short, actionable message.

    FastMCP validates the arguments before the tool runs and reports the raw
    Pydantic text ("1 validation error for call[...]", error codes, a link to
    the Pydantic documentation). A model can act on what is wrong and what is
    accepted instead: the allowed keys come from the tool's own input schema,
    so they cannot drift from what the tool accepts.

    Args:
        tool: Name of the tool.
        errors: `pydantic.ValidationError.errors()`.
        schema: Input JSON schema of the tool.
    """
    problems = []
    for error in errors:
        location = [str(part) for part in error.get("loc", ())]
        kind = error.get("type", "")
        if kind in ("extra_forbidden", "unexpected_keyword_argument"):
            allowed = _allowed_keys(schema, location[:-1])
            what = "option" if location[:-1] else "argument"
            problem = f"unknown {what} '{location[-1]}'"
            if allowed:
                problem += f" (allowed: {', '.join(allowed)})"
        elif kind in ("missing", "missing_argument"):
            problem = f"missing required argument '{'.'.join(location)}'"
        else:
            given = repr(error.get("input"))
            given = given if len(given) <= 60 else given[:57] + "..."
            problem = f"'{'.'.join(location)}': {error.get('msg', 'invalid value')} (got {given})"
        problems.append(problem)
    return (f"Invalid arguments for '{tool}': {'; '.join(problems)}. "
            f"Fix the arguments and call the tool again.")


def compact_schema(schema: Any) -> Any:
    """Copy of a JSON schema where `anyOf: [X, null]` becomes `X` and `default: null` is dropped.

    The tool definitions are sent with every request, so they are kept small: an optional parameter is
    published by its type only, as omitting it is the way to leave it unset. Only the published schema changes:
    the arguments are still validated against the signatures, so a client sending `null` is accepted.
    """
    if isinstance(schema, list):
        return [compact_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    compact = {key: compact_schema(value) for key, value in schema.items()
               if not (key == "default" and value is None)}
    variants = compact.get("anyOf")
    if isinstance(variants, list) and len(variants) == 2 and {"type": "null"} in variants:
        del compact["anyOf"]
        compact.update(next(variant for variant in variants if variant != {"type": "null"}))
    return compact


def _guard(fn):
    """Turn backend exceptions into actionable MCP errors.

    Without this, a plain ``AttributeError`` from an internal bug reaches the
    client verbatim ("'NoneType' object has no attribute ..."), which tells the
    model nothing it can act upon, and the full traceback is dumped by FastMCP.
    Expected failures keep their message; unexpected ones are logged with their
    traceback on the server and reported as a short, honest summary.

    Works on both plain and ``async`` tools: the progress-reporting ones are
    coroutines, and they need the same protection.
    """
    from fastmcp.exceptions import ToolError

    def translate(exc: BaseException) -> ToolError:
        if is_actionable(exc):
            return ToolError(str(exc))
        logger.exception(f"Unexpected error in MCP tool '{fn.__name__}'")
        return ToolError(
            f"'{fn.__name__}' failed unexpectedly ({type(exc).__name__}). "
            f"This is a bug in the FMU Manipulation Toolbox, not something "
            f"you can fix by retrying; the server log has the details."
        )

    if inspect.iscoroutinefunction(fn):
        @functools.wraps(fn)
        async def async_wrapper(*args, **kwargs):
            try:
                return await fn(*args, **kwargs)
            except ToolError:
                raise
            except Exception as exc:  # noqa: BLE001 - converted for the client
                raise translate(exc) from None

        return async_wrapper

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ToolError:
            raise
        except Exception as exc:  # noqa: BLE001 - converted for the client
            raise translate(exc) from None

    return wrapper


#: Tool behaviour advertised to clients, so they can decide what needs
#: confirmation and what can be retried safely.
READ_ONLY = {"readOnlyHint": True, "idempotentHint": True}
IDEMPOTENT_WRITE = {"readOnlyHint": False, "idempotentHint": True}
WRITE = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False}
DESTRUCTIVE_WRITE = {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False}


async def _offload(fn, *args):
    """Run a blocking backend call without freezing the event loop.

    FastMCP runs *synchronous* tools in a worker thread already, but an
    ``async`` tool runs on the event loop itself: calling the bridge directly
    from one would block every other client exchange — including the progress
    notifications the tool is trying to send.
    """
    import anyio

    return await anyio.to_thread.run_sync(functools.partial(fn, *args))


def build_server(bridge: AssemblyBridge, name: str = "fmutool",
                 policy: PathPolicy | None = None):
    """Create the FastMCP server exposing ``bridge`` to an MCP client.

    Args:
        bridge: Backend applying the requested assembly operations.
        name: Server name advertised to MCP clients.
        policy: Filesystem guard-rails applied to every path the client
            provides. Defaults to :meth:`PathPolicy.from_environment`.

    Returns:
        fastmcp.FastMCP: The configured server.

    Raises:
        McpUnavailableError: If the optional ``fastmcp`` package is missing.
    """
    try:
        from fastmcp import Context, FastMCP
        from fastmcp.exceptions import ToolError, ValidationError as FastMcpValidationError
        from fastmcp.server.middleware import Middleware
        from pydantic import Field, ValidationError as PydanticValidationError
        from typing import Annotated
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise McpUnavailableError(
            "The 'fastmcp' package is required for the AI assistant "
            "(pip install 'fmu_manipulation_toolbox[mcp]')."
        ) from exc

    # Imported here (rather than at module level) because it needs Pydantic,
    # which ships with fastmcp: importing this package must stay possible
    # without the optional `mcp` extra.
    from .models import (
        DEFAULT_PORT_LIMIT, MAX_PORT_LIMIT, ContainerOptions, FmuPorts, FmuSummary, Link,
        RemovalReport, StartValue, option_reference,
    )

    if policy is None:
        policy = PathPolicy.from_environment()
    # What each tool does; the functions below only add what MCP clients need (signatures, schemas).
    toolbox = Toolbox(bridge, policy)

    mcp = FastMCP(name)

    class ArgumentErrors(Middleware):
        """Report invalid arguments with `describe_argument_errors` instead of the raw Pydantic text."""

        async def on_call_tool(self, context, call_next):
            try:
                return await call_next(context)
            except FastMcpValidationError as error:
                cause = error.__cause__
                if not isinstance(cause, PydanticValidationError):
                    raise
                tool_name = context.message.name
                tool = await mcp.get_tool(tool_name)
                schema = tool.parameters if tool is not None else {}
                raise ToolError(describe_argument_errors(tool_name, cause.errors(), schema)) from None

    class CompactSchemas(Middleware):
        """Publish the input schemas without the `null` variant of the optional parameters (see `compact_schema`)."""

        async def on_list_tools(self, context, call_next):
            tools = await call_next(context)
            return [tool.model_copy(update={"parameters": compact_schema(tool.parameters)}) for tool in tools]

    mcp.add_middleware(ArgumentErrors())
    mcp.add_middleware(CompactSchemas())

    # Repeated in the schema of many tools, sent with every request: keep these descriptions short.
    FmuName = Annotated[str, Field(
        description="FMU of the assembly, e.g. 'pid.fmu' (see `list_fmus`).")]
    PortName = Annotated[str, Field(
        description="Port name, as given by `list_fmu_ports`.")]
    # Port filters: omitted, every port.
    CausalityFilter = Annotated[list[str] | None, Field(
        description="Only these causalities, e.g. ['input'].")]
    PatternFilter = Annotated[str | None, Field(
        description="Only the names matching this regex, e.g. '^engine_'.")]
    TypeFilter = Annotated[list[str] | None, Field(
        description="Only these types, e.g. ['Real'] (on FMI 3: Float32, Float64).")]
    VariabilityFilter = Annotated[list[str] | None, Field(
        description="Only these variabilities, e.g. ['tunable'].")]
    # The single-FMU tools that write never modify their source.
    OutputFmu = Annotated[str, Field(description="Destination .fmu file (the source is kept).")]
    Overwrite = Annotated[bool, Field(description="Replace the output if it exists.")]
    ContainerName = Annotated[str | None, Field(
        description="Container name; the root if omitted.")]
    # Shared by the port listings and the sections of `get_assembly_json`.
    Offset = Annotated[int, Field(
        ge=0, description="First item to return, for paging.")]
    Limit = Annotated[int, Field(
        ge=1, le=MAX_PORT_LIMIT, description="Most items to return.")]

    @mcp.tool(annotations=READ_ONLY)
    @_guard
    def list_fmus() -> list[str]:
        """List the FMUs currently in the assembly, by file name.

        Call this first: the canvas may already contain FMUs the user added
        through the GUI. The returned names are what every other tool expects.
        """
        return toolbox.list_fmus()

    @mcp.tool(annotations=READ_ONLY)
    @_guard
    def list_fmu_ports(
        fmu: FmuName,
        causality: CausalityFilter = None,
        type: TypeFilter = None,
        variability: VariabilityFilter = None,
        name_pattern: PatternFilter = None,
        offset: Offset = 0,
        limit: Limit = DEFAULT_PORT_LIMIT,
    ) -> FmuPorts:
        """List the ports of an FMU **already in the assembly**.

        Call it before `add_link`, `expose_input`, `expose_output` or
        `set_start_value`: never guess a port name. Paginated: filter rather
        than page, and check `truncated`. For a file, use `inspect_fmu_file`.
        """
        return FmuPorts(**toolbox.list_fmu_ports(fmu, causality, type, variability, name_pattern,
                                                 offset, limit))

    @mcp.tool(annotations=READ_ONLY)
    @_guard
    def inspect_fmu_file(
        path: Annotated[str, Field(
            description="Path to an existing .fmu file.")],
        causality: CausalityFilter = None,
        type: TypeFilter = None,
        variability: VariabilityFilter = None,
        name_pattern: PatternFilter = None,
        offset: Offset = 0,
        limit: Limit = DEFAULT_PORT_LIMIT,
    ) -> FmuPorts:
        """Inspect an `.fmu` file **without** adding it to the assembly.

        Same result and filters as `list_fmu_ports`.
        """
        return FmuPorts(**toolbox.inspect_fmu_file(path, causality, type, variability, name_pattern,
                                                   offset, limit))

    @mcp.tool(annotations=WRITE)
    @_guard
    def add_fmu(
        path: Annotated[str, Field(
            description="Path to an existing .fmu file.")],
    ) -> FmuSummary:
        """Add an FMU to the assembly and summarise it.

        The returned `fmu` name is what the other tools expect; `counts` gives
        the number of ports per causality. Adding a file again adds another
        instance of it, named `<stem>-<n>.fmu`: call it once per instance.
        """
        return FmuSummary(**toolbox.add_fmu(path))

    @mcp.tool(annotations=DESTRUCTIVE_WRITE)
    @_guard
    def remove_fmu(name: FmuName) -> RemovalReport:
        """Remove an FMU from the assembly, along with its links.

        Reports how many links were discarded, so you can tell the user what
        was lost. This cannot be undone from here: confirm before calling it.
        """
        return RemovalReport(**toolbox.remove_fmu(name))

    @mcp.tool(annotations=IDEMPOTENT_WRITE)
    @_guard
    def add_link(
        from_fmu: FmuName,
        from_port: Annotated[str, Field(
            description="OUTPUT port of the source FMU, e.g. 'velocity'.")],
        to_fmu: FmuName,
        to_port: Annotated[str, Field(
            description="INPUT port of the destination FMU, e.g. 'velocity'.")],
    ) -> str:
        """Connect an OUTPUT port of one FMU to an INPUT port of another.

        Numeric conversions are applied but may lose precision: confirm a
        real-to-boolean link with the user. `auto_link` (on by default) already
        connects ports with the same name and type: this is for the others.
        """
        return toolbox.add_link(from_fmu, from_port, to_fmu, to_port)

    @mcp.tool(annotations=IDEMPOTENT_WRITE)
    @_guard
    def add_links(
        links: Annotated[list[Link], Field(
            description="Links to create, applied in order.", min_length=1)],
    ) -> dict[str, Any]:
        """Create several links in one call (see `add_link`).

        Links are applied in order and independently: a rejected link does not
        undo the others, so read `failed` before reporting the wiring as done.
        """
        return toolbox.add_links([link.model_dump() for link in links])

    @mcp.tool(annotations=DESTRUCTIVE_WRITE)
    @_guard
    def remove_link(
        from_fmu: FmuName,
        from_port: Annotated[str, Field(
            description="OUTPUT port of the source FMU.")],
        to_fmu: FmuName,
        to_port: Annotated[str, Field(
            description="INPUT port of the destination FMU.")],
    ) -> str:
        """Disconnect a link created by `add_link`.

        Only explicit links can be removed: those created by `auto_link` are
        derived at build time, so disable the option instead of trying to undo
        them one by one.
        """
        return toolbox.remove_link(from_fmu, from_port, to_fmu, to_port)

    @mcp.tool(annotations=IDEMPOTENT_WRITE)
    @_guard
    def expose_input(fmu: FmuName, port: PortName) -> str:
        """Surface an input port of an embedded FMU on the container boundary.

        Only needed when `auto_input` is disabled, or when the user asks for a
        specific container interface: unconnected inputs are exposed
        automatically otherwise.
        """
        return toolbox.expose_input(fmu, port)

    @mcp.tool(annotations=IDEMPOTENT_WRITE)
    @_guard
    def expose_output(fmu: FmuName, port: PortName) -> str:
        """Surface an output port of an embedded FMU on the container boundary.

        Only needed when `auto_output` is disabled, or when the user asks for a
        specific container interface.
        """
        return toolbox.expose_output(fmu, port)

    @mcp.tool(annotations=IDEMPOTENT_WRITE)
    @_guard
    def set_start_value(
        fmu: FmuName,
        port: PortName,
        value: Annotated[StartValue, Field(
            description="Typed value: 0.01, 3, true or 'text'.")],
    ) -> str:
        """Set the initial value of a port, or the value of a parameter.

        Use the natural type of the port as reported by `list_fmu_ports`.
        """
        return toolbox.set_start_value(fmu, port, value)

    @mcp.tool(annotations=DESTRUCTIVE_WRITE)
    @_guard
    def unset_start_value(fmu: FmuName, port: PortName) -> str:
        """Drop a start value set with `set_start_value`.

        The port falls back to the value declared by the FMU, if any; what the
        FMU declares cannot be dropped.
        """
        return toolbox.unset_start_value(fmu, port)

    @mcp.tool(annotations=IDEMPOTENT_WRITE)
    @_guard
    def set_container_options(options: ContainerOptions) -> dict[str, Any]:
        """Update the runtime options of the root container.

        Only the options you provide are changed. Prefer leaving `step_size`
        unset so the toolbox derives it from the embedded FMUs, rather than
        inventing a value. Returns every option after the update.
        """
        return toolbox.set_container_options(options.changes())

    @mcp.tool(annotations=READ_ONLY)
    @_guard
    def get_assembly_json(
        node: ContainerName = None,
        section: Annotated[Literal["input", "output", "link", "start", "drop"] | None, Field(
            description="Section to page through.")] = None,
        offset: Offset = 0,
        limit: Limit = DEFAULT_PORT_LIMIT,
    ) -> dict[str, Any]:
        """Return the assembly: FMUs, links, exposed ports and options.

        Review it with the user before building. A large assembly comes one
        container (`node`) at a time; if `truncated`, page its sections with
        `section`. For an overview: `analyze_assembly`.
        """
        return toolbox.get_assembly_json(node, section, offset, limit)

    @mcp.tool(annotations=READ_ONLY)
    @_guard
    def analyze_assembly(
        mode: Annotated[Literal["summary", "lint"], Field(
            description="summary: tree, options, grouped ports and links. "
                        "lint: known traps.")] = "summary",
        node: ContainerName = None,
    ) -> dict[str, Any]:
        """Analyse the assembly, without building it.

        Start here to describe or diagnose an assembly. The lint checks the
        ports with the container builder; quote its findings.
        """
        return toolbox.analyze_assembly(mode, node)

    @mcp.tool(annotations=DESTRUCTIVE_WRITE)
    @_guard
    def save_as_json(
        path: Annotated[str, Field(
            description="Destination file, must end with '.json'.")],
        overwrite: Annotated[bool, Field(
            description="Replace the file if it already exists. Ask the user "
                        "first.")] = False,
    ) -> str:
        """Export the assembly description as a JSON file.

        This writes the *description*, not a usable FMU; use `save_as_fmu` to
        build the container itself.
        """
        return toolbox.save_as_json(path, overwrite)

    @mcp.tool(annotations=DESTRUCTIVE_WRITE)
    @_guard
    async def save_as_fmu(
        ctx: Context,
        path: Annotated[str, Field(
            description="Destination file, must end with '.fmu'.")],
        fmi_version: Annotated[Literal[2, 3], Field(
            description="FMI version of the *container* interface: 2 for "
                        "FMI 2.0, 3 for FMI 3.0.")] = 2,
        datalog: Annotated[bool, Field(
            description="Record the inputs/outputs of every embedded FMU to a "
                        "CSV log at each step.")] = False,
        overwrite: Annotated[bool, Field(
            description="Replace the file if it already exists. Ask the user "
                        "first.")] = False,
    ) -> str:
        """Build the container into an .fmu file: the final step.

        Review the assembly (`get_assembly_json`) and confirm the path with the
        user first. Slow (reports progress): never start a second build while
        one runs.
        """
        destination = toolbox.fmu_destination(path, overwrite)
        # Progress notifications carry the status message rather than
        # `ctx.info()`: the MCP logging capability is deprecated since
        # SEP-2577, while progress is the mechanism meant for exactly this.
        await ctx.report_progress(
            0, 2, f"Building the FMI-{fmi_version} container into '{destination.name}'...")
        # The backend call is blocking (it may even wait on a GUI main thread):
        # running it in a worker thread keeps the event loop free, so progress
        # notifications and client pings are still served meanwhile.
        result = await _offload(bridge.save_as_fmu, str(destination), fmi_version, datalog)
        await ctx.report_progress(2, 2, f"Container written to '{destination}'.")
        return result

    # -- single-FMU tools (fmutool / checker) ------------------------------
    # These never touch the assembly: they read or rewrite one `.fmu` file.

    @mcp.tool(annotations=READ_ONLY)
    @_guard
    def summarize_fmu(
        path: Annotated[str, Field(description="Path to an existing .fmu file.")],
    ) -> dict[str, Any]:
        """Summarise an FMU: identity, capabilities, platforms, port counts.

        Use it to answer "what is this FMU?" without adding it anywhere. For
        the port list itself, prefer `inspect_fmu_file`, which is filterable
        and paginated.
        """
        return toolbox.summarize_fmu(path)

    @mcp.tool(annotations=READ_ONLY)
    @_guard
    def check_fmu(
        path: Annotated[str, Field(description="Path to an existing .fmu file.")],
    ) -> dict[str, Any]:
        """Validate an FMU against the FMI schema and the registered checkers.

        `compliant` is true only if the schema validates and no checker reported
        an error. Messages of one rule are grouped (`count`, `examples`). Quote
        them; if `truncated`, say the list is incomplete (full report:
        `fmutool -input <fmu> -check`).
        """
        return toolbox.check_fmu(path)

    @mcp.tool(annotations=READ_ONLY)
    @_guard
    def describe_port(
        fmu: Annotated[str, Field(
            description="Name of an FMU of the assembly, or path to a .fmu file.")],
        port: PortName,
    ) -> dict[str, Any]:
        """Everything the FMU declares about one port.

        Attributes (min, max, nominal, start...), dimensions, declared type,
        aliases, terminals. The port pages only keep a summary of each port.
        """
        return toolbox.describe_port(fmu, port)

    @mcp.tool(annotations=DESTRUCTIVE_WRITE)
    @_guard
    def dump_ports_csv(
        fmu: Annotated[str, Field(description="Path to an existing .fmu file.")],
        path: Annotated[str, Field(
            description="Destination file, must end with '.csv'.")],
        overwrite: Annotated[bool, Field(
            description="Replace the file if it already exists.")] = False,
    ) -> dict[str, Any]:
        """Export every port of an FMU to a CSV file, for bulk renaming.

        The `newName` column is the one to edit before feeding the file back
        to `rename_ports`.
        """
        return toolbox.dump_ports_csv(fmu, path, overwrite)

    @mcp.tool(annotations=DESTRUCTIVE_WRITE)
    @_guard
    def rename_ports(
        fmu: Annotated[str, Field(description="Path to the .fmu file to read.")],
        output: OutputFmu,
        mapping: Annotated[dict[str, str] | None, Field(
            description="Current name -> new name, e.g. {'u': 'speed'}.")] = None,
        csv: Annotated[str | None, Field(
            description="Or a CSV mapping, as produced by `dump_ports_csv`.")] = None,
        overwrite: Overwrite = False,
    ) -> dict[str, Any]:
        """Rename — or drop — ports of an FMU, from `mapping` or `csv`.

        An **empty** new name **removes** the port: report `removed`, and
        `unknown` names. Renaming breaks what is connected to the old names.
        """
        return toolbox.rename_ports(fmu, output, mapping, csv, overwrite)

    @mcp.tool(annotations=DESTRUCTIVE_WRITE)
    @_guard
    def apply_operation(
        fmu: Annotated[str, Field(description="Path to the .fmu file to read.")],
        output: OutputFmu,
        operation: Annotated[Literal["strip_toplevel", "merge_toplevel", "trim_until",
                                     "remove_regexp", "keep_only_regexp",
                                     "remove_sources"], Field(
            description="strip_toplevel: 'Bus.sig' -> 'sig'; merge_toplevel: -> "
                        "'Bus_sig'; trim_until: cut up to `argument`; remove_regexp, "
                        "keep_only_regexp: by name; remove_sources: drop the sources.")],
        argument: Annotated[str | None, Field(
            description="The separator or regular expression, for the "
                        "operations that need one.")] = None,
        causality: CausalityFilter = None,
        type: TypeFilter = None,
        variability: VariabilityFilter = None,
        overwrite: Overwrite = False,
    ) -> dict[str, Any]:
        """Rewrite the port names of an FMU with one descriptor operation.

        This changes the FMU **interface**: confirm with the user. The output is
        a separate FMU, never the source.
        """
        return toolbox.apply_operation(fmu, output, operation, argument, causality, type, variability,
                                       overwrite)

    @mcp.resource("guide://usage")
    def usage_guide() -> str:
        """How to drive the Container Builder to assemble FMUs."""
        return USAGE_GUIDE

    @mcp.resource("fmi://conventions")
    def fmi_conventions() -> str:
        """What causality, variability, types and units imply when wiring FMUs."""
        return FMI_CONVENTIONS

    @mcp.resource("container://options")
    def container_options() -> str:
        """Every container option, its type, its meaning and its default."""
        return container_options_reference(option_reference())

    @mcp.resource("assembly://current")
    @_guard
    def current_assembly() -> str:
        """The current assembly description (JSON), bounded like `get_assembly_json`."""
        return json.dumps(analysis.assembly_page(bridge.get_assembly_json()))

    @mcp.resource("fmu://{name}/ports")
    @_guard
    def fmu_ports_resource(name: str) -> str:
        """The ports of one FMU of the assembly, as JSON."""
        return FmuPorts(**ports_page(bridge.list_fmu_ports(name))).model_dump_json()

    # -- prompts -----------------------------------------------------------
    # The procedures live here rather than in a repository file: they must
    # reach whichever client connects, not only the ones reading this repo.

    @mcp.prompt
    def build_container(
        fmus: Annotated[str, Field(
            description="Optional list of the FMU files to combine.")] = "",
        output: Annotated[str, Field(
            description="Optional path of the container to produce.")] = "",
    ) -> str:
        """Assemble several FMUs into a valid FMU Container, step by step."""
        return build_container_prompt(fmus or None, output or None)

    @mcp.prompt
    def diagnose_assembly(
        symptom: Annotated[str, Field(
            description="Optional description of what goes wrong.")] = "",
    ) -> str:
        """Investigate a container that fails to build or misbehaves."""
        return diagnose_assembly_prompt(symptom or None)

    # Same name as the tool it relies on: prompts and tools are separate namespaces in MCP.
    @mcp.prompt(name="analyze_assembly")
    def analyze_assembly_procedure(
        focus: Annotated[str, Field(
            description="Optional aspect to focus on, e.g. 'thermal loop'.")] = "",
    ) -> str:
        """Describe the content and the behaviour of the loaded assembly."""
        return analyze_assembly_prompt(focus or None)

    @mcp.prompt
    def inspect_fmu(
        fmu: Annotated[str, Field(
            description="Optional FMU name on the canvas, or path to a file.")] = "",
    ) -> str:
        """Produce a readable identity card for an FMU."""
        return inspect_fmu_prompt(fmu or None)

    return mcp

