#include <math.h>
#include <string.h>

#include "convert.h"
#include "container.h"
#include "logger.h"

/*
 * Simple conversion routines between C types.
 *
 * Two families of routines are provided:
 *   - convert_<FROM>_<TO>   : conversions that do not incur any precision
 *                             loss (widening integers, F32 -> F64, ...).
 *   - convert__<FROM>_<TO>  : conversions that may incur a precision loss
 *                             (narrowing integers, sign changes,
 *                             real <-> integer, F64 -> F32, ...). The
 *                             routine name is prefixed with a single
 *                             underscore to make the potential loss
 *                             explicit at the call site.
 *
 * Type suffixes:
 *   F32/F64    : IEEE 754 float / double
 *   D8..D64    : signed integers (int8_t .. int64_t)
 *   U8..U64    : unsigned integers (uint8_t .. uint64_t)
 *   B / B1     : container boolean (int) / bit-packed boolean (bool)
 */
convert_table_t *convert_new(unsigned long nb) {
    convert_table_t *table = NULL;

    if (nb > 0) { 
        table = malloc(sizeof(*table));
        if (table) {
            table->nb = nb;
            table->entries = malloc(nb * sizeof(*table->entries));
            if (! table->entries) {
                logger(LOGGER_ERROR, "Cannot allocate conversion table for %lu entries.", nb);
                free(table);
                table = NULL;
            }
        } else
            logger(LOGGER_ERROR, "Cannot allocate conversion table");
    } 
    return table;
}


void convert_free(convert_table_t *table) {
    if (table) {
        free(table->entries);
        free(table);
    }
}


void convert_proceed(const container_t *container, const convert_table_t *table) {
    if (table) {
        for(unsigned long i = 0; i < table->nb; i += 1)
            table->entries[i].function(container, table->entries[i].from, table->entries[i].to);
    }
    return;
}


#define CONVERSION_FUNCTION(name, from_type, from_c_type, to_type, to_c_type)                                       \
static void convert_ ## name(const container_t *container, fmu_vr_t from, fmu_vr_t to) {                            \
    unsigned long dimension = container->port_ ## from_type [from].dimension;                                       \
    const from_c_type *from_value = container-> from_type + container->port_ ## from_type [from].links[0].fmu_vr;   \
    to_c_type         *to_value   = container-> to_type   + container->port_ ## to_type [to].links[0].fmu_vr;       \
                                                                                                                    \
    for(unsigned long i = 0; i < dimension; i += 1)                                                                 \
        to_value[i] = (to_c_type)from_value[i];                                                                     \
}


#define CONVERSION_FUNCTION_F_B(name, from_type, from_c_type, to_type, to_c_type)                                   \
static void convert_ ## name(const container_t *container, fmu_vr_t from, fmu_vr_t to) {                            \
    unsigned long dimension = container->port_ ## from_type [from].dimension;                                       \
    const from_c_type *from_value = container-> from_type + container->port_ ## from_type [from].links[0].fmu_vr;   \
    to_c_type         *to_value   = container-> to_type   + container->port_ ## to_type [to].links[0].fmu_vr;       \
                                                                                                                    \
    for(unsigned long i = 0; i < dimension; i += 1)                                                                 \
        to_value[i] = (to_c_type)(fabs(from_value[i]) > container->tolerance);                                      \
}


#define CONVERSION_FUNCTION_D_B(name, from_type, from_c_type, to_type, to_c_type)                                   \
static void convert_ ## name(const container_t *container, fmu_vr_t from, fmu_vr_t to) {                            \
    unsigned long dimension = container->port_ ## from_type [from].dimension;                                       \
    const from_c_type *from_value = container-> from_type + container->port_ ## from_type [from].links[0].fmu_vr;   \
    to_c_type         *to_value   = container-> to_type   + container->port_ ## to_type [to].links[0].fmu_vr;       \
                                                                                                                    \
    for(unsigned long i = 0; i < dimension; i += 1)                                                                 \
        to_value[i] = (to_c_type)(from_value[i] != 0);                                                              \
}


