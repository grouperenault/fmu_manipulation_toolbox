"""Analysis of an assembly: bounded summary and paged views of its containers (docs/local/assembly_analysis.md).

The assembly JSON (the format of `Assembly.json_encode`, produced by both bridges) grows with the number of ports:
a real assembly of 3 nested containers is over 100k characters, far more than a tool result can carry. The
functions here only read that JSON and reduce it to what describes the assembly: the container tree, the options
of every level, and the ports and links grouped by FMU and by name prefix, each group with a count and a few
examples. Two bounds keep the summary small: per container, the number of groups (`MAX_GROUPS`, the ports that share
their prefix with no other being merged); for the whole tree, its size (`MAX_SUMMARY_SIZE`), beyond which the
sub-containers are reduced to their name, options, FMUs and counts.

The same JSON is also served as is, but paged (`assembly_page`): one container at a time, and one section of it
(exposed inputs, links...) at a time when the container alone is too large.

Pure functions on plain data: this module depends on the standard library only, like the bridge protocol.
"""

import json
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
    path = f"{path}/{node.get('name')}" if path else str(node.get("name"))
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
        known = ", ".join(str(node.get("name")) for _, node in containers)
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
