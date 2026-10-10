"""Typed payloads exchanged with the MCP client.

Keeping these as Pydantic models (rather than free-form dictionaries) means the
tool schema advertises the accepted keys, their types and their meaning, so the
model does not have to guess them from a docstring — and a typo is rejected
with a precise message instead of silently doing nothing.

This module imports Pydantic, which ships with ``fastmcp``; it is therefore
only imported when the server is actually built.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, SerializerFunctionWrapHandler, model_serializer

#: Value kinds accepted for a start value, before conversion to the FMI
#: textual representation.
StartValue = bool | int | float | str

#: Maximum number of ports returned by a single call, to keep the answer
#: readable and the context small on industrial FMUs.
DEFAULT_PORT_LIMIT = 50

#: Largest page of ports a client may ask for: about 31k characters (~9k tokens) of compact ports.
MAX_PORT_LIMIT = 200

#: Descriptions of the ports longer than this are cut (with `…`): they help to match ports by meaning, but some
#: generators write whole paragraphs (docs/local/mcp_optimize.md, decision D3).
MAX_DESCRIPTION_LENGTH = 80


class ContainerOptions(BaseModel):
    """Runtime options of the root container.

    Every field is optional: only the ones explicitly provided are updated,
    the others keep their current value.
    """

    model_config = ConfigDict(extra="forbid")

    step_size: float | None = Field(
        default=None, gt=0,
        description="Internal fixed time step, in seconds (e.g. 0.001). Leave "
                    "unset to let the toolbox derive it from the embedded FMUs.",
    )
    mt: bool | None = Field(
        default=None,
        description="Run the embedded FMUs in parallel threads.",
    )
    profiling: bool | None = Field(
        default=None,
        description="Expose the real-time ratio of each embedded FMU during "
                    "simulation.",
    )
    sequential: bool | None = Field(
        default=None,
        description="Use sequential scheduling instead of the default "
                    "Gauss-Seidel sweep. Mutually exclusive in intent with `mt`.",
    )
    auto_link: bool | None = Field(
        default=None,
        description="Automatically connect ports sharing the same name and "
                    "type. Enabled by default: explicit links are only needed "
                    "for ports whose names differ.",
    )
    auto_input: bool | None = Field(
        default=None,
        description="Automatically expose unconnected inputs as container "
                    "inputs. Enabled by default.",
    )
    auto_output: bool | None = Field(
        default=None,
        description="Automatically expose unconnected outputs as container "
                    "outputs. Enabled by default.",
    )
    auto_parameter: bool | None = Field(
        default=None,
        description="Also expose the parameters of the embedded FMUs.",
    )
    auto_local: bool | None = Field(
        default=None,
        description="Also expose the local variables of the embedded FMUs.",
    )
    ts_multiplier: bool | None = Field(
        default=None,
        description="Add a TS_MULTIPLIER input to scale the time step at "
                    "runtime.",
    )

    def changes(self) -> dict[str, Any]:
        """Return only the options the client explicitly provided."""
        provided = self.model_dump(exclude_unset=True)
        return {key: value for key, value in provided.items() if value is not None}


def option_reference() -> list[dict[str, Any]]:
    """Describe the container options from the model's own JSON schema.

    Reading the schema rather than a hand-written list guarantees that the
    `container://options` resource cannot advertise an option the tool would
    reject, nor omit one it accepts.
    """
    schema = ContainerOptions.model_json_schema()
    reference = []
    for name, field in schema.get("properties", {}).items():
        # Optional fields are rendered as `anyOf: [{type: X}, {type: null}]`.
        candidates = field.get("anyOf", [field])
        types = [candidate["type"] for candidate in candidates
                 if candidate.get("type") not in (None, "null")]
        reference.append({
            "name": name,
            "type": types[0] if types else "",
            "description": field.get("description", ""),
        })
    return reference


def format_start_value(value: StartValue) -> str:
    """Render ``value`` the way ``modelDescription.xml`` expects it.

    Booleans are the trap here: ``str(True)`` yields ``"True"``, which FMI
    does not accept.

    Examples:
        >>> format_start_value(True)
        'true'
        >>> format_start_value(0.01)
        '0.01'
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