#define CONVERSION_FUNCTION_B(name, from_type, from_c_type, to_type, to_c_type)                                     \
static void convert_ ## name(const container_t *container, fmu_vr_t from, fmu_vr_t to) {                            \
    unsigned long dimension = container->port_ ## from_type [from].dimension;                                       \
    const from_c_type *from_value = container-> from_type + container->port_ ## from_type [from].links[0].fmu_vr;   \
    to_c_type         *to_value   = container-> to_type   + container->port_ ## to_type [to].links[0].fmu_vr;       \
                                                                                                                    \
    for(unsigned long i = 0; i < dimension; i += 1)                                                                 \
        to_value[i] = (to_c_type)(from_value[i]?1:0);                                                               \
}


/*
 * Lossless conversions (widening, same size, F32 -> F64, B <-> B1).
 */
CONVERSION_FUNCTION(F32_F64, reals32, float, reals64, double)

CONVERSION_FUNCTION(D8_D16, integers8, int8_t, integers16,  int16_t)
CONVERSION_FUNCTION(D8_U16, integers8, int8_t, uintegers16, uint16_t)
CONVERSION_FUNCTION(D8_D32, integers8, int8_t, integers32,  int32_t)
CONVERSION_FUNCTION(D8_U32, integers8, int8_t, uintegers32, uint32_t)
CONVERSION_FUNCTION(D8_D64, integers8, int8_t, integers64,  int64_t)
CONVERSION_FUNCTION(D8_U64, integers8, int8_t, uintegers64, uint64_t)

CONVERSION_FUNCTION(U8_D16, uintegers8, uint8_t, integers16,  int16_t)
CONVERSION_FUNCTION(U8_U16, uintegers8, uint8_t, uintegers16, uint16_t)
CONVERSION_FUNCTION(U8_D32, uintegers8, uint8_t, integers32,  int32_t)
CONVERSION_FUNCTION(U8_U32, uintegers8, uint8_t, uintegers32, uint32_t)
CONVERSION_FUNCTION(U8_D64, uintegers8, uint8_t, integers64,  int64_t)
CONVERSION_FUNCTION(U8_U64, uintegers8, uint8_t, uintegers64, uint64_t)

CONVERSION_FUNCTION(D16_D32, integers16, int16_t, integers32,  int32_t)
CONVERSION_FUNCTION(D16_U32, integers16, int16_t, uintegers32, uint32_t)
CONVERSION_FUNCTION(D16_D64, integers16, int16_t, integers64,  int64_t)
CONVERSION_FUNCTION(D16_U64, integers16, int16_t, uintegers64, uint64_t)

CONVERSION_FUNCTION(U16_D32, uintegers16, uint16_t, integers32,  int32_t)
CONVERSION_FUNCTION(U16_U32, uintegers16, uint16_t, uintegers32, uint32_t)
CONVERSION_FUNCTION(U16_D64, uintegers16, uint16_t, integers64,  int64_t)
CONVERSION_FUNCTION(U16_U64, uintegers16, uint16_t, uintegers64, uint64_t)

CONVERSION_FUNCTION(D32_D64, integers32, int32_t, integers64,  int64_t)
CONVERSION_FUNCTION(D32_U64, integers32, int32_t, uintegers64, uint64_t)

CONVERSION_FUNCTION(U32_D64, uintegers32, uint32_t, integers64,  int64_t)
CONVERSION_FUNCTION(U32_U64, uintegers32, uint32_t, uintegers64, uint64_t)

CONVERSION_FUNCTION(B1_B, booleans1, bool, booleans,  int)
CONVERSION_FUNCTION(B_B1, booleans,  int,  booleans1, bool)


/*
 * Conversions with potential precision loss.
 * The routine name is prefixed with an underscore.
 */

