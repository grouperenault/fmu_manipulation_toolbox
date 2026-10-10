"""Analysis of an assembly: summary, paged views and lint of its containers (docs/local/assembly_analysis.md).

The assembly JSON (the format of `Assembly.json_encode`, produced by both bridges) grows with the number of ports:
a real assembly of 3 nested containers is over 100k characters, far more than a tool result can carry. The
functions here only read that JSON and reduce it to what describes the assembly: the container tree, the options
of every level, and the ports and links grouped by FMU and by name prefix, each group with a count and a few
examples. Two bounds keep the summary small: per container, the number of groups (`MAX_GROUPS`, the ports that share
their prefix with no other being merged); for the whole tree, its size (`MAX_SUMMARY_SIZE`), beyond which the
sub-containers are reduced to their name, options, FMUs and counts.

The same JSON is also served as is, but paged (`assembly_page`): one container at a time, and one section of it
(exposed inputs, links...) at a time when the container alone is too large.

Finally, `lint_assembly` reports the known traps of the structure (options, steps, wiring), grouped per rule like the
report of `check_fmu`; given the descriptions of the FMUs, it also replays the assembly into the container builder
(`replay`, imported only then) to check the ports.

Pure functions on plain data: this module depends on the standard library only, like the bridge protocol.
"""

import json
from collections.abc import Callable
from fractions import Fraction
from pathlib import PureWindowsPath
from typing import Any

#: Most groups returned per list (exposed inputs, exposed outputs, links) of a container; the largest groups first.
#: Real port names form many small groups: 15 keeps a 3-level assembly of ~600 ports around 10k characters.
MAX_GROUPS = 15

#: Size (characters of JSON) of a result: beyond it, the sub-containers of a summary are reduced and the sections of
#: a container are left to paging. The result budget of a tool (docs/local/done/mcp_optimize.md, decision D6).
MAX_RESULT_SIZE = 12_000

#: Sections of a container in the assembly JSON, and the position of the FMU references in their entries.
SECTIONS = {"input": (1,), "output": (0,), "link": (0, 2), "start": (0,), "drop": (0,)}

#: Examples kept for a group of ports or of links.
MAX_EXAMPLES = 3

#: Options of a container, in the order of `Assembly.json_encode`.
OPTIONS = ("step_size", "mt", "profiling", "sequential", "auto_link", "auto_input", "auto_output",
           "auto_parameter", "auto_local", "ts_multiplier")


def fmu_name(reference: str) -> str:
    """Base name of an FMU of the JSON: the root level designates the FMUs by path, the other levels by name."""
    return PureWindowsPath(reference).name  # Understands both separators.


def container_label(node: dict[str, Any]) -> str:
    """Name of a container in a message: a hand-written description may leave the root unnamed."""
    return str(node.get("name") or "(root)")


def port_prefix(name: str) -> str:
    """Prefix shared by the ports of a bus (decision D7).

    The first segment before `.` (`Sc_2_DV.Rho` → `Sc_2_DV`); for a name without `.`, the part before the first
    `_`, separator included (`SNR_T_amb` → `SNR_`); an empty prefix for a name with neither.
    """
    if "." in name:
        return name.split(".", 1)[0]
    if "_" in name:
        return name.split("_", 1)[0] + "_"
    return ""


def _grouped(entries: list[tuple[tuple, str]]) -> dict[str, Any]:
    """Group `(key, example)` pairs by key.

    The groups of two elements or more are listed, at most `MAX_GROUPS`, the largest first (ties in order of
    appearance); the elements alone in their group are merged into ``ungrouped``, with their count and a few
    examples.
    """
    groups: dict[tuple, list[str]] = {}
    for key, example in entries:
        groups.setdefault(key, []).append(example)
    shared = sorted(((key, examples) for key, examples in groups.items() if len(examples) > 1),
                    key=lambda item: -len(item[1]))  # Stable: ties keep their order.
    alone = [examples[0] for examples in groups.values() if len(examples) == 1]
    result = {
        "total": len(shared),
        "truncated": len(shared) > MAX_GROUPS,
        "groups": [(key, len(examples), examples[:MAX_EXAMPLES]) for key, examples in shared[:MAX_GROUPS]],
    }
    if alone:
        result["ungrouped"] = {"count": len(alone), "examples": alone[:MAX_EXAMPLES]}
    return result