# ---------------------------------------------------------------------------
# FMU description
# ---------------------------------------------------------------------------


class Port(BaseModel):
    """One variable of an FMU, as declared in ``modelDescription.xml``."""

    name: str = Field(description="Port name, to be used as-is in the other tools.")
    type: str = Field(description="FMI type, e.g. 'Real' (FMI 2) or 'Float64' (FMI 3).")
    causality: str = Field(
        description="'input', 'output', 'parameter', 'local', 'independent' or "
                    "'calculatedParameter'. Only 'output' ports can start a "
                    "link, only 'input' ports can end one.")
    variability: str | None = Field(
        default=None, description="'constant', 'fixed', 'tunable', 'discrete' "
                                  "or 'continuous'.")
    unit: str | None = Field(default=None, description="Unit, when declared.")
    start: str | None = Field(default=None, description="Start value declared by the FMU.")
    description: str | None = Field(
        default=None, description=f"Free-text description, cut after {MAX_DESCRIPTION_LENGTH} characters.")

    @model_serializer(mode="wrap")
    def _compact(self, handler: SerializerFunctionWrapHandler):
        """Leave out the attributes the FMU does not declare: a `null` costs tokens and says nothing.

        No return annotation on purpose: Pydantic would publish it as the output schema of `Port`, and the clients
        would lose the description of its fields.
        """
        return {key: value for key, value in handler(self).items() if value is not None}

    @classmethod
    def from_description(cls, port: dict[str, Any]) -> "Port":
        """A port of a bridge description, its description cut to `MAX_DESCRIPTION_LENGTH` characters."""
        description = port.get("description")
        if description and len(description) > MAX_DESCRIPTION_LENGTH:
            port = {**port, "description": description[:MAX_DESCRIPTION_LENGTH - 1].rstrip() + "…"}
        return cls(**port)


class FmuPorts(BaseModel):
    """A page of ports, plus what it took to get there.

    ``total`` counts the ports matching the filter, not the ports returned:
    compare it with ``returned`` to know whether a page is missing.
    """

    fmu: str
    fmi_version: int | None = None
    generator: str = ""
    kinds: list[str] = Field(
        default_factory=list,
        description="FMI kinds advertised by the FMU: 'CoSimulation' and/or "
                    "'ModelExchange'.")
    terminals: list[str] = Field(default_factory=list)
    counts: dict[str, int] = Field(
        default_factory=dict,
        description="Number of ports per causality, over the whole FMU, "
                    "regardless of the filter.")
    total: int = Field(description="Ports matching the filter.")
    returned: int = Field(description="Ports actually included in `ports`.")
    offset: int = 0
    truncated: bool = Field(
        description="True when more ports match: call again with a higher "
                    "`offset`, or narrow the filter.")
    ports: list[Port] = Field(default_factory=list)


class FmuSummary(BaseModel):
    """What an FMU brings to the assembly, returned right after adding it."""

    fmu: str = Field(description="Name to use in the other tools.")
    path: str
    fmi_version: int | None = None
    generator: str = ""
    kinds: list[str] = Field(default_factory=list)
    counts: dict[str, int] = Field(
        default_factory=dict, description="Number of ports per causality.")
    terminals: list[str] = Field(default_factory=list)


class RemovalReport(BaseModel):
    """What removing an FMU actually discarded."""

    fmu: str
    removed_links: int = Field(description="Links discarded along with the FMU.")


class Link(BaseModel):
    """One connection, for the bulk wiring tool."""

    model_config = ConfigDict(extra="forbid")

    from_fmu: str = Field(description="Source FMU, e.g. 'controller.fmu'.")
    from_port: str = Field(description="OUTPUT port of the source FMU.")
    to_fmu: str = Field(description="Destination FMU.")
    to_port: str = Field(description="INPUT port of the destination FMU.")

    def __str__(self) -> str:
        return f"{self.from_fmu}/{self.from_port} -> {self.to_fmu}/{self.to_port}"