/* From F32 (float) */
CONVERSION_FUNCTION(_F32_D8,  reals32, float, integers8,   int8_t)
CONVERSION_FUNCTION(_F32_U8,  reals32, float, uintegers8,  uint8_t)
CONVERSION_FUNCTION(_F32_D16, reals32, float, integers16,  int16_t)
CONVERSION_FUNCTION(_F32_U16, reals32, float, uintegers16, uint16_t)
CONVERSION_FUNCTION(_F32_D32, reals32, float, integers32,  int32_t)
CONVERSION_FUNCTION(_F32_U32, reals32, float, uintegers32, uint32_t)
CONVERSION_FUNCTION(_F32_D64, reals32, float, integers64,  int64_t)
CONVERSION_FUNCTION(_F32_U64, reals32, float, uintegers64, uint64_t)

/* From F64 (double) */
CONVERSION_FUNCTION(_F64_F32, reals64, double, reals32,     float)
CONVERSION_FUNCTION(_F64_D8,  reals64, double, integers8,   int8_t)
CONVERSION_FUNCTION(_F64_U8,  reals64, double, uintegers8,  uint8_t)
CONVERSION_FUNCTION(_F64_D16, reals64, double, integers16,  int16_t)
CONVERSION_FUNCTION(_F64_U16, reals64, double, uintegers16, uint16_t)
CONVERSION_FUNCTION(_F64_D32, reals64, double, integers32,  int32_t)
CONVERSION_FUNCTION(_F64_U32, reals64, double, uintegers32, uint32_t)
CONVERSION_FUNCTION(_F64_D64, reals64, double, integers64,  int64_t)
CONVERSION_FUNCTION(_F64_U64, reals64, double, uintegers64, uint64_t)

/* From D8 (int8_t) */
CONVERSION_FUNCTION(_D8_F32, integers8, int8_t, reals32,    float)
CONVERSION_FUNCTION(_D8_F64, integers8, int8_t, reals64,    double)
CONVERSION_FUNCTION(_D8_U8,  integers8, int8_t, uintegers8, uint8_t)

/* From U8 (uint8_t) */
CONVERSION_FUNCTION(_U8_F32, uintegers8, uint8_t, reals32,   float)
CONVERSION_FUNCTION(_U8_F64, uintegers8, uint8_t, reals64,   double)
CONVERSION_FUNCTION(_U8_D8,  uintegers8, uint8_t, integers8, int8_t)

/* From D16 (int16_t) */
CONVERSION_FUNCTION(_D16_F32, integers16, int16_t, reals32,     float)
CONVERSION_FUNCTION(_D16_F64, integers16, int16_t, reals64,     double)
CONVERSION_FUNCTION(_D16_D8,  integers16, int16_t, integers8,   int8_t)
CONVERSION_FUNCTION(_D16_U8,  integers16, int16_t, uintegers8,  uint8_t)
CONVERSION_FUNCTION(_D16_U16, integers16, int16_t, uintegers16, uint16_t)

/* From U16 (uint16_t) */
CONVERSION_FUNCTION(_U16_F32, uintegers16, uint16_t, reals32,    float)
CONVERSION_FUNCTION(_U16_F64, uintegers16, uint16_t, reals64,    double)
CONVERSION_FUNCTION(_U16_D8,  uintegers16, uint16_t, integers8,  int8_t)
CONVERSION_FUNCTION(_U16_U8,  uintegers16, uint16_t, uintegers8, uint8_t)
CONVERSION_FUNCTION(_U16_D16, uintegers16, uint16_t, integers16, int16_t)

/* From D32 (int32_t) */
CONVERSION_FUNCTION(_D32_F32, integers32, int32_t, reals32,     float)
CONVERSION_FUNCTION(_D32_F64, integers32, int32_t, reals64,     double)
CONVERSION_FUNCTION(_D32_D8,  integers32, int32_t, integers8,   int8_t)
CONVERSION_FUNCTION(_D32_U8,  integers32, int32_t, uintegers8,  uint8_t)
CONVERSION_FUNCTION(_D32_D16, integers32, int32_t, integers16,  int16_t)
CONVERSION_FUNCTION(_D32_U16, integers32, int32_t, uintegers16, uint16_t)
CONVERSION_FUNCTION(_D32_U32, integers32, int32_t, uintegers32, uint32_t)

