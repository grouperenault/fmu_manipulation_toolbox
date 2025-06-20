import argparse

from .utils import *
from ..fmu_operations import *
from ..checker import checker_list
from ..version import __version__ as version
from ..help import Help

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

if __name__ == "__main__":
    fmutool()
