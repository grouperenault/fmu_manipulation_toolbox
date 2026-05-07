"""Detail panels package for the FMU container builder.

Re-exports all public classes so existing imports continue to work:
    from .details import ContainerParameters, DetailPanelStack, ...
"""

from .container_detail import ContainerParameters, ContainerDetailWidget
from .fmu_detail import FMUDetailWidget
from .wire_detail import WireDetailWidget
from .stack import DetailPanelStack

__all__ = [
    "ContainerParameters",
    "ContainerDetailWidget",
    "FMUDetailWidget",
    "WireDetailWidget",
    "DetailPanelStack",
]

