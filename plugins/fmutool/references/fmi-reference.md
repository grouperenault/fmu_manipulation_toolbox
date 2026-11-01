# FMI conventions for the FMU Manipulation Toolbox

## Causality — what a port may be used for
| Causality | Meaning | Usable as |
|---|---|---|
| `input` | Value provided from outside at each step | **destination** of `add_link`, `expose_input`, `set_start_value` |
| `output` | Value produced by the FMU | **source** of `add_link`, `expose_output` |
| `parameter` | Constant over the simulation, set before it starts | `set_start_value` only |
| `calculatedParameter` | Derived by the FMU from other parameters | read-only |
| `local` | Internal variable, observable but not connectable | read-only |
| `independent` | The time variable | never connect it |

A link always goes **output → input**. Linking anything else is rejected.

## Variability — when a value may change
`constant` < `fixed` < `tunable` < `discrete` < `continuous`. Only `fixed` and
`tunable` variables accept a meaningful start value from the user; writing a
start value on a `constant` is at best ignored.

## Types
FMI 2.0 uses `Real`, `Integer`, `Boolean`, `String`, `Enumeration`.
FMI 3.0 splits reals and integers by width: `Float32`/`Float64`,
`Int8`...`UInt64`, plus `Boolean`, `String`, `Binary`, `Clock`.

The container converts between numeric types when a link requires it, but the
conversion may lose precision (`Float64` → `Int32`) or meaning
(`Float64` → `Boolean`). Mention it to the user rather than silently wiring it.

## Start values
Start values are written as text into `modelDescription.xml`: booleans are
`true`/`false` (lowercase), reals use a dot as decimal separator. The
`set_start_value` tool accepts a typed value and performs the conversion.

## Units
A unit is only declarative: the toolbox does **not** convert between units.
Two ports in `m/s` and `km/h` will be linked happily and give wrong results —
check the `unit` field of `list_fmu_ports` before wiring physical quantities.

## The container itself
A container is a plain FMU, so it can be embedded into another container. It
runs the embedded FMUs with a fixed internal step (`step_size`) and exposes
only the ports you chose to expose.

## Selecting ports: causality, type, variability, name

The inspection tools (`inspect_fmu_file`, `list_fmu_ports`) and `apply_operation`
take the same filters. Omitted, a filter keeps every port; given together, a
port must match each of them.

| Filter | Values | Notes |
|---|---|---|
| `causality` | `input`, `output`, `parameter`, `local` (listings also accept `independent`, `calculatedParameter`...) | A port without `causality` is `local` |
| `type` | `Real`, `Integer`, `Boolean`, `String`, `Enumeration`, `Float32`, `Float64`, `Int8`...`UInt64`, `Binary`, `Clock` | On an FMI 3 FMU, an FMI 2 name selects its family: `Real` = `Float32` + `Float64`, `Integer` = every integer type. `Float64` selects nothing on an FMI 2 FMU |
| `variability` | `constant`, `fixed`, `tunable`, `discrete`, `continuous` | A port without `variability` has the default of the standard (below) |
| `name_pattern` | regular expression, searched anywhere in the name | Listings only; operations take their own `argument` |

Default variability when the FMU declares none:

| FMI version | Port | Default |
|---|---|---|
| 2.0 | any | `continuous` |
| 3.0 | `parameter`, `structuralParameter`, `calculatedParameter` | `fixed` |
| 3.0 | other `Float32`/`Float64` | `continuous` |
| 3.0 | other types | `discrete` |

## Reading a port listing

- `counts` describes the whole FMU; `total` counts the ports matching the
  filters and `returned` those of the page. When `truncated` is true, narrow the
  filters rather than paging through hundreds of ports.
- An attribute absent from a port is not declared on the variable (no `unit`,
  no `start`...). A unit may still come from its declared type: `describe_port`
  resolves it. Descriptions are cut after 80 characters.
- `describe_port` gives everything about one port: every declared attribute
  (`min`, `max`, `nominal`, `initial`, `declaredType`...), FMI 3 `dimensions`,
  the resolved declared type (`inherited`: the attributes the port takes from
  it, such as its unit; enumeration `items`), the `aliases` (FMI 3 `<Alias>`;
  FMI 2 variables sharing the value reference) and the `terminals` the port
  belongs to.

## What the toolbox refuses

An operation is refused, and the FMU left unchanged, when its result would
break the standard: every variable removed, a removed variable still referenced
by a kept one (`der(x)` is the derivative of `x`; a clock; an array dimension),
or two variables with the same name. The error names the culprits: report them,
narrow the operation (filters, a stricter regular expression) and try again.
