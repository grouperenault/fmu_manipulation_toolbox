import argparse
import csv
import logging
import re
import struct
import sys
import zipfile
from pathlib import Path
from typing import IO

from ..model_description import ModelDescription, ModelDescriptionError
from ..version import __version__ as version
from .utils import close_logger, make_wide, setup_logger

logger = setup_logger()

class DatalogError(Exception):
    """The datalog or its container cannot be converted."""


class DatalogConverter:
    """Convert the LS-BUS operations of a container datalog to a PCAPNG file, for the Wireshark plugin of FMI-LS-BUS.

    Each operation is an exported PDU (link type 252): its PROTO_NAME selects the dissector of the plugin. The CSV does
    not tell the type of bus of its columns: it is read from the MIME type of the variables, in the container.
    """

    LINKTYPE_WIRESHARK_UPPER_PDU = 252
    EXP_PDU_TAG_END_OF_OPT = 0
    EXP_PDU_TAG_PROTO_NAME = 12
    OPERATION_HEADER_SIZE = 8
    #: Dissector of the plugin for each type of bus of the MIME types.
    PROTOCOLS = {
        "can": "fmi_ls_bus_can",
        "lin": "fmi_ls_bus_lin",
        "flexray": "fmi_ls_bus_flexray",
        "ethernet": "fmi_ls_bus_eth",
    }
    MIME_TYPE = re.compile(r"application/org\.fmi-standard\.fmi-ls-bus\.([\w-]+)\b.*", re.IGNORECASE)

    def __init__(self, csv_filename: Path | str, fmu_filename: Path | str):
        self.csv_filename = Path(csv_filename)
        self.fmu_filename = Path(fmu_filename)
        self.pcap_filename = self.csv_filename.with_suffix(".pcapng")
        self.nb_operations = 0

    def read_bus_types(self) -> dict[str, str]:
        """Type of bus of each LS-BUS binary of the container, by name of column of the datalog."""
        bus_types = {}
        try:
            with zipfile.ZipFile(self.fmu_filename) as container:
                lines = container.read("resources/container.txt").decode("utf-8").splitlines()
                position = lines.index("# NB of embedded FMU's") + 1
                nb_fmu = sum(int(token) for token in lines[position].split())
                for index in range(nb_fmu):
                    fmu_name = lines[position + 1 + 3 * index].split()[0]
                    descriptor = container.read(f"resources/{index:02x}/modelDescription.xml")
                    for port in ModelDescription.load(descriptor).iter_ports():
                        match = self.MIME_TYPE.fullmatch(port.get("mimeType", ""))
                        if match:
                            bus_types[f"{Path(fmu_name).stem.lower()}.{port.get('name')}"] = match.group(1).lower()
        except (OSError, KeyError, ValueError, IndexError, zipfile.BadZipFile, ModelDescriptionError) as error:
            raise DatalogError(f"Cannot read the container '{self.fmu_filename}': {error}") from error
        return bus_types

    @staticmethod
    def write_block(file: IO[bytes], block_type: int, body: bytes):
        padding = -len(body) % 4
        total_length = len(body) + padding + 12
        file.write(struct.pack("<II", block_type, total_length) + body + bytes(padding) +
                   struct.pack("<I", total_length))

    def open_pcap(self):
        logger.info(f"Creating PCAPNG file '{self.pcap_filename}'...")
        file = open(self.pcap_filename, "wb")
        # Section Header Block: byte-order magic, version 1.0, section length not specified
        self.write_block(file, 0x0A0D0D0A, struct.pack("<IHHq", 0x1A2B3C4D, 1, 0, -1))
        # Interface Description Block: link type, reserved, no snapshot length. The time resolution is the microsecond.
        self.write_block(file, 1, struct.pack("<HHI", self.LINKTYPE_WIRESHARK_UPPER_PDU, 0, 0))
        return file

    def open_csv(self):
        logger.debug(f"Loading '{self.csv_filename}'")
        return open(self.csv_filename)

    def exported_pdu_header(self, bus_type: str) -> bytes:
        protocol = self.PROTOCOLS[bus_type].encode()
        protocol += bytes(-len(protocol) % 4)
        return (struct.pack(">HH", self.EXP_PDU_TAG_PROTO_NAME, len(protocol)) + protocol +
                struct.pack(">HH", self.EXP_PDU_TAG_END_OF_OPT, 0))

    def write_operations(self, data: bytes, bus_type: str, timestamp: int, column: str):
        """A binary may hold several operations: each of them is one packet."""
        offset = 0
        while offset < len(data):
            if len(data) - offset < self.OPERATION_HEADER_SIZE:
                logger.warning(f"{column}: {len(data) - offset} byte(s) left, not enough for an operation.")
                return
            opcode, length = struct.unpack_from("<II", data, offset)
            if length < self.OPERATION_HEADER_SIZE or offset + length > len(data):
                logger.warning(f"{column}: operation 0x{opcode:04X} has an invalid length {length}.")
                return

            logger.debug(f"time={timestamp / 1e6} {column} {bus_type} operation 0x{opcode:04X} length={length}")
            packet = self.exported_pdu_header(bus_type) + data[offset:offset + length]
            self.write_block(self.pcapfile, 6, struct.pack("<IIIII", 0, timestamp >> 32, timestamp & 0xFFFFFFFF,
                                                           len(packet), len(packet)) + packet)
            self.nb_operations += 1
            offset += length

    def convert(self):
        bus_types = self.read_bus_types()
        with self.open_csv() as self.csvfile, self.open_pcap() as self.pcapfile:
            # The datalog follows the locale of the importer: its first column is "time", then comes the separator.
            delimiter = self.csvfile.readline()[len("time"):][:1] or ","
            self.csvfile.seek(0)
            csv_reader = csv.DictReader(self.csvfile, delimiter=delimiter)

            data_column_names = [name for name in csv_reader.fieldnames if name in bus_types]
            if not data_column_names:
                raise DatalogError(f"No column of '{self.csv_filename}' is an LS-BUS binary of '{self.fmu_filename}'.")
            unknown = [bus_types[name] for name in data_column_names if bus_types[name] not in self.PROTOCOLS]
            if unknown:
                raise DatalogError(f"Unknown type of bus: {', '.join(sorted(set(unknown)))}.")

            clock_column_names = {}
            for column_name in data_column_names:
                splitted_name = column_name.split(".")
                splitted_name[-1] = splitted_name[-1].replace("_Data", "_Clock")
                clock_column_name = ".".join(splitted_name)

                if clock_column_name in csv_reader.fieldnames:
                    logger.debug(f"{column_name} is clocked by {clock_column_name}")
                    clock_column_names[column_name] = clock_column_name

            for row in csv_reader:
                timestamp = round(float(row["time"].replace(",", ".")) * 1e6)

                for names in data_column_names:
                    hex_data = row[names]
                    if hex_data:
                        try:
                            clock = row[clock_column_names[names]] == "1"
                        except KeyError:
                            clock = True
                        if clock:
                            self.write_operations(bytes.fromhex(hex_data), bus_types[names], timestamp, names)

        logger.info(f"{self.nb_operations} operation(s) written to '{self.pcap_filename}'.")


