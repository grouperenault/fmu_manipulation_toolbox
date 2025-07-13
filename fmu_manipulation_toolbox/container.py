import logging
import getpass
import os
import shutil
import uuid
import platform
import zipfile
from datetime import datetime
from pathlib import Path
from typing import *

from .operations import FMU, OperationAbstract, FMUError
from .version import __version__ as tool_version


logger = logging.getLogger("fmu_manipulation_toolbox")


class FMUPort:

    @staticmethod
    def simple_type_name(type_name: str) -> str:
        table = {
            'Float64': 'Real',
            'Int32': 'Integer'
        }
        try:
            return table[type_name]
        except KeyError:
            return type_name

    def __init__(self, attrs: Dict[str, str]):
        self.causality = attrs.get("causality", "local")
        self.variability = attrs.get("variability", "continuous")
        self.name = attrs.get("name")
        self.vr = int(attrs.get("valueReference"))
        self.description = attrs.get("description", None)

        self.type_name = self.simple_type_name(attrs.pop("type_name", None))
        self.start_value = attrs.get("start", None)
        self.initial = attrs.get("initial", None)

    def set_port_type(self, type_name: str, attrs: Dict[str, str]):
        self.type_name = self.simple_type_name(type_name)
        self.start_value = attrs.get("start", None)
        self.initial = attrs.get("initial", None)

    def xml(self, vr: int, name=None, causality=None, start=None, fmi_version=2):
        if name is None:
            name = self.name
        if causality is None:
            causality = self.causality
        if start is None:
            start = self.start_value
        if self.variability is None:
            self.variability = "continuous" if self.type_name == "Real" else "discrete"


        if fmi_version == 2:
            child_attrs =  {
                "start": start,
            }
            if "Float" in self.type_name:
                type_name = "Real"
            elif "Int" in self.type_name:
                type_name = "Integer"
            else:
                type_name = self.type_name

            filtered_child_attrs = {key: value for key, value in child_attrs.items() if value is not None}
            child_str = (f"<{type_name} " +
                         " ".join([f'{key}="{value}"' for (key, value) in filtered_child_attrs.items()]) +
                         "/>")

            scalar_attrs = {
                "name": name,
                "valueReference": vr,
                "causality": causality,
                "variability": self.variability,
                "initial": self.initial,
                "description": self.description,
            }
            filtered_attrs = {key: value for key, value in scalar_attrs.items() if value is not None}
            scalar_attrs_str = " ".join([f'{key}="{value}"' for (key, value) in filtered_attrs.items()])
            return f'<ScalarVariable {scalar_attrs_str}>{child_str}</ScalarVariable>'
        else:
            if "Real" == self.type_name:
                type_name = "Float64"
            elif "Integer" == self.type_name:
                type_name = "Int32"
            else:
                type_name = self.type_name

            scalar_attrs = {
                "name": name,
                "valueReference": vr,
                "causality": causality,
                "variability": self.variability,
                "initial": self.initial,
                "description": self.description,
                "start": start
            }
            filtered_attrs = {key: value for key, value in scalar_attrs.items() if value is not None}
            scalar_attrs_str = " ".join([f'{key}="{value}"' for (key, value) in filtered_attrs.items()])

            return f'<{type_name} {scalar_attrs_str}/>'


class EmbeddedFMU(OperationAbstract):
    capability_list = ("needsExecutionTool",
                       "canBeInstantiatedOnlyOncePerProcess")

    def __init__(self, filename):
        self.fmu = FMU(filename)
        self.name = Path(filename).name
        self.id = Path(filename).stem.lower()

        self.step_size = None
        self.start_time = None
        self.stop_time = None
        self.model_identifier = None
        self.guid = None
        self.fmi_version = None
        self.ports: Dict[str, FMUPort] = {}

        self.capabilities: Dict[str, str] = {}
        self.current_port = None  # used during apply_operation()

        self.fmu.apply_operation(self)  # Should be the last command in constructor!
        if self.model_identifier is None:
            raise FMUContainerError(f"FMU '{self.name}' does not implement Co-Simulation mode.")

    def fmi_attrs(self, attrs):
        fmi_version = attrs['fmiVersion']
        if fmi_version == "2.0":
            self.guid = attrs['guid']
            self.fmi_version = 2
        if fmi_version == "3.0":
            self.guid = attrs['instantiationToken']
            self.fmi_version = 3


    def scalar_attrs(self, attrs) -> int:
        if 'type_name' in attrs:  # FMI 3.0
            port = FMUPort(attrs)
            self.ports[port.name] = port
        else: # FMI 2.0
            self.current_port = FMUPort(attrs)
            self.ports[self.current_port.name] = self.current_port

        return 0

    def cosimulation_attrs(self, attrs: Dict[str, str]):
        self.model_identifier = attrs['modelIdentifier']
        for capability in self.capability_list:
            self.capabilities[capability] = attrs.get(capability, "false")

    def experiment_attrs(self, attrs: Dict[str, str]):
        try:
            self.step_size = float(attrs['stepSize'])
        except KeyError:
            logger.warning(f"FMU '{self.name}' does not specify preferred step size")
        self.start_time = float(attrs.get("startTime", 0.0))
        self.stop_time = float(attrs.get("stopTime", self.start_time + 1.0))

    def scalar_type(self, type_name, attrs):
        if self.current_port:
            if type_name == "Enumeration":
                type_name = "Integer"
            self.current_port.set_port_type(type_name, attrs)
        self.current_port = None

    def __repr__(self):
        return f"FMU '{self.name}' ({len(self.ports)} variables)"


