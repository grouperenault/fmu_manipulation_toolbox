"""FMU-level tools: summary, conformity check and descriptor manipulation.

These capabilities belong to `fmutool`, not to the container assembly: they
read or rewrite a **single** ``.fmu`` file and never touch the assembly. They
are therefore independent of the
:class:`~fmu_manipulation_toolbox.assistant.bridge.AssemblyBridge`, and behave
identically whether the server runs standalone or behind the GUI.

Two design points are worth stating, because they shape the whole module:

* the toolbox reports through the **logger**, not through return values
  (`OperationSummary` and the checkers log and return nothing), so the only
  honest way to expose them is to capture what they log;
* ``FMU.apply_operation`` rewrites the *extracted* ``modelDescription.xml``.
  The source archive is only modified if ``repack`` is called, which is why
  the read-only tools here never call it.
"""

import difflib
import logging
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from ..checker import get_checkers
from ..model_description import ModelDescription, ModelVariable, default_variability, matches_type
from ..terminals import Terminals
from ..operations import (
    FMU, OperationKeepOnlyRegexp, OperationMergeTopLevel, OperationRemoveRegexp,
    OperationRemoveSources, OperationRename, OperationRenameFromCSV, OperationSaveNamesToCSV,
    OperationStripTopLevel, OperationSummary, OperationTrimUntil,
)

logger = logging.getLogger("fmu_manipulation_toolbox")

#: Descriptor operations a client may apply, mapped to their implementation.
#: Only name-level, reversible-by-rebuild operations are exposed: anything
#: that drops binaries or sources is a one-way trip and stays in the CLI,
#: except `remove_sources` which is explicit enough in its naming.
OPERATIONS = {
    "strip_toplevel": (OperationStripTopLevel, False),
    "merge_toplevel": (OperationMergeTopLevel, False),
    "trim_until": (OperationTrimUntil, True),
    "remove_regexp": (OperationRemoveRegexp, True),
    "keep_only_regexp": (OperationKeepOnlyRegexp, True),
    "remove_sources": (OperationRemoveSources, False),
}

#: Causalities an operation can be restricted to.
CAUSALITIES = ("input", "output", "parameter", "local")

#: Types a port filter accepts: the FMI 2.0 names (which also select their FMI 3.0 family) and the FMI 3.0 ones.
TYPES = tuple(dict.fromkeys(ModelDescription.FMI2_VARIABLE_TYPES + ModelDescription.FMI3_VARIABLE_TYPES))

#: Variabilities a port filter accepts.
VARIABILITIES = ModelDescription.VARIABILITIES


def check_port_filters(causality: list[str] | None = None, types: list[str] | None = None,
                       variabilities: list[str] | None = None) -> None:
    """Refuse the unknown values of the port filters, listing the accepted ones.

    Raises:
        ValueError: If a value is not one of :data:`CAUSALITIES`, :data:`TYPES`
            or :data:`VARIABILITIES`.
    """
    for label, values, accepted in (("causality", causality, CAUSALITIES), ("type", types, TYPES),
                                    ("variability", variabilities, VARIABILITIES)):
        unknown = set(values or ()) - set(accepted)
        if unknown:
            raise ValueError(f"Unknown {label} {sorted(unknown)}. Available: {list(accepted)}.")


def select_ports(ports: list[dict[str, Any]], fmi_version: int | None, causality: list[str] | None = None,
                 types: list[str] | None = None, variabilities: list[str] | None = None) -> list[dict[str, Any]]:
    """The ports of a description (`describe_fmu`, the bridges) that every filter set accepts.

    Same rules as `FMU.apply_operation`: FMI 2.0 type names select their FMI
    3.0 family, an undeclared variability is the default of the standard.
    """
    # Any causality can be listed (`independent`, `calculatedParameter`...): only the other filters are checked.
    check_port_filters(None, types, variabilities)
    version = fmi_version or 2
    selected = []
    for port in ports:
        port_causality = port.get("causality") or "local"
        if causality and port_causality not in causality:
            continue
        if types and not matches_type(version, port.get("type"), types):
            continue
        if variabilities and (port.get("variability")
                              or default_variability(version, port_causality, port.get("type"))) not in variabilities:
            continue
        selected.append(port)
    return selected


