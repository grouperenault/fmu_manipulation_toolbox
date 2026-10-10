"""Inventory of the distributions (wheel and sdist) of fmu_manipulation_toolbox.

Safety net of the packaging migration (docs/local/packaging.md, phase 0): the
inventory records what the distributions contain (file names) and declare
(metadata, entry points), so that a change of build configuration can be
checked to produce the same package.

The distributions are built in a temporary local clone of the repository, onto
which the working copy of the files tracked by git is copied, so that untracked
local files never leak into the inventory. A clone is needed because
setuptools-scm reads the version from the git tags and puts the files tracked by
git into the sdist. The native binaries are built by the CI and are not tracked:
`--placeholder-binaries` creates empty files with their expected names, which is
enough for an inventory of names. In the CI, where the real binaries are
present, run without this option.

The sdist and the wheel are both built from the sources (`--sdist --wheel`):
the sdist does not contain the prebuilt binaries, so a wheel built from it
would not either.

Requires the `build` package (`pip install build`).

Usage, from the repository root:

    python tools/dist_inventory.py --placeholder-binaries --write tests/data/packaging
    python tools/dist_inventory.py --placeholder-binaries --check tests/data/packaging

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
from typing import Dict, List

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


def tracked_files(untracked: bool = False) -> List[str]:
    """Files tracked by git; with `untracked`, also the untracked files that are not ignored."""
    command = ["git", "ls-files", "-z"] + (["--cached", "--others", "--exclude-standard"] if untracked else [])
    output = subprocess.run(command, cwd=REPOSITORY, check=True, capture_output=True).stdout
    return [name for name in output.decode("utf-8").split("\0") if name]


def build(source: Path, outdir: Path):
    subprocess.run([sys.executable, "-m", "build", "--sdist", "--wheel", "--outdir", str(outdir), str(source)],
                   check=True, stdout=subprocess.DEVNULL)


def git(*args: str, cwd: Path):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def wheel_inventory(wheel: Path) -> Dict[str, str]:
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        dist_info = next(name.split("/")[0] for name in names if name.split("/")[0].endswith(".dist-info"))
        metadata = email.parser.Parser().parsestr(archive.read(f"{dist_info}/METADATA").decode("utf-8"))
        entry_points = archive.read(f"{dist_info}/entry_points.txt").decode("utf-8")

    # The version is part of the .dist-info directory name: replace it.
    files = sorted(name.replace(dist_info, "<name>-<version>.dist-info", 1) for name in names)
    fields = []
    for field in METADATA_FIELDS:
        for value in metadata.get_all(field) or []:
            fields.append(f"{field}: {' '.join(value.split())}")
    return {
        "wheel-files.txt": "\n".join(files),
        "wheel-tag.txt": "-".join(wheel.stem.split("-")[-3:]),  # e.g. py3-none-any
        "metadata.txt": "\n".join(fields),
        "entry-points.txt": entry_points.strip(),
    }


def sdist_inventory(sdist: Path) -> Dict[str, str]:
    with tarfile.open(sdist) as archive:
        names = [member.name for member in archive.getmembers() if member.isfile()]
    # Drop the top directory, which carries the version.
    return {"sdist-files.txt": "\n".join(sorted(name.split("/", 1)[1] for name in names))}


def inventory(placeholder_binaries: bool, untracked: bool = False) -> Dict[str, str]:
    with tempfile.TemporaryDirectory() as tmp:
        source, outdir = Path(tmp) / "source", Path(tmp) / "dist"
        # The clone brings the history and the tags; its index is independent from the one of the repository.
        git("clone", "--quiet", "--no-checkout", str(REPOSITORY), str(source), cwd=Path(tmp))
        for name in tracked_files(untracked):
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
        build(source, outdir)
        wheel = next(outdir.glob("*.whl"))
        sdist = next(outdir.glob("*.tar.gz"))
        return {**wheel_inventory(wheel), **sdist_inventory(sdist)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--write", type=Path, metavar="DIR", help="write the inventory into DIR")
    action.add_argument("--check", type=Path, metavar="DIR", help="compare with the inventory stored in DIR")
    parser.add_argument("--placeholder-binaries", action="store_true",
                        help="use empty files instead of the native binaries (local runs)")
    parser.add_argument("--untracked", action="store_true",
                        help="also copy the untracked files that are not ignored (to check changes before adding them)")
    args = parser.parse_args()

    current = inventory(args.placeholder_binaries, args.untracked)
    if args.write:
        args.write.mkdir(parents=True, exist_ok=True)
        for name, content in current.items():
            (args.write / name).write_text(content + "\n", encoding="utf-8")
        print(f"Inventory written to {args.write}")
        return 0

    differences = 0
    for name, content in current.items():
        reference = (args.check / name).read_text(encoding="utf-8").splitlines()
        diff = list(difflib.unified_diff(reference, content.splitlines(), f"reference/{name}", f"current/{name}",
                                         lineterm=""))
        if diff:
            differences += 1
            print("\n".join(diff))
    print("Inventory unchanged." if not differences else f"{differences} inventory file(s) differ.")
    return 1 if differences else 0


if __name__ == "__main__":
    sys.exit(main())