/* From U32 (uint32_t) */
CONVERSION_FUNCTION(_U32_F32, uintegers32, uint32_t, reals32,    float)
CONVERSION_FUNCTION(_U32_F64, uintegers32, uint32_t, reals64,    double)
CONVERSION_FUNCTION(_U32_D8,  uintegers32, uint32_t, integers8,  int8_t)
CONVERSION_FUNCTION(_U32_U8,  uintegers32, uint32_t, uintegers8, uint8_t)
CONVERSION_FUNCTION(_U32_D16, uintegers32, uint32_t, integers16, int16_t)
CONVERSION_FUNCTION(_U32_U16, uintegers32, uint32_t, uintegers16, uint16_t)
CONVERSION_FUNCTION(_U32_D32, uintegers32, uint32_t, integers32, int32_t)

/* From D64 (int64_t) */
CONVERSION_FUNCTION(_D64_F32, integers64, int64_t, reals32,     float)
CONVERSION_FUNCTION(_D64_F64, integers64, int64_t, reals64,     double)
CONVERSION_FUNCTION(_D64_D8,  integers64, int64_t, integers8,   int8_t)
CONVERSION_FUNCTION(_D64_U8,  integers64, int64_t, uintegers8,  uint8_t)
CONVERSION_FUNCTION(_D64_D16, integers64, int64_t, integers16,  int16_t)
CONVERSION_FUNCTION(_D64_U16, integers64, int64_t, uintegers16, uint16_t)
CONVERSION_FUNCTION(_D64_D32, integers64, int64_t, integers32,  int32_t)
CONVERSION_FUNCTION(_D64_U32, integers64, int64_t, uintegers32, uint32_t)
CONVERSION_FUNCTION(_D64_U64, integers64, int64_t, uintegers64, uint64_t)

/* From U64 (uint64_t) */
CONVERSION_FUNCTION(_U64_F32, uintegers64, uint64_t, reals32,    float)
CONVERSION_FUNCTION(_U64_F64, uintegers64, uint64_t, reals64,    double)
CONVERSION_FUNCTION(_U64_D8,  uintegers64, uint64_t, integers8,  int8_t)
CONVERSION_FUNCTION(_U64_U8,  uintegers64, uint64_t, uintegers8, uint8_t)
CONVERSION_FUNCTION(_U64_D16, uintegers64, uint64_t, integers16, int16_t)
CONVERSION_FUNCTION(_U64_U16, uintegers64, uint64_t, uintegers16, uint16_t)
CONVERSION_FUNCTION(_U64_D32, uintegers64, uint64_t, integers32, int32_t)
CONVERSION_FUNCTION(_U64_U32, uintegers64, uint64_t, uintegers32, uint32_t)
CONVERSION_FUNCTION(_U64_D64, uintegers64, uint64_t, integers64, int64_t)


/*
 * Boolean <-> numeric conversions.
 *
 * Numeric -> boolean (lossy, prefixed with '_'):
 *     any non-zero numeric value is considered 'true'.
 * Boolean -> numeric (lossless):
 *     'true' becomes 1, 'false' becomes 0.
 */

/* Numeric -> B (int) */
CONVERSION_FUNCTION_F_B(_F32_B, reals32, float,  booleans, int)
CONVERSION_FUNCTION_F_B(_F64_B, reals64, double, booleans, int)

CONVERSION_FUNCTION_D_B(_D8_B,  integers8,   int8_t,   booleans, int)
CONVERSION_FUNCTION_D_B(_U8_B,  uintegers8,  uint8_t,  booleans, int)
CONVERSION_FUNCTION_D_B(_D16_B, integers16,  int16_t,  booleans, int)
CONVERSION_FUNCTION_D_B(_U16_B, uintegers16, uint16_t, booleans, int)
CONVERSION_FUNCTION_D_B(_D32_B, integers32,  int32_t,  booleans, int)
CONVERSION_FUNCTION_D_B(_U32_B, uintegers32, uint32_t, booleans, int)
CONVERSION_FUNCTION_D_B(_D64_B, integers64,  int64_t,  booleans, int)
CONVERSION_FUNCTION_D_B(_U64_B, uintegers64, uint64_t, booleans, int)

