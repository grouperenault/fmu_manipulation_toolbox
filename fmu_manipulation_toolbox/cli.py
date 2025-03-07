import argparse
import logging
import sys
from colorama import Fore, Style, init

from .fmu_operations import *
from .fmu_container import FMUContainerError
from .assembly import Assembly, AssemblyError
from .checker import checker_list
from .version import __version__ as version
from .help import Help


def setup_logger():
    class CustomFormatter(logging.Formatter):
        def format(self, record):
            log_format = "%(levelname)-8s | %(message)s"
            format_per_level = {
                logging.DEBUG: str(Fore.BLUE) + log_format,
                logging.INFO: str(Fore.CYAN) + log_format,
                logging.WARNING: str(Fore.YELLOW) + log_format,
                logging.ERROR: str(Fore.RED) + log_format,
                logging.CRITICAL: str(Fore.RED + Style.BRIGHT) + log_format,
            }
            formatter = logging.Formatter(format_per_level[record.levelno])
            return formatter.format(record)
    init()
    logger = logging.getLogger("fmu_manipulation_toolbox")
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(CustomFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    return logger


def make_wide(formatter, w=120, h=36):
    """Return a wider HelpFormatter, if possible."""
    try:
        # https://stackoverflow.com/a/5464440
        # beware: "Only the name of this class is considered a public API."
        kwargs = {'width': w, 'max_help_position': h}
        formatter(None, **kwargs)
        return lambda prog: formatter(prog, **kwargs)
    except TypeError:
        return formatter


def fmutool():
    print(f"FMU Manipulation Toolbox version {version}")
    help_message = Help()

    parser = argparse.ArgumentParser(prog='fmutool',
                                     description="Analyse and Manipulate a FMU by modifying its 'modelDescription.xml'",
                                     formatter_class=make_wide(argparse.HelpFormatter),
                                     add_help=False,
                                     epilog="see: https://github.com/grouperenault/fmu_manipulation_toolbox/blob/main/README.md")

    def add_option(option, *args, **kwargs):
        parser.add_argument(option, *args, help=help_message.usage(option), **kwargs)

    add_option('-h', '-help', action="help")

    # I/O
    add_option('-input', action='store', dest='fmu_input', default=None, required=True, metavar='path/to/module.fmu')
    add_option('-output', action='store', dest='fmu_output', default=None, metavar='path/to/module-modified.fmu')

    # Port name manipulation
    add_option('-remove-toplevel', action='append_const', dest='operations_list', const=OperationStripTopLevel())
    add_option('-merge-toplevel', action='append_const', dest='operations_list', const=OperationMergeTopLevel())
    add_option('-trim-until', action='append', dest='operations_list', type=OperationTrimUntil, metavar='prefix')
    add_option('-remove-regexp', action='append', dest='operations_list', type=OperationRemoveRegexp,
               metavar='regular-expression')
    add_option('-keep-only-regexp', action='append', dest='operations_list', type=OperationKeepOnlyRegexp,
               metavar='regular-expression')
    add_option('-remove-all', action='append_const', dest='operations_list', const=OperationRemoveRegexp('.*'))

    # Batch Rename
    add_option('-dump-csv', action='append', dest='operations_list', type=OperationSaveNamesToCSV,
               metavar='path/to/list.csv')
    add_option('-rename-from-csv', action='append', dest='operations_list', type=OperationRenameFromCSV,
               metavar='path/to/translation.csv')

    # Remoting
    add_option('-add-remoting-win32', action='append_const', dest='operations_list', const=OperationAddRemotingWin32())
    add_option('-add-remoting-win64', action='append_const', dest='operations_list', const=OperationAddRemotingWin64())
    add_option('-add-frontend-win32', action='append_const', dest='operations_list', const=OperationAddFrontendWin32())
    add_option('-add-frontend-win64', action='append_const', dest='operations_list', const=OperationAddFrontendWin64())

    # Extraction / Removal
    add_option('-extract-descriptor', action='store', dest='extract_description',
               metavar='path/to/saved-modelDescriptor.xml')
    add_option('-remove-sources', action='append_const', dest='operations_list',
               const=OperationRemoveSources())
    # Filter
    add_option('-only-parameters', action='append_const', dest='apply_on', const='parameter')
    add_option('-only-inputs', action='append_const', dest='apply_on', const='input')
    add_option('-only-outputs', action='append_const', dest='apply_on', const='output')
    # Checker
    add_option('-summary', action='append_const', dest='operations_list', const=OperationSummary())
    add_option('-check', action='append_const', dest='operations_list', const=[checker() for checker in checker_list])

    cli_options = parser.parse_args()
    # handle the "no operation" use case
    if not cli_options.operations_list:
        cli_options.operations_list = []

    if cli_options.fmu_input == cli_options.fmu_output:
        print(f"FATAL ERROR: '-input' and '-output' should point to different files.")
        sys.exit(-3)

    print(f"READING Input='{cli_options.fmu_input}'")
    try:
        fmu = FMU(cli_options.fmu_input)
    except FMUException as reason:
        print(f"FATAL ERROR: {reason}")
        sys.exit(-4)

    if cli_options.apply_on:
        print("Applying operation for :")
        for causality in cli_options.apply_on:
            print(f"     - causality = {causality}")

    def flatten(list_of_list: list):
        return [x for xs in list_of_list for x in xs]

    for operation in flatten(cli_options.operations_list):
        print(f"     => {operation}")
        try:
            fmu.apply_operation(operation, cli_options.apply_on)
        except OperationException as reason:
            print(f"ERROR: {reason}")
            sys.exit(-6)

    if cli_options.extract_description:
        print(f"WRITING ModelDescriptor='{cli_options.extract_description}'")
        fmu.save_descriptor(cli_options.extract_description)

    if cli_options.fmu_output:
        print(f"WRITING Output='{cli_options.fmu_output}'")
        try:
            fmu.repack(cli_options.fmu_output)
        except FMUException as reason:
            print(f"FATAL ERROR: {reason}")
            sys.exit(-5)
    else:
        print(f"INFO    Modified FMU is not saved. If necessary use '-output' option.")


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