def _port_groups(ports: list[tuple[str, str]]) -> dict[str, Any]:
    """Exposed ports, given as `(fmu, exposed name)`, grouped by FMU and prefix of the exposed name."""
    grouped = _grouped([((fmu, port_prefix(name)), name) for fmu, name in ports])
    grouped["groups"] = [{"fmu": fmu, "prefix": prefix, "count": count, "examples": examples}
                         for (fmu, prefix), count, examples in grouped["groups"]]
    return grouped


def _link_groups(links: list[list[str]]) -> dict[str, Any]:
    """Links grouped by source FMU, source prefix, destination FMU and destination prefix."""
    entries = []
    for from_fmu, from_port, to_fmu, to_port in links:
        key = (fmu_name(from_fmu), port_prefix(from_port), fmu_name(to_fmu), port_prefix(to_port))
        entries.append((key, from_port if from_port == to_port else f"{from_port} -> {to_port}"))
    grouped = _grouped(entries)
    grouped["groups"] = [{"from": from_fmu, "from_prefix": from_prefix, "to": to_fmu, "to_prefix": to_prefix,
                          "count": count, "examples": examples}
                         for (from_fmu, from_prefix, to_fmu, to_prefix), count, examples in grouped["groups"]]
    return grouped


def _summarize_node(node: dict[str, Any], detailed: bool) -> dict[str, Any]:
    inputs = node.get("input", [])
    outputs = node.get("output", [])
    links = node.get("link", [])
    summary = {
        "name": node.get("name"),
        "options": {option: node[option] for option in OPTIONS if option in node},
        "fmus": [fmu_name(fmu) for fmu in node.get("fmu", [])],
        "counts": {
            "inputs": len(inputs),
            "outputs": len(outputs),
            "links": len(links),
            "start_values": len(node.get("start", [])),
            "dropped": len(node.get("drop", [])),
        },
    }
    if detailed:
        summary["inputs"] = _port_groups([(fmu_name(fmu), exposed) for exposed, fmu, _ in inputs])
        summary["outputs"] = _port_groups([(fmu_name(fmu), exposed) for fmu, _, exposed in outputs])
        summary["links"] = _link_groups(links)
    else:
        summary["reduced"] = True
    summary["containers"] = [_summarize_node(child, detailed) for child in node.get("container", [])]
    return summary


def summarize_assembly(assembly: dict[str, Any]) -> dict[str, Any]:
    """Summarise an assembly, container by container, recursively.

    Args:
        assembly: The assembly, in the format of `Assembly.json_encode`.

    Returns:
        For the root container, and for every sub-container in ``containers``: ``name``, ``options`` (those given
        by the JSON: an option absent from a hand-written file takes the default of the builder), ``fmus`` (base
        names), ``counts`` (exposed inputs and outputs, links, start values, dropped ports), and ``inputs``,
        ``outputs`` and ``links`` grouped by FMU and port prefix: ``total`` groups of two elements or more,
        ``truncated`` when only the `MAX_GROUPS` largest are listed, the ``groups`` themselves (``count``,
        ``examples``) and ``ungrouped`` for the elements that share their prefix with no other.

        When the whole tree exceeds `MAX_RESULT_SIZE`, only the root is detailed: the sub-containers keep their
        name, options, FMUs and counts, and are marked ``reduced``. An empty assembly gives an empty mapping.
    """
    if not assembly:
        return {}
    summary = _summarize_node(assembly, detailed=True)
    if len(json.dumps(summary)) > MAX_RESULT_SIZE:
        summary["containers"] = [_summarize_node(child, detailed=False) for child in assembly.get("container", [])]
    return summary


# ---------------------------------------------------------------------------
# Paged views of the assembly JSON
# ---------------------------------------------------------------------------

def _named(node: dict[str, Any]) -> dict[str, Any]:
    """Copy of a container, recursively, with its FMUs designated by base name, as the other tools do."""
    named = {}
    for key, value in node.items():
        if key == "fmu":
            named[key] = [fmu_name(fmu) for fmu in value]
        elif key in SECTIONS:
            named[key] = [[fmu_name(item) if i in SECTIONS[key] else item for i, item in enumerate(entry)]
                          for entry in value]
        elif key == "container":
            named[key] = [_named(child) for child in value]
        else:
            named[key] = value
    return named


