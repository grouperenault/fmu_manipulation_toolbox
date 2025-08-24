import argparse
import logging

from .utils import setup_logger, make_wide
from ..split import FMUSplitter, FMUSplitterError
from ..version import __version__ as version


def fmusplit():
    logger = setup_logger()

    logger.info(f"FMUSplit version {version}")
    parser = argparse.ArgumentParser(prog="fmusplit", description="Split FMU Container into FMU's",
                                     formatter_class=make_wide(argparse.ArgumentDefaultsHelpFormatter),
                                     add_help=False,
                                     epilog="see: https://github.com/grouperenault/fmu_manipulation_toolbox/blob/main/"
                                            "container/README.md")
    parser.add_argument('-h', '-help', action="help")

    parser.add_argument("-debug", action="store_true", dest="debug",
                        help="Add lot of useful log during the process.")

    parser.add_argument("-fmu", action="append", dest="fmu_filename_list", default=[],
                        metavar="filename.fmu", required=True,
                        help="Description of the FMU container to split.")

    config = parser.parse_args()

    if config.debug:
        logger.setLevel(logging.DEBUG)

    for fmu_filename in config.fmu_filename_list:
        try:
            splitter = FMUSplitter(fmu_filename)
            splitter.split_fmu()
        except FMUSplitterError as e:
            logger.fatal(f"{fmu_filename}: {e}")
            continue
        except FileNotFoundError as e:
            logger.fatal(f"Cannot read file: {e}")
            continue


if __name__ == "__main__":
    fmusplit()
