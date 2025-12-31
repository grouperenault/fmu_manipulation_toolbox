#include <errno.h>
#include <stdio.h>
#include <string.h>

#include "datalog.h"
#include "container.h"

static fmu_status_t datalog_do_step(container_t *container) {
    /* write a row in datalog */
    fprintf(container->datalog->file, "%e", container->start_time + container->nb_steps * container->time_step);
    fprintf(container->datalog->file, "\n");

    /* and process a step */
    return container->datalog->do_step(container);
}


#define CONFIG_FILE_SZ			1024
typedef struct {
	FILE						*fp;
	char						line[CONFIG_FILE_SZ];
} config_file_t;


static int get_line(config_file_t* file) {
    do {
        if (!fgets(file->line, CONFIG_FILE_SZ, file->fp)) {
            file->line[0] = '\0';
            return -1;
        }
    } while (file->line[0] == '#');

    /* CHOMP() */
    if (file->line[strlen(file->line) - 1] == '\n')
        file->line[strlen(file->line) - 1] = '\0'; 
    
    return 0;
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
        INIT(clocks);
    }

    return datalog;

#undef INIT
}


datalog_t *datalog_new(container_t *container, const char *dirname) {
    datalog_t *datalog;
    char filename[1024];
    config_file_t config;

    strncpy(filename, dirname, sizeof(filename) - 1);
    filename[sizeof(filename) - 1] = '\0';
    strncat(filename, "/datalog.txt", sizeof(filename) - strlen(filename) - 1);

    config.fp = fopen(filename, "wtx");
    if (! config.fp)
        return NULL;

    logger(LOGGER_WARNING, "Container enable datalog.");
    fprintf(datalog->file, "time");
    datalog = datalog_init();
    if (!datalog) {
        logger(LOGGER_ERROR, "Cannot allocate datalog memory.");
        return NULL;
    }

    if (get_line(&config)) {
        logger(LOGGER_ERROR, "Cannot determine datalog file name");
        free(datalog);
        return NULL;
    }

    datalog->file = fopen(config.line, "wtx");
    if (!datalog) {
        logger(LOGGER_ERROR, "Cannot open datalog file '%s': %s", config.line, strerror(errno));
        free(datalog);
        return NULL;
    }

    if (get_line(&config)) {
        logger(LOGGER_ERROR, "Cannot determine datalog for " "real64");
        datalog_free(datalog);
        return NULL;
    }

#define READ(type) \
    if (sscanf(config.line, "%lu", &datalog->nb_ ## type) < 1) { \
        logger(LOGGER_ERROR, "Cannot get datalog definition of " #type); \
        datalog_free(datalog); \
        return NULL; \
    } \
    datalog->vr_ ## type = malloc(datalog->nb_ ## type * sizeof(*datalog->vr_ ## type)); \
    datalog->values_ ## type = malloc(datalog->nb_ ## type * sizeof(*datalog->values_ ## type)); \
    if (!datalog->vr_ ## type || !datalog->values_## type) { \
        logger(LOGGER_ERROR, "Cannot allocate memory for definition of " #type); \
        datalog_free(datalog); \
        return NULL; \
    } \
    for(unsigned long i=0; i < datalog->nb_ ## type; i += 1) { \
        int offset = 0; \
        if (get_line(&config)) { \
            logger(LOGGER_ERROR, "Cannot get definition of " #type); \
            datalog_free(datalog); \
            return NULL; \
        } \
        if (sscanf(config.line, "%d%n", &datalog->vr_ ## type [i], &offset) < 1) { \
            logger(LOGGER_ERROR, "Cannot read definition of " #type); \
            datalog_free(datalog); \
            return NULL; \
        } \
        fprintf(datalog->file, ",%s", config.line+offset); \
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
        READ(clocks);

    fprintf(datalog->file, "\n");
    container->do_step = datalog_do_step;   
    
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
        FREE(clocks);
        free(datalog);
    }
    return;
#undef FREE
}