def _containers(node: dict[str, Any], path: str = ""):
    """Every container of the tree, with the path of names that leads to it."""
    path = f"{path}/{container_label(node)}" if path else container_label(node)
    yield path, node
    for child in node.get("container", []):
        yield from _containers(child, path)


def find_container(assembly: dict[str, Any], name: str) -> dict[str, Any]:
    """The container of the tree named `name` (decision D5).

    Raises:
        ValueError: When no container, or more than one, bears that name; the message lists the candidates.
    """
    containers = list(_containers(assembly))
    matches = [node for path, node in containers if node.get("name") == name]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        known = ", ".join(container_label(node) for _, node in containers)
        raise ValueError(f"No container is named '{name}' (containers: {known}).")
    paths = ", ".join(path for path, node in containers if node.get("name") == name)
    raise ValueError(f"Several containers are named '{name}' ({paths}): rename one of them to designate it.")


def _counts(node: dict[str, Any]) -> dict[str, int]:
    return {section: len(node.get(section, [])) for section in SECTIONS}


def assembly_page(assembly: dict[str, Any], node: str | None = None, section: str | None = None,
                  offset: int = 0, limit: int = 50) -> dict[str, Any]:
    """A bounded view of the assembly JSON, FMUs designated by name (decisions D2, D5, D6).

    Args:
        assembly: The assembly, in the format of `Assembly.json_encode`.
        node: Name of the container to show; the root when omitted.
        section: One of `SECTIONS`, to page through the entries of that section of the container.
        offset: Index of the first entry of the section to return.
        limit: Most entries of the section to return.

    Returns:
        Without `node` nor `section`, the whole assembly when it fits `MAX_RESULT_SIZE`. Otherwise one container:
        its options and FMUs, ``counts`` of its sections, its sub-containers reduced to their ``name`` and
        ``counts``, and its sections when they fit, else ``truncated`` (ask for them with `section`). With
        `section`: ``node``, ``section``, ``total``, ``offset``, ``returned``, ``truncated`` and the ``entries``.
        An empty assembly gives an empty mapping.

    Raises:
        ValueError: For an unknown section, or a container `find_container` cannot designate.
    """
    if not assembly:
        return {}
    if section is not None and section not in SECTIONS:
        raise ValueError(f"Unknown section '{section}' (sections: {', '.join(SECTIONS)}).")
    container = assembly if node is None else find_container(assembly, node)

    if section is not None:
        entries = _named({section: container.get(section, [])})[section]
        page = entries[offset:offset + limit]
        return {"node": container.get("name"), "section": section, "total": len(entries), "offset": offset,
                "returned": len(page), "truncated": offset + len(page) < len(entries), "entries": page}

    if node is None:
        whole = _named(assembly)
        if len(json.dumps(whole)) <= MAX_RESULT_SIZE:
            return whole

    level = _named({key: value for key, value in container.items() if key != "container"})
    level["counts"] = _counts(container)
    if "container" in container:
        level["container"] = [{"name": child.get("name"), "counts": _counts(child)}
                              for child in container["container"]]
    level["truncated"] = len(json.dumps(level)) > MAX_RESULT_SIZE
    if level["truncated"]:
        for key in SECTIONS:
            level.pop(key, None)
    return level


# ---------------------------------------------------------------------------
# Structural lint
# ---------------------------------------------------------------------------

#: Most groups of findings returned by `lint_assembly`, as `check_fmu` (docs/local/done/mcp_optimize.md, D1).
MAX_FINDING_GROUPS = 50

#: Ratio between the step of a container and the step of a sub-container above which it is reported as a warning.
STEP_RATIO_THRESHOLD = 10

#: Value of an `auto_*` option absent from the JSON: the default of `Assembly` when it reads the file.
AUTO_DEFAULTS = {"auto_link": True, "auto_input": True, "auto_output": True, "auto_parameter": False,
                 "auto_local": False}

SEVERITIES = ("error", "warning", "info")

