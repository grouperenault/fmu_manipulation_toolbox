"""
Build the skills of the Claude Code plugin as `.zip` files, to upload to claude.ai (Settings > Capabilities > Skills)
or to use with the Claude API.

    python tools/build_skill_zips.py                  # into dist/skills/
    python tools/build_skill_zips.py --output out/    # elsewhere

The plugin (`plugins/fmutool/`) is the only source of the skills. A skill of the plugin links to the shared
reference as `../../references/<file>`; a `.zip` holds one skill only, so the referenced files are copied into it,
under `references/`, and the links rewritten. Not shipped; checked by `tests/unit/test_agent_skills.py`.
"""

import argparse
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugins" / "fmutool"

#: Links of a skill to the shared references of the plugin.
SHARED_LINK = re.compile(r"\]\(\.\./\.\./references/([^)]+)\)")


def build(plugin: Path = PLUGIN, output: Path = ROOT / "dist" / "skills") -> list[Path]:
    """Write one `<skill>.zip` per skill of `plugin` into `output`; returns their paths."""
    output.mkdir(parents=True, exist_ok=True)
    archives = []
    for skill in sorted(path.parent for path in (plugin / "skills").glob("*/SKILL.md")):
        text = (skill / "SKILL.md").read_text(encoding="utf-8")
        shared = sorted(set(SHARED_LINK.findall(text)))
        archive = output / f"{skill.name}.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zip_file:
            zip_file.writestr(f"{skill.name}/SKILL.md", SHARED_LINK.sub(r"](references/\1)", text))
            for name in shared:
                zip_file.write(plugin / "references" / name, f"{skill.name}/references/{name}")
            for path in sorted(skill.rglob("*")):
                if path.is_file() and path.name != "SKILL.md":
                    zip_file.write(path, f"{skill.name}/{path.relative_to(skill).as_posix()}")
        archives.append(archive)
    return archives


def main():
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / "skills",
                        help="Directory of the .zip files (default: dist/skills).")
    options = parser.parse_args()
    for archive in build(output=options.output):
        print(archive)
    return 0


if __name__ == "__main__":
    sys.exit(main())