/* Numeric -> B1 (bool) */
CONVERSION_FUNCTION_F_B(_F32_B1, reals32, float,  booleans1, bool)
CONVERSION_FUNCTION_F_B(_F64_B1, reals64, double, booleans1, bool)

CONVERSION_FUNCTION_D_B(_D8_B1,  integers8,   int8_t,   booleans1, bool)
CONVERSION_FUNCTION_D_B(_U8_B1,  uintegers8,  uint8_t,  booleans1, bool)
CONVERSION_FUNCTION_D_B(_D16_B1, integers16,  int16_t,  booleans1, bool)
CONVERSION_FUNCTION_D_B(_U16_B1, uintegers16, uint16_t, booleans1, bool)
CONVERSION_FUNCTION_D_B(_D32_B1, integers32,  int32_t,  booleans1, bool)
CONVERSION_FUNCTION_D_B(_U32_B1, uintegers32, uint32_t, booleans1, bool)
CONVERSION_FUNCTION_D_B(_D64_B1, integers64,  int64_t,  booleans1, bool)
CONVERSION_FUNCTION_D_B(_U64_B1, uintegers64, uint64_t, booleans1, bool)

/* B (int) -> Numeric (result is 0 or 1, lossless) */
CONVERSION_FUNCTION_B(B_F32, booleans, int, reals32,     float)
CONVERSION_FUNCTION_B(B_F64, booleans, int, reals64,     double)
CONVERSION_FUNCTION_B(B_D8,  booleans, int, integers8,   int8_t)
CONVERSION_FUNCTION_B(B_U8,  booleans, int, uintegers8,  uint8_t)
CONVERSION_FUNCTION_B(B_D16, booleans, int, integers16,  int16_t)
CONVERSION_FUNCTION_B(B_U16, booleans, int, uintegers16, uint16_t)
CONVERSION_FUNCTION_B(B_D32, booleans, int, integers32,  int32_t)
CONVERSION_FUNCTION_B(B_U32, booleans, int, uintegers32, uint32_t)
CONVERSION_FUNCTION_B(B_D64, booleans, int, integers64,  int64_t)
CONVERSION_FUNCTION_B(B_U64, booleans, int, uintegers64, uint64_t)

/* B1 (bool) -> Numeric (result is 0 or 1, lossless) */
CONVERSION_FUNCTION_B(B1_F32, booleans1, bool, reals32,     float)
CONVERSION_FUNCTION_B(B1_F64, booleans1, bool, reals64,     double)
CONVERSION_FUNCTION_B(B1_D8,  booleans1, bool, integers8,   int8_t)
CONVERSION_FUNCTION_B(B1_U8,  booleans1, bool, uintegers8,  uint8_t)
CONVERSION_FUNCTION_B(B1_D16, booleans1, bool, integers16,  int16_t)
CONVERSION_FUNCTION_B(B1_U16, booleans1, bool, uintegers16, uint16_t)
CONVERSION_FUNCTION_B(B1_D32, booleans1, bool, integers32,  int32_t)
CONVERSION_FUNCTION_B(B1_U32, booleans1, bool, uintegers32, uint32_t)
CONVERSION_FUNCTION_B(B1_D64, booleans1, bool, integers64,  int64_t)
CONVERSION_FUNCTION_B(B1_U64, booleans1, bool, uintegers64, uint64_t)


