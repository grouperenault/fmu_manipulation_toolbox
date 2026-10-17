"""Port-level lint of an assembly: its rules replayed into the container builder, without building.

`analysis.lint_assembly` only reads the assembly JSON. Whether a port exists, has the right causality, or can be
linked to another one is decided by the builder (`container/builder.py`): rather than re-implementing those checks,
each container of the assembly is replayed into an `FMUContainer` that is never built. Every rule the builder
refuses becomes an error, with the message of the builder; the `auto_*` rules are then dry-run, so that the inputs
left unfed can be told.

A sub-container only exists once built: the entries that involve one are not checked, and the `auto_*` rules do not
see its ports. Both are reported.

This module imports the container builder: it is only imported when the port-level lint runs.
"""

import logging
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..container import FMUContainer
from ..container.errors import FMUContainerError
from .analysis import AUTO_DEFAULTS, container_label, fmu_name
from .fmutools import _captured_logs, _messages

#: Report of one finding: `(rule, severity, example)`.
Report = Callable[[str, str, str], None]

#: Describes an FMU of the assembly by name, as `AssemblyBridge.list_fmu_ports` does (``path`` and ``ports``).
Describe = Callable[[str], dict[str, Any]]

#: Prefix of the message logged by the builder for a lossy conversion (`container/rules.py`, `Link.add_target`).
LOSSY_CONVERSION = "Lossy conversion"


class PortChecker:
    """Replays the containers of one assembly into the builder; the FMU descriptions are read once."""

    def __init__(self, describe: Describe):
        self._describe = describe
        self._descriptions: dict[str, dict[str, Any] | None] = {}

    def description(self, name: str) -> dict[str, Any] | None:
        """Description of the FMU `name` given by the bridge, or `None` when the bridge does not know it."""
        if name not in self._descriptions:
            try:
                self._descriptions[name] = self._describe(name)
            except (ValueError, FileNotFoundError):
                self._descriptions[name] = None
        return self._descriptions[name]

    def _port(self, fmu: str, port: str) -> dict[str, Any] | None:
        description = self.description(fmu)
        if description is None:
            return None
        return next((candidate for candidate in description.get("ports", []) if candidate["name"] == port), None)

    def is_clock(self, fmu: str, port: str) -> bool:
        """Whether `port` of `fmu` is a clock: the builder lets several feeders reach an input clock (LS-BUS)."""
        candidate = self._port(fmu, port)
        return candidate is not None and str(candidate.get("type", "")).lower() == "clock"

    def lint_node(self, node: dict[str, Any], report: Report) -> None:
        """Replay one container (not its sub-containers) and report what the builder refuses or leaves unfed."""
        where = container_label(node)
        children = {str(child.get("name")) for child in node.get("container", [])}

        container = FMUContainer(Path(where).stem or "container", Path(tempfile.gettempdir()),
                                 reset_ports=bool(node.get("reset_ports", False)))
        loaded: set[str] = set()
        files = node.get("path", {})
        for reference in node.get("fmu", []):
            name = fmu_name(reference)
            description = self.description(name)
            path = Path(description["path"]) if description and description.get("path") \
                else Path(files.get(reference, reference))
            if not path.is_absolute() or not path.is_file():
                report("not-checked", "info", f"{where}: {name}, file not found")
                continue
            try:
                container.get_fmu(str(path), name)
                loaded.add(name)
            except FMUContainerError as error:
                report("not-checked", "info", f"{where}: {name}, {error.reason}")

        skipped: dict[str, int] = {}

        def checkable(*fmus: str) -> bool:
            """Whether every FMU of an entry is loaded; the entries with a sub-container are counted apart."""
            for fmu in fmus:
                if fmu in children:
                    skipped[fmu] = skipped.get(fmu, 0) + 1
                    return False
            return all(fmu in loaded for fmu in fmus)

        # Replayed in the order of `AssemblyNode.make_fmu`. A second feeder of an input, or a second port under one
        # output name, is already reported by the structural lint: not replayed, except for clocks, which the
        # builder accepts.
        fed: set[tuple[str, str]] = set()
        outputs: set[str] = set()

        def replay(rule: str, call, *arguments) -> None:
            try:
                with _captured_logs() as records:
                    call(*arguments)
            except FMUContainerError as error:
                report(rule, "error", f"{where}: {error.reason}")
                return
            for message in _messages(records, logging.WARNING):
                if message.startswith(LOSSY_CONVERSION):
                    report("lossy-link", "warning", f"{where}: {message}")

        def first_feeder(fmu: str, port: str) -> bool:
            if (fmu, port) in fed and not self.is_clock(fmu, port):
                return False
            fed.add((fmu, port))
            return True

        for exposed, reference, port in node.get("input", []):
            fmu = fmu_name(reference)
            if checkable(fmu) and first_feeder(fmu, port):
                replay("invalid-input", container.add_input, exposed, fmu, port)
        for reference, port, exposed in node.get("output", []):
            fmu = fmu_name(reference)
            if checkable(fmu) and exposed not in outputs:
                outputs.add(exposed)
                replay("invalid-output", container.add_output, fmu, port, exposed)
        for from_reference, from_port, to_reference, to_port in node.get("link", []):
            from_fmu, to_fmu = fmu_name(from_reference), fmu_name(to_reference)
            if checkable(from_fmu, to_fmu) and first_feeder(to_fmu, to_port):
                replay("invalid-link", container.add_link, from_fmu, from_port, to_fmu, to_port)
                self._check_units(where, from_fmu, from_port, to_fmu, to_port, report)
        for reference, port in node.get("drop", []):
            fmu = fmu_name(reference)
            if checkable(fmu):
                replay("invalid-drop", container.drop_port, fmu, port)
        for reference, port, value in node.get("start", []):
            fmu = fmu_name(reference)
            if checkable(fmu):
                replay("invalid-start", container.add_start_value, fmu, port, value)

        for child, count in skipped.items():
            report("sub-container-unchecked", "info", f"{where}: {count} entries with {child}")

        auto = {option: bool(node.get(option, default)) for option, default in AUTO_DEFAULTS.items()}
        if children and (auto["auto_link"] or auto["auto_input"] or auto["auto_output"]):
            report("auto-rules-partial", "info", f"{where}: {', '.join(sorted(children))}")
        try:
            container.add_implicit_rule(**auto)
        except FMUContainerError as error:
            report("auto-rules-error", "error", f"{where}: {error.reason}")
            return

        for cport in container.get_all_cports():
            port = cport.port
            if (port.causality == "input" and cport not in container.rules and cport not in container.start_values
                    and port.start_value is None):
                report("dangling-input", "warning", f"{where}: {cport.fmu.name}/{port.name}")

    def _check_units(self, where: str, from_fmu: str, from_port: str, to_fmu: str, to_port: str,
                     report: Report) -> None:
        """Linked ports with two different declared units: the toolbox does not convert units."""
        source, target = self._port(from_fmu, from_port), self._port(to_fmu, to_port)
        from_unit = source.get("unit") if source else None
        to_unit = target.get("unit") if target else None
        if from_unit and to_unit and from_unit != to_unit:
            report("link-unit", "warning",
                   f"{where}: {from_fmu}/{from_port} ({from_unit}) -> {to_fmu}/{to_port} ({to_unit})")

