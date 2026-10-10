# Plan: removal of `FMUPort`

**Created**: 10 October 2026 — **Updated**: 10 October 2026 (decisions taken; phase 1 done) — **Status**: in progress — **Roadmap**: 2.0 ("suppress FMUPort (API break)") —
**Origin**: note "Removal of `FMUPort`" of `done/refactoring.md`

`FMUPort` is the object given to `OperationAbstract.port_attrs()`, the callback of every operation and checker,
built-in or written by users. Since the ElementTree migration (`done/refactoring.md`, phase 2), it is a subclass of
`ModelVariable` (`model_description.py`), the view on one variable of the descriptor tree, and only adds a
deprecated *detached* mode. The goal is to keep a single type, `ModelVariable`.

---

## 1. Current state

### What `FMUPort` adds to `ModelVariable`

| Member | Behaviour |
|---|---|
| `FMUPort()` without element | builds a *detached* port, not attached to a descriptor (`DeprecationWarning`) |
| `push_attrs(attrs)` | adds an attribute level to a detached port (`DeprecationWarning`; `FMUError` on an attached port) |
| `detached` | `True` for a detached port |
| `fmi_type`, `attrs_list`, `dimensions` | read the detached data when detached, otherwise those of `ModelVariable` |
| `dimensions` setter | adds a `<Dimension>` element, or a detached dimension (`DeprecationWarning`) |
| `__repr__` | `<FMUPort Float64 'x'>` instead of `<ModelVariable Float64 'x'>` |

Everything else (`[]`, `get()`, `in`, `fmi_type`, `attrs_list`, `dimensions`, `element`, `fmi_version`) is
`ModelVariable`. `ModelVariable.__setitem__` refuses to create an attribute (`KeyError`), as `FMUPort` does.

**The deprecation of the detached mode was never released**: it is listed in the `Upstream` section of
`CHANGELOG.md` (ElementTree migration), so 2.0 is the first release to show it.

### Uses

| Where | Use |
|---|---|
| `operations.py` | the class; `Manipulation.handle_ports` builds one `FMUPort(element, fmi_version)` per variable; `OperationAbstract.port_attrs(fmu_port: FMUPort)` and one built-in operation annotate it |
| `assistant/headless.py`, `gui/fmucontainer/graph/node.py`, `gui/fmueditor/__main__.py` | import and annotations only (`fmueditor` also writes `fmu_port.attrs_list[0][key]` to create an attribute: available on `ModelVariable`) |
| `container/embedded.py` | none since the container refactoring (`isinstance(attrs, ModelVariable)`) |
| `model_description.py` | docstrings describing `ModelVariable` as "compatible with `FMUPort`" |
| Tests | `test_model_description.py` (compatibility of the two types), `test_operations_errors.py` (detached mode, `push_attrs` on an attached port, `_make_port` helper), `test_container_xml.py` (`attrs_list`) |
| User documentation | `docs/user-guide/fmutool/python-api.md` (custom operations, the `fmu_port` argument), `docs/user-guide/fmutool/checker.md` (custom checker); API reference of `operations` |
| **User code** | every custom operation or checker (including those registered through the `fmu_manipulation_toolbox.checkers` entry points) imports `FMUPort` for its annotations: `from fmu_manipulation_toolbox.operations import OperationAbstract, FMUPort` |

---

## 2. Goals

1. One type for the variables given to operations: `ModelVariable`, documented as such.
2. No detached port: a variable is always a view on a descriptor.
3. User code still importing `FMUPort` fails with a clear message (migration: one line), and never crashes
   `fmutool` when it is a third-party checker.
4. No change of behaviour for the operations: same attributes, same writes into the tree.

---

## 3. Decisions

Decided on 10 October 2026: **D1 (b)**, `FMUPort` is removed in 2.0, without alias. The detached mode goes with the
class (**D2 (a)** by consequence), **D3 (a)**, and D4 is without object.


| # | Question | Options | Recommendation |
|---|---|---|---|
| D1 | The name `FMUPort` | (a) deprecated alias of `ModelVariable` in 2.0 (module `__getattr__`, warning at import), removed in 3.0; (b) removed in 2.0 | **(a)**: every custom operation or checker imports it, often only for an annotation; an alias costs a few lines and `isinstance(port, FMUPort)` keeps working |
| D2 | The detached mode (`FMUPort()`, `push_attrs()`, `detached`, `dimensions` setter) | (a) removed in 2.0; (b) kept deprecated through 2.x | **(a)**: 2.0 is a major version; the only use is building a port by hand to call `port_attrs` outside an FMU (our tests); *implied by D1 (b): the detached mode goes with the class* |
| D3 | Where users import `ModelVariable` | (a) documented from `model_description`, also importable from `operations` (already imported there), without warning; (b) `model_description` only | **(a)**: custom operations keep a single import line (`from fmu_manipulation_toolbox.operations import OperationAbstract, ModelVariable`) |
| D4 | Warning category of the alias | (a) `DeprecationWarning`; (b) `FutureWarning` | *Without object since D1 (b)* |

