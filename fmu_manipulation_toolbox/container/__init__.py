"""FMU Containers: FMUs embedding other FMUs.

[FMUContainer][fmu_manipulation_toolbox.container.FMUContainer] is the entry point. The package is split by concern
(`types`, `arrays`, `embedded`, `rules`, `layout`, `txt`, `builder`); every class stays importable from
`fmu_manipulation_toolbox.container`, as when the package was a single module.
"""
from .arrays import ArrayAggregate
from .builder import FMUContainer, Platform
from .embedded import EmbeddedFMU, EmbeddedFMUPort
from .errors import FMUContainerError
from .layout import ContainerLayout, ValueReferenceTable
from .rules import AutoWired, ContainerInput, ContainerPort, Link
from .txt import Clock, ClockList, FMUIOList, InvolvedFMU, IOReference, LocalVariable, Port

__all__ = [
    "ArrayAggregate", "AutoWired", "Clock", "ClockList", "ContainerInput", "ContainerLayout", "ContainerPort", "EmbeddedFMU",
    "EmbeddedFMUPort", "FMUContainer", "FMUContainerError", "FMUIOList", "IOReference", "InvolvedFMU", "Link",
    "LocalVariable", "Platform", "Port", "ValueReferenceTable",
]
