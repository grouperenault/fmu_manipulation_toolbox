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

import logging
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from ..checker import get_checkers
from ..operations import (
    FMU, OperationKeepOnlyRegexp, OperationMergeTopLevel, OperationRemoveRegexp,
    OperationRemoveSources, OperationRenameFromCSV, OperationSaveNamesToCSV,
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


#: Most groups of messages returned by `check_fmu` per list: an industrial FMU can produce thousands of errors,
#: which would fill the context window of the model (docs/local/mcp_optimize.md, phase 1).
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
    and feeding it back to :func:`rename_ports_from_csv` is the intended
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


def rename_ports_from_csv(fmu_path: Path, csv_path: Path, output_path: Path) -> dict[str, Any]:
    """Rename (or drop) the ports of an FMU according to a CSV mapping.

    The CSV is the one produced by :func:`dump_ports_csv`: column 0 is the
    current name, column 1 the new one. **An empty new name removes the
    port** — which is the usual way to trim an interface, and also the usual
    way to lose a port by accident.

    Args:
        fmu_path: FMU to read.
        csv_path: CSV mapping file.
        output_path: Destination FMU. The source is never modified.

    Returns:
        A mapping with ``fmu``, ``output``, ``renamed`` and ``removed``.
    """
    operation = OperationRenameFromCSV(str(csv_path))
    # `OperationRenameFromCSV` reads every row, header included: the CSV
    # produced by `dump_ports_csv` starts with `name;newName`, which would
    # otherwise be counted as a rename.
    translations = {old: new for old, new in operation.translations.items()
                    if (old, new) != ("name", "newName")}
    renamed = sum(1 for old, new in translations.items() if new and new != old)
    removed = sum(1 for new in translations.values() if not new)

    with FMU(str(fmu_path)) as fmu:
        fmu.apply_operation(operation)
        fmu.repack(str(output_path))

    return {"fmu": fmu_path.name, "output": str(output_path),
            "renamed": renamed, "removed": removed}


def apply_operation(fmu_path: Path, output_path: Path, operation: str,
                    argument: str | None = None,
                    causality: list[str] | None = None) -> dict[str, Any]:
    """Apply one descriptor operation to an FMU and write the result.

    Args:
        fmu_path: FMU to read.
        output_path: Destination FMU. The source is never modified.
        operation: One of :data:`OPERATIONS`.
        argument: Required by the parameterised operations (``trim_until``,
            ``remove_regexp``, ``keep_only_regexp``), rejected by the others.
        causality: Restrict the operation to these causalities.

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

    if causality:
        unknown = set(causality) - set(CAUSALITIES)
        if unknown:
            raise ValueError(f"Unknown causality {sorted(unknown)}. "
                             f"Available: {list(CAUSALITIES)}.")

    # A malformed regular expression surfaces here, as a plain `re.error`:
    # turn it into something the caller can act upon.
    try:
        instance = factory(argument) if needs_argument else factory()
    except Exception as exc:  # noqa: BLE001 - reported to the client
        raise ValueError(f"Cannot apply '{operation}': {exc}") from None

    with FMU(str(fmu_path)) as fmu:
        fmu.apply_operation(instance, causality or None)
        fmu.repack(str(output_path))

    return {"fmu": fmu_path.name, "output": str(output_path),
            "operation": repr(instance)}



