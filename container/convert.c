#include "convert.h"


void convert_proceed(const container_t *container, const convert_table_t *table) {

    for(unsigned long i = 0; i < table->nb; i += 1)
        table[i].function(container, table[i].from, table[i].to);

    return;
}


static void convert_F16_F32(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->reals[to] = container->reals16[from];
}


static void convert_D8_D16(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->integers16[to] = container->integers8[from];
}


static void convert_D8_U16(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->uintegers16[to] = container->integers8[from];
}


static void convert_D8_D32(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->integers[to] = container->integers8[from];
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
    container->integers[to] = container->uintegers8[from];
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
    container->integers[to] = container->integers16[from];
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
    container->integers[to] = container->uintegers16[from];
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
    container->integers64[to] = container->integers[from];
}


static void convert_D32_U64(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->uintegers64[to] = container->integers[from];
}


static void convert_U32_D64(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->integers64[to] = container->uintegers32[from];
}


static void convert_U32_U64(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->uintegers64[to] = container->uintegers32[from];
}


convert_function_t convert_function_get(convert_function_id_t id) {
#define CASE(x) case CONVERT_ ## x: return convert_ ## x
    switch(id) {
        CASE(F16_F32);

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

    }
#undef CASE
    /* never reached */
    return NULL;
}
