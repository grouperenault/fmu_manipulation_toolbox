"""Types of the container and conversions between them.

Shared by the container builder (`container.py`), which writes `container.txt`, and by `split.py`, which reads it
back. The C runtime (`container/`) uses the same type order and conversion names: `container.txt` lists its
sections in the order of `ALL_TYPES`, and every value of `CONVERSION_FUNCTION` is a `CASE(...)` of
`container/convert.c`.
"""

#: Container types, in the order of the sections of `container.txt`. The index of a type is also stored in the
#: upper byte of the value references of the container (see `ValueReferenceTable`).
ALL_TYPES = (
    "real64", "real32",
    "integer8", "uinteger8", "integer16", "uinteger16", "integer32", "uinteger32", "integer64", "uinteger64",
    "boolean", "boolean1",
    "string",
    "binary", "clock"
)

#: Types without start value in `container.txt`.
NO_START_VALUE_TYPES = ("binary", "clock")

#: Types accepting a start value, in the order of `ALL_TYPES`.
START_VALUE_TYPES = tuple(type_name for type_name in ALL_TYPES if type_name not in NO_START_VALUE_TYPES)

#: FMI type (as named in `modelDescription.xml`) -> container type, by FMI version.
FMI_TO_CONTAINER = {
    2: {
        'Real': 'real64',
        'Integer': 'integer32',
        'String': 'string',
        'Boolean': 'boolean'
    },
    3: {
        'Float64': 'real64',
        'Float32': 'real32',
        'Int8': 'integer8',
        'UInt8': 'uinteger8',
        'Int16': 'integer16',
        'UInt16': 'uinteger16',
        'Int32': 'integer32',
        'UInt32': 'uinteger32',
        'Int64': 'integer64',
        'UInt64': 'uinteger64',
        'String': 'string',
        'Boolean': 'boolean1',
        'Binary': 'binary',
        'Clock': 'clock'
    }
}

#: Container type -> FMI type, by FMI version (inverse of `FMI_TO_CONTAINER`).
CONTAINER_TO_FMI = {
    fmi_version: {container_type: fmi_type for fmi_type, container_type in types.items()}
    for fmi_version, types in FMI_TO_CONTAINER.items()
}

