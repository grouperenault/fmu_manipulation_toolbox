import argparse
import logging
import sys

from typing import *
from pathlib import Path

from .utils import setup_logger, make_wide
from ..assembly import Assembly, AssemblyError
from ..container import FMUContainerError
from ..version import __version__ as version


def fmucontainer(command_options: Sequence[str]):
    logger = setup_logger()

    logger.info(f"FMUContainer version {version}")
    parser = argparse.ArgumentParser(prog="fmucontainer", description="Generate FMU from FMU's",
                                     formatter_class=make_wide(argparse.ArgumentDefaultsHelpFormatter),
                                     add_help=False,
                                     epilog="see: https://github.com/grouperenault/fmu_manipulation_toolbox/blob/main/"
                                            "container/README.md")

    parser.add_argument('-h', '-help', action="help")

    parser.add_argument("-fmu-directory", action="store", dest="fmu_directory", required=False, default=".",
                        help="Directory containing initial FMU’s and used to generate containers. "
                             "If not defined, current directory is used.")

    parser.add_argument("-fmi", action="store", dest="fmi_version", required=False, default="2",
                        help="Define version of FMI to be used for container interface."
                             "Only '2' or '3' is supported.")

    parser.add_argument("-container", action="append", dest="container_descriptions_list", default=[],
                        metavar="filename.{csv|json|ssp},[:step_size]", required=True,
                        help="Description of the container to create.")

    parser.add_argument("-debug", action="store_true", dest="debug",
                        help="Add lot of useful log during the process.")

    parser.add_argument("-no-auto-input", action="store_false", dest="auto_input", default=True,
                        help="Create ONLY explicit input.")

    parser.add_argument("-no-auto-output", action="store_false", dest="auto_output", default=True,
                        help="Create ONLY explicit output.")

    parser.add_argument("-auto-parameter", action="store_true", dest="auto_parameter", default=False,
                        help="Expose parameters of the embedded fmu's.")

    parser.add_argument("-auto-local", action="store_true", dest="auto_local", default=False,
                        help="Expose local variables of the embedded fmu's.")

    parser.add_argument("-no-auto-link", action="store_false", dest="auto_link", default=True,
                        help="Create ONLY explicit links.")

    parser.add_argument("-mt", action="store_true", dest="mt", default=False,
                        help="Enable Multi-Threaded mode for the generated container.")

    parser.add_argument("-profile", action="store_true", dest="profiling", default=False,
                        help="Enable Profiling mode for the generated container.")

    parser.add_argument("-sequential", action="store_true", dest="sequential", default=False,
                        help="Use sequential mode to schedule embedded fmu's.")

    parser.add_argument("-dump-json",  action="store_true", dest="dump", default=False,
                        help="Dump a JSON file for each container.")

    parser.add_argument("-vr", action="store_true", dest="ts_multiplier", default=False,
                        help="Add TS_MULTIPLIER input port to control step_size")

    config = parser.parse_args(command_options)

    if config.debug:
        logger.setLevel(logging.DEBUG)

    fmu_directory = Path(config.fmu_directory)
    logger.info(f"FMU directory: '{fmu_directory}'")

    for description in config.container_descriptions_list:
        try:
            tokens = description.split(":")
            filename = ":".join(tokens[:-1])
            step_size = float(tokens[-1])
        except ValueError:
            step_size = None
            filename = description

        try:
            assembly = Assembly(filename, step_size=step_size, auto_link=config.auto_link,
                                auto_input=config.auto_input, auto_output=config.auto_output,
                                auto_local=config.auto_local, mt=config.mt, sequential=config.sequential,
                                profiling=config.profiling, fmu_directory=fmu_directory, debug=config.debug,
                                auto_parameter=config.auto_parameter, ts_multiplier=config.ts_multiplier)
        except FileNotFoundError as e:
            logger.fatal(f"Cannot read file: {e}")
            sys.exit(-1)
        except (FMUContainerError, AssemblyError) as e:
            logger.fatal(f"{filename}: {e}")
            sys.exit(-2)

        try:
            assembly.make_fmu(dump_json=config.dump, fmi_version=int(config.fmi_version))
        except FMUContainerError as e:
            logger.fatal(f"{filename}: {e}")
            sys.exit(-3)

if __name__ == "__main__":
    fmucontainer(sys.argv[1:])
