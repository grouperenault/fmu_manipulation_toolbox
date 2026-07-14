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


static void convert_F32_F64(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->reals64[to] = (double)container->reals32[from];
}


static void convert_D8_D16(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->integers16[to] = container->integers8[from];
}


static void convert_D8_U16(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->uintegers16[to] = container->integers8[from];
}


static void convert_D8_D32(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->integers32[to] = container->integers8[from];
}


static void convert_D8_U32(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->uintegers32[to] = container->integers8[from];
}


static void convert_D8_D64(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->integers64[to] = container->integers8[from];
}


static void convert_D8_U64(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->uintegers64[to] = container->integers8[from];
}


static void convert_U8_D16(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->integers16[to] = container->uintegers8[from];
}


static void convert_U8_U16(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->uintegers16[to] = container->uintegers8[from];
}


static void convert_U8_D32(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->integers32[to] = container->uintegers8[from];
}


static void convert_U8_U32(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->uintegers32[to] = container->uintegers8[from];
}


static void convert_U8_D64(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->integers64[to] = container->uintegers8[from];
}


static void convert_U8_U64(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->uintegers64[to] = container->uintegers8[from];
}


static void convert_D16_D32(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->integers32[to] = container->integers16[from];
}


static void convert_D16_U32(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->uintegers32[to] = container->integers16[from];
}


static void convert_D16_D64(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->integers64[to] = container->integers16[from];
}


static void convert_D16_U64(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->uintegers64[to] = container->integers16[from];
}


static void convert_U16_D32(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->integers32[to] = container->uintegers16[from];
}


static void convert_U16_U32(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->uintegers32[to] = container->uintegers16[from];
}


static void convert_U16_D64(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->integers64[to] = container->uintegers16[from];
}


static void convert_U16_U64(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->uintegers64[to] = container->uintegers16[from];
}


static void convert_D32_D64(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->integers64[to] = container->integers32[from];
}


static void convert_D32_U64(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->uintegers64[to] = container->integers32[from];
}


static void convert_U32_D64(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->integers64[to] = container->uintegers32[from];
}


static void convert_U32_U64(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->uintegers64[to] = container->uintegers32[from];
}

static void convert_B1_B(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->booleans[to] = container->booleans1[from];
}

static void convert_B_B1(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->booleans1[to] = container->booleans[from];
}


/*
 * Conversions with potential precision loss.
 * The routine name is prefixed with an underscore.
 */

/* From F32 (float) */
static void convert__F32_D8(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->integers8[to] = (int8_t)container->reals32[from];
}
static void convert__F32_U8(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->uintegers8[to] = (uint8_t)container->reals32[from];
}
static void convert__F32_D16(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->integers16[to] = (int16_t)container->reals32[from];
}
static void convert__F32_U16(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->uintegers16[to] = (uint16_t)container->reals32[from];
}
static void convert__F32_D32(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->integers32[to] = (int32_t)container->reals32[from];
}
static void convert__F32_U32(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->uintegers32[to] = (uint32_t)container->reals32[from];
}
static void convert__F32_D64(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->integers64[to] = (int64_t)container->reals32[from];
}
static void convert__F32_U64(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->uintegers64[to] = (uint64_t)container->reals32[from];
}

/* From F64 (double) */
static void convert__F64_F32(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->reals32[to] = (float)container->reals64[from];
}
static void convert__F64_D8(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->integers8[to] = (int8_t)container->reals64[from];
}
static void convert__F64_U8(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->uintegers8[to] = (uint8_t)container->reals64[from];
}
static void convert__F64_D16(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->integers16[to] = (int16_t)container->reals64[from];
}
static void convert__F64_U16(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->uintegers16[to] = (uint16_t)container->reals64[from];
}
static void convert__F64_D32(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->integers32[to] = (int32_t)container->reals64[from];
}
static void convert__F64_U32(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->uintegers32[to] = (uint32_t)container->reals64[from];
}
static void convert__F64_D64(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->integers64[to] = (int64_t)container->reals64[from];
}
static void convert__F64_U64(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->uintegers64[to] = (uint64_t)container->reals64[from];
}

/* From D8 (int8_t) */
static void convert__D8_F32(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->reals32[to] = (float)container->integers8[from];
}
static void convert__D8_F64(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->reals64[to] = (double)container->integers8[from];
}
static void convert__D8_U8(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->uintegers8[to] = (uint8_t)container->integers8[from];
}

