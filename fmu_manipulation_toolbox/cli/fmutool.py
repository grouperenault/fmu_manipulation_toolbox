import argparse
import logging
import os
import shlex
import sys

from .utils import setup_logger, close_logger, make_wide, ParagraphHelpFormatter, ExitCode, ErrorCounter
from ..operations import (OperationSummary, OperationError, OperationRemoveRegexp,
                          OperationRemoveSources, OperationTrimUntil, OperationKeepOnlyRegexp, OperationMergeTopLevel,
                          OperationStripTopLevel, OperationRenameFromCSV, OperationSaveNamesToCSV, FMU, FMUError)
from ..remoting import  (OperationAddFrontendWin32, OperationAddFrontendWin64, OperationAddRemotingWin32,
                         OperationAddRemotingWin64)
from ..checker import get_checkers
from ..compiler import OperationCompileSources
from ..version import __version__ as version
from ..help import Help


def fmutool():
    logger = setup_logger()

    logger.info(f"FMU Manipulation Toolbox version {version}")
    help_message = Help()

    parser = argparse.ArgumentParser(prog='fmutool',
                                     description="Analyse and Manipulate a FMU by modifying its 'modelDescription.xml'",
                                     formatter_class=make_wide(ParagraphHelpFormatter),
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
    # Compilation
    compile_operation = OperationCompileSources()
    add_option('-compile-sources', action='append_const', dest='operations_list', const=compile_operation)
    add_option('-compile-options', action='store', dest='compile_options', metavar='"options"')
    add_option('-link-options', action='store', dest='link_options', metavar='"options"')
    add_option('-link-libraries', action='store', dest='link_libraries', metavar='library1,library2')
    # Filter
    add_option('-only-parameters', action='append_const', dest='apply_on', const='parameter')
    add_option('-only-inputs', action='append_const', dest='apply_on', const='input')
    add_option('-only-outputs', action='append_const', dest='apply_on', const='output')
    add_option('-only-locals', action='append_const', dest='apply_on', const='local')
    # Checker
    add_option('-summary', action='append_const', dest='operations_list', const=OperationSummary())
    checkers = [checker() for checker in get_checkers()]
    add_option('-check', action='append_const', dest='operations_list', const=checkers)
    # Logging
    add_option('-debug', action='store_true', dest='debug')

    cli_options = parser.parse_args(sys.argv[1:])
    if cli_options.debug:
        logger.setLevel(logging.DEBUG)
    # handle the "no operation" use case
    if not cli_options.operations_list:
        cli_options.operations_list = []

    compile_parameters = {"-compile-options": cli_options.compile_options,
                          "-link-options": cli_options.link_options,
                          "-link-libraries": cli_options.link_libraries}
    given = [option for option, value in compile_parameters.items() if value is not None]
    if given and compile_operation not in cli_options.operations_list:
        logger.fatal(f"{', '.join(given)} need(s) '-compile-sources'.")
        close_logger(logger)
        sys.exit(ExitCode.USAGE_ERROR)
    posix = os.name != "nt"
    compile_operation.compiler_options = shlex.split(cli_options.compile_options or "", posix=posix)
    compile_operation.linker_options = shlex.split(cli_options.link_options or "", posix=posix)
    compile_operation.libraries = [name.strip() for name in (cli_options.link_libraries or "").split(",")
                                   if name.strip()]

    if cli_options.fmu_input == cli_options.fmu_output:
        logger.fatal(f"'-input' and '-output' should point to different files.")
        close_logger(logger)
        sys.exit(ExitCode.USAGE_ERROR)

    logger.info(f"READING Input='{cli_options.fmu_input}'")
    try:
        fmu = FMU(cli_options.fmu_input)
    except FMUError as reason:
        logger.fatal(f"{reason}")
        close_logger(logger)
        readable = os.path.isfile(cli_options.fmu_input) and os.access(cli_options.fmu_input, os.R_OK)
        sys.exit(ExitCode.INVALID_INPUT if readable else ExitCode.INPUT_UNREADABLE)

    if cli_options.apply_on:
        logger.info("Applying operation for :")
        for causality in cli_options.apply_on:
            logger.info(f"     - causality = {causality}")

    # Checker operations are added as a list into operations_list
    def operation_iterator():
        for op in cli_options.operations_list:
            if isinstance(op, list):
                for sub_op in op:
                    yield sub_op
            else:
                yield op

    # Errors logged by the checkers make `-check` fail, once everything else is done.
    check_errors = ErrorCounter()
    with fmu:
        for operation in operation_iterator():
            logger.info(f"     => {operation}")
            is_check = any(operation is checker for checker in checkers)
            if is_check:
                logger.addHandler(check_errors)
            try:
                fmu.apply_operation(operation, cli_options.apply_on)
            except OperationError as reason:
                logger.fatal(f"{reason}")
                close_logger(logger)
                sys.exit(ExitCode.OPERATION_FAILED)
            except FMUError as reason:  # unreadable modelDescription.xml
                logger.fatal(f"{reason}")
                close_logger(logger)
                sys.exit(ExitCode.INVALID_INPUT)
            finally:
                if is_check:
                    logger.removeHandler(check_errors)

        try:
            if cli_options.extract_description:
                logger.info(f"WRITING ModelDescriptor='{cli_options.extract_description}'")
                fmu.save_descriptor(cli_options.extract_description)

            if cli_options.fmu_output:
                logger.info(f"WRITING Output='{cli_options.fmu_output}'")
                fmu.repack(cli_options.fmu_output)
            else:
                logger.info(f"INFO    Modified FMU is not saved. If necessary use '-output' option.")
        except (FMUError, OSError) as reason:
            logger.fatal(f"FATAL ERROR: {reason}")
            close_logger(logger)
            sys.exit(ExitCode.OUTPUT_ERROR)

    if check_errors.count:
        logger.error(f"-check: {check_errors.count} error(s) found.")
        close_logger(logger)
        sys.exit(ExitCode.CHECK_FAILED)

    close_logger(logger)


if __name__ == "__main__":
    fmutool()
