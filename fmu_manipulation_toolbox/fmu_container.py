import logging
import os
import shutil
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import *

from .fmu_operations import FMU, OperationAbstract
from .version import __version__ as tool_version


logger = logging.getLogger("fmu_manipulation_toolbox")


class FMUPort:
    def __init__(self, attrs: Dict[str, str]):
        self.name = attrs["name"]
        self.vr = int(attrs["valueReference"])
        self.causality = attrs.get("causality", "local")
        self.attrs = attrs.copy()
        self.attrs.pop("name")
        self.attrs.pop("valueReference")
        if "causality" in self.attrs:
            self.attrs.pop("causality")
        self.type_name = None
        self.child = None

    def set_port_type(self, type_name: str, attrs: Dict[str, str]):
        self.type_name = type_name
        self.child = attrs.copy()
        for unsupported in ("unit", "declaredType"):
            if unsupported in self.child:
                self.child.pop(unsupported)

    def xml(self, vr: int, name=None, causality=None, start=None):

        if self.child is None:
            raise FMUContainerError(f"FMUPort has no child. Bug?")

        child_str = f"<{self.type_name}"
        if self.child:
            if start is not None and 'start' in self.child:
                self.child['start'] = start
            child_str += " " + " ".join([f'{key}="{value}"' for (key, value) in self.child.items()]) + "/>"
        else:
            child_str += "/>"

        if name is None:
            name = self.name
        if causality is None:
            causality = self.causality

        variability = "continuous" if self.type_name == "Real" else "discrete"

        scalar_attrs = {
            "name": name,
            "valueReference": vr,
            "causality": causality,
            "variability": variability,
        }
        scalar_attrs.update(self.attrs)

        scalar_attrs_str = " ".join([f'{key}="{value}"' for (key, value) in scalar_attrs.items()])

        return f'<ScalarVariable {scalar_attrs_str}>{child_str}</ScalarVariable>'


class EmbeddedFMU(OperationAbstract):
    capability_list = ("needsExecutionTool",
                       "canBeInstantiatedOnlyOncePerProcess")

    def __init__(self, filename):
        self.fmu = FMU(filename)
        self.name = Path(filename).name
        self.id = Path(filename).stem

        self.fmi_version = None
        self.step_size = None
        self.start_time = None
        self.stop_time = None
        self.model_identifier = None
        self.guid = None
        self.ports: Dict[str, FMUPort] = {}

        self.capabilities: Dict[str, str] = {}
        self.current_port = None  # used during apply_operation()

        self.fmu.apply_operation(self)  # Should be the last command in constructor!
        if self.model_identifier is None:
            raise FMUContainerError(f"FMU '{self.name}' does not implement Co-Simulation mode.")

    def fmi_attrs(self, attrs):
        self.guid = attrs['guid']
        self.fmi_version = attrs['fmiVersion']

    def scalar_attrs(self, attrs) -> int:
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
        return hash(f"{self.fmu.name}/{self.port.name}")

    def __eq__(self, other):
        return str(self) == str(other)


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