/* From U8 (uint8_t) */
static void convert__U8_F32(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->reals32[to] = (float)container->uintegers8[from];
}
static void convert__U8_F64(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->reals64[to] = (double)container->uintegers8[from];
}
static void convert__U8_D8(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->integers8[to] = (int8_t)container->uintegers8[from];
}

/* From D16 (int16_t) */
static void convert__D16_F32(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->reals32[to] = (float)container->integers16[from];
}
static void convert__D16_F64(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->reals64[to] = (double)container->integers16[from];
}
static void convert__D16_D8(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->integers8[to] = (int8_t)container->integers16[from];
}
static void convert__D16_U8(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->uintegers8[to] = (uint8_t)container->integers16[from];
}
static void convert__D16_U16(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->uintegers16[to] = (uint16_t)container->integers16[from];
}

/* From U16 (uint16_t) */
static void convert__U16_F32(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->reals32[to] = (float)container->uintegers16[from];
}
static void convert__U16_F64(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->reals64[to] = (double)container->uintegers16[from];
}
static void convert__U16_D8(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->integers8[to] = (int8_t)container->uintegers16[from];
}
static void convert__U16_U8(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->uintegers8[to] = (uint8_t)container->uintegers16[from];
}
static void convert__U16_D16(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->integers16[to] = (int16_t)container->uintegers16[from];
}

/* From D32 (int32_t) */
static void convert__D32_F32(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->reals32[to] = (float)container->integers32[from];
}
static void convert__D32_F64(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->reals64[to] = (double)container->integers32[from];
}
static void convert__D32_D8(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->integers8[to] = (int8_t)container->integers32[from];
}
static void convert__D32_U8(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->uintegers8[to] = (uint8_t)container->integers32[from];
}
static void convert__D32_D16(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->integers16[to] = (int16_t)container->integers32[from];
}
static void convert__D32_U16(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->uintegers16[to] = (uint16_t)container->integers32[from];
}
static void convert__D32_U32(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->uintegers32[to] = (uint32_t)container->integers32[from];
}

/* From U32 (uint32_t) */
static void convert__U32_F32(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->reals32[to] = (float)container->uintegers32[from];
}
static void convert__U32_F64(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->reals64[to] = (double)container->uintegers32[from];
}
static void convert__U32_D8(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->integers8[to] = (int8_t)container->uintegers32[from];
}
static void convert__U32_U8(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->uintegers8[to] = (uint8_t)container->uintegers32[from];
}
static void convert__U32_D16(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->integers16[to] = (int16_t)container->uintegers32[from];
}
static void convert__U32_U16(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->uintegers16[to] = (uint16_t)container->uintegers32[from];
}
static void convert__U32_D32(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->integers32[to] = (int32_t)container->uintegers32[from];
}

/* From D64 (int64_t) */
static void convert__D64_F32(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->reals32[to] = (float)container->integers64[from];
}
static void convert__D64_F64(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->reals64[to] = (double)container->integers64[from];
}
static void convert__D64_D8(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->integers8[to] = (int8_t)container->integers64[from];
}
static void convert__D64_U8(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->uintegers8[to] = (uint8_t)container->integers64[from];
}
static void convert__D64_D16(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->integers16[to] = (int16_t)container->integers64[from];
}
static void convert__D64_U16(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->uintegers16[to] = (uint16_t)container->integers64[from];
}
static void convert__D64_D32(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->integers32[to] = (int32_t)container->integers64[from];
}
static void convert__D64_U32(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->uintegers32[to] = (uint32_t)container->integers64[from];
}
static void convert__D64_U64(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->uintegers64[to] = (uint64_t)container->integers64[from];
}

/* From U64 (uint64_t) */
static void convert__U64_F32(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->reals32[to] = (float)container->uintegers64[from];
}
static void convert__U64_F64(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->reals64[to] = (double)container->uintegers64[from];
}
static void convert__U64_D8(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->integers8[to] = (int8_t)container->uintegers64[from];
}
static void convert__U64_U8(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->uintegers8[to] = (uint8_t)container->uintegers64[from];
}
static void convert__U64_D16(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->integers16[to] = (int16_t)container->uintegers64[from];
}
static void convert__U64_U16(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->uintegers16[to] = (uint16_t)container->uintegers64[from];
}
static void convert__U64_D32(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->integers32[to] = (int32_t)container->uintegers64[from];
}
static void convert__U64_U32(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->uintegers32[to] = (uint32_t)container->uintegers64[from];
}
static void convert__U64_D64(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->integers64[to] = (int64_t)container->uintegers64[from];
}