@contextmanager
def _captured_logs(level: int = logging.DEBUG):
    """Collect what the toolbox logs while the block runs.

    The toolbox reports its findings through the logger; a tool that ignored
    it would return an empty answer while the interesting part scrolled past
    on the server's own output.
    """
    records: list[logging.LogRecord] = []

    class _Collector(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = _Collector(level)
    logger.addHandler(handler)
    # The logger may be configured above our level (or not configured at all);
    # lower it for the duration so nothing is dropped before reaching us.
    previous_level = logger.level
    if previous_level > level or previous_level == logging.NOTSET:
        logger.setLevel(level)
    try:
        yield records
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)


def _messages(records: list[logging.LogRecord], *levels: int) -> list[str]:
    """Render the selected records, tolerating a malformed logging call.

    A ``logger.error(a, b)`` where ``b`` was meant as context (not as a
    printf argument) raises at formatting time. That is a bug in the caller,
    but losing the diagnostic entirely — which is exactly what the client
    needs — would be worse than reporting it awkwardly.
    """
    messages = []
    for record in records:
        if record.levelno not in levels:
            continue
        try:
            messages.append(record.getMessage())
        except (TypeError, ValueError):
            messages.append(" ".join(str(part) for part in (record.msg, *record.args)))
    return messages


def summarize_fmu(path: Path) -> dict[str, Any]:
    """Summarise an FMU: identity, capabilities, platforms and port counts.

    Args:
        path: Path to an existing ``.fmu`` file.

    Returns:
        A mapping with ``fmu``, ``fmi_version``, ``counts`` (ports per
        causality), ``model_exchange`` (``nx``/``nz`` when applicable) and
        ``report``, the full human-readable summary.
    """
    operation = OperationSummary()
    with _captured_logs(logging.INFO) as records, FMU(str(path)) as fmu:
        fmu.apply_operation(operation)

    summary: dict[str, Any] = {
        "fmu": path.name,
        "fmi_version": operation.fmi_version,
        "counts": dict(operation.nb_port_per_causality),
        "report": "\n".join(_messages(records, logging.INFO)),
    }
    if operation.has_model_exchange:
        summary["model_exchange"] = {
            "continuous_states": operation.number_of_continuous_states,
            "event_indicators": operation.number_of_event_indicators,
        }
    return summary


#: Aliases listed by `describe_port`: an FMI 2.0 FMU may share one value reference between many variables.
MAX_ALIASES = 20