class FMUContainerError(Exception):
    def __init__(self, reason: str):
        self.reason = reason

    def __repr__(self):
        return f"{self.reason}"


class ContainerPort:
    def __init__(self, fmu: EmbeddedFMU, port_name: str):
        self.fmu = fmu
        try:
            self.port = fmu.ports[port_name]
        except KeyError:
            raise FMUContainerError(f"Port '{fmu.name}/{port_name}' does not exist")
        self.vr = None

    def __repr__(self):
        return f"Port {self.fmu.name}/{self.port.name}"

    def __hash__(self):
        return hash(str(self))

    def __eq__(self, other):
        return str(self) == str(other)


class ContainerInput:
    def __init__(self, name: str, cport_to: ContainerPort):
        self.name = name
        self.type_name = cport_to.port.type_name
        self.causality = cport_to.port.causality
        self.cport_list = [cport_to]
        self.vr = None

    def add_cport(self, cport_to: ContainerPort):
        if cport_to in self.cport_list: # Cannot be reached ! (Assembly prevent this to happen)
            raise FMUContainerError(f"Duplicate INPUT {cport_to} already connected to {self.name}")

        if cport_to.port.type_name != self.type_name:
            raise FMUContainerError(f"Cannot connect {self.name} of type {self.type_name} to "
                                    f"{cport_to} of type {cport_to.port.type_name}")

        if cport_to.port.causality != self.causality:
            raise FMUContainerError(f"Cannot connect {self.causality.upper()} {self.name} to "
                                    f"{cport_to.port.causality.upper()} {cport_to}")

        self.cport_list.append(cport_to)


class Local:
    def __init__(self, cport_from: ContainerPort):
        self.name = cport_from.fmu.id + "." + cport_from.port.name  # strip .fmu suffix
        self.cport_from = cport_from
        self.cport_to_list: List[ContainerPort] = []
        self.vr = None

        if not cport_from.port.causality == "output":
            raise FMUContainerError(f"{cport_from} is  {cport_from.port.causality} instead of OUTPUT")

    def add_target(self, cport_to: ContainerPort):
        if not cport_to.port.causality == "input":
            raise FMUContainerError(f"{cport_to} is {cport_to.port.causality} instead of INPUT")

        if cport_to.port.type_name == self.cport_from.port.type_name:
            self.cport_to_list.append(cport_to)
        else:
            raise FMUContainerError(f"failed to connect {self.cport_from} to {cport_to} due to type.")


class ValueReferenceTable:
    def __init__(self):
        self.vr_table: Dict[str, int] = {
            "Real": 0,
            "Integer": 0,
            "Boolean": 0,
            "String": 0,
        }

    def get_vr(self, cport: ContainerPort) -> int:
        return self.add_vr(cport.port.type_name)

    def add_vr(self, type_name: str) -> int:
        vr = self.vr_table[type_name]
        self.vr_table[type_name] += 1
        return vr


class AutoWired:
    def __init__(self):
        self.rule_input = []
        self.rule_output = []
        self.rule_link = []
        self.nb_param = 0

    def __repr__(self):
        return (f"{self.nb_param} parameters, {len(self.rule_input) - self.nb_param} inputs,"
                f" {len(self.rule_output)} outputs, {len(self.rule_link)} links.")

    def add_input(self, from_port, to_fmu, to_port):
        self.rule_input.append([from_port, to_fmu, to_port])

    def add_parameter(self, from_port, to_fmu, to_port):
        self.rule_input.append([from_port, to_fmu, to_port])
        self.nb_param += 1

    def add_output(self, from_fmu, from_port, to_port):
        self.rule_output.append([from_fmu, from_port, to_port])

    def add_link(self, from_fmu, from_port, to_fmu, to_port):
        self.rule_link.append([from_fmu, from_port, to_fmu, to_port])


