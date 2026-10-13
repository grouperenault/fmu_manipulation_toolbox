# How to Contribute

You're welcome to share your ideas or join us in contributing to the project.
By getting involved, you help enhance the project and make it accessible to a wider community.

## Reporting Issues

If you encounter a bug or unexpected behavior, please follow these steps:

1. Check the existing issues to see if the problem has already been reported.
2. If not, open a new issue and include:
    - A clear and concise description of the problem.
    - Steps to reproduce the issue, if applicable.
    - Details about your environment (e.g., operating system, Python version).
    - Any relevant error messages or logs.

## Suggestions for Improvements

We're always happy to hear new ideas for features or enhancements! If you'd like to suggest one:

1. Check whether someone has already proposed it.
2. If not, open a new issue describing the improvement and include:
    - A clear explanation of the feature and its use cases.
    - Why it would add value to the project.
    - Examples of how the feature could work, if applicable.

## Submitting Code

For legal reasons, we are unable to accept pull requests. If you have ideas for improvements,
please create an issue or get in touch with the development team.

## Running Tests

The test suite lives under `tests/` and uses [pytest](https://docs.pytest.org/). It is organised
by test type:

| Directory | Contents |
|-----------|----------|
| `tests/unit/` | fast, pure-Python tests (model description, operations, checkers, container internals, MCP server) — no FMI simulation |
| `tests/integration/` | container / split / CLI tests, invariants of the operations, file I/O, optional FMI simulation (`fmpy`) |
| `tests/gui/` | PySide6 GUI tests (require `pytest-qt`) |
| `tests/data/<area>/` | read-only reference data (FMUs, JSON, CSV, …) per functional area |
| `tests/_helpers/` | helpers shared by the tests (see below) |
| `tests/benchmarks/` | performance measurements, not collected by pytest (see below) |

### Install the test dependencies

The tests run against the installed package. From the repository root, install it in editable mode
(pip ≥ 21.3):

```bash
pip install -e ".[all]"       # full dev setup: GUI, MCP and test dependencies
# or, the test dependencies only:
pip install -e ".[test]"      # pytest, pytest-qt, pytest-cov, fmpy, numpy, PySide6
```

`pip install -r requirements.txt` is equivalent to the first command.

### Run the suite

Tests are run from the `tests/` directory (the `pytest.ini` there sets the import paths):

```bash
cd tests
pytest                        # run everything
pytest --cov=fmu_manipulation_toolbox        # with coverage
pytest -v integration/test_container.py      # a single module
```

### Selecting a subset with markers

Markers are declared in `tests/pytest.ini`. Select (or exclude) with `-m`:

```bash
pytest -m unit                # fast unit tests only
pytest -m "not gui"           # skip the GUI tests
pytest -m "integration and fmi3"
pytest -m lsbus               # LS-BUS tests
```

| Marker | Meaning |
|--------|---------|
| `unit` / `integration` / `gui` | test type |
| `slow` | end-to-end test running an FMI simulation |
| `needs_fmpy` | requires the `fmpy` package |
| `needs_container` / `needs_remoting` | requires the compiled container / remoting binaries |
| `windows_only` | only runs on win32 (auto-skipped elsewhere) |
| `fmi2` / `fmi3` | exercises a specific FMI version |
| `lsbus` | exercises the LS-BUS feature |
| `area(name)` | selects the `tests/data/<name>` directory copied into `tests/tmp/<test>` |

Platform- or binary-dependent tests are skipped automatically (with an explicit reason) when their
prerequisites are missing — they never fail silently.

### Adding a test

1. Put reference data under `tests/data/<area>/` (inputs and `REF-*` files only — never commit
   generated outputs). Every FMU of `tests/data/` is picked up automatically by
   `integration/test_operations_invariants.py`, which checks that each built-in operation keeps an
   XSD-valid descriptor valid and that read-only operations leave it unchanged.
2. Add the test to the matching module in `tests/unit/`, `tests/integration/` or `tests/gui/`.
3. Decorate it with the relevant markers, e.g. `@pytest.mark.area("<area>")`. The `area_dir`
   fixture copies that data directory into `tests/tmp/<test>/` and `chdir`s into it, so your test
   can refer to files by their bare names and write outputs without polluting the source tree.
   The `tests/tmp/` tree is wiped at the start of every session and kept afterwards, so the
   generated artefacts are easy to inspect when debugging a failure.
4. Reuse the shared helpers in `tests/_helpers/`:
    - `assertions.py`: file and XML comparisons (`assert_identical_files`, `assert_equivalent_xml`, …);
    - `simulation.py`: FMI simulation with `fmpy` and comparison with a reference. Simulate through
      `simulate()` rather than `fmpy.simulate_fmu()`: it always gives a logger to fmpy, whose default
      logger crashes the process after a simulation given a logger (fmpy 0.3.32);
    - `mcp_budget.py`: synthetic FMUs and assemblies of industrial size, and the context budget of the MCP
      server (`python tests/_helpers/mcp_budget.py` prints its measurements);
    - `assistant_bridge.py`: `FakeBridge`, an in-memory bridge to drive the MCP server without Qt.
5. Write the docstrings and comments of a test about the behaviour it checks and why it matters, not about
   the plan, the phase or the issue that introduced it: the history belongs to git.

### Benchmarks

`tests/benchmarks/bench_manipulation.py` measures the time and the peak memory of `FMU.apply_operation` on
large synthetic descriptors, to spot a performance regression. It is not part of the test suite; run it from
the repository root, it prints a Markdown table:

```bash
python tests/benchmarks/bench_manipulation.py [--variables 1000 10000 100000] [--repeat 3]
```

## Screenshots of the documentation

The screenshots of the graphical interfaces in the user guide are made by `tools/screenshots.py`, from the FMUs
of `tests/data`: after a change of an interface, make them again rather than by hand, so that they all look
alike. The windows are rendered without being shown, with the native style of the platform (the published ones
are made on macOS); PySide6 is needed, and the `mcp` extra for the *AI Assistant* entries of the Configuration
menu:

```bash
python tools/screenshots.py                 # every screenshot, written into docs/
python tools/screenshots.py --list          # their names and files
python tools/screenshots.py fmutool canvas-menu
```

## Packaging and releases

The package is described by `pyproject.toml` (built with setuptools); `MANIFEST.in` selects the content of the
source distribution.

### Version

The version comes from the git tags, through [setuptools-scm](https://setuptools-scm.readthedocs.io/): a
release tagged `V1.9.4.2` is published as `1.9.4.2`, and any other commit gets a development version such as
`1.9.4.3.dev79+g230faf6`. There is no version number to edit in the sources. A clone needs the tags
(`git fetch --tags`) to compute it; a shallow clone gives `0.1.dev1+g<commit>`.

Pre-releases use `rc` tags (`V2.0.0rc1`). Never use `dev` tags (`V0.0dev3`): setuptools-scm cannot compute the
version of the later commits from them, and every build fails.

### Building

```bash
pip install build
python -m build --sdist --wheel
```

Build both archives from the source tree: the wheel embeds the prebuilt native binaries of every platform
(`fmu_manipulation_toolbox/resources/<platform>/`, produced by the CI), which the sdist leaves out. A wheel built
from the sdist would have no binaries.

### Content check

`tools/dist_inventory.py` builds the archives and compares them with the reference of `tests/data/packaging/`
(data files and binaries of the wheel, metadata, entry points) and with rules computed from the files tracked by
git (Python modules of the wheel, content of the sdist). The CI runs it on every build.

```bash
pip install build
python tools/dist_inventory.py --check tests/data/packaging                          # needs the binaries
python tools/dist_inventory.py --check tests/data/packaging --placeholder-binaries   # without them
```

Add `--untracked` to take files not yet added to git into account. After a deliberate change (new data file,
dependency, entry point), review the difference and update the reference:

```bash
python tools/dist_inventory.py --write tests/data/packaging --placeholder-binaries
```