def describe_port(path: Path, port: str) -> dict[str, Any]:
    """Describe one port of an FMU with everything its descriptor declares.

    The port pages (`describe_fmu`) keep a few fields per port to stay small;
    this is the full card of a single port.

    Args:
        path: Path to an existing ``.fmu`` file.
        port: Name of the port.

    Returns:
        A mapping with ``fmu``, ``fmi_version``, ``name``, ``type``,
        ``causality`` and ``variability`` (the defaults of the standard when not
        declared), ``attributes`` (every attribute as declared, FMI 2.0
        ``<ScalarVariable>`` and type element merged, and the ``<Start>`` values
        of FMI 3.0 ``String`` and ``Binary`` variables under ``start``), and
        when they apply: ``dimensions`` (FMI 3.0 arrays), ``declared_type``
        (name, attributes and enumeration items of the type definition, and
        ``inherited``: the attributes the port takes from it), ``aliases`` (the
        first :data:`MAX_ALIASES`, with ``aliases_total`` beyond) and ``terminals``
        (terminal name, kind and member name).

    Raises:
        ValueError: If the FMU has no such port; the message suggests close names.
    """
    with FMU(str(path)) as fmu:
        md = fmu.model_description
        variables = {element.get("name"): element for element in md.variables()}
        element = variables.get(port)
        if element is None:
            close = difflib.get_close_matches(port, list(variables), n=5)
            hint = f" Close names: {close}." if close else ""
            raise ValueError(f"'{path.name}' has no port '{port}'.{hint}")
        variable = ModelVariable(element, md.fmi_version)
        terminals = Terminals(fmu.tmp_directory)

    attributes: dict[str, str] = {}
    for attrs in variable.attrs_list:
        for key, value in attrs.items():
            attributes.setdefault(key, value)

    card: dict[str, Any] = {
        "fmu": path.name,
        "fmi_version": md.fmi_version,
        "name": port,
        "type": variable.fmi_type,
        "causality": variable.causality,
        "variability": variable.variability,
        "attributes": attributes,
    }
    if variable.dimensions:
        card["dimensions"] = [{key: value} for key, value in variable.dimensions]

    declared = _declared_type(md, variable)
    if declared:
        declared["inherited"] = {key: value for key, value in declared["attributes"].items()
                                 if key not in attributes}
        card["declared_type"] = declared

    aliases = _aliases(md, variable, variables)
    if aliases:
        card["aliases"] = aliases[:MAX_ALIASES]
        if len(aliases) > MAX_ALIASES:
            card["aliases_total"] = len(aliases)

    # `Terminals` lists the sub-terminals at the top level too: one pass covers them all.
    memberships = [{"terminal": terminal.name, "kind": terminal.kind, "member": member}
                   for terminal in terminals
                   for member, name in terminal.members.items() if name == port]
    if memberships:
        card["terminals"] = memberships
    return card


def _declared_type(md: ModelDescription, variable: ModelVariable) -> dict[str, Any] | None:
    """The type definition named by `declaredType`, with its enumeration items."""
    name = variable.get("declaredType")
    definitions = md.root.find("TypeDefinitions")
    if not name or definitions is None:
        return None
    for definition in definitions:
        if definition.get("name") != name:
            continue
        # FMI-2: <SimpleType name="..."><Real unit="..."/></SimpleType>; FMI-3: <Float64Type name="..." unit="..."/>.
        typed = definition[0] if md.fmi_version == 2 and len(definition) else definition
        attributes = {key: value for key, value in definition.attrib.items() if key != "name"}
        if typed is not definition:
            attributes.update(typed.attrib)
        declared: dict[str, Any] = {"name": name, "attributes": attributes}
        items = [dict(item.attrib) for item in typed.findall("Item")]
        if items:
            declared["items"] = items
        return declared
    return {"name": name, "attributes": {}, "error": "no such type definition"}


def _aliases(md: ModelDescription, variable: ModelVariable,
             variables: dict[str, Any]) -> list[dict[str, str]]:
    """FMI-3: the `<Alias>` elements. FMI-2: the variables sharing the value reference and the type."""
    if md.fmi_version == 3:
        return [dict(alias.attrib) for alias in variable.element.findall("Alias")]
    vr = variable.element.get("valueReference")
    aliases = []
    for name, element in variables.items():
        if element is variable.element or element.get("valueReference") != vr:
            continue
        other = ModelVariable(element, md.fmi_version)
        if other.fmi_type == variable.fmi_type:
            aliases.append({"name": name, "causality": other.causality})
    return aliases


#: Most groups of messages returned by `check_fmu` per list: an industrial FMU can produce thousands of errors,
#: which would fill the context window of the model.
MAX_MESSAGE_GROUPS = 50

#: Examples kept for a group of messages of the same rule.
MAX_EXAMPLES = 3

_QUOTED = re.compile(r"'[^']*'")


