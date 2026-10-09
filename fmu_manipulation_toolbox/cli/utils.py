import logging
import sys
from enum import IntEnum
from colorama import Fore, Style, init


class ExitCode(IntEnum):
    """Exit status of the command line tools (`fmutool`, `fmucontainer`, `fmusplit`)."""
    SUCCESS = 0
    INTERNAL_ERROR = 1      # unexpected error: Python reports it with a traceback
    USAGE_ERROR = 2         # invalid command line (also used by argparse)
    INPUT_UNREADABLE = 3    # input file missing or unreadable
    INVALID_INPUT = 4       # not an FMU / a container, invalid assembly, unreadable descriptor
    OPERATION_FAILED = 5    # operation or build refused or failed
    OUTPUT_ERROR = 6        # output cannot be written
    CHECK_FAILED = 7        # `-check` found the FMU non-compliant


class ErrorCounter(logging.Handler):
    """Count the records of level ERROR or above, e.g. those logged by the checkers."""

    def __init__(self):
        super().__init__(level=logging.ERROR)
        self.count = 0

    def emit(self, record):
        self.count += 1


def setup_logger() -> logging.Logger:
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


def close_logger(logger: logging.Logger):
    for handler in logger.handlers:
        logger.removeHandler(handler)
        handler.close()
    logger.setLevel(logging.NOTSET)
    logger.propagate = True


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
