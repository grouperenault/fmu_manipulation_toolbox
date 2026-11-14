"""
Check that a release tag can be published: run by `.github/workflows/release.yml` before publishing to PyPI.

    python tools/check_release_tag.py V2.1a1        # from a clone with the tags, the tag checked out

A tag is accepted when:

- without its `V` (or `v`) prefix, it is a PEP 440 version, written in its normalized form (`V2.1a1`, `V2.1.0rc1`,
  `V2.1`);
- it is not a development release, but `.dev0`: setuptools-scm cannot compute the version of the commits that follow
  a `.devN` tag (N > 0), and every later build fails (CONTRIBUTING.md, Version). Pre-releases are tagged `aN`, `bN`
  or `rcN`;
- setuptools-scm gives that version to the tagged commit, and can compute the version of a commit after it (checked
  on a throw-away commit, removed afterwards).

The first two checks need `packaging` only; the last one needs `setuptools-scm` and the git history (fetch-depth 0).
Not shipped; the first two checks are tested by `tests/unit/test_release_tag.py`.
"""

import argparse
import subprocess
import sys

from packaging.version import InvalidVersion, Version


class TagError(ValueError):
    """The tag cannot be published."""


def tag_version(tag: str) -> Version:
    """The version a tag publishes, once checked (prefix, PEP 440, normalized form, no `.devN` but `.dev0`)."""
    if tag[:1] not in ("V", "v"):
        raise TagError(f"'{tag}' does not start with 'V': release tags are 'V<version>', e.g. 'V2.1a1'.")
    text = tag[1:]
    try:
        version = Version(text)
    except InvalidVersion:
        raise TagError(f"'{text}' (tag '{tag}') is not a PEP 440 version.") from None
    if str(version) != text:
        raise TagError(f"'{tag}' is not written in its normalized form: tag 'V{version}' instead.")
    if version.local is not None:
        raise TagError(f"'{tag}' has a local part ('+{version.local}'): PyPI refuses it.")
    if version.dev is not None and version.dev != 0:
        raise TagError(f"'{tag}' is a development release '.dev{version.dev}': setuptools-scm cannot compute the "
                       f"version of the commits after it, and every later build would fail. Tag a pre-release "
                       f"instead: 'V{version.base_version}a1', 'b1' or 'rc1'.")
    return version


def check_scm(version: Version) -> None:
    """setuptools-scm gives `version` to the current commit, and can version a commit after it."""
    from setuptools_scm import get_version

    computed = get_version(local_scheme="no-local-version")
    if Version(computed) != version:
        raise TagError(f"setuptools-scm gives version '{computed}' to the tagged commit, not '{version}': is the tag "
                       f"checked out, with the whole history (fetch-depth: 0)?")
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    subprocess.run(["git", "-c", "user.name=check", "-c", "user.email=check@localhost", "commit", "--allow-empty",
                    "--quiet", "--no-verify", "-m", "check_release_tag: throw-away commit"], check=True)
    try:
        after = get_version(local_scheme="no-local-version")
    except Exception as error:  # noqa: BLE001 - setuptools-scm raises plain exceptions
        raise TagError(f"setuptools-scm cannot version the commits after this tag: {error}") from None
    finally:
        subprocess.run(["git", "reset", "--quiet", "--soft", head], check=True)
    if not Version(after) > version:
        raise TagError(f"the commits after this tag would get version '{after}', not above '{version}'.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Check that a release tag can be published.")
    parser.add_argument("tag", help="The tag, e.g. 'V2.1a1' (in GitHub Actions: $GITHUB_REF_NAME).")
    parser.add_argument("--no-scm", action="store_true", help="Check the name only, not setuptools-scm.")
    options = parser.parse_args(argv)
    try:
        version = tag_version(options.tag)
        if not options.no_scm:
            check_scm(version)
    except TagError as error:
        print(f"::error::Release tag refused: {error}")
        return 1
    print(f"Release tag '{options.tag}' publishes version {version}"
          f"{' (pre-release)' if version.is_prerelease else ''}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
