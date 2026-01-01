#include <inttypes.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>

#include "fmi3Functions.h"

#include "config.h"
#include "datalog.h"
#include "container.h"


static fmu_status_t datalog_do_step(container_t *container) {
    const datalog_t *datalog = container->datalog;
    /* write a row in datalog */
    fprintf(datalog->file, "%e", container->start_time + container->nb_steps * container->time_step);

#define LOG3(type, fmi_type, format) \
    if (datalog->nb_ ## type > 0) { \
        fmi3Get ## fmi_type (container, datalog->vr_ ## type, datalog->nb_ ## type, datalog->values_ ## type, datalog->nb_ ## type); \
        for(unsigned long i = 0; i < datalog->nb_ ## type; i += 1) \
            fprintf(datalog->file, "," format, datalog->values_ ## type [i]); \
    }
#define LOG2(type, fmi_type, format) \
    if (datalog->nb_ ## type > 0) { \
        fmi2Get ## fmi_type (container, datalog->vr_ ## type, datalog->nb_ ## type, datalog->values_ ## type); \
        for(unsigned long i = 0; i < datalog->nb_ ## type; i += 1) \
            fprintf(datalog->file, "," format, datalog->values_ ## type [i]); \
    }

    LOG3(reals64, Float64, "%lf");
    LOG3(reals32, Float32, "%f");
    LOG3(integers8, Int8, "%" PRId8);
    LOG3(uintegers8, UInt8, "%" PRIu8);
    LOG3(integers16, Int16, "%" PRId16);
    LOG3(uintegers16, UInt16, "%" PRIu16);
    LOG3(integers32, Int32, "%" PRId32);
    LOG3(uintegers32, UInt32, "%" PRIu32);
    LOG3(integers64, Int64, "%" PRId64);
    LOG3(uintegers64, UInt64, "%" PRIu64);
    LOG2(booleans, Boolean, "%d");          /* FMI 2.0 call */
    LOG3(booleans1, Boolean, "%d");
    LOG3(strings, String, "%s");
  
    /* binaries */
    if (datalog->nb_binaries > 0) {
        fmi3GetBinary(container, datalog->vr_binaries, datalog->nb_binaries, datalog->size_binaries, datalog->values_binaries, datalog->nb_binaries);
        for(unsigned long i = 0; i < datalog->nb_binaries; i += 1) {
            fprintf(datalog->file, ",");
            for(size_t j=0; j < datalog->size_binaries[i]; j += 1) {
                fprintf(datalog->file, "%02X", datalog->values_binaries[i][j]);
            }
        }
    }

    /* clocks */
    if (datalog->nb_clocks > 0) {
        fmi3GetClock(container, datalog->vr_clocks, datalog->nb_clocks, datalog->values_clocks);
        for(unsigned long i = 0; i < datalog->nb_clocks; i += 1)
            fprintf(datalog->file, ",%d", datalog->values_clocks[i]);
    }

#undef LOG2
#undef LOG3

    fprintf(datalog->file, "\n");

    /* and process a step */
    return datalog->do_step(container);
}


static datalog_t *datalog_init(void) {
#define INIT(type) \
    datalog->nb_ ## type = 0; \
    datalog->vr_ ## type = NULL; \
    datalog->values_ ## type = NULL

    datalog_t *datalog = malloc(sizeof(*datalog));
    if (datalog) {
        datalog->file = NULL;

        INIT(reals64);
        INIT(reals32);
        INIT(integers8);
        INIT(uintegers8);
        INIT(integers16);
        INIT(uintegers16);
        INIT(integers32);
        INIT(uintegers32);
        INIT(integers64);
        INIT(uintegers64);
        INIT(booleans);
        INIT(booleans1);
        INIT(strings);
        INIT(binaries);
        datalog->size_binaries = NULL;
        INIT(clocks);
    }

    return datalog;

#undef INIT
}


int datalog_configure(config_file_t *config, datalog_t *datalog) {
   logger(LOGGER_WARNING, "Container enable DATALOG.");

    if (get_line(config)) {
        logger(LOGGER_ERROR, "Cannot determine datalog file name");
        return -1;
    }

    datalog->file = fopen(config->line, "wt");
    if (!datalog->file) {
        logger(LOGGER_ERROR, "Cannot open datalog file '%s': %s", config->line, strerror(errno));
        return -2;
    }
    fprintf(datalog->file, "time");


#define READ(type) \
    if (get_line(config)) { \
        logger(LOGGER_ERROR, "Cannot determine datalog for " "real64"); \
        datalog_free(datalog); \
        return -3; \
    } \
    if (sscanf(config->line, "%lu", &datalog->nb_ ## type) < 1) { \
        logger(LOGGER_ERROR, "Cannot get datalog definition of " #type); \
        return -4; \
    } \
    datalog->vr_ ## type = malloc(datalog->nb_ ## type * sizeof(*datalog->vr_ ## type)); \
    datalog->values_ ## type = malloc(datalog->nb_ ## type * sizeof(*datalog->values_ ## type)); \
    if (!datalog->vr_ ## type || !datalog->values_## type) { \
        logger(LOGGER_ERROR, "Cannot allocate memory for definition of " #type); \
        return -5; \
    } \
    for(unsigned long i=0; i < datalog->nb_ ## type; i += 1) { \
        int offset = 0; \
        if (get_line(config)) { \
            logger(LOGGER_ERROR, "Cannot get definition of " #type); \
            return -6; \
        } \
        if (sscanf(config->line, "%d %n", &datalog->vr_ ## type [i], &offset) < 1) { \
            logger(LOGGER_ERROR, "Cannot read definition of " #type); \
            return -7; \
        } \
        fprintf(datalog->file, ",%s", config->line+offset); \
    }

    READ(reals64);
    READ(reals32);
    READ(integers8);
    READ(uintegers8);
    READ(integers16);
    READ(uintegers16);
    READ(integers32);
    READ(uintegers32);
    READ(integers64);
    READ(uintegers64);
    READ(booleans);
    READ(booleans1);
    READ(strings);
    READ(binaries);
    if (datalog->nb_binaries > 0) {
        datalog->size_binaries = malloc(datalog->nb_binaries * sizeof(*datalog->size_binaries));
        if (! datalog->size_binaries) {
            logger(LOGGER_ERROR, "Cannot allocate memory for size of binaries");
            return -5;
        }
    }
    READ(clocks);

    fprintf(datalog->file, "\n");

    return 0;
}


datalog_t *datalog_new(container_t *container, const char *dirname) {
    config_file_t config;

    if (config_file_open(&config, dirname, "datalog.txt"))
        return NULL;

    datalog_t *datalog = datalog_init();
    if (!datalog) {
        logger(LOGGER_ERROR, "Cannot allocate datalog memory.");
        config_file_close(&config);
        return NULL;
    }
    if (datalog_configure(&config, datalog)) {
        datalog_free(datalog);
        datalog = NULL;
    } else {
        datalog->do_step = container->do_step;
        container->do_step = datalog_do_step; 
    }

    config_file_close(&config);
      
    return datalog;

#undef READ
}


void datalog_free(datalog_t *datalog) {
#define FREE(type) \
    free(datalog->vr_ ## type); \
    free(datalog->values_ ## type)

    if (datalog) {
        if (datalog->file)
            fclose(datalog->file);
        
        FREE(reals64);
        FREE(reals32);
        FREE(integers8);
        FREE(uintegers8);
        FREE(integers16);
        FREE(uintegers16);
        FREE(integers32);
        FREE(uintegers32);
        FREE(integers64);
        FREE(uintegers64);
        FREE(booleans);
        FREE(booleans1);
        FREE(strings);
        FREE(binaries);
        free(datalog->size_binaries);
        FREE(clocks);

        free(datalog);
    }
    return;
#undef FREE
}
