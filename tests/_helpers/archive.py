"""Helpers to derive test FMUs from a reference archive (drop or replace some of its entries)."""
import zipfile
from pathlib import Path


def rewrite_fmu(source: Path | str, destination: Path | str, drop: tuple[str, ...] = (),
                replace: dict[str, bytes] | None = None) -> Path:
    """Copy the FMU `source` to `destination`, without the entries whose name starts with one of `drop`.

    `replace` maps entry names to new contents (an entry that does not exist in `source` is added).
    """
    replace = dict(replace or {})
    destination = Path(destination)
    with zipfile.ZipFile(source) as zin, zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            if item.filename.startswith(drop):
                continue
            if item.filename in replace:
                zout.writestr(item.filename, replace.pop(item.filename))
            else:
                zout.writestr(item, zin.read(item.filename))
        for name, content in replace.items():
            zout.writestr(name, content)
    return destination


def read_entry(fmu: Path | str, name: str) -> bytes | None:
    """Content of the entry `name` of the FMU, or None when it does not exist."""
    with zipfile.ZipFile(fmu) as zin:
        try:
            return zin.read(name)
        except KeyError:
            return None
