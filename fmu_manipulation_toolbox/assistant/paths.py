"""Filesystem guard-rails for the assistant tools.

An MCP client is driven by a language model: it can get a path wrong, pick a
surprising extension, or silently clobber a file the user cares about. This
module centralises the checks applied before the assistant reads or writes
anything, so that no tool has to re-implement them.

Two rules are always enforced:

* **extension** — an assembly is read/written as ``.json``, a container is
  built as ``.fmu``; anything else is rejected rather than written anyway;
* **no silent overwrite** — an existing file is only replaced when the caller
  explicitly asks for it.

A third, optional rule restricts every access to a directory tree
(``FMUCONTAINER_MCP_ROOT``), which is useful when the server is exposed to an
agent that should not roam the whole filesystem.
"""

import os
from pathlib import Path
from typing import Optional, Sequence

#: Environment variable restricting the assistant to a directory tree.
ROOT_ENV_VAR = "FMUCONTAINER_MCP_ROOT"


class PathValidationError(ValueError):
    """Raised when a path is rejected by the :class:`PathPolicy`."""


class PathPolicy:
    """Validates the paths the assistant is asked to read from or write to.

    Args:
        root: Directory the assistant is confined to. When ``None`` (the
            default) any location is allowed, which matches the GUI use case
            where the user picks their own working directories.

    Raises:
        PathValidationError: If ``root`` is not an existing directory.
    """

    def __init__(self, root: Optional[Path] = None):
        if root is None:
            self.root = None
        else:
            root = Path(root).expanduser()
            if not root.is_dir():
                raise PathValidationError(f"Allowed root is not a directory: '{root}'")
            self.root = root.resolve()

    @classmethod
    def from_environment(cls) -> "PathPolicy":
        """Build a policy from ``FMUCONTAINER_MCP_ROOT``, if it is set."""
        root = os.environ.get(ROOT_ENV_VAR)
        return cls(Path(root) if root else None)

    # -- internals ---------------------------------------------------------

    def _resolve(self, path: str) -> Path:
        try:
            resolved = Path(path).expanduser().resolve()
        except (OSError, RuntimeError) as exc:  # e.g. symlink loop
            raise PathValidationError(f"Invalid path '{path}': {exc}") from exc

        if self.root is not None and not resolved.is_relative_to(self.root):
            raise PathValidationError(
                f"'{path}' is outside the allowed directory '{self.root}'. "
                f"Use a path inside it, or restart the assistant without "
                f"{ROOT_ENV_VAR} set."
            )
        return resolved

    @staticmethod
    def _check_suffix(resolved: Path, suffixes: Sequence[str], original: str):
        if resolved.suffix.lower() not in suffixes:
            expected = " or ".join(f"'{suffix}'" for suffix in suffixes)
            raise PathValidationError(
                f"'{original}' must end with {expected} (got '{resolved.suffix}')."
            )

    # -- public API --------------------------------------------------------

    def resolve_input(self, path: str, suffixes: Sequence[str] = (".fmu",)) -> Path:
        """Validate a file the assistant is about to read.

        Args:
            path: Path provided by the client.
            suffixes: Accepted lowercase extensions.

        Returns:
            Path: The resolved, existing file.

        Raises:
            PathValidationError: If the extension is wrong or the path escapes
                the allowed root.
            FileNotFoundError: If the file does not exist.
        """
        resolved = self._resolve(path)
        self._check_suffix(resolved, suffixes, path)
        if not resolved.exists():
            raise FileNotFoundError(f"File not found: '{path}'")
        if not resolved.is_file():
            raise PathValidationError(f"'{path}' is not a file.")
        return resolved

    def resolve_output(self, path: str, suffixes: Sequence[str],
                       overwrite: bool = False) -> Path:
        """Validate a file the assistant is about to write.

        Args:
            path: Path provided by the client.
            suffixes: Accepted lowercase extensions.
            overwrite: Whether replacing an existing file is allowed.

        Returns:
            Path: The resolved destination.

        Raises:
            PathValidationError: If the extension is wrong, the path escapes
                the allowed root, the parent directory is missing, the target
                is a directory, or it already exists and ``overwrite`` is
                ``False``.
        """
        resolved = self._resolve(path)
        self._check_suffix(resolved, suffixes, path)

        if resolved.is_dir():
            raise PathValidationError(f"'{path}' is a directory.")

        parent = resolved.parent
        if not parent.is_dir():
            raise PathValidationError(f"Directory does not exist: '{parent}'")

        if resolved.exists() and not overwrite:
            raise PathValidationError(
                f"'{path}' already exists. Confirm with the user, then call the "
                f"tool again with overwrite=True to replace it."
            )
        return resolved

