# Robustness of the reading of `container.txt`

**Created**: 17 October 2026 — **Status**: decisions taken (17 October 2026), Step 1 to start — **Branch**:
`feature/init-propagation`, after Step 4 of `docs/local/init_propagation.md` — **Roadmap**: not listed

## Context

`container.txt` (`resources/container.txt` of a container FMU, specified in
`docs/developer/container-txt-format.md`) is written by the builder (`fmu_manipulation_toolbox/container/builder.py`,
`txt.py`), read by the C runtime (`container/container.c`, line reader in `container/config.c`) and read back by
`fmusplit` (`fmu_manipulation_toolbox/split.py`, versions 0 to 8).

A review of the format (17 October 2026) concluded that a complete restructuring (JSON, XML, tagged sections) is
not worth it: the file is a private contract between the builder and the runtime, always shipped together in the
same FMU; the runtime has no dependency; `fmusplit` must read the existing versions anyway. Two weaknesses of the
reading were found instead:

1. **The runtime does not check the version.** `get_line()` (`container/config.c`) skips every line starting with
   `#`, including the `# Version <N>` header. A `container.txt` that does not match its runtime (edited by hand,
   copied from another container, runtime replaced) is read with a shifted layout: the error, if any, is reported
   lines later and does not name the cause.
2. **The lines are limited to 4095 characters.** `config_file_t.line` is a fixed buffer of `CONFIG_FILE_SZ` (4096)
   bytes read by `fgets()`. A longer line is cut: its end is read as the next line, which shifts the rest of the
   file or silently truncates a value. The lines at risk:
   - start values of an array (`<FMU_VR> <DIM> <RESET> <VALUE> ...`, one line for all the values: about 200
     `real64` values);
   - a `string` start value (one value per line) longer than 4095 characters;
   - a container input with a large fan-out, a clocked group with many inputs, the importer clocks of an FMU.

## Decisions (2026-10-17)

1. **Version check: strict equality.** The runtime reads the `# Version <N>` header and refuses any version other
   than its own, and a missing header, with an error that names both versions. No compatibility with the older
   versions (unchanged: the runtime is always shipped with the `container.txt` of its builder).
2. **Long lines: dynamic buffer.** `get_line()` grows its buffer (`realloc`) until the end of the line. The format
   does not change: no new version.
3. **Version constants and a consistency test.** `CONTAINER_TXT_VERSION` on the Python side (used by the builder
   to write the header) and `#define CONTAINER_TXT_VERSION` on the C side (used by the runtime to check it); a test
   checks that they are equal.
4. **Branch**: `feature/init-propagation`, as additional steps after the propagation plan (format version 8,
   introduced by its Step 1).

## Steps

### Step 1 – Version constants and version check

- `fmu_manipulation_toolbox/container/types.py`: `CONTAINER_TXT_VERSION = 8`, next to `ALL_TYPES` (module shared
  by the writer and by `split.py`).
- `fmu_manipulation_toolbox/container/builder.py`: the header is written from `CONTAINER_TXT_VERSION` instead of
  the literal `# Version 8`.
- `container/container.h`: `#define CONTAINER_TXT_VERSION 8`.
- `container/config.c` / `config.h`: a function that reads the first line of the file **without** skipping the
  comments and parses `# Version %d` (the line is counted in `line_number`, so that the next errors keep their
  line numbers).
- `container/container.c`, `container_configure()`: the version is read and checked right after
  `config_file_open()`, before `read_flags()`. Errors (`LOGGER_ERROR`):
  - missing or unreadable header: `container.txt has no format version header: the container was built by an
    incompatible version of FMU Manipulation Toolbox.`;
  - other version: `container.txt format version <N>, this runtime reads version <M>: build the container again
    with the version of FMU Manipulation Toolbox that provides this runtime.`
- `split.py`: unchanged (it reads every version).
- Tests:
  - unit test: `CONTAINER_TXT_VERSION` of `types.py` equals the `#define` of `container/container.h` (parsed from
    the source tree);
  - integration tests (rebuilt runtime): a built container whose `container.txt` header is changed to
    `# Version 7`, then removed: the instantiation fails and the log contains the expected message; the unchanged
    container still instantiates.

Commit message: `Check the format version of container.txt in the runtime`

### Step 2 – Lines of any length

- `container/config.h`: `config_file_t.line` becomes a `char *` with its allocated size (`line_size`);
  `CONFIG_FILE_SZ` is kept for the path buffers that use it (`config_file_open()`, `container_configure()`,
  `read_conf_one_fmu()`), its use as line size is removed.
- `container/config.c`:
  - `config_file_open()`: initial allocation (4096 bytes); `config_file_close()` frees it;
  - `get_line()`: reads with `fgets()` at the end of the data already read, doubles the buffer with `realloc()`
    while the chunk read does not end with `\n` and the end of file is not reached (last line without `\n`
    accepted); the comment skip, the line counter and the removal of the `\n` are unchanged; an allocation failure
    is an error distinct from the end of file, reported as `Cannot allocate memory to read line #<n>.`.
- The readers of `container.c` use `file->line` and `file->line + offset` only: no change expected; to be checked
  (no `sizeof(file->line)`).
- Tests (rebuilt runtime):
  - `string` start value of 10,000 characters on `String_input` of `Feedthrough.fmu` (FMI 2.0,
    `tests/data/compile/2.0/`), `String_output` exposed: the output of the simulated container equals the start
    value;
  - the existing REF `container.txt` and results are unchanged (format unchanged).

Commit message: `Read the lines of container.txt whatever their length`

### Step 3 – Documentation

- `docs/developer/container-txt-format.md`:
  - *General Syntax Rules*: the first line `# Version <N>` is mandatory and checked by the runtime (strict
    equality with `CONTAINER_TXT_VERSION`, the two constants); no line length limit;
  - *Version Header*: the check and its error messages.
- `docs/help/troubleshooting.md`: entry *FMU Container fails to instantiate: format version of container.txt*
  (cause: `container.txt` and runtime from different versions; remedy: build the container again).
- `CHANGELOG.md`, section *FMU Container*:
  - 🟠 **FIXED** the runtime reads the lines of `container.txt` of any length: the start values of large arrays and
    the strings longer than 4095 characters were cut and shifted the reading of the file;
  - 🔵 **CHANGED** the runtime checks the format version of `container.txt` and refuses to instantiate a container
    whose `container.txt` does not come from the same version of the toolbox, with an explicit error.

Commit message: `Document the checks of the reading of container.txt`

## Out of scope

- Restructuring the format (see *Context*).
- `fmusplit` and the versions newer than the ones it knows (it reads them as the last known version today).
