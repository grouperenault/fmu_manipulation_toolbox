import argparse
import csv
import logging
import sys

from pathlib import Path
from typing import *

from .utils import setup_logger, close_logger, make_wide
from ..version import __version__ as version

logger = setup_logger()

class DatalogConverter:
    def __init__(self, cvs_filename: Union[Path, str]):
        self.csv_filename = Path(cvs_filename)
        self.pcap_filename = self.csv_filename.with_suffix(".pcap")

    def open_pcap(self):
        logger.info(f"Creating PCAP file '{self.pcap_filename}'...")
        file = open(self.pcap_filename, "wb")
        file.write(int(0xA1B2C3D4).to_bytes(4, byteorder="big"))  # Magic number
                                                                  # meaning the timestamp are in min seconds and microseconds

        file.write(int(2).to_bytes(2, byteorder="big"))           # Major Version of fileformat
        file.write(int(4).to_bytes(2, byteorder="big"))           # Minor Version
        file.write(int(0).to_bytes(4, byteorder="big"))           # Reserved. SHOULD BE 0.
        file.write(int(0).to_bytes(4, byteorder="big"))           # Reserved. SHOULD BE 0.

        file.write(int(0xFFFF).to_bytes(4, byteorder="big"))      # snaplen indicating the maximum number of octets
                                                                  # captured from each packet.

        file.write(int(227).to_bytes(4, byteorder="big"))         # link type. his field is defined in the Section
                                                                  # # 8.1 IANA registry.
        return file

    def open_csv(self):
        logger.debug(f"Loading '{self.csv_filename}'")
        file = open(self.csv_filename, "rt")
        return file

    def decode_hexstring(self, hex_string: bytes, time_s, time_us):
        opcode = int.from_bytes(hex_string[0:4], byteorder="little")
        length = int.from_bytes(hex_string[4:8], byteorder="little")
        can_id = int.from_bytes(hex_string[8:12], byteorder="little")
        if opcode == 0x10:  # TRANSMIT
            rtr = int.from_bytes(hex_string[13:14], byteorder="little")
            ide = int.from_bytes(hex_string[12:13], byteorder="little")
            data_length = int.from_bytes(hex_string[14:16], byteorder="little")
            raw_data = hex_string[16:]

            logger.debug(f"{time_s} {time_us} OP=0x{opcode:04X} len={length} {data_length} id={can_id}"
                         f" ide={ide} rtr={rtr} len={data_length} {raw_data}")

            # TimeStamp
            self.pcapfile.write(time_s.to_bytes(4, byteorder="big"))
            self.pcapfile.write(time_us.to_bytes(4, byteorder="big"))

            # Packet length
            packet_length = data_length + 8
            self.pcapfile.write(packet_length.to_bytes(4, byteorder="big"))
            self.pcapfile.write(packet_length.to_bytes(4, byteorder="big"))

            # Control and flags
            control = (can_id & 0x1FFFFFFF) | ((rtr & 0b1) << 30) | ((ide & 0b1) << 31)
            self.pcapfile.write(control.to_bytes(4, byteorder="big"))

            # Frame Length
            self.pcapfile.write(data_length.to_bytes(1, byteorder="big"))

            # Reserved
            self.pcapfile.write(int(0).to_bytes(2, byteorder="big"))

            # DLC
            dlc = int(data_length)  # Classic CAN
            self.pcapfile.write(dlc.to_bytes(1, byteorder="big"))

            # PAYLOAD
            self.pcapfile.write(raw_data)

    def convert(self):
        with self.open_csv() as self.csvfile, self.open_pcap() as self.pcapfile:
            csv_reader = csv.DictReader(self.csvfile)

            column_names = [ name for name in csv_reader.fieldnames if "_Data" in name ]
            for row in csv_reader:
                time_s, time_us = divmod(float(row["time"]), 1)
                time_s = int(time_s)
                time_us = int(time_us * 1000000)

                for names in column_names:
                    datalog = row[names]
                    if datalog:
                        self.decode_hexstring(bytes.fromhex(datalog), time_s, time_us)


def datalog2pcap():
    logger.info(f"FMUContainer version {version}")
    logger.warning(f"Datalog2PCAP is still experimental.")

    parser = argparse.ArgumentParser(prog="datalog2pcap", description="Convert datalog from container to PCAP file.",
                                     formatter_class=make_wide(argparse.ArgumentDefaultsHelpFormatter),
                                     add_help=False,
                                     epilog="see: https://github.com/grouperenault/fmu_manipulation_toolbox/blob/main/"
                                            "doc/datalog.md")

    parser.add_argument('-h', '-help', action="help")

    parser.add_argument("-can", action="store", dest="can_filename", default=None,
                        metavar="can-datalog.csv", required=True,
                        help="Datalog with CAN data and clocks.")

    parser.add_argument("-debug", action="store_true", dest="debug",
                        help="Add lot of useful log during the process.")

    config = parser.parse_args(sys.argv[1:])

    if config.debug:
        logger.setLevel(logging.DEBUG)

    DatalogConverter(config.can_filename).convert()

    close_logger(logger)


if __name__ == "__main__":
    datalog2pcap()