---

## 4. Plan

### Phase 1 — `ModelVariable` inside the package (no visible change)

1. Annotations and docstrings: `OperationAbstract.port_attrs` and the built-in operations (`operations.py`),
   `assistant/headless.py`, `gui/fmucontainer/graph/node.py`, `gui/fmueditor/__main__.py`.
2. `model_description.py`: describe `ModelVariable` for itself (the view given to `port_attrs`), not by comparison
   with `FMUPort`; `iter_ports()` docstring.
3. `handle_ports` still builds `FMUPort` (subclass), so that phase 1 alone changes nothing.

*Exit criterion*: `FMUPort` only appears in its class, in `handle_ports` and in the tests of the compatibility;
suite green.

**Status on 10 October 2026: done.**

| Item | File |
|---|---|
| `OperationAbstract.port_attrs(fmu_port: ModelVariable)`, docstring pointing to `ModelVariable`; `OperationSaveNamesToCSV.port_attrs` annotation | `operations.py` |
| `ModelVariable` imported from `operations` (D3) instead of `FMUPort`, annotations of the `port_attrs` callbacks | `assistant/headless.py`, `gui/fmucontainer/graph/node.py`, `gui/fmueditor/__main__.py` |
| `ModelVariable` described for itself (object given to `port_attrs`, levels of attributes, start values of `String`/`Binary`), no comparison with `FMUPort` left; `_StartValue`, `dimensions`, `__setitem__` and `iter_ports()` docstrings | `model_description.py` |

`FMUPort` now only appears in its class and in `Manipulation.handle_ports` (`operations.py`), and in the tests of
the compatibility and of the detached mode (`test_model_description.py`, `test_operations_errors.py`), handled in
phase 2.

Checks performed: full suite **2003 passed, 2 skipped** (clean Python 3.14 environment, GUI tests included);
ruff `F` on the changed files: only `F541` already present; `mkdocs build`: no warning.

### Phase 2 — Removal (D1, D2, D3)

1. Remove the class and the detached mode; `handle_ports` builds `ModelVariable`; `ModelVariable` stays importable
   from `operations` (D3).
2. **Third-party checkers** still importing `FMUPort` must not crash `fmutool`: today `get_checkers()` loads the
   `fmu_manipulation_toolbox.checkers` entry points without protection, and `add_from_file()` only catches
   `ModuleNotFoundError`, not `ImportError`. Both report the checker that cannot be loaded (`logger.error`, with
   the hint "`FMUPort` was removed in 2.0: use `ModelVariable`" when the error names it) and go on with the other
   checkers.
3. Tests:
   - replace the detached-mode tests of `test_operations_errors.py` (the `_make_port` helper builds a
     `ModelVariable`);
   - `from fmu_manipulation_toolbox.operations import FMUPort` raises `ImportError`;
   - a custom checker importing `FMUPort`, loaded by `add_from_file()` and through a (monkeypatched) entry point:
     error logged with the hint, the built-in checkers still run;
   - `test_model_description.py`: the compatibility tests become plain `ModelVariable` tests.

*Exit criterion*: no `FMUPort` left in the package; the characterization references of the operations
(`tests/data/refactoring/`) unchanged; suite green.

### Phase 3 — User documentation

- `docs/user-guide/fmutool/python-api.md`: custom operations with `ModelVariable`; the `fmu_port` argument
  described as a `ModelVariable` (link to the API reference of `model_description`); migration note from 1.x
  (replace the import and the annotations of `FMUPort` by `ModelVariable`).
- `docs/user-guide/fmutool/checker.md`: example checker with `ModelVariable`.
- `CHANGELOG.md`: `CHANGED` (**breaking**): `FMUPort` removed, replaced by `ModelVariable` (same interface, import
  from `fmu_manipulation_toolbox.model_description` or `operations`), detached ports removed (`FMUPort()`,
  `push_attrs()`, `detached`, `dimensions` setter); the ports given to `port_attrs` print as
  `<ModelVariable ...>`; `FIXED`: a checker that cannot be loaded is reported instead of stopping `fmutool`.

*Exit criterion*: no `FMUPort` in the user documentation except the migration note; `mkdocs build` without
warning.

---

## 5. Risks

| Risk | Mitigation |
|---|---|
| Third-party checkers and operations import `FMUPort` and fail to load | Breaking entry and migration note (one-line change); a checker that cannot be loaded is reported and skipped, `fmutool` keeps running (phase 2) |
| Code building detached ports breaks | Breaking entry in `CHANGELOG.md`; the failure is immediate (`ImportError`), not a late one |
| A difference between `FMUPort` and `ModelVariable` not covered by the tests | Phase 1 keeps `FMUPort` instances; the characterization references of every built-in operation are compared in phase 2 |

## 6. Delivery

One PR for the three phases (small change), in 2.0, after the container refactoring (`done/container.md`).
