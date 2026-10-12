"""
Matching engine of the link assistant (no Qt).

Proposes links between the outputs of an FMU and the inputs of another one, by applying a matching criterion on
the port names, and checks each link against the constraints of the container builder (type conversion, unit,
input already fed).
"""

import difflib
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from fmu_manipulation_toolbox.container.types import FMI_TO_CONTAINER, CONVERSION_FUNCTION, is_lossy


_SEPARATORS = re.compile(r"[._\-\[\]\s]+")


def normalize(name: str) -> str:
    """Name without case nor separators: `Throttle_Pos` and `throttle.pos` give `throttlepos`."""
    return _SEPARATORS.sub("", name).lower()


@dataclass(frozen=True)
class PortInfo:
    """What the assistant needs to know about a port (see `NodeItem.fmu_port_*`)."""
    name: str
    causality: str
    fmi_type: str
    fmi_version: int = 2
    unit: str = ""
    description: str = ""
    size: int = 1               # number of elements of an array (or FMI-2 array aggregate)

    @property
    def container_type(self) -> str:
        return FMI_TO_CONTAINER.get(self.fmi_version, {}).get(self.fmi_type, "")


# ── Status ──────────────────────────────────────────────────────────────

OK = 0
WARNING = 1
ERROR = 2


@dataclass(frozen=True)
class Status:
    level: int
    message: str = ""

    @property
    def symbol(self) -> str:
        return ("✔", "⚠", "✖")[self.level]

    def __str__(self):
        return f"{self.symbol} {self.message}".rstrip()


@dataclass
class Checks:
    """Which differences are errors (✖) instead of warnings (⚠)."""
    compatible_type: bool = True
    same_unit: bool = False


def link_status(output: PortInfo, input: PortInfo, fed: set[str] = frozenset(),
                checks: Checks | None = None) -> Status:
    """Status of the link `output` → `input`; `fed` holds the inputs that already have a feeder."""
    checks = checks or Checks()
    if input.name in fed:
        return Status(ERROR, "input already fed")
    if output.size != input.size:
        return Status(ERROR, f"size {output.size} → {input.size}")

    warnings = []
    type_from, type_to = output.container_type, input.container_type
    if type_from != type_to:
        conversion = CONVERSION_FUNCTION.get(f"{type_from}/{type_to}")
        if conversion is None:
            message = f"{output.fmi_type} → {input.fmi_type} not convertible"
            if checks.compatible_type:
                return Status(ERROR, message)
            warnings.append(message)
        elif is_lossy(conversion):
            warnings.append(f"{output.fmi_type} → {input.fmi_type} (lossy)")
    if output.unit != input.unit:
        message = f"unit {output.unit or '-'} → {input.unit or '-'}"
        if checks.same_unit:
            return Status(ERROR, message)
        warnings.append(message)

    if warnings:
        return Status(WARNING, ", ".join(warnings))
    return Status(OK, f"array of {output.size}" if output.size > 1 else "")


# ── Rules ───────────────────────────────────────────────────────────────

class Rule:
    """A matching criterion: proposes, for an output name, the input it should be linked to.

    With `ignore_case`, names are compared without case nor separators (`normalize`) by every criterion.
    """
    kind = ""
    short = ""                  # origin of the staged links

    def prepare(self, inputs: dict[str, PortInfo], ignore_case: bool = True):
        """Called once per run, before `match`, with the inputs still free (the dict shrinks during the run)."""
        self._inputs = inputs
        self._ignore_case = ignore_case
        self._index: dict[str, str] = {}
        for name in inputs:
            self._index.setdefault(self._key(name), name)

    def _key(self, name: str) -> str:
        return normalize(name) if self._ignore_case else name

    def _lookup_key(self, key: str) -> str | None:
        name = self._index.get(key)
        return name if name in self._inputs else None

    def match(self, output: PortInfo) -> tuple[str, float] | None:
        """Return (input name, score in [0, 1]) or None."""
        raise NotImplementedError


class SameNameRule(Rule):
    kind = "Same name"
    short = "same name"

    def match(self, output):
        name = self._lookup_key(self._key(output.name))
        return (name, 1.0) if name else None


@dataclass
class AffixRule(Rule):
    """Replace a prefix and/or a suffix of the output name."""
    from_prefix: str = ""
    to_prefix: str = ""
    from_suffix: str = ""
    to_suffix: str = ""
    kind = "Replace prefix / suffix"
    short = "prefix / suffix"

    def match(self, output):
        # `normalize` works character by character, so it can be applied to each part of the name.
        key = self._key(output.name)
        from_prefix, from_suffix = self._key(self.from_prefix), self._key(self.from_suffix)
        if len(key) <= len(from_prefix) + len(from_suffix) \
                or not key.startswith(from_prefix) or not key.endswith(from_suffix):
            return None
        core = key[len(from_prefix):len(key) - len(from_suffix)]
        name = self._lookup_key(self._key(self.to_prefix) + core + self._key(self.to_suffix))
        return (name, 1.0) if name else None