def datalog2pcap():
    logger.info(f"FMUContainer version {version}")
    logger.warning("Datalog2PCAP is still experimental.")

    parser = argparse.ArgumentParser(prog="datalog2pcap",
                                     description="Convert the LS-BUS datalog of a container to a PCAPNG file.",
                                     formatter_class=make_wide(argparse.ArgumentDefaultsHelpFormatter),
                                     add_help=False,
                                     epilog="see: https://github.com/grouperenault/fmu_manipulation_toolbox/blob/main/"
                                            "doc/datalog.md")

    parser.add_argument('-h', '-help', action="help")

    parser.add_argument("csv_filename", metavar="datalog.csv", help="Datalog with LS-BUS data and clocks.")

    parser.add_argument("-fmu", action="store", dest="fmu_filename", metavar="container.fmu", required=True,
                        help="Container that produced the datalog: it gives the type of bus of each column.")

    parser.add_argument("-debug", action="store_true", dest="debug",
                        help="Add lot of useful log during the process.")

    config = parser.parse_args(sys.argv[1:])

    if config.debug:
        logger.setLevel(logging.DEBUG)

    try:
        DatalogConverter(config.csv_filename, config.fmu_filename).convert()
    except DatalogError as error:
        logger.critical(f"{error}")
        close_logger(logger)
        sys.exit(1)

    close_logger(logger)


if __name__ == "__main__":
    datalog2pcap()