#: `"<from type>/<to type>"` -> name of the conversion function of the runtime. Lossy conversions start with `_`
#: (see `is_lossy`).
CONVERSION_FUNCTION = {
    # ------------------------------------------------------------------
    # Lossless conversions (widening integers, F32 -> F64, boolean/int
    # normalisation, boolean -> numeric which yields 0 or 1).
    # ------------------------------------------------------------------
    "real32/real64": "F32_F64",

    "integer8/integer16": "D8_D16",
    "integer8/uinteger16": "D8_U16",
    "integer8/integer32": "D8_D32",
    "integer8/uinteger32": "D8_U32",
    "integer8/integer64": "D8_D64",
    "integer8/uinteger64": "D8_U64",

    "uinteger8/integer16": "U8_D16",
    "uinteger8/uinteger16": "U8_U16",
    "uinteger8/integer32": "U8_D32",
    "uinteger8/uinteger32": "U8_U32",
    "uinteger8/integer64": "U8_D64",
    "uinteger8/uinteger64": "U8_U64",

    "integer16/integer32": "D16_D32",
    "integer16/uinteger32": "D16_U32",
    "integer16/integer64": "D16_D64",
    "integer16/uinteger64": "D16_U64",

    "uinteger16/integer32": "U16_D32",
    "uinteger16/uinteger32": "U16_U32",
    "uinteger16/integer64": "U16_D64",
    "uinteger16/uinteger64": "U16_U64",

    "integer32/integer64": "D32_D64",
    "integer32/uinteger64": "D32_U64",

    "uinteger32/integer64": "U32_D64",
    "uinteger32/uinteger64": "U32_U64",

    "boolean/boolean1": "B_B1",
    "boolean1/boolean": "B1_B",

    # Boolean -> numeric: result is 0 or 1, lossless.
    "boolean/real32":    "B_F32",
    "boolean/real64":    "B_F64",
    "boolean/integer8":  "B_D8",
    "boolean/uinteger8": "B_U8",
    "boolean/integer16": "B_D16",
    "boolean/uinteger16":"B_U16",
    "boolean/integer32": "B_D32",
    "boolean/uinteger32":"B_U32",
    "boolean/integer64": "B_D64",
    "boolean/uinteger64":"B_U64",

    "boolean1/real32":    "B1_F32",
    "boolean1/real64":    "B1_F64",
    "boolean1/integer8":  "B1_D8",
    "boolean1/uinteger8": "B1_U8",
    "boolean1/integer16": "B1_D16",
    "boolean1/uinteger16":"B1_U16",
    "boolean1/integer32": "B1_D32",
    "boolean1/uinteger32":"B1_U32",
    "boolean1/integer64": "B1_D64",
    "boolean1/uinteger64":"B1_U64",

    # ------------------------------------------------------------------
    # Lossy conversions (prefixed with '_' so the C side and the Python
    # side both flag them). A warning is emitted when such a conversion
    # is instantiated (see Link.add_target).
    # ------------------------------------------------------------------

    # From F32
    "real32/integer8":   "_F32_D8",
    "real32/uinteger8":  "_F32_U8",
    "real32/integer16":  "_F32_D16",
    "real32/uinteger16": "_F32_U16",
    "real32/integer32":  "_F32_D32",
    "real32/uinteger32": "_F32_U32",
    "real32/integer64":  "_F32_D64",
    "real32/uinteger64": "_F32_U64",

    # From F64
    "real64/real32":     "_F64_F32",
    "real64/integer8":   "_F64_D8",
    "real64/uinteger8":  "_F64_U8",
    "real64/integer16":  "_F64_D16",
    "real64/uinteger16": "_F64_U16",
    "real64/integer32":  "_F64_D32",
    "real64/uinteger32": "_F64_U32",
    "real64/integer64":  "_F64_D64",
    "real64/uinteger64": "_F64_U64",

    # From D8 / U8
    "integer8/real32":   "_D8_F32",
    "integer8/real64":   "_D8_F64",
    "integer8/uinteger8": "_D8_U8",

    "uinteger8/real32":  "_U8_F32",
    "uinteger8/real64":  "_U8_F64",
    "uinteger8/integer8": "_U8_D8",

    # From D16 / U16
    "integer16/real32":   "_D16_F32",
    "integer16/real64":   "_D16_F64",
    "integer16/integer8": "_D16_D8",
    "integer16/uinteger8":"_D16_U8",
    "integer16/uinteger16":"_D16_U16",

    "uinteger16/real32":   "_U16_F32",
    "uinteger16/real64":   "_U16_F64",
    "uinteger16/integer8": "_U16_D8",
    "uinteger16/uinteger8":"_U16_U8",
    "uinteger16/integer16":"_U16_D16",

    # From D32 / U32
    "integer32/real32":    "_D32_F32",
    "integer32/real64":    "_D32_F64",
    "integer32/integer8":  "_D32_D8",
    "integer32/uinteger8": "_D32_U8",
    "integer32/integer16": "_D32_D16",
    "integer32/uinteger16":"_D32_U16",
    "integer32/uinteger32":"_D32_U32",

    "uinteger32/real32":    "_U32_F32",
    "uinteger32/real64":    "_U32_F64",
    "uinteger32/integer8":  "_U32_D8",
    "uinteger32/uinteger8": "_U32_U8",
    "uinteger32/integer16": "_U32_D16",
    "uinteger32/uinteger16":"_U32_U16",
    "uinteger32/integer32": "_U32_D32",

    # From D64 / U64
    "integer64/real32":    "_D64_F32",
    "integer64/real64":    "_D64_F64",
    "integer64/integer8":  "_D64_D8",
    "integer64/uinteger8": "_D64_U8",
    "integer64/integer16": "_D64_D16",
    "integer64/uinteger16":"_D64_U16",
    "integer64/integer32": "_D64_D32",
    "integer64/uinteger32":"_D64_U32",
    "integer64/uinteger64":"_D64_U64",

    "uinteger64/real32":    "_U64_F32",
    "uinteger64/real64":    "_U64_F64",
    "uinteger64/integer8":  "_U64_D8",
    "uinteger64/uinteger8": "_U64_U8",
    "uinteger64/integer16": "_U64_D16",
    "uinteger64/uinteger16":"_U64_U16",
    "uinteger64/integer32": "_U64_D32",
    "uinteger64/uinteger32":"_U64_U32",
    "uinteger64/integer64": "_U64_D64",

    # Numeric -> boolean: non-zero is considered true.
    "real32/boolean":     "_F32_B",
    "real64/boolean":     "_F64_B",
    "integer8/boolean":   "_D8_B",
    "uinteger8/boolean":  "_U8_B",
    "integer16/boolean":  "_D16_B",
    "uinteger16/boolean": "_U16_B",
    "integer32/boolean":  "_D32_B",
    "uinteger32/boolean": "_U32_B",
    "integer64/boolean":  "_D64_B",
    "uinteger64/boolean": "_U64_B",

    "real32/boolean1":     "_F32_B1",
    "real64/boolean1":     "_F64_B1",
    "integer8/boolean1":   "_D8_B1",
    "uinteger8/boolean1":  "_U8_B1",
    "integer16/boolean1":  "_D16_B1",
    "uinteger16/boolean1": "_U16_B1",
    "integer32/boolean1":  "_D32_B1",
    "uinteger32/boolean1": "_U32_B1",
    "integer64/boolean1":  "_D64_B1",
    "uinteger64/boolean1": "_U64_B1",
}


def is_lossy(conversion: str) -> bool:
    """Whether a conversion of `CONVERSION_FUNCTION` may lose information (narrowing, sign change, to boolean)."""
    return conversion.startswith("_")