class FMUContainer:
    def __init__(self, identifier: str, fmu_directory: Union[str, Path], description_pathname=None):
        self.fmu_directory = Path(fmu_directory)
        self.identifier = identifier
        if not self.fmu_directory.is_dir():
            raise FMUContainerError(f"{self.fmu_directory} is not a valid directory")
        self.involved_fmu: Dict[str, EmbeddedFMU] = {}
        self.execution_order: List[EmbeddedFMU] = []

        self.description_pathname = description_pathname

        self.start_time = None
        self.stop_time = None

        # Rules
        self.inputs: Dict[str, ContainerPort] = {}
        self.outputs: Dict[str, ContainerPort] = {}
        self.locals: Dict[ContainerPort, Local] = {}

        self.rules: Dict[ContainerPort, str] = {}
        self.start_values: Dict[ContainerPort, str] = {}

    def get_fmu(self, fmu_filename: str) -> EmbeddedFMU:
        if fmu_filename in self.involved_fmu:
            return self.involved_fmu[fmu_filename]

        try:
            fmu = EmbeddedFMU(self.fmu_directory / fmu_filename)
            self.involved_fmu[fmu_filename] = fmu
            self.execution_order.append(fmu)
            if not fmu.fmi_version == "2.0":
                raise FMUContainerError("Only FMI-2.0 is supported by FMUContainer")
            logger.debug(f"Adding FMU #{len(self.execution_order)}: {fmu}")
        except Exception as e:
            raise FMUContainerError(f"Cannot load '{fmu_filename}': {e}")

        return fmu

    def mark_ruled(self, cport: ContainerPort, rule: str):
        if cport in self.rules:
            previous_rule = self.rules[cport]
            if rule not in ("OUTPUT", "LINK") and previous_rule not in ("OUTPUT", "LINK"):
                raise FMUContainerError(f"try to {rule} port {cport} which is already {previous_rule}")

        self.rules[cport] = rule

    def add_input(self, container_port_name: str, to_fmu_filename: str, to_port_name: str):
        if not container_port_name:
            container_port_name = to_port_name
        cport_to = ContainerPort(self.get_fmu(to_fmu_filename), to_port_name)
        if not cport_to.port.causality == "input":  # check causality
            raise FMUContainerError(f"Tried to use '{cport_to}' as INPUT of the container but FMU causality is "
                                    f"'{cport_to.port.causality}'.")

        logger.debug(f"INPUT: {to_fmu_filename}:{to_port_name}")
        self.mark_ruled(cport_to, 'INPUT')
        self.inputs[container_port_name] = cport_to

    def add_output(self, from_fmu_filename: str, from_port_name: str, container_port_name: str):
        if not container_port_name:  # empty is allowed
            container_port_name = from_port_name

        cport_from = ContainerPort(self.get_fmu(from_fmu_filename), from_port_name)
        if cport_from.port.causality not in ("output", "local"):  # check causality
            raise FMUContainerError(f"Tried to use '{cport_from}' as INPUT of the container but FMU causality is "
                                    f"'{cport_from.port.causality}'.")

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
            if cport.port.type_name == 'Real':
                value = float(value)
            elif cport.port.type_name == 'Integer':
                value = int(value)
            elif cport.port.type_name == 'Boolean':
                value = int(bool(value))
            else:
                value = value
        except ValueError:
            raise FMUContainerError(f"Start value is not conforming to '{cport.port.type_name}' format.")

        self.start_values[cport] = value

    def find_input(self, port_to_connect: FMUPort) -> Optional[ContainerPort]:
        for fmu in self.execution_order:
            for port in fmu.ports.values():
                if (port.causality == 'input' and port.name == port_to_connect.name
                        and port.type_name == port_to_connect.type_name):
                    return ContainerPort(fmu, port.name)
        return None

    def add_implicit_rule(self, auto_input=True, auto_output=True, auto_link=True, auto_parameter=False,
                          auto_local=False):
        # Auto Link outputs
        for fmu in self.execution_order:
            for port_name in fmu.ports:
                cport = ContainerPort(fmu, port_name)
                if cport not in self.rules:
                    if cport.port.causality == 'parameter' and auto_parameter:
                        parameter_name = cport.fmu.model_identifier+"."+cport.port.name
                        logger.info(f"AUTO PARAMETER: {cport} as {parameter_name}")
                        self.inputs[parameter_name] = cport
                        self.mark_ruled(cport, 'PARAMETER')
                    elif cport.port.causality == 'output':
                        candidate_cport = self.find_input(cport.port)
                        if auto_link and candidate_cport:
                            local = Local(cport)
                            local.add_target(candidate_cport)
                            logger.info(f"AUTO LINK: {cport} -> {candidate_cport}")
                            self.mark_ruled(cport, 'LINK')
                            self.mark_ruled(candidate_cport, 'LINK')
                            self.locals[cport] = local
                        elif auto_output:
                            self.mark_ruled(cport, 'OUTPUT')
                            self.outputs[port_name] = cport
                            logger.info(f"AUTO OUTPUT: Expose {cport}")
                    elif cport.port.causality == 'local':
                        local_portname = None
                        if port_name.startswith("container."):
                            local_portname = "container." + cport.fmu.id + "." + port_name[10:]
                            logger.info(f"PROFILING: Expose {cport}")
                        elif auto_local:
                            local_portname = cport.fmu.id + "." + port_name
                            logger.info(f"AUTO LOCAL: Expose {cport}")
                        if local_portname:
                            self.mark_ruled(cport, 'OUTPUT')
                            self.outputs[local_portname] = cport

        if auto_input:
            # Auto link inputs
            for fmu in self.execution_order:
                for port_name in fmu.ports:
                    cport = ContainerPort(fmu, port_name)
                    if cport not in self.rules:
                        if cport.port.causality == 'input':
                            self.mark_ruled(cport, 'INPUT')
                            self.inputs[port_name] = cport
                            logger.info(f"AUTO INPUT: Expose {cport}")

    def minimum_step_size(self) -> float:
        step_size = None
        for fmu in self.execution_order:
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
        for fmu in self.execution_order:
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
                 profiling=False):
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
            self.make_fmu_txt(txt_file, step_size, mt, profiling)

        self.make_fmu_package(base_directory, fmu_filename)
        if not debug:
            self.make_fmu_cleanup(base_directory)

    def make_fmu_xml(self, xml_file, step_size: float, profiling: bool):
        vr_table = ValueReferenceTable()

        timestamp = datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ')
        guid = str(uuid.uuid4())
        embedded_fmu = ", ".join([fmu_name for fmu_name in self.involved_fmu])
        try:
            author = os.getlogin()
        except OSError:
            author = "Unspecified"

        capabilities = {}
        for capability in EmbeddedFMU.capability_list:
            capabilities[capability] = "false"
            for fmu in self.involved_fmu.values():
                if fmu.capabilities[capability] == "true":
                    capabilities[capability] = "true"

        if self.start_time is None:
            self.start_time = self.execution_order[0].start_time
            logger.info(f"start_time={self.start_time} (deduced from '{self.execution_order[0].name}')")
        else:
            logger.info(f"start_time={self.start_time}")

        if self.stop_time is None:
            self.stop_time = self.execution_order[0].stop_time
            logger.info(f"stop_time={self.stop_time} (deduced from '{self.execution_order[0].name}')")
        else:
            logger.info(f"stop_time={self.stop_time}")

        xml_file.write(f"""<?xml version="1.0" encoding="ISO-8859-1"?>
<fmiModelDescription
  fmiVersion="2.0"
  modelName="{self.identifier}"
  generationTool="FMUContainer-{tool_version}"
  generationDateAndTime="{timestamp}"
  guid="{guid}"
  description="FMUContainer with {embedded_fmu}"
  author="{author}"
  license="Proprietary"
  copyright="See Embedded FMU's copyrights."
  variableNamingConvention="structured">

  <CoSimulation
    modelIdentifier="{self.identifier}"
    canHandleVariableCommunicationStepSize="true"
    canBeInstantiatedOnlyOncePerProcess="{capabilities['canBeInstantiatedOnlyOncePerProcess']}"
    canNotUseMemoryManagementFunctions="true"
    canGetAndSetFMUstate="false"
    canSerializeFMUstate="false"
    providesDirectionalDerivative="false"
    needsExecutionTool="{capabilities['needsExecutionTool']}">
  </CoSimulation>

  <LogCategories>
    <Category name="fmucontainer"/>
  </LogCategories>

  <DefaultExperiment stepSize="{step_size}" startTime="{self.start_time}" stopTime="{self.stop_time}"/>

  <ModelVariables>
""")
        if profiling:
            for fmu in self.execution_order:
                vr = vr_table.add_vr("Real")
                name = f"container.{fmu.id}.rt_ratio"
                print(f'<ScalarVariable valueReference="{vr}" name="{name}" causality="local">'
                      f'<Real /></ScalarVariable>', file=xml_file)

        # Local variable should be first to ensure to attribute them the lowest VR.
        for local in self.locals.values():
            vr = vr_table.get_vr(local.cport_from)
            print(f'    {local.cport_from.port.xml(vr, name=local.name, causality="local")}', file=xml_file)
            local.vr = vr

        for input_port_name, cport in self.inputs.items():
            vr = vr_table.get_vr(cport)
            start = self.start_values.get(cport, None)
            print(f"    {cport.port.xml(vr, name=input_port_name, start=start)}", file=xml_file)
            cport.vr = vr

        for output_port_name, cport in self.outputs.items():
            vr = vr_table.get_vr(cport)
            print(f"    {cport.port.xml(vr, name=output_port_name)}", file=xml_file)
            cport.vr = vr

        xml_file.write("""  </ModelVariables>

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

    def make_fmu_txt(self, txt_file, step_size: float, mt: bool, profiling: bool):
        if mt:
            print("# Use MT\n1", file=txt_file)
        else:
            print("# Don't use MT\n0", file=txt_file)

        if profiling:
            print("# Profiling ENABLED\n1", file=txt_file)
        else:
            print("# Profiling DISABLED\n0", file=txt_file)

        print(f"# Internal time step in seconds", file=txt_file)
        print(f"{step_size}", file=txt_file)
        print(f"# NB of embedded FMU's", file=txt_file)
        print(f"{len(self.involved_fmu)}", file=txt_file)
        fmu_rank: Dict[str, int] = {}
        for i, fmu in enumerate(self.execution_order):
            print(f"{fmu.name}", file=txt_file)
            print(f"{fmu.model_identifier}", file=txt_file)
            print(f"{fmu.guid}", file=txt_file)
            fmu_rank[fmu.name] = i

        # Prepare data structure
        type_names_list = ("Real", "Integer", "Boolean", "String")  # Ordered list
        inputs_per_type: Dict[str, List[ContainerPort]] = {}        # Container's INPUT
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

            for fmu in self.execution_order:
                inputs_fmu_per_type[type_name][fmu.name] = {}
                start_values_fmu_per_type[type_name][fmu.name] = {}
                outputs_fmu_per_type[type_name][fmu.name] = {}

        # Fill data structure
        # Inputs
        for input_port_name, cport in self.inputs.items():
            inputs_per_type[cport.port.type_name].append(cport)
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

        print(f"# NB local variables Real, Integer, Boolean, String", file=txt_file)
        for type_name in type_names_list:
            nb = len(locals_per_type[type_name])
            if profiling and type_name == "Real":
                nb += len(self.execution_order)
            print(f"{nb} ", file=txt_file, end='')
        print("", file=txt_file)

        print("# CONTAINER I/O: <VR> <FMU_INDEX> <FMU_VR>", file=txt_file)
        for type_name in type_names_list:
            print(f"# {type_name}", file=txt_file)
            nb = len(inputs_per_type[type_name])+len(outputs_per_type[type_name])+len(locals_per_type[type_name])
            if profiling and type_name == "Real":
                nb += len(self.execution_order)
                print(nb, file=txt_file)
                for profiling_port, _ in enumerate(self.execution_order):
                    print(f"{profiling_port} -2 {profiling_port}", file=txt_file)
            else:
                print(nb, file=txt_file)
            for cport in inputs_per_type[type_name]:
                print(f"{cport.vr} {fmu_rank[cport.fmu.name]} {cport.port.vr}", file=txt_file)
            for cport in outputs_per_type[type_name]:
                print(f"{cport.vr} {fmu_rank[cport.fmu.name]} {cport.port.vr}", file=txt_file)
            for local in locals_per_type[type_name]:
                print(f"{local.vr} -1 {local.vr}", file=txt_file)

        # LINKS
        for fmu in self.execution_order:
            for type_name in type_names_list:
                print(f"# Inputs of {fmu.name} - {type_name}: <VR> <FMU_VR>", file=txt_file)
                print(len(inputs_fmu_per_type[type_name][fmu.name]), file=txt_file)
                for cport, vr in inputs_fmu_per_type[type_name][fmu.name].items():
                    print(f"{vr} {cport.port.vr}", file=txt_file)

            for type_name in type_names_list:
                print(f"# Start values of {fmu.name} - {type_name}: <FMU_VR> <VALUE>", file=txt_file)
                print(len(start_values_fmu_per_type[type_name][fmu.name]), file=txt_file)
                for cport, value in start_values_fmu_per_type[type_name][fmu.name].items():
                    print(f"{cport.port.vr} {value}", file=txt_file)

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
            logger.debug(f"Copying {self.description_pathname}")
            shutil.copy(self.description_pathname, documentation_directory)

        shutil.copy(origin / "model.png", base_directory)
        for bitness in ('win32', 'win64'):
            library_filename = origin / bitness / "container.dll"
            if library_filename.is_file():
                binary_directory = binaries_directory / bitness
                binary_directory.mkdir(exist_ok=True)
                shutil.copy(library_filename, binary_directory / f"{self.identifier}.dll")

        for fmu in self.involved_fmu.values():
            shutil.copytree(self.long_path(fmu.fmu.tmp_directory),
                            self.long_path(resources_directory / fmu.name), dirs_exist_ok=True)
        return resources_directory

    def make_fmu_package(self, base_directory: Path, fmu_filename: Path):
        logger.debug(f"Zipping directory '{base_directory}' => '{fmu_filename}'")
        with zipfile.ZipFile(self.fmu_directory / fmu_filename, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for root, dirs, files in os.walk(base_directory):
                for file in files:
                    zip_file.write(self.long_path(os.path.join(root, file)),
                                   os.path.relpath(os.path.join(root, file), base_directory))
        logger.info(f"'{fmu_filename}' is available.")

    def make_fmu_cleanup(self, base_directory: Path):
        logger.debug(f"Delete directory '{base_directory}'")
        shutil.rmtree(self.long_path(base_directory))
