"""FMI-2 array families (`name[i]`, `name[i,j]`) seen as N-D arrays."""

import itertools
import logging
import re
from collections import defaultdict
from collections.abc import Iterable


logger = logging.getLogger("fmu_manipulation_toolbox")


# ---------------------------------------------------------------------------
# FMI-2 array-aggregate helpers
#
# FMI-2 has no native array concept: vectors and matrices are conventionally
# exposed as a set of scalar ports named `basename[i]` or `basename[i,j,...]`
# (Modelica-style comma notation, conforming to how FMI-2.0 exporters
# typically flatten arrays). The `ArrayAggregate` class below detects such
# families and represents them as virtual N-D aggregates so they can be
# connected to FMI-3 array ports of matching shape.
# ---------------------------------------------------------------------------


class ArrayAggregate:
    """Represents an FMI-2 array-element family (`basename[i]`, `basename[i,j]`,
    ...) aggregated as a virtual N-D array so it can be linked to an FMI-3
    array port of matching shape.

    Attributes:
        basename: Name of the virtual aggregate (without brackets).
        dims: Shape as a tuple of positive integers, e.g. `(3,)` for a 1D
            vector of length 3, `(2, 3)` for a 2×3 matrix.
        ordered_element_names: Original scalar port names sorted in
            **row-major** order (last index varies fastest), matching the
            FMI-3 array memory layout.
    """

    __slots__ = ("basename", "dims", "ordered_element_names")

    # Trailing bracket group: `[3]`, `[1,2]`, ... (Modelica-style, single
    # bracket with comma-separated indices) at the end of a name.
    _ARRAY_ELEM_RE = re.compile(r"^(.+)\[(\d+(?:,\d+)*)]$")

    def __init__(self, basename: str, dims: tuple[int, ...], ordered_element_names: list[str]):
        self.basename = basename
        self.dims = dims
        self.ordered_element_names = ordered_element_names

    @property
    def size(self) -> int:
        """Total number of scalar elements (product of `dims`)."""
        return len(self.ordered_element_names)

    @property
    def rank(self) -> int:
        """Number of axes (`len(dims)`)."""
        return len(self.dims)

    @property
    def shape_str(self) -> str:
        """Human-readable shape, e.g. `"2x3"` for a 2×3 matrix."""
        return "x".join(str(d) for d in self.dims)

    def __repr__(self):
        return f"ArrayAggregate({self.basename!r}, shape={self.shape_str}, size={self.size})"

    # -- Alternative constructors / parsers ------------------------------------

    @classmethod
    def parse_element_name(cls, name: str) -> tuple[str, tuple[int, ...]] | None:
        """Return `(basename, indices)` if `name` has the form `basename[i,j,...]`
        (Modelica-style comma notation, conforming to FMI-2.0 array-element
        naming). Returns `None` if `name` is not a recognized array element
        name.
        """
        m = cls._ARRAY_ELEM_RE.match(name)
        if not m:
            return None
        basename = m.group(1)
        indices = tuple(int(tok) for tok in m.group(2).split(","))
        return basename, indices

    @classmethod
    def detect_all(
            cls,
            port_names: Iterable[str],
            existing_names: set[str] | None = None,
            log_prefix: str = "",
    ) -> list["ArrayAggregate"]:
        """Detect FMI-2 array-element families among `port_names` and return the
        valid N-D aggregates as `ArrayAggregate` instances.

        Only aggregates whose indices form a complete, contiguous hyperrectangle
        starting at 0 or 1 on every axis are returned. Attribute homogeneity
        (type, causality, ...) is **not** checked here; callers must filter
        further if needed.

        `existing_names` avoids emitting an aggregate whose basename collides
        with an already-existing (scalar) port.
        """
        if existing_names is None:
            existing_names = set()

        groups: dict[str, list[tuple[tuple[int, ...], str]]] = defaultdict(list)
        for name in port_names:
            parsed = cls.parse_element_name(name)
            if parsed is None:
                continue
            basename, indices = parsed
            groups[basename].append((indices, name))

        aggregates: list[ArrayAggregate] = []
        for basename, elements in groups.items():
            if basename in existing_names:
                continue

            rank = len(elements[0][0])
            if not all(len(idx) == rank for idx, _ in elements):
                if log_prefix:
                    logger.debug(f"'{log_prefix}': mixed ranks for array '{basename}', "
                                 f"aggregate not created.")
                continue

            mins = [min(idx[a] for idx, _ in elements) for a in range(rank)]
            maxs = [max(idx[a] for idx, _ in elements) for a in range(rank)]
            if not all(s in (0, 1) for s in mins):
                continue
            dims = tuple(maxs[a] - mins[a] + 1 for a in range(rank))

            expected_count = 1
            for d in dims:
                expected_count *= d
            actual_set = {idx for idx, _ in elements}
            if len(actual_set) != len(elements) or expected_count != len(elements):
                if log_prefix:
                    logger.debug(f"'{log_prefix}': non-contiguous / duplicated array elements "
                                 f"for '{basename}', aggregate not created.")
                continue
            expected_set = set(itertools.product(
                *(range(mins[a], mins[a] + dims[a]) for a in range(rank))))
            if expected_set != actual_set:
                if log_prefix:
                    logger.debug(f"'{log_prefix}': non-contiguous array elements for '{basename}', "
                                 f"aggregate not created.")
                continue

            # Row-major sort: last index varies fastest.
            elements.sort(key=lambda e: e[0])
            ordered_names = [n for _, n in elements]
            aggregates.append(cls(basename, dims, ordered_names))

        return aggregates