def _grouped(messages: list[str]) -> tuple[list[dict[str, Any]], bool]:
    """Group the messages that differ only by their quoted parts (variable names...), in order of appearance.

    Returns at most `MAX_MESSAGE_GROUPS` groups, and whether some were left out. A group of one message is
    `{"message": m, "count": 1}`; a larger one carries the common text, with `'…'` for the quoted parts, and a
    few complete examples.
    """
    groups: dict[str, list[str]] = {}
    for message in messages:
        groups.setdefault(_QUOTED.sub("'…'", message), []).append(message)
    result = []
    for template, members in groups.items():
        if len(members) == 1:
            result.append({"message": members[0], "count": 1})
        else:
            result.append({"message": template, "count": len(members), "examples": members[:MAX_EXAMPLES]})
    return result[:MAX_MESSAGE_GROUPS], len(result) > MAX_MESSAGE_GROUPS


def check_fmu(path: Path) -> dict[str, Any]:
    """Validate an FMU against the FMI schema and the registered checkers.

    Args:
        path: Path to an existing ``.fmu`` file.

    Returns:
        A mapping with ``fmu``; ``compliant``, true only when the descriptor
        validates against the FMI schema **and** no checker reported an error;
        ``compliant_with`` (the FMI version of the schema it validates against,
        if any); ``error_count`` and ``warning_count`` (messages); ``errors``
        and ``warnings``, the messages grouped by rule (see `_grouped`), at
        most `MAX_MESSAGE_GROUPS` groups each; ``truncated`` when groups were
        left out; ``checkers`` (what was run).
    """
    checkers = [checker() for checker in get_checkers()]
    with _captured_logs(logging.WARNING) as records, FMU(str(path)) as fmu:
        for checker in checkers:
            fmu.apply_operation(checker)

    # The built-in schema checker is the only one with a documented verdict
    # attribute; the others only log.
    compliant_with = next((getattr(checker, "compliant_with_version", None)
                           for checker in checkers
                           if getattr(checker, "compliant_with_version", None)), None)

    errors = _messages(records, logging.ERROR, logging.CRITICAL)
    warnings = _messages(records, logging.WARNING)
    error_groups, errors_truncated = _grouped(errors)
    warning_groups, warnings_truncated = _grouped(warnings)
    return {
        "fmu": path.name,
        "compliant": compliant_with is not None and not errors,
        "compliant_with": compliant_with,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": error_groups,
        "warnings": warning_groups,
        "truncated": errors_truncated or warnings_truncated,
        "checkers": [repr(checker) for checker in checkers],
    }


def dump_ports_csv(fmu_path: Path, csv_path: Path) -> dict[str, Any]:
    """Write every port of an FMU to a CSV file.

    The file has one row per port, with columns ``name``, ``newName``,
    ``valueReference``, ``causality``, ``variability``, ``scalarType`` and
    ``startValue``, separated by semicolons. Editing the ``newName`` column
    and feeding it back to :func:`rename_ports` is the intended
    round-trip.

    Args:
        fmu_path: FMU to read.
        csv_path: Destination CSV file.

    Returns:
        A mapping with ``fmu``, ``csv`` and ``ports`` (how many were written).
    """
    operation = OperationSaveNamesToCSV(str(csv_path))
    with FMU(str(fmu_path)) as fmu:
        fmu.apply_operation(operation)
    # One header row, then one row per port.
    rows = csv_path.read_text(encoding="utf-8").splitlines()
    return {"fmu": fmu_path.name, "csv": str(csv_path), "ports": max(len(rows) - 1, 0)}


#: Names of a renaming mapping absent from the FMU listed in the report of `rename_ports`; the total is always given.
MAX_UNKNOWN_NAMES = 20