/*
 * Boolean <-> numeric conversions.
 *
 * Numeric -> boolean (lossy, prefixed with '_'):
 *     any non-zero numeric value is considered 'true'.
 * Boolean -> numeric (lossless):
 *     'true' becomes 1, 'false' becomes 0.
 */

/* Numeric -> B (int) */
static void convert__F32_B(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->booleans[to] = (fabsf(container->reals32[from]) > (float)container->tolerance);
}
static void convert__F64_B(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->booleans[to] = (fabs(container->reals64[from]) > container->tolerance);
}
static void convert__D8_B(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->booleans[to] = (container->integers8[from] != 0);
}
static void convert__U8_B(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->booleans[to] = (container->uintegers8[from] != 0);
}
static void convert__D16_B(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->booleans[to] = (container->integers16[from] != 0);
}
static void convert__U16_B(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->booleans[to] = (container->uintegers16[from] != 0);
}
static void convert__D32_B(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->booleans[to] = (container->integers32[from] != 0);
}
static void convert__U32_B(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->booleans[to] = (container->uintegers32[from] != 0);
}
static void convert__D64_B(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->booleans[to] = (container->integers64[from] != 0);
}
static void convert__U64_B(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->booleans[to] = (container->uintegers64[from] != 0);
}

/* Numeric -> B1 (bool) */
static void convert__F32_B1(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->booleans1[to] = (fabsf(container->reals32[from]) > (float)container->tolerance);
}
static void convert__F64_B1(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->booleans1[to] = (fabs(container->reals64[from]) > container->tolerance);
}
static void convert__D8_B1(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->booleans1[to] = (container->integers8[from] != 0);
}
static void convert__U8_B1(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->booleans1[to] = (container->uintegers8[from] != 0);
}
static void convert__D16_B1(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->booleans1[to] = (container->integers16[from] != 0);
}
static void convert__U16_B1(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->booleans1[to] = (container->uintegers16[from] != 0);
}
static void convert__D32_B1(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->booleans1[to] = (container->integers32[from] != 0);
}
static void convert__U32_B1(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->booleans1[to] = (container->uintegers32[from] != 0);
}
static void convert__D64_B1(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->booleans1[to] = (container->integers64[from] != 0);
}
static void convert__U64_B1(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->booleans1[to] = (container->uintegers64[from] != 0);
}

/* B (int) -> Numeric (result is 0 or 1, lossless) */
static void convert_B_F32(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->reals32[to] = container->booleans[from] ? 1.0f : 0.0f;
}
static void convert_B_F64(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->reals64[to] = container->booleans[from] ? 1.0 : 0.0;
}
static void convert_B_D8(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->integers8[to] = container->booleans[from] ? 1 : 0;
}
static void convert_B_U8(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->uintegers8[to] = container->booleans[from] ? 1 : 0;
}
static void convert_B_D16(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->integers16[to] = container->booleans[from] ? 1 : 0;
}
static void convert_B_U16(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->uintegers16[to] = container->booleans[from] ? 1 : 0;
}
static void convert_B_D32(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->integers32[to] = container->booleans[from] ? 1 : 0;
}
static void convert_B_U32(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->uintegers32[to] = container->booleans[from] ? 1 : 0;
}
static void convert_B_D64(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->integers64[to] = container->booleans[from] ? 1 : 0;
}
static void convert_B_U64(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->uintegers64[to] = container->booleans[from] ? 1 : 0;
}

/* B1 (bool) -> Numeric (result is 0 or 1, lossless) */
static void convert_B1_F32(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->reals32[to] = container->booleans1[from] ? 1.0f : 0.0f;
}
static void convert_B1_F64(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->reals64[to] = container->booleans1[from] ? 1.0 : 0.0;
}
static void convert_B1_D8(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->integers8[to] = container->booleans1[from] ? 1 : 0;
}
static void convert_B1_U8(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->uintegers8[to] = container->booleans1[from] ? 1 : 0;
}
static void convert_B1_D16(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->integers16[to] = container->booleans1[from] ? 1 : 0;
}
static void convert_B1_U16(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->uintegers16[to] = container->booleans1[from] ? 1 : 0;
}
static void convert_B1_D32(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->integers32[to] = container->booleans1[from] ? 1 : 0;
}
static void convert_B1_U32(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->uintegers32[to] = container->booleans1[from] ? 1 : 0;
}
static void convert_B1_D64(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->integers64[to] = container->booleans1[from] ? 1 : 0;
}
static void convert_B1_U64(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->uintegers64[to] = container->booleans1[from] ? 1 : 0;
}


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
