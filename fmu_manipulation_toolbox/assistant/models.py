"""Typed payloads exchanged with the MCP client.

Keeping these as Pydantic models (rather than free-form dictionaries) means the
tool schema advertises the accepted keys, their types and their meaning, so the
model does not have to guess them from a docstring — and a typo is rejected
with a precise message instead of silently doing nothing.

This module imports Pydantic, which ships with ``fastmcp``; it is therefore
only imported when the server is actually built.
"""

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

#: Value kinds accepted for a start value, before conversion to the FMI
#: textual representation.
StartValue = Union[bool, int, float, str]

#: Maximum number of ports returned by a single call, to keep the answer
#: readable and the context small on industrial FMUs.
DEFAULT_PORT_LIMIT = 100


class ContainerOptions(BaseModel):
    """Runtime options of the root container.

    Every field is optional: only the ones explicitly provided are updated,
    the others keep their current value.
    """

    model_config = ConfigDict(extra="forbid")

    step_size: Optional[float] = Field(
        default=None, gt=0,
        description="Internal fixed time step, in seconds (e.g. 0.001). Leave "
                    "unset to let the toolbox derive it from the embedded FMUs.",
    )
    mt: Optional[bool] = Field(
        default=None,
        description="Run the embedded FMUs in parallel threads.",
    )
    profiling: Optional[bool] = Field(
        default=None,
        description="Expose the real-time ratio of each embedded FMU during "
                    "simulation.",
    )
    sequential: Optional[bool] = Field(
        default=None,
        description="Use sequential scheduling instead of the default "
                    "Gauss-Seidel sweep. Mutually exclusive in intent with `mt`.",
    )
    auto_link: Optional[bool] = Field(
        default=None,
        description="Automatically connect ports sharing the same name and "
                    "type. Enabled by default: explicit links are only needed "
                    "for ports whose names differ.",
    )
    auto_input: Optional[bool] = Field(
        default=None,
        description="Automatically expose unconnected inputs as container "
                    "inputs. Enabled by default.",
    )
    auto_output: Optional[bool] = Field(
        default=None,
        description="Automatically expose unconnected outputs as container "
                    "outputs. Enabled by default.",
    )
    auto_parameter: Optional[bool] = Field(
        default=None,
        description="Also expose the parameters of the embedded FMUs.",
    )
    auto_local: Optional[bool] = Field(
        default=None,
        description="Also expose the local variables of the embedded FMUs.",
    )
    ts_multiplier: Optional[bool] = Field(
        default=None,
        description="Add a TS_MULTIPLIER input to scale the time step at "
                    "runtime.",
    )

    def changes(self) -> Dict[str, Any]:
        """Return only the options the client explicitly provided."""
        provided = self.model_dump(exclude_unset=True)
        return {key: value for key, value in provided.items() if value is not None}


def option_reference() -> List[Dict[str, Any]]:
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
    variability: Optional[str] = Field(
        default=None, description="'constant', 'fixed', 'tunable', 'discrete' "
                                  "or 'continuous'.")
    unit: Optional[str] = Field(default=None, description="Unit, when declared.")
    start: Optional[str] = Field(default=None, description="Start value declared by the FMU.")
    description: Optional[str] = Field(default=None, description="Free-text description.")


class FmuPorts(BaseModel):
    """A page of ports, plus what it took to get there.

    ``total`` counts the ports matching the filter, not the ports returned:
    compare it with ``returned`` to know whether a page is missing.
    """

    fmu: str
    fmi_version: Optional[int] = None
    generator: str = ""
    kinds: List[str] = Field(
        default_factory=list,
        description="FMI kinds advertised by the FMU: 'CoSimulation' and/or "
                    "'ModelExchange'.")
    terminals: List[str] = Field(default_factory=list)
    counts: Dict[str, int] = Field(
        default_factory=dict,
        description="Number of ports per causality, over the whole FMU, "
                    "regardless of the filter.")
    total: int = Field(description="Ports matching the filter.")
    returned: int = Field(description="Ports actually included in `ports`.")
    offset: int = 0
    truncated: bool = Field(
        description="True when more ports match: call again with a higher "
                    "`offset`, or narrow the filter.")
    ports: List[Port] = Field(default_factory=list)


class FmuSummary(BaseModel):
    """What an FMU brings to the assembly, returned right after adding it."""

    fmu: str = Field(description="Name to use in the other tools.")
    path: str
    fmi_version: Optional[int] = None
    generator: str = ""
    kinds: List[str] = Field(default_factory=list)
    counts: Dict[str, int] = Field(
        default_factory=dict, description="Number of ports per causality.")
    terminals: List[str] = Field(default_factory=list)


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


