"""Test FMUs implementing FMI-LS-REF: the Reference-FMUs of `tests/data/compile`, compiled for the host platform.

`reference_fmu` keeps their own LS-REF files (a `result` file, output of their default experiment);
`ls_ref_fmu` replaces them with the experiments of `tests/data/ls-ref/<model>`, whose `resources/` directory goes to
the `resources/` of the FMU and the other files to `extra/org.fmi-standard.fmi-ls-ref/`.
"""
from pathlib import Path

from _helpers.archive import rewrite_fmu
from fmu_manipulation_toolbox.compiler import OperationCompileSources
from fmu_manipulation_toolbox.operations import FMU

DATA_DIR = Path(__file__).parent.parent / "data"
REF = "extra/org.fmi-standard.fmi-ls-ref"


def compiled_fmu(version: str, model: str, destination: Path, files: dict[str, Path | str] | None = None) -> Path:
    """`tests/data/compile/<version>/<model>.fmu` compiled for the host platform, saved as `destination`.

    With `files` (archive entry -> file to copy, or text), its `extra/` is replaced by these entries.
    """
    destination = Path(destination)
    replace = {entry: content.read_bytes() if isinstance(content, Path) else content.encode()
               for entry, content in (files or {}).items()}
    sources = rewrite_fmu(DATA_DIR / "compile" / version / f"{model}.fmu",
                          destination.with_name(f"{destination.stem}-sources.fmu"),
                          drop=("binaries/",) + (("extra/",) if files is not None else ()), replace=replace)
    with FMU(sources) as fmu:
        fmu.apply_operation(OperationCompileSources())
        fmu.repack(str(destination))
    return destination


def reference_fmu(version: str, model: str, destination: Path) -> Path:
    """A Reference-FMU with its own LS-REF files, compiled for the host platform."""
    return compiled_fmu(version, model, destination)


def ls_ref_files(model: str) -> dict[str, Path]:
    """Entries of the archive of the LS-REF files of `tests/data/ls-ref/<model>` (lower case)."""
    directory = DATA_DIR / "ls-ref" / model.lower()
    files = {}
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            relative = path.relative_to(directory).as_posix()
            files[relative if relative.startswith("resources/") else f"{REF}/{relative}"] = path
    if model == "BouncingBall":
        files[f"{REF}/REF-BouncingBall.csv"] = DATA_DIR / "compile" / "REF-BouncingBall.csv"
    return files


def ls_ref_fmu(version: str, model: str, destination: Path) -> Path:
    """A Reference-FMU with the experiments of `tests/data/ls-ref/<model>`, compiled for the host platform."""
    return compiled_fmu(version, model, destination, ls_ref_files(model))
