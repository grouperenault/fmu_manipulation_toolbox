"""Detail panels package for the FMU container builder.

Re-exports all public classes so existing imports continue to work:
    from .details import ContainerParameters, DetailPanelStack, ...
"""

from .configuration_detail import ConfigurationDetailWidget
from .container_detail import ContainerDetailWidget, ContainerParameters
from .fmu_detail import FMUDetailWidget
from .stack import DetailPanelStack
from .wire_detail import WireDetailWidget

__all__ = [
    "ContainerParameters",
    "ContainerDetailWidget",
    "ConfigurationDetailWidget",
    "FMUDetailWidget",
    "WireDetailWidget",
    "DetailPanelStack",
]