#: Rules of the lint: what each one means, as given to the model with its findings. The structural rules read the
#: JSON only; the port-level ones (`replay.PortChecker`) replay it into the container builder.
RULES = {
    "input-fed-twice": "An input of an embedded FMU is fed more than once (links and/or exposed inputs): the "
                       "container build refuses it.",
    "duplicate-output": "Several ports are exposed under the same container output name: the container build "
                        "refuses it.",
    "invalid-input": "The container build refuses this exposed input (message of the builder).",
    "invalid-output": "The container build refuses this exposed output (message of the builder).",
    "invalid-link": "The container build refuses this link: unknown port, causality, type... (message of the "
                    "builder).",
    "invalid-drop": "The container build refuses this dropped port (message of the builder).",
    "invalid-start": "The container build refuses this start value (message of the builder).",
    "auto-rules-error": "An `auto_*` rule fails at build time (message of the builder).",
    "nested-mt": "Multi-threading (`mt`) is enabled on a container and on one of its ancestors.",
    "mt-sequential": "Both `mt` and `sequential` are enabled on a container.",
    "step-ratio": "The step of a sub-container differs from the step of its container: a warning when their ratio "
                  f"is above {STEP_RATIO_THRESHOLD} or is not an integer.",
    "auto-off-nothing-exposed": "An `auto_*` rule is off and the root container exposes no port of that kind: the "
                                "container will have no input, or no output.",
    "lossy-link": "A link converts its value with a possible loss of information (message of the builder).",
    "link-unit": "Linked ports declare different units: the toolbox does not convert units.",
    "dangling-input": "An input is neither linked nor exposed, even by the `auto_*` rules, and has no start value.",
    "fan-out": "One output, or one container input, feeds several inputs.",
    "source-fmu": "Nothing feeds this FMU (no exposed input, no incoming link): it is a source of the assembly, e.g. "
                  "a scenario or a stub of constants.",
    "auto-rules-partial": "This container holds sub-containers and an `auto_*` rule is on: the dry run of the rules "
                          "does not see the ports of the sub-containers, which only exist once built.",
    "sub-container-unchecked": "Entries involving a sub-container are not checked against its ports, which only "
                               "exist once built.",
    "not-checked": "The ports of this FMU could not be checked.",
}


def _auto(node: dict[str, Any], option: str) -> bool:
    return bool(node.get(option, AUTO_DEFAULTS[option]))


def _ancestry(node: dict[str, Any], ancestors: tuple = ()):
    """Every container of the tree, with its ancestors (root first)."""
    yield node, ancestors
    for child in node.get("container", []):
        yield from _ancestry(child, ancestors + (node,))


def _lint_node(node: dict[str, Any], ancestors: tuple, report, is_clock) -> None:
    """Structural findings of one container: `report(rule, severity, example)` for each.

    `is_clock(fmu, port)` tells the input clocks, which several feeders may reach (LS-BUS).
    """
    where = container_label(node)

    if node.get("mt"):
        mt_ancestors = [ancestor for ancestor in ancestors if ancestor.get("mt")]
        if mt_ancestors:
            report("nested-mt", "warning", f"{where} inside {container_label(mt_ancestors[-1])}")
        if node.get("sequential"):
            report("mt-sequential", "warning", where)

    if ancestors and node.get("step_size") and ancestors[-1].get("step_size"):
        parent = ancestors[-1]
        ratio = Fraction(str(parent["step_size"])) / Fraction(str(node["step_size"]))
        if ratio != 1:
            text = (f"{where} ({node['step_size']} s) in {container_label(parent)} ({parent['step_size']} s): "
                    f"ratio {float(ratio):g}")
            integer = ratio.denominator == 1
            report("step-ratio", "info" if integer and ratio <= STEP_RATIO_THRESHOLD else "warning",
                   text if integer else f"{text}, not an integer")

    # What feeds each input of the embedded FMUs, and what each output or container input feeds.
    feeders: dict[tuple[str, str], list[str]] = {}
    fed_by_output: dict[tuple[str, str], list[str]] = {}
    fed_by_input: dict[str, list[str]] = {}
    for exposed, fmu, port in node.get("input", []):
        target = (fmu_name(fmu), port)
        feeders.setdefault(target, []).append(f"container input '{exposed}'")
        fed_by_input.setdefault(exposed, []).append(f"{target[0]}/{port}")
    for from_fmu, from_port, to_fmu, to_port in node.get("link", []):
        source = (fmu_name(from_fmu), from_port)
        feeders.setdefault((fmu_name(to_fmu), to_port), []).append(f"link from {source[0]}/{from_port}")
        fed_by_output.setdefault(source, []).append(f"{fmu_name(to_fmu)}/{to_port}")

    for (fmu, port), sources in feeders.items():
        if len(sources) > 1 and not is_clock(fmu, port):
            report("input-fed-twice", "error", f"{where}: {fmu}/{port} fed by {', '.join(sources)}")

    exposed_outputs: dict[str, list[str]] = {}
    for fmu, port, exposed in node.get("output", []):
        exposed_outputs.setdefault(exposed, []).append(f"{fmu_name(fmu)}/{port}")
    for exposed, ports in exposed_outputs.items():
        if len(ports) > 1:
            report("duplicate-output", "error", f"{where}: output '{exposed}' exposes {', '.join(ports)}")

    for (fmu, port), targets in fed_by_output.items():
        if len(targets) > 1:
            report("fan-out", "info", f"{where}: {fmu}/{port} -> {', '.join(targets)}")
    for exposed, targets in fed_by_input.items():
        if len(targets) > 1:
            report("fan-out", "info", f"{where}: container input '{exposed}' -> {', '.join(targets)}")

    # Derived links and exposures are not in the JSON: a source can only be told when no rule may feed the FMU.
    if not _auto(node, "auto_link") and not _auto(node, "auto_input"):
        fed = {fmu for fmu, _ in feeders}
        for fmu in [fmu_name(fmu) for fmu in node.get("fmu", [])] + [str(child.get("name"))
                                                                     for child in node.get("container", [])]:
            if fmu not in fed:
                report("source-fmu", "info", f"{where}: {fmu}")

    if not ancestors:
        for option, section, kind in (("auto_input", "input", "input"), ("auto_output", "output", "output")):
            if not _auto(node, option) and not node.get(section):
                report("auto-off-nothing-exposed", "warning", f"{where}: {option} off, no {kind} exposed")