def rename_ports(fmu_path: Path, output_path: Path, mapping: dict[str, str] | None = None,
                 csv_path: Path | None = None) -> dict[str, Any]:
    """Rename (or drop) the ports of an FMU, from a mapping or from a CSV file.

    The CSV is the one produced by :func:`dump_ports_csv`: column 0 is the
    current name, column 1 the new one. **An empty new name removes the
    port** — which is the usual way to trim an interface, and also the usual
    way to lose a port by accident.

    Args:
        fmu_path: FMU to read.
        output_path: Destination FMU. The source is never modified.
        mapping: Current name -> new name.
        csv_path: CSV mapping file. Exactly one of `mapping` and `csv_path` is given.

    Returns:
        A mapping with ``fmu``, ``output``, ``renamed`` and ``removed`` (ports
        actually renamed or removed), and when some names of the mapping are not
        ports of the FMU: ``unknown`` (the first of them) and ``unknown_total``.

    Raises:
        ValueError: If neither or both of `mapping` and `csv_path` are given.
    """
    if (mapping is None) == (csv_path is None):
        raise ValueError("Give either `mapping` or `csv`, not both.")
    if csv_path is not None:
        operation: OperationRename = OperationRenameFromCSV(str(csv_path))
        # `OperationRenameFromCSV` reads every row, header included: the CSV
        # produced by `dump_ports_csv` starts with `name;newName`, which must not
        # be taken for a port.
        if operation.translations.get("name") == "newName":
            del operation.translations["name"]
    else:
        operation = OperationRename(mapping)

    with FMU(str(fmu_path)) as fmu:
        fmu.apply_operation(operation)
        fmu.repack(str(output_path))

    translations = operation.translations
    report: dict[str, Any] = {
        "fmu": fmu_path.name, "output": str(output_path),
        "renamed": sum(1 for old in operation.found if translations[old] and translations[old] != old),
        "removed": sum(1 for old in operation.found if not translations[old]),
    }
    unknown = [old for old in translations if old not in operation.found]
    if unknown:
        report["unknown"] = unknown[:MAX_UNKNOWN_NAMES]
        report["unknown_total"] = len(unknown)
    return report


def apply_operation(fmu_path: Path, output_path: Path, operation: str,
                    argument: str | None = None,
                    causality: list[str] | None = None,
                    types: list[str] | None = None,
                    variabilities: list[str] | None = None) -> dict[str, Any]:
    """Apply one descriptor operation to an FMU and write the result.

    Args:
        fmu_path: FMU to read.
        output_path: Destination FMU. The source is never modified.
        operation: One of :data:`OPERATIONS`.
        argument: Required by the parameterised operations (``trim_until``,
            ``remove_regexp``, ``keep_only_regexp``), rejected by the others.
        causality: Restrict the operation to these causalities.
        types: Restrict the operation to these types (see :func:`check_port_filters`).
        variabilities: Restrict the operation to these variabilities.

    Returns:
        A mapping with ``fmu``, ``output`` and ``operation`` (what was done,
        as the toolbox describes it).

    Raises:
        ValueError: If the operation is unknown, or its argument is missing,
            unexpected or invalid.
    """
    try:
        factory, needs_argument = OPERATIONS[operation]
    except KeyError:
        raise ValueError(f"Unknown operation '{operation}'. "
                         f"Available: {sorted(OPERATIONS)}.") from None

    if needs_argument and not argument:
        raise ValueError(f"Operation '{operation}' requires an `argument`.")
    if argument and not needs_argument:
        raise ValueError(f"Operation '{operation}' does not take an `argument`.")

    check_port_filters(causality, types, variabilities)

    # A malformed regular expression surfaces here, as a plain `re.error`:
    # turn it into something the caller can act upon.
    try:
        instance = factory(argument) if needs_argument else factory()
    except Exception as exc:  # noqa: BLE001 - reported to the client
        raise ValueError(f"Cannot apply '{operation}': {exc}") from None

    with FMU(str(fmu_path)) as fmu:
        fmu.apply_operation(instance, causality or None, types=types or None,
                            variabilities=variabilities or None)
        fmu.repack(str(output_path))

    return {"fmu": fmu_path.name, "output": str(output_path),
            "operation": repr(instance)}
