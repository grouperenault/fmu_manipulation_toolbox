"""Inventory of the distributions (wheel and sdist) of fmu_manipulation_toolbox.

Safety net of the packaging migration (docs/local/packaging.md, phases 0 and 4).
Two kinds of checks:

- **Reference files** (`--write` / `--check DIR`), compared line by line, for what
  must only change on purpose: the wheel tag, the metadata (the version is
  excluded), the entry points, and every file of the wheel that is not a Python
  module tracked by git (data files, native binaries, `_version.py`, .dist-info).
- **Rules computed from the files tracked by git**, for what follows the code
  (no reference to update when a module or a test is added): the wheel contains
  exactly the Python modules of the package; the sdist contains the package and
  the C sources (container/, remoting/, fmi/), and neither the prebuilt binaries,
  nor tests/data, docs/ or .github/ (MANIFEST.in, decision D3).

By default the distributions are built in a temporary local clone of the
repository, onto which the working copy of the files tracked by git is copied,
so that untracked local files never leak into the inventory. A clone is needed
because setuptools-scm reads the version from the git tags and puts the files
tracked by git into the sdist. The native binaries are built by the CI and are
not tracked: `--placeholder-binaries` creates empty files with their expected
names, which is enough for an inventory of names. Both distributions are built
from the sources (`--sdist --wheel`): the sdist does not contain the prebuilt
binaries, so a wheel built from it would not either.

With `--dist DIR`, the distributions already built in DIR are inventoried
instead (the CI checks the very files it publishes).

Requires the `build` package (`pip install build`), except with `--dist`.

Usage, from the repository root:

    python tools/dist_inventory.py --placeholder-binaries --check tests/data/packaging
    python tools/dist_inventory.py --placeholder-binaries --write tests/data/packaging
    python tools/dist_inventory.py --dist dist --check tests/data/packaging

Add `--untracked` to check new files before adding them to git.
"""
import argparse
import difflib
import email.parser
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]

#: Native binaries shipped in the wheel: built by the CI, never tracked by git.
BINARIES = [
    "fmu_manipulation_toolbox/resources/win32/client_sm.dll",
    "fmu_manipulation_toolbox/resources/win32/server_sm.exe",
    "fmu_manipulation_toolbox/resources/win64/client_sm.dll",
    "fmu_manipulation_toolbox/resources/win64/server_sm.exe",
    "fmu_manipulation_toolbox/resources/win64/container.dll",
    "fmu_manipulation_toolbox/resources/linux64/client_sm.so",
    "fmu_manipulation_toolbox/resources/linux64/server_sm",
    "fmu_manipulation_toolbox/resources/linux64/container.so",
    "fmu_manipulation_toolbox/resources/linux32/client_sm.so",
    "fmu_manipulation_toolbox/resources/linux32/server_sm",
    "fmu_manipulation_toolbox/resources/darwin64/container.dylib",
]

#: Metadata fields that describe the package (the version is excluded: it changes with every tag).
METADATA_FIELDS = ["Metadata-Version", "Name", "Summary", "Home-page", "Author", "Author-email", "License",
                   "License-Expression", "License-File", "Keywords", "Project-URL", "Classifier",
                   "Requires-Python", "Requires-Dist", "Provides-Extra", "Description-Content-Type"]


def tracked_files(untracked: bool = False) -> list[str]:
    """Files tracked by git; with `untracked`, also the untracked files that are not ignored."""
    command = ["git", "ls-files", "-z"] + (["--cached", "--others", "--exclude-standard"] if untracked else [])
    output = subprocess.run(command, cwd=REPOSITORY, check=True, capture_output=True).stdout
    return [name for name in output.decode("utf-8").split("\0") if name]


def build(source: Path, outdir: Path):
    subprocess.run([sys.executable, "-m", "build", "--sdist", "--wheel", "--outdir", str(outdir), str(source)],
                   check=True, stdout=subprocess.DEVNULL)


def git(*args: str, cwd: Path):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


PACKAGE = "fmu_manipulation_toolbox/"
#: Sources of the native binaries: must be in the sdist.
C_SOURCES = ("container/", "remoting/", "fmi/")
#: Never in the sdist (MANIFEST.in): test data, documentation, CI, prebuilt binaries.
SDIST_EXCLUDED = ("tests/data/", "docs/", ".github/") + tuple(
    f"{PACKAGE}resources/{platform}/" for platform in ("win32", "win64", "linux32", "linux64", "darwin64"))


def package_modules(tracked: list[str]) -> list[str]:
    return sorted(name for name in tracked if name.startswith(PACKAGE) and name.endswith(".py"))


