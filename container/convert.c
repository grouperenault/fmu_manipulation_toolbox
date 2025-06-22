#include "convert.h"


void convert_proceed(const container_t *container, const convert_table_t *table) {

    for(unsigned long i = 0; i < table->nb; i += 1)
        table[i].function(container, table[i].from, table[i].to);

    return;
}


static void convert_real16_to_real32(const container_t *container, fmu_vr_t from, fmu_vr_t to) {
    container->reals[to] = container->reals16[from];
}


convert_function_t convert_function_get(int function) {
    switch(function) {
        case 0: return convert_real16_to_real32;
    }

    /* never reached */
    return NULL;
}
