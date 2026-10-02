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
| `tests/unit/` | fast, pure-Python tests (operations, checker) — no FMI simulation |
| `tests/integration/` | container / split / CLI tests, file I/O, optional FMI simulation (`fmpy`) |
| `tests/gui/` | PySide6 GUI tests (require `pytest-qt`) |
| `tests/data/<area>/` | read-only reference data (FMUs, JSON, CSV, …) per functional area |

### Install the test dependencies

```bash
pip install -e ".[test]"      # pytest, pytest-qt, pytest-cov, fmpy, numpy, PySide6
# or, for a full dev setup:
pip install -r requirements.txt
```

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
   generated outputs).
2. Add the test to the matching module in `tests/unit/`, `tests/integration/` or `tests/gui/`.
3. Decorate it with the relevant markers, e.g. `@pytest.mark.area("<area>")`. The `area_dir`
   fixture copies that data directory into `tests/tmp/<test>/` and `chdir`s into it, so your test
   can refer to files by their bare names and write outputs without polluting the source tree.
   The `tests/tmp/` tree is wiped at the start of every session and kept afterwards, so the
   generated artefacts are easy to inspect when debugging a failure.
4. Reuse the shared helpers in `tests/_helpers/` (`assertions.py`, `simulation.py`).