convert_function_t convert_function_get(const char *function_name) {
#define CASE(x) if (strcmp(function_name, #x) == 0) return convert_ ## x
    CASE(F32_F64);

    CASE(D8_D16);
    CASE(D8_U16);
    CASE(D8_D32);
    CASE(D8_U32);
    CASE(D8_D64);
    CASE(D8_U64);
    
    CASE(U8_D16);
    CASE(U8_U16);
    CASE(U8_D32);
    CASE(U8_U32);
    CASE(U8_D64);
    CASE(U8_U64);
    
    CASE(D16_D32);
    CASE(D16_U32);
    CASE(D16_D64);
    CASE(D16_U64);
    
    CASE(U16_D32);
    CASE(U16_U32);
    CASE(U16_D64);
    CASE(U16_U64);
    
    CASE(D32_D64);
    CASE(D32_U64);
    
    CASE(U32_D64);
    CASE(U32_U64);

    CASE(B1_B);
    CASE(B_B1);

    /* Conversions with potential precision loss (prefixed with '_'). */
    CASE(_F32_D8);
    CASE(_F32_U8);
    CASE(_F32_D16);
    CASE(_F32_U16);
    CASE(_F32_D32);
    CASE(_F32_U32);
    CASE(_F32_D64);
    CASE(_F32_U64);

    CASE(_F64_F32);
    CASE(_F64_D8);
    CASE(_F64_U8);
    CASE(_F64_D16);
    CASE(_F64_U16);
    CASE(_F64_D32);
    CASE(_F64_U32);
    CASE(_F64_D64);
    CASE(_F64_U64);

    CASE(_D8_F32);
    CASE(_D8_F64);
    CASE(_D8_U8);

    CASE(_U8_F32);
    CASE(_U8_F64);
    CASE(_U8_D8);

    CASE(_D16_F32);
    CASE(_D16_F64);
    CASE(_D16_D8);
    CASE(_D16_U8);
    CASE(_D16_U16);

    CASE(_U16_F32);
    CASE(_U16_F64);
    CASE(_U16_D8);
    CASE(_U16_U8);
    CASE(_U16_D16);

    CASE(_D32_F32);
    CASE(_D32_F64);
    CASE(_D32_D8);
    CASE(_D32_U8);
    CASE(_D32_D16);
    CASE(_D32_U16);
    CASE(_D32_U32);

    CASE(_U32_F32);
    CASE(_U32_F64);
    CASE(_U32_D8);
    CASE(_U32_U8);
    CASE(_U32_D16);
    CASE(_U32_U16);
    CASE(_U32_D32);

    CASE(_D64_F32);
    CASE(_D64_F64);
    CASE(_D64_D8);
    CASE(_D64_U8);
    CASE(_D64_D16);
    CASE(_D64_U16);
    CASE(_D64_D32);
    CASE(_D64_U32);
    CASE(_D64_U64);

    CASE(_U64_F32);
    CASE(_U64_F64);
    CASE(_U64_D8);
    CASE(_U64_U8);
    CASE(_U64_D16);
    CASE(_U64_U16);
    CASE(_U64_D32);
    CASE(_U64_U32);
    CASE(_U64_D64);

    /* Numeric -> boolean (lossy, non-zero = true). */
    CASE(_F32_B);
    CASE(_F64_B);
    CASE(_D8_B);
    CASE(_U8_B);
    CASE(_D16_B);
    CASE(_U16_B);
    CASE(_D32_B);
    CASE(_U32_B);
    CASE(_D64_B);
    CASE(_U64_B);

    CASE(_F32_B1);
    CASE(_F64_B1);
    CASE(_D8_B1);
    CASE(_U8_B1);
    CASE(_D16_B1);
    CASE(_U16_B1);
    CASE(_D32_B1);
    CASE(_U32_B1);
    CASE(_D64_B1);
    CASE(_U64_B1);

    /* Boolean -> numeric (lossless, true = 1, false = 0). */
    CASE(B_F32);
    CASE(B_F64);
    CASE(B_D8);
    CASE(B_U8);
    CASE(B_D16);
    CASE(B_U16);
    CASE(B_D32);
    CASE(B_U32);
    CASE(B_D64);
    CASE(B_U64);

    CASE(B1_F32);
    CASE(B1_F64);
    CASE(B1_D8);
    CASE(B1_U8);
    CASE(B1_D16);
    CASE(B1_U16);
    CASE(B1_D32);
    CASE(B1_U32);
    CASE(B1_D64);
    CASE(B1_U64);
#undef CASE

    /* should not be reached */
    return NULL;
}
