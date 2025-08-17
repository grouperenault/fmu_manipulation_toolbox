#include <string.h>

#include "convert.h"
#include "container.h"
#include "logger.h"


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
    container->reals64[to] = container->reals32[from];
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
#undef CASE

    /* should not be reached */
    return NULL;
}