@dataclass
class RegexRule(Rule):
    """Rewrite the whole output name with a regular expression (`re.fullmatch`, then `expand`)."""
    pattern: str = ""
    replacement: str = ""
    kind = "Regular expression"
    short = "regex"

    def prepare(self, inputs, ignore_case=True):
        super().prepare(inputs, ignore_case)
        try:
            self._regex = re.compile(self.pattern, re.IGNORECASE if ignore_case else 0) if self.pattern else None
        except re.error:
            self._regex = None

    def match(self, output):
        if self._regex is None:
            return None
        found = self._regex.fullmatch(output.name)
        if not found:
            return None
        try:
            target = found.expand(self.replacement)
        except (re.error, IndexError):
            return None
        name = self._lookup_key(self._key(target))
        return (name, 1.0) if name else None


def _trigrams(key: str) -> set[str]:
    return {key[i:i + 3] for i in range(len(key) - 2)} or {key}


@dataclass
class SimilarityRule(Rule):
    """Closest input name (`difflib` ratio) above a threshold.

    `difflib` against every input is too slow for thousands of ports (O(outputs × inputs)): the inputs sharing the
    most 3-character fragments with the output are found first with an index, and only `CANDIDATES` of them are
    compared. The fragments found in more than `COMMON` of the inputs (`ecu`, `eng`, …) do not discriminate and are
    left out of the index.
    """
    threshold: float = 0.8
    kind = "Similar names"
    short = "similar"
    CANDIDATES = 20
    COMMON = 0.1

    def prepare(self, inputs, ignore_case=True):
        super().prepare(inputs, ignore_case)
        grams: dict[str, list[str]] = defaultdict(list)
        for key in self._index:
            for gram in _trigrams(key):
                grams[gram].append(key)
        limit = max(20, int(len(self._index) * self.COMMON))
        self._grams = {gram: keys for gram, keys in grams.items() if len(keys) <= limit}

    def match(self, output):
        key = self._key(output.name)
        hits: Counter = Counter()
        for gram in _trigrams(key):
            hits.update(self._grams.get(gram, ()))
        best, best_score = None, self.threshold
        for candidate, _ in hits.most_common(self.CANDIDATES):
            if self._lookup_key(candidate) is None:
                continue
            matcher = difflib.SequenceMatcher(None, key, candidate)
            if matcher.real_quick_ratio() < best_score or matcher.quick_ratio() < best_score:
                continue
            score = matcher.ratio()
            if score >= best_score:
                best, best_score = candidate, score
        return (self._index[best], best_score) if best else None


RULE_KINDS = (SameNameRule, AffixRule, RegexRule, SimilarityRule)


# ── Suggestions ─────────────────────────────────────────────────────────

@dataclass
class Suggestion:
    output: PortInfo
    input: PortInfo
    score: float
    status: Status
    checked: bool = field(default=False)


def suggest(outputs: list[PortInfo], inputs: list[PortInfo], rule: Rule, ignore_case: bool = True,
            fed: set[str] = frozenset(), excluded_outputs: set[str] = frozenset(),
            excluded_inputs: set[str] = frozenset(), checks: Checks | None = None) -> list[Suggestion]:
    """Apply one criterion to the outputs, in order; an input is proposed only once.

    `excluded_outputs` / `excluded_inputs` are already linked or staged and are not proposed again. The inputs of
    `fed` are still proposed, with an error status, so that the user sees why a name does not get linked.
    """
    free_inputs = {port.name: port for port in inputs if port.name not in excluded_inputs}
    rule.prepare(free_inputs, ignore_case)
    suggestions = []
    for output in outputs:
        if output.name in excluded_outputs:
            continue
        found = rule.match(output)
        if found is None:
            continue
        input = free_inputs.pop(found[0])
        status = link_status(output, input, fed, checks)
        if found[1] < 1.0 and status.level == OK:
            status = Status(WARNING, f"similar name ({found[1]:.2f})")
        suggestions.append(Suggestion(output, input, found[1], status, checked=status.level != ERROR))
    return suggestions


def staged_statuses(links: list[tuple[PortInfo, PortInfo]], fed: set[str] = frozenset(),
                    checks: Checks | None = None) -> list[Status]:
    """Status of each staged link (`link_status`, plus an error when two links feed the same input)."""
    count: dict[str, int] = {}
    for _, input in links:
        count[input.name] = count.get(input.name, 0) + 1
    statuses = []
    for output, input in links:
        if count[input.name] > 1:
            statuses.append(Status(ERROR, "input fed by several staged links"))
        else:
            statuses.append(link_status(output, input, fed, checks))
    return statuses
