import logging
import shutil

from pathlib import Path
from .operations import OperationAbstract, OperationError

logger = logging.getLogger("fmu_manipulation_toolbox")

class OperationAddRemotingWinAbstract(OperationAbstract):
    bitness_from = None
    bitness_to = None

    def __repr__(self):
        return f"Add '{self.bitness_to}' remoting on '{self.bitness_from}' FMU"

    def __init__(self):
        self.vr = {
            "Real": [],
            "Integer": [],
            "Boolean": []
        }
        self.nb_input = 0;
        self.nb_output = 0;

    def fmi_attrs(self, attrs):
        if not attrs["fmiVersion"] == "2.0":
            raise OperationError(f"Adding remoting is only available for FMI-2.0")

    def cosimulation_attrs(self, attrs):
        fmu_bin = {
            "win32": Path(self.fmu.tmp_directory) / "binaries" / "win32",
            "win64": Path(self.fmu.tmp_directory) / "binaries" / "win64",
        }

        if not fmu_bin[self.bitness_from].is_dir():
            raise OperationError(f"{self.bitness_from} interface does not exist")

        if fmu_bin[self.bitness_to].is_dir():
            logger.info(f"{self.bitness_to} already exists. Add front-end.")
            shutil.move(fmu_bin[self.bitness_to] / Path(attrs['modelIdentifier']).with_suffix(".dll"),
                        fmu_bin[self.bitness_to] / Path(attrs['modelIdentifier']).with_suffix("-remoted.dll"))
        else:
            fmu_bin[self.bitness_to].mkdir()

        to_path = Path(__file__).parent / "resources" / self.bitness_to
        try:
            shutil.copyfile(to_path / "client_sm.dll",
                            fmu_bin[self.bitness_to] / Path(attrs['modelIdentifier']).with_suffix(".dll"))
        except FileNotFoundError as e:
            logger.critical(f"Cannot add remoting client: {e}")

        from_path = Path(__file__).parent / "resources" / self.bitness_from
        try:
            shutil.copyfile(from_path / "server_sm.exe",
                            fmu_bin[self.bitness_from] / "server_sm.exe")
        except FileNotFoundError as e:
            logger.critical(f"Cannot add remoting server: {e}")

        shutil.copyfile(Path(__file__).parent / "resources" / "license.txt",
                        fmu_bin[self.bitness_to] / "license.txt")

    def port_attrs(self, fmu_port) -> int:
        try:
            self.vr[fmu_port.fmi_type].append(fmu_port["valueReference"])
            if fmu_port["causality"] in ("input", "parameter"):
                self.nb_input += 1
            else:
                self.nb_output += 1
        except KeyError:
            logger.error(f"Type '{fmu_port.fmi_type}' is not supported by remoting.")

        return 0

    def closure(self):
        target_dir = Path(self.fmu.tmp_directory) / "resources"
        if not target_dir.is_dir():
            target_dir.mkdir()

        logger.info(f"Remoting nb input port: {self.nb_input}")
        logger.info(f"Remoting nb output port: {self.nb_output}")
        with open(target_dir/ "remoting_table.txt", "wt") as file:
            for fmi_type in ('Real', 'Integer', 'Boolean'):
                print(len(self.vr[fmi_type]), file=file)
            for fmi_type in ('Real', 'Integer', 'Boolean'):
                for vr in sorted(self.vr[fmi_type]):
                    print(vr, file=file)

class OperationAddRemotingWin64(OperationAddRemotingWinAbstract):
    bitness_from = "win32"
    bitness_to = "win64"


class OperationAddFrontendWin32(OperationAddRemotingWinAbstract):
    bitness_from = "win32"
    bitness_to = "win32"


class OperationAddFrontendWin64(OperationAddRemotingWinAbstract):
    bitness_from = "win64"
    bitness_to = "win64"


class OperationAddRemotingWin32(OperationAddRemotingWinAbstract):
    bitness_from = "win64"
    bitness_to = "win32"