class FMUContainer:
    HEADER_XML_2 = """<?xml version="1.0" encoding="ISO-8859-1"?>
<fmiModelDescription
  fmiVersion="2.0"
  modelName="{identifier}"
  generationTool="FMUContainer-{tool_version}"
  generationDateAndTime="{timestamp}"
  guid="{guid}"
  description="FMUContainer with {embedded_fmu}"
  author="{author}"
  license="Proprietary"
  copyright="See Embedded FMU's copyrights."
  variableNamingConvention="structured">

  <CoSimulation
    modelIdentifier="{identifier}"
    canHandleVariableCommunicationStepSize="true"
    canBeInstantiatedOnlyOncePerProcess="{only_once}"
    canNotUseMemoryManagementFunctions="true"
    canGetAndSetFMUstate="false"
    canSerializeFMUstate="false"
    providesDirectionalDerivative="false"
    needsExecutionTool="{execution_tool}">
  </CoSimulation>

  <LogCategories>
    <Category name="fmucontainer"/>
  </LogCategories>

  <DefaultExperiment stepSize="{step_size}" startTime="{start_time}" stopTime="{stop_time}"/>

  <ModelVariables>
    <ScalarVariable valueReference="0" name="time" causality="independent"><Real /></ScalarVariable>
"""

    HEADER_XML_3 = """<?xml version="1.0" encoding="ISO-8859-1"?>
    <fmiModelDescription
      fmiVersion="3.0"
      modelName="{identifier}"
      generationTool="FMUContainer-{tool_version}"
      generationDateAndTime="{timestamp}"
      instantiationToken="{guid}"
      description="FMUContainer with {embedded_fmu}"
      author="{author}"
      license="Proprietary"
      copyright="See Embedded FMU's copyrights."
      variableNamingConvention="structured">

      <CoSimulation
        modelIdentifier="{identifier}"
        canHandleVariableCommunicationStepSize="true"
        canBeInstantiatedOnlyOncePerProcess="{only_once}"
        canNotUseMemoryManagementFunctions="true"
        canGetAndSetFMUstate="false"
        canSerializeFMUstate="false"
        providesDirectionalDerivative="false"
        needsExecutionTool="{execution_tool}">
      </CoSimulation>

      <LogCategories>
        <Category name="fmucontainer"/>
      </LogCategories>

      <DefaultExperiment stepSize="{step_size}" startTime="{start_time}" stopTime="{stop_time}"/>

      <ModelVariables>
        <Float64 valueReference="0" name="time" causality="independent"/>
"""

    def __init__(self, identifier: str, fmu_directory: Union[str, Path], description_pathname=None, fmi_version=2):
        self.fmu_directory = Path(fmu_directory)
        self.identifier = identifier
        if not self.fmu_directory.is_dir():
            raise FMUContainerError(f"{self.fmu_directory} is not a valid directory")
        self.involved_fmu: OrderedDict[str, EmbeddedFMU] = OrderedDict()

        self.description_pathname = description_pathname
        self.fmi_version = fmi_version

        self.start_time = None
        self.stop_time = None

        # Rules
        self.inputs: Dict[str, ContainerInput] = {}
        self.outputs: Dict[str, ContainerPort] = {}
        self.locals: Dict[ContainerPort, Local] = {}

        self.rules: Dict[ContainerPort, str] = {}
        self.start_values: Dict[ContainerPort, str] = {}


    def convert_type_name(self, type_name: str) -> str:
        if self.fmi_version == 2:
            table = {}
        elif self.fmi_version == 3:
            table = {}
        else:
            table = {}

        try:
            return table[type_name]
        except KeyError:
            return type_name

    def get_fmu(self, fmu_filename: str) -> EmbeddedFMU:
        if fmu_filename in self.involved_fmu:
            return self.involved_fmu[fmu_filename]

        try:
            fmu = EmbeddedFMU(self.fmu_directory / fmu_filename)
            if fmu.fmi_version > self.fmi_version:
                logger.fatal(f"Try to embed FMU-{fmu.fmi_version} into container FMI-{self.fmi_version}")
            self.involved_fmu[fmu.name] = fmu

            logger.debug(f"Adding FMU #{len(self.involved_fmu)}: {fmu}")
        except (FMUContainerError, FMUError) as e:
            raise FMUContainerError(f"Cannot load '{fmu_filename}': {e}")

        return fmu

    def mark_ruled(self, cport: ContainerPort, rule: str):
        if cport in self.rules:
            previous_rule = self.rules[cport]
            if rule not in ("OUTPUT", "LINK") and previous_rule not in ("OUTPUT", "LINK"):
                raise FMUContainerError(f"try to {rule} port {cport} which is already {previous_rule}")

        self.rules[cport] = rule

    def get_all_cports(self):
        return [ContainerPort(fmu, port_name) for fmu in self.involved_fmu.values() for port_name in fmu.ports]

    def add_input(self, container_port_name: str, to_fmu_filename: str, to_port_name: str):
        if not container_port_name:
            container_port_name = to_port_name
        cport_to = ContainerPort(self.get_fmu(to_fmu_filename), to_port_name)
        if cport_to.port.causality not in ("input", "parameter"):  # check causality
            raise FMUContainerError(f"Tried to use '{cport_to}' as INPUT of the container but FMU causality is "
                                    f"'{cport_to.port.causality}'.")

        try:
            input_port = self.inputs[container_port_name]
            input_port.add_cport(cport_to)
        except KeyError:
            self.inputs[container_port_name] = ContainerInput(container_port_name, cport_to)

        logger.debug(f"INPUT: {to_fmu_filename}:{to_port_name}")
        self.mark_ruled(cport_to, 'INPUT')

    def add_output(self, from_fmu_filename: str, from_port_name: str, container_port_name: str):
        if not container_port_name:  # empty is allowed
            container_port_name = from_port_name

        cport_from = ContainerPort(self.get_fmu(from_fmu_filename), from_port_name)
        if cport_from.port.causality not in ("output", "local"):  # check causality
            raise FMUContainerError(f"Tried to use '{cport_from}' as OUTPUT of the container but FMU causality is "
                                    f"'{cport_from.port.causality}'.")

        if container_port_name in self.outputs:
            raise FMUContainerError(f"Duplicate OUTPUT {container_port_name} already connected to {cport_from}")

        logger.debug(f"OUTPUT: {from_fmu_filename}:{from_port_name}")
        self.mark_ruled(cport_from, 'OUTPUT')
        self.outputs[container_port_name] = cport_from

    def drop_port(self, from_fmu_filename: str, from_port_name: str):
        cport_from = ContainerPort(self.get_fmu(from_fmu_filename), from_port_name)
        if not cport_from.port.causality == "output":  # check causality
            raise FMUContainerError(f"{cport_from}: trying to DROP {cport_from.port.causality}")

        logger.debug(f"DROP: {from_fmu_filename}:{from_port_name}")
        self.mark_ruled(cport_from, 'DROP')

    def add_link(self, from_fmu_filename: str, from_port_name: str, to_fmu_filename: str, to_port_name: str):
        cport_from = ContainerPort(self.get_fmu(from_fmu_filename), from_port_name)
        try:
            local = self.locals[cport_from]
        except KeyError:
            local = Local(cport_from)

        cport_to = ContainerPort(self.get_fmu(to_fmu_filename), to_port_name)
        local.add_target(cport_to)  # Causality is check in the add() function

        self.mark_ruled(cport_from, 'LINK')
        self.mark_ruled(cport_to, 'LINK')
        self.locals[cport_from] = local

    def add_start_value(self, fmu_filename: str, port_name: str, value: str):
        cport = ContainerPort(self.get_fmu(fmu_filename), port_name)

        try:
            if cport.port.type_name in ('Real', 'Float64', 'Float32'):
                value = float(value)
            elif cport.port.type_name in ('Integer', 'Int8', 'UInt8', 'Int16', 'UInt16', 'Int32', 'UInt32', 'Int64', 'UInt64'):
                value = int(value)
            elif cport.port.type_name == 'Boolean':
                value = int(bool(value))
            else:
                value = value
        except ValueError:
            raise FMUContainerError(f"Start value is not conforming to '{cport.port.type_name}' format.")

        self.start_values[cport] = value

    def find_inputs(self, port_to_connect: FMUPort) -> List[ContainerPort]:
        candidates = []
        for cport in self.get_all_cports():
            if (cport.port.causality == 'input' and cport not in self.rules and cport.port.name == port_to_connect.name
                    and cport.port.type_name == port_to_connect.type_name):
                candidates.append(cport)
        return candidates

    def add_implicit_rule(self, auto_input=True, auto_output=True, auto_link=True, auto_parameter=False,
                          auto_local=False) -> AutoWired:

        auto_wired = AutoWired()
        # Auto Link outputs
        for cport in self.get_all_cports():
            if cport.port.causality == 'output':
                candidates_cport_list = self.find_inputs(cport.port)
                if auto_link and candidates_cport_list:
                    for candidate_cport in candidates_cport_list:
                        logger.info(f"AUTO LINK: {cport} -> {candidate_cport}")
                        self.add_link(cport.fmu.name, cport.port.name,
                                      candidate_cport.fmu.name, candidate_cport.port.name)
                        auto_wired.add_link(cport.fmu.name, cport.port.name,
                                            candidate_cport.fmu.name, candidate_cport.port.name)
                elif auto_output and cport not in self.rules:
                    logger.info(f"AUTO OUTPUT: Expose {cport}")
                    self.add_output(cport.fmu.name, cport.port.name, cport.port.name)
                    auto_wired.add_output(cport.fmu.name, cport.port.name, cport.port.name)
            elif cport.port.causality == 'local':
                local_portname = None
                if cport.port.name.startswith("container."):
                    local_portname = "container." + cport.fmu.id + "." + cport.port.name[10:]
                    logger.info(f"PROFILING: Expose {cport}")
                elif auto_local:
                    local_portname = cport.fmu.id + "." + cport.port.name
                    logger.info(f"AUTO LOCAL: Expose {cport}")
                if local_portname:
                    self.add_output(cport.fmu.name, cport.port.name, local_portname)
                    auto_wired.add_output(cport.fmu.name, cport.port.name, local_portname)

        if auto_input:
            # Auto link inputs
            for cport in self.get_all_cports():
                if cport not in self.rules:
                    if cport.port.causality == 'parameter' and auto_parameter:
                        parameter_name = cport.fmu.id + "." + cport.port.name
                        logger.info(f"AUTO PARAMETER: {cport} as {parameter_name}")
                        self.add_input(parameter_name, cport.fmu.name, cport.port.name)
                        auto_wired.add_parameter(parameter_name, cport.fmu.name, cport.port.name)
                    elif cport.port.causality == 'input':
                        logger.info(f"AUTO INPUT: Expose {cport}")
                        self.add_input(cport.port.name, cport.fmu.name, cport.port.name)
                        auto_wired.add_input(cport.port.name, cport.fmu.name, cport.port.name)

        logger.info(f"Auto-wiring: {auto_wired}")

        return auto_wired

    def minimum_step_size(self) -> float:
        step_size = None
        for fmu in self.involved_fmu.values():
            if step_size:
                if fmu.step_size and fmu.step_size < step_size:
                    step_size = fmu.step_size
            else:
                step_size = fmu.step_size

        if not step_size:
            step_size = 0.1
            logger.warning(f"Defaulting to step_size={step_size}")

        return step_size

    def sanity_check(self, step_size: Optional[float]):
        for fmu in self.involved_fmu.values():
            if not fmu.step_size:
                continue
            ts_ratio = step_size / fmu.step_size
            if ts_ratio < 1.0:
                logger.warning(f"Container step_size={step_size}s is lower than FMU '{fmu.name}' "
                               f"step_size={fmu.step_size}s.")
            if ts_ratio != int(ts_ratio):
                logger.warning(f"Container step_size={step_size}s should divisible by FMU '{fmu.name}' "
                               f"step_size={fmu.step_size}s.")
            for port_name in fmu.ports:
                cport = ContainerPort(fmu, port_name)
                if cport not in self.rules:
                    if cport.port.causality == 'input':
                        logger.error(f"{cport} is not connected")
                    if cport.port.causality == 'output':
                        logger.warning(f"{cport} is not connected")

    def make_fmu(self, fmu_filename: Union[str, Path], step_size: Optional[float] = None, debug=False, mt=False,
                 profiling=False, sequential=False):
        if isinstance(fmu_filename, str):
            fmu_filename = Path(fmu_filename)

        if step_size is None:
            logger.info(f"step_size  will be deduced from the embedded FMU's")
            step_size = self.minimum_step_size()
        self.sanity_check(step_size)

        logger.info(f"Building FMU '{fmu_filename}', step_size={step_size}")

        base_directory = self.fmu_directory / fmu_filename.with_suffix('')
        resources_directory = self.make_fmu_skeleton(base_directory)
        with open(base_directory / "modelDescription.xml", "wt") as xml_file:
            self.make_fmu_xml(xml_file, step_size, profiling)
        with open(resources_directory / "container.txt", "wt") as txt_file:
            self.make_fmu_txt(txt_file, step_size, mt, profiling, sequential)

        self.make_fmu_package(base_directory, fmu_filename)
        if not debug:
            self.make_fmu_cleanup(base_directory)

    def make_fmu_xml(self, xml_file, step_size: float, profiling: bool):
        vr_table = ValueReferenceTable()

        timestamp = datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ')
        guid = str(uuid.uuid4())
        embedded_fmu = ", ".join([fmu_name for fmu_name in self.involved_fmu])
        try:
            author = getpass.getuser()
        except OSError:
            author = "Unspecified"

        capabilities = {}
        for capability in EmbeddedFMU.capability_list:
            capabilities[capability] = "false"
            for fmu in self.involved_fmu.values():
                if fmu.capabilities[capability] == "true":
                    capabilities[capability] = "true"

        first_fmu = next(iter(self.involved_fmu.values()))
        if self.start_time is None:
            self.start_time = first_fmu.start_time
            logger.info(f"start_time={self.start_time} (deduced from '{first_fmu.name}')")
        else:
            logger.info(f"start_time={self.start_time}")

        if self.stop_time is None:
            self.stop_time = first_fmu.stop_time
            logger.info(f"stop_time={self.stop_time} (deduced from '{first_fmu.name}')")
        else:
            logger.info(f"stop_time={self.stop_time}")

        if self.fmi_version == 2:
            xml_file.write(self.HEADER_XML_2.format(identifier=self.identifier, tool_version=tool_version,
                                                    timestamp=timestamp, guid=guid, embedded_fmu=embedded_fmu,
                                                    author=author,
                                                    only_once=capabilities['canBeInstantiatedOnlyOncePerProcess'],
                                                    execution_tool=capabilities['needsExecutionTool'],
                                                    start_time=self.start_time, stop_time=self.stop_time,
                                                    step_size=step_size))
        elif self.fmi_version == 3:
            xml_file.write(self.HEADER_XML_3.format(identifier=self.identifier, tool_version=tool_version,
                                                    timestamp=timestamp, guid=guid, embedded_fmu=embedded_fmu,
                                                    author=author,
                                                    only_once=capabilities['canBeInstantiatedOnlyOncePerProcess'],
                                                    execution_tool=capabilities['needsExecutionTool'],
                                                    start_time=self.start_time, stop_time=self.stop_time,
                                                    step_size=step_size))

        vr_time = vr_table.add_vr("Real")
        logger.debug(f"Time as vr = {vr_time}")
        if profiling:
            for fmu in self.involved_fmu.values():
                vr = vr_table.add_vr("Real")
                port = FMUPort({"valueReference": vr,
                                "name": f"container.{fmu.id}.rt_ratio",
                                "type_name": "Real",
                                "description": f"RT ratio for embedded FMU '{fmu.name}'"})
                print(f"        {port.xml(vr, fmi_version=self.fmi_version)}", file=xml_file)

        # Local variable should be first to ensure to attribute them the lowest VR.
        for local in self.locals.values():
            vr = vr_table.get_vr(local.cport_from)
            print(f"        {local.cport_from.port.xml(vr, name=local.name, causality='local', fmi_version=self.fmi_version)}", file=xml_file)
            local.vr = vr

        for input_port_name, input_port in self.inputs.items():
            vr = vr_table.add_vr(input_port.type_name)
            # Get Start and XML from first connected input
            start = self.start_values.get(input_port.cport_list[0], None)
            print(f"        {input_port.cport_list[0].port.xml(vr, name=input_port_name, start=start, fmi_version=self.fmi_version)}", file=xml_file)
            input_port.vr = vr

        for output_port_name, cport in self.outputs.items():
            vr = vr_table.get_vr(cport)
            print(f"        {cport.port.xml(vr, name=output_port_name, fmi_version=self.fmi_version)}", file=xml_file)
            cport.vr = vr

        if self.fmi_version == 2:
            self.make_fmu_xml_epilog_2(xml_file)
        elif self.fmi_version == 3:
            self.make_fmu_xml_epilog_3(xml_file)

    def make_fmu_xml_epilog_2(self, xml_file):
        xml_file.write(f"""  </ModelVariables>

  <ModelStructure>
    <Outputs>
 """)
        index_offset = len(self.locals) + len(self.inputs) + 1
        for i, _ in enumerate(self.outputs.keys()):
            print(f'      <Unknown index="{index_offset+i}"/>', file=xml_file)

        xml_file.write("""    </Outputs>
    <InitialUnknowns>
""")

        for i, _ in enumerate(self.outputs.keys()):
            print(f'      <Unknown index="{index_offset+i}"/>', file=xml_file)

            xml_file.write("""    </InitialUnknowns>
  </ModelStructure>

</fmiModelDescription>
 """)

    def make_fmu_xml_epilog_3(self, xml_file):
        xml_file.write(f"""  </ModelVariables>

  <ModelStructure>
""")
        for output in self.outputs.values():
            print(f'      <Output valueReference="{output.vr}"/>', file=xml_file)

        xml_file.write("""
  </ModelStructure>

</fmiModelDescription>
""")

    def make_fmu_txt(self, txt_file, step_size: float, mt: bool, profiling: bool, sequential: bool):
        print("# Container flags <MT> <Profiling> <Sequential>", file=txt_file)
        flags = [ str(int(flag == True)) for flag in (mt, profiling, sequential)]
        print(" ".join(flags), file=txt_file)

        print(f"# Internal time step in seconds", file=txt_file)
        print(f"{step_size}", file=txt_file)
        print(f"# NB of embedded FMU's", file=txt_file)
        print(f"{len(self.involved_fmu)}", file=txt_file)
        fmu_rank: Dict[str, int] = {}
        for i, fmu in enumerate(self.involved_fmu.values()):
            print(f"{fmu.name} {fmu.fmi_version}", file=txt_file)
            print(f"{fmu.model_identifier}", file=txt_file)
            print(f"{fmu.guid}", file=txt_file)
            fmu_rank[fmu.name] = i

        # Prepare data structure
        type_names_list = ("Real", "Integer", "Boolean", "String")  # Ordered list
        inputs_per_type: Dict[str, List[ContainerInput]] = {}       # Container's INPUT
        outputs_per_type: Dict[str, List[ContainerPort]] = {}       # Container's OUTPUT

        inputs_fmu_per_type: Dict[str, Dict[str, Dict[ContainerPort, int]]] = {}      # [type][fmu]
        start_values_fmu_per_type = {}
        outputs_fmu_per_type = {}
        locals_per_type: Dict[str, List[Local]] = {}

        for type_name in type_names_list:
            inputs_per_type[type_name] = []
            outputs_per_type[type_name] = []
            locals_per_type[type_name] = []

            inputs_fmu_per_type[type_name] = {}
            start_values_fmu_per_type[type_name] = {}
            outputs_fmu_per_type[type_name] = {}

            for fmu in self.involved_fmu.values():
                inputs_fmu_per_type[type_name][fmu.name] = {}
                start_values_fmu_per_type[type_name][fmu.name] = {}
                outputs_fmu_per_type[type_name][fmu.name] = {}

        # Fill data structure
        # Inputs
        for input_port_name, input_port in self.inputs.items():
            inputs_per_type[input_port.type_name].append(input_port)
        for cport, value in self.start_values.items():
            start_values_fmu_per_type[cport.port.type_name][cport.fmu.name][cport] = value
        # Outputs
        for output_port_name, cport in self.outputs.items():
            outputs_per_type[cport.port.type_name].append(cport)
        # Locals
        for local in self.locals.values():
            vr = local.vr
            locals_per_type[local.cport_from.port.type_name].append(local)
            outputs_fmu_per_type[local.cport_from.port.type_name][local.cport_from.fmu.name][local.cport_from] = vr
            for cport_to in local.cport_to_list:
                inputs_fmu_per_type[cport_to.port.type_name][cport_to.fmu.name][cport_to] = vr

        print(f"# NB local variables ", ", ".join(type_names_list), file=txt_file)
        nb_local = []
        for type_name in type_names_list:
            nb = len(locals_per_type[type_name])
            if type_name == "Real":
                nb += 1  # reserver a slot for "time"
                if profiling:
                    nb += len(self.involved_fmu)
            nb_local.append(str(nb))
        print(" ".join(nb_local), file=txt_file, end='')
        print("", file=txt_file)

        print("# CONTAINER I/O: <VR> <NB> <FMU_INDEX> <FMU_VR> [<FMU_INDEX> <FMU_VR>]", file=txt_file)
        for type_name in type_names_list:
            print(f"# {type_name}", file=txt_file)
            nb = len(inputs_per_type[type_name]) + len(outputs_per_type[type_name]) + len(locals_per_type[type_name])
            nb_input_link = 0
            for input_port in inputs_per_type[type_name]:
                nb_input_link += len(input_port.cport_list) - 1

            if type_name == "Real":
                nb += 1  # reserver a slot for "time"
                if profiling:
                    nb += len(self.involved_fmu)
                print(f"{nb} {nb + nb_input_link}", file=txt_file)
                print(f"0 1 -1 0", file=txt_file)  # Time slot
                if profiling:
                    for profiling_port, _ in enumerate(self.involved_fmu.values()):
                        print(f"{profiling_port+1} 1 -2 {profiling_port+1}", file=txt_file)
            else:
                print(f"{nb} {nb+nb_input_link}", file=txt_file)
            for input_port in inputs_per_type[type_name]:
                cport_string = [f"{fmu_rank[cport.fmu.name]} {cport.port.vr}" for cport in input_port.cport_list]
                print(f"{input_port.vr} {len(input_port.cport_list)}", " ".join(cport_string), file=txt_file)
            for cport in outputs_per_type[type_name]:
                print(f"{cport.vr} 1 {fmu_rank[cport.fmu.name]} {cport.port.vr}", file=txt_file)
            for local in locals_per_type[type_name]:
                print(f"{local.vr} 1 -1 {local.vr}", file=txt_file)

        # LINKS
        for fmu in self.involved_fmu.values():
            for type_name in type_names_list:
                print(f"# Inputs of {fmu.name} - {type_name}: <VR> <FMU_VR>", file=txt_file)
                print(len(inputs_fmu_per_type[type_name][fmu.name]), file=txt_file)
                for cport, vr in inputs_fmu_per_type[type_name][fmu.name].items():
                    print(f"{vr} {cport.port.vr}", file=txt_file)

            for type_name in type_names_list:
                print(f"# Start values of {fmu.name} - {type_name}: <FMU_VR> <RESET> <VALUE>", file=txt_file)
                print(len(start_values_fmu_per_type[type_name][fmu.name]), file=txt_file)
                for cport, value in start_values_fmu_per_type[type_name][fmu.name].items():
                    reset = 1 if cport.port.causality == "input" else 0
                    print(f"{cport.port.vr} {reset} {value}", file=txt_file)

            for type_name in type_names_list:
                print(f"# Outputs of {fmu.name} - {type_name}: <VR> <FMU_VR>", file=txt_file)
                print(len(outputs_fmu_per_type[type_name][fmu.name]), file=txt_file)
                for cport, vr in outputs_fmu_per_type[type_name][fmu.name].items():
                    print(f"{vr} {cport.port.vr}", file=txt_file)

    @staticmethod
    def long_path(path: Union[str, Path]) -> str:
        # https://stackoverflow.com/questions/14075465/copy-a-file-with-a-too-long-path-to-another-directory-in-python
        if os.name == 'nt':
            return "\\\\?\\" + os.path.abspath(str(path))
        else:
            return path

    @staticmethod
    def copyfile(origin, destination):
        logger.debug(f"Copying {origin} in {destination}")
        shutil.copy(origin, destination)

    def get_bindir_and_suffixe(self) -> (str, str, str):
        suffixes = {
            "Windows": "dll",
            "Linux": "so",
            "Darwin": "dylib"
        }

        origin_bindirs = {
            "Windows": "win64",
            "Linux": "linux64",
            "Darwin": "darwin64"
        }

        if self.fmi_version == 3:
            target_bindirs = {
                "Windows": "x86_64-windows",
                "Linux": "x86_64-linux",
                "Darwin": "aarch64-darwin"
            }
        else:
            target_bindirs = origin_bindirs

        os_name = platform.system()
        try:
            return origin_bindirs[os_name], suffixes[os_name], target_bindirs[os_name]
        except KeyError:
            raise FMUContainerError(f"OS '{os_name}' is not supported.")

    def make_fmu_skeleton(self, base_directory: Path) -> Path:
        logger.debug(f"Initialize directory '{base_directory}'")

        origin = Path(__file__).parent / "resources"
        resources_directory = base_directory / "resources"
        documentation_directory = base_directory / "documentation"
        binaries_directory = base_directory / "binaries"

        base_directory.mkdir(exist_ok=True)
        resources_directory.mkdir(exist_ok=True)
        binaries_directory.mkdir(exist_ok=True)
        documentation_directory.mkdir(exist_ok=True)

        if self.description_pathname:
            self.copyfile(self.description_pathname, documentation_directory)

        self.copyfile(origin / "model.png", base_directory)

        origin_bindir, suffixe, target_bindir = self.get_bindir_and_suffixe()

        library_filename = origin / origin_bindir / f"container.{suffixe}"
        if not library_filename.is_file():
            raise FMUContainerError(f"File {library_filename} not found")
        binary_directory = binaries_directory / target_bindir
        binary_directory.mkdir(exist_ok=True)
        self.copyfile(library_filename, binary_directory / f"{self.identifier}.{suffixe}")

        for i, fmu in enumerate(self.involved_fmu.values()):
            shutil.copytree(self.long_path(fmu.fmu.tmp_directory),
                            self.long_path(resources_directory / f"{i:02x}"), dirs_exist_ok=True)

        return resources_directory

    def make_fmu_package(self, base_directory: Path, fmu_filename: Path):
        logger.debug(f"Zipping directory '{base_directory}' => '{fmu_filename}'")
        zip_directory = self.long_path(str(base_directory.absolute()))
        offset = len(zip_directory) + 1
        with zipfile.ZipFile(self.fmu_directory / fmu_filename, "w", zipfile.ZIP_DEFLATED) as zip_file:
            def add_file(directory: Path):
                for entry in directory.iterdir():
                    if entry.is_dir():
                        add_file(directory / entry)
                    elif entry.is_file:
                        zip_file.write(str(entry), str(entry)[offset:])

            add_file(Path(zip_directory))
        logger.info(f"'{fmu_filename}' is available.")

    def make_fmu_cleanup(self, base_directory: Path):
        logger.debug(f"Delete directory '{base_directory}'")
        shutil.rmtree(self.long_path(base_directory))