def wheel_inventory(wheel: Path, tracked: list[str]) -> tuple[dict[str, str], list[str]]:
    """Reference files of the wheel, and the list of its files."""
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        dist_info = next(name.split("/")[0] for name in names if name.split("/")[0].endswith(".dist-info"))
        metadata = email.parser.Parser().parsestr(archive.read(f"{dist_info}/METADATA").decode("utf-8"))
        entry_points = archive.read(f"{dist_info}/entry_points.txt").decode("utf-8")

    # The version is part of the .dist-info directory name: replace it.
    files = sorted(name.replace(dist_info, "<name>-<version>.dist-info", 1) for name in names)
    modules = set(package_modules(tracked))
    fields = []
    for field in METADATA_FIELDS:
        for value in metadata.get_all(field) or []:
            fields.append(f"{field}: {' '.join(value.split())}")
    references = {
        "wheel-data-files.txt": "\n".join(name for name in files if name not in modules),
        "wheel-tag.txt": "-".join(wheel.stem.split("-")[-3:]),  # e.g. py3-none-any
        "metadata.txt": "\n".join(fields),
        "entry-points.txt": entry_points.strip(),
    }
    return references, files


def sdist_files(sdist: Path) -> list[str]:
    with tarfile.open(sdist) as archive:
        names = [member.name for member in archive.getmembers() if member.isfile()]
    # Drop the top directory, which carries the version.
    return sorted(name.split("/", 1)[1] for name in names)


def rule_violations(wheel: list[str], sdist: list[str], tracked: list[str]) -> list[str]:
    """Rules computed from the files tracked by git (see the module docstring)."""
    violations = []
    modules = package_modules(tracked)
    wheel_modules = {name for name in wheel if name.startswith(PACKAGE) and name.endswith(".py")}
    wheel_modules.discard(f"{PACKAGE}_version.py")  # generated by setuptools-scm, listed in wheel-data-files.txt
    violations += [f"wheel: missing module {name}" for name in sorted(set(modules) - wheel_modules)]
    violations += [f"wheel: unexpected module {name}" for name in sorted(wheel_modules - set(modules))]

    expected = [name for name in tracked
                if name.startswith((PACKAGE,) + C_SOURCES) and not name.startswith(SDIST_EXCLUDED)]
    expected += ["pyproject.toml", "README.md", "LICENSE.txt"]
    violations += [f"sdist: missing {name}" for name in sorted(set(expected) - set(sdist))]
    violations += [f"sdist: must not contain {name}" for name in sdist if name.startswith(SDIST_EXCLUDED)]
    return violations


def inventory(placeholder_binaries: bool, untracked: bool = False,
              dist: Path | None = None) -> tuple[dict[str, str], list[str]]:
    """Reference files and rule violations of the distributions."""
    tracked = tracked_files(untracked)
    with tempfile.TemporaryDirectory() as tmp:
        if dist is None:
            source, dist = Path(tmp) / "source", Path(tmp) / "dist"
            # The clone brings the history and the tags; its index is independent from the one of the repository.
            git("clone", "--quiet", "--no-checkout", str(REPOSITORY), str(source), cwd=Path(tmp))
            for name in tracked:
                target = source / name
                target.parent.mkdir(parents=True, exist_ok=True)
                if (REPOSITORY / name).is_file():
                    shutil.copy2(REPOSITORY / name, target)
            git("add", "--all", cwd=source)
            # Added after `git add`: like in the CI, the binaries are present but not tracked.
            for name in BINARIES:
                target = source / name
                if (REPOSITORY / name).is_file() and not placeholder_binaries:
                    shutil.copy2(REPOSITORY / name, target)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.touch()
            build(source, dist)
        references, wheel = wheel_inventory(next(dist.glob("*.whl")), tracked)
        sdist = sdist_files(next(dist.glob("*.tar.gz")))
        return references, rule_violations(wheel, sdist, tracked)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--write", type=Path, metavar="DIR", help="write the reference files into DIR")
    action.add_argument("--check", type=Path, metavar="DIR", help="compare with the reference files of DIR")
    parser.add_argument("--dist", type=Path, metavar="DIR",
                        help="inventory the wheel and sdist already built in DIR instead of building them")
    parser.add_argument("--placeholder-binaries", action="store_true",
                        help="use empty files instead of the native binaries (local runs)")
    parser.add_argument("--untracked", action="store_true",
                        help="also copy the untracked files that are not ignored (to check changes before adding them)")
    args = parser.parse_args()

    references, violations = inventory(args.placeholder_binaries, args.untracked, args.dist)
    if violations:
        print("\n".join(violations))
    if args.write:
        args.write.mkdir(parents=True, exist_ok=True)
        for name, content in references.items():
            (args.write / name).write_text(content + "\n", encoding="utf-8")
        print(f"Reference files written to {args.write}.")
        return 1 if violations else 0

    differences = 0
    for name, content in references.items():
        reference = (args.check / name).read_text(encoding="utf-8").splitlines()
        diff = list(difflib.unified_diff(reference, content.splitlines(), f"reference/{name}", f"current/{name}",
                                         lineterm=""))
        if diff:
            differences += 1
            print("\n".join(diff))
    if differences:
        print(f"{differences} reference file(s) differ: update them on purpose with --write after review.")
    if violations:
        print(f"{len(violations)} rule violation(s).")
    if not differences and not violations:
        print("Inventory unchanged, rules satisfied.")
    return 1 if differences or violations else 0


if __name__ == "__main__":
    sys.exit(main())
