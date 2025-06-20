import argparse

from pathlib import Path

from .utils import *
from ..assembly import Assembly, AssemblyError
from ..fmu_container import FMUContainerError
from ..version import __version__ as version


def fmucontainer():
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

    parser.add_argument("-dump-json",  action="store_true", dest="dump", default=False,
                        help="Dump a JSON file for each container.")

    config = parser.parse_args()

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
                                auto_local=config.auto_local, mt=config.mt,
                                profiling=config.profiling, fmu_directory=fmu_directory, debug=config.debug,
                                auto_parameter=config.auto_parameter)
        except FileNotFoundError as e:
            logger.fatal(f"Cannot read file: {e}")
            continue
        except (FMUContainerError, AssemblyError) as e:
            logger.fatal(f"{filename}: {e}")
            continue

        try:
            assembly.make_fmu(dump_json=config.dump)
        except FMUContainerError as e:
            logger.fatal(f"{filename}: {e}")
            continue

if __name__ == "__main__":
    fmucontainer()
