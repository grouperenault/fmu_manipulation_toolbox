"""Text files exchanged with the user or between platforms (CSV, JSON, container.txt).

Opening a text file without an explicit encoding uses the encoding of the
platform: UTF-8 on Linux and macOS, but cp1252 on most Windows installations.
A description file with a non-ASCII name (`débit`, `µ`...) written on one
platform was then misread on the other. These helpers make UTF-8 the rule:

- files are always written in UTF-8;
- files are read as UTF-8, with or without a byte order mark (Excel adds one
  when it saves a CSV as UTF-8);
- a file that is not valid UTF-8, typically written by a former version on
  Windows, is still read with the encoding of the platform, with a warning.
"""
import io
import locale
import logging
from pathlib import Path

logger = logging.getLogger("fmu_manipulation_toolbox")

ENCODING = "utf-8"

PathLike = str | Path


def read_text(path: PathLike) -> str:
    """Read a text file written in UTF-8 (BOM accepted), or in the platform encoding as a fallback."""
    raw = Path(path).read_bytes()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        fallback = locale.getpreferredencoding(False)
        logger.warning(f"'{path}' is not encoded in UTF-8: read as {fallback}. "
                       f"Save it in UTF-8 to share it between platforms.")
        return raw.decode(fallback, errors="replace")


def open_text(path: PathLike) -> io.StringIO:
    """`read_text` as a file object, suitable for `csv.reader` (line endings are kept as is)."""
    return io.StringIO(read_text(path), newline="")