def lint_assembly(assembly: dict[str, Any], node: str | None = None,
                  describe: Callable[[str], dict[str, Any]] | None = None) -> dict[str, Any]:
    """Report the known traps of an assembly (decisions D8, D14, D15).

    Args:
        assembly: The assembly, in the format of `Assembly.json_encode`.
        node: Name of the only container to lint (`find_container`); the whole tree when omitted.
        describe: Description of an FMU by name, as `AssemblyBridge.list_fmu_ports` gives it. With it, the rules of
            every container are also replayed into the container builder (`replay.PortChecker`); without it, only
            the structural rules, read from the JSON, are checked.

    Returns:
        ``error_count``, ``warning_count`` and ``info_count`` (findings, not groups); ``findings``: one group per
        rule and severity, errors first, with ``rule``, ``severity``, ``message`` (what the rule means), ``count``
        and at most `MAX_EXAMPLES` ``examples``, each naming its container; ``truncated`` when groups beyond
        `MAX_FINDING_GROUPS` were left out. An empty assembly has no finding.

    Raises:
        ValueError: For a container `find_container` cannot designate.
    """
    groups: dict[tuple[str, str], list[str]] = {}

    def report(rule: str, severity: str, example: str) -> None:
        groups.setdefault((rule, severity), []).append(example)

    if assembly:
        selected = None if node is None else find_container(assembly, node)
        checker = None
        if describe is not None:
            from .replay import PortChecker  # The container builder: only loaded when the ports are checked.
            checker = PortChecker(describe)
        for container, ancestors in _ancestry(assembly):
            if selected is not None and container is not selected:
                continue
            _lint_node(container, ancestors, report, checker.is_clock if checker else lambda fmu, port: False)
            if checker is not None:
                checker.lint_node(container, report)

    rule_order = list(RULES)
    ordered = sorted(groups.items(), key=lambda item: (SEVERITIES.index(item[0][1]), rule_order.index(item[0][0])))
    counts = {severity: sum(len(examples) for (_, level), examples in groups.items() if level == severity)
              for severity in SEVERITIES}
    return {
        "error_count": counts["error"],
        "warning_count": counts["warning"],
        "info_count": counts["info"],
        "truncated": len(ordered) > MAX_FINDING_GROUPS,
        "findings": [{"rule": rule, "severity": severity, "message": RULES[rule], "count": len(examples),
                      "examples": examples[:MAX_EXAMPLES]}
                     for (rule, severity), examples in ordered[:MAX_FINDING_GROUPS]],
    }
