#include <errno.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>



#include "container.h"
#include "logger.h"
#include "fmu.h"

#pragma warning(disable : 4100)     /* no complain abourt unref formal param */
#pragma warning(disable : 4996)     /* no complain about strncpy/strncat */


/*----------------------------------------------------------------------------
                       D O   S T E P
----------------------------------------------------------------------------*/

void container_set_start_values(container_t* container, int early_set) {
    if (early_set)
        logger(LOGGER_DEBUG, "Setting start values...");
    else
        logger(LOGGER_DEBUG, "Re-setting some start values...");
    for (int i = 0; i < container->nb_fmu; i += 1) {
#define SET_START(fmi_type, type) \
        for(unsigned long j=0; j<container->fmu[i].fmu_io.start_ ## type .nb; j ++) { \
            if (early_set || container->fmu[i].fmu_io.start_ ## type.start_values[j].reset) \
                fmuSet ## fmi_type(&container->fmu[i], &container->fmu[i].fmu_io.start_ ## type.start_values[j].vr, 1, \
                    &container->fmu[i].fmu_io.start_ ## type.start_values[j].value); \
        }
 
        SET_START(Real, reals64);
        SET_START(Integer, integers32);
        SET_START(Boolean, booleans);
        SET_START(String, strings);
#undef SET_START
    }
    logger(LOGGER_DEBUG, "Start values are set.");
    return;
}


static fmu_status_t container_do_step_serie(container_t *container, fmi2Boolean noSetFMUStatePriorToCurrentPoint) {
    fmu_status_t status;

    for (int i = 0; i < container->nb_fmu; i += 1) {
        fmu_t* fmu = &container->fmu[i];

        status = fmu_set_inputs(fmu);
        if (status != FMU_STATUS_OK)
            return status;
            
        /* COMPUTATION */
        status = fmuDoStep(fmu, container->time, container->time_step);
        if (status != FMU_STATUS_OK)
            return status;

        status = fmu_get_outputs(fmu);
        if (status != FMU_STATUS_OK)
            return status;
        
    }

    return status;
}


static fmu_status_t container_do_step_parallel_mt(container_t* container) {
    fmu_status_t status = FMU_STATUS_OK;

    /* Launch computation for all threads*/
    for(size_t i = 0; i < container->nb_fmu; i += 1) {
        container->fmu[i].status = FMU_STATUS_ERROR;
        thread_mutex_unlock(&container->fmu[i].mutex_container);
    }

    /* Consolidate results */
    for (size_t i = 0; i < container->nb_fmu; i += 1) {
        thread_mutex_lock(&container->fmu[i].mutex_fmu);
        if (container->fmu[i].status != FMU_STATUS_OK)
            return FMU_STATUS_ERROR;
    }

    for (size_t i = 0; i < container->nb_fmu; i += 1) {
        status = fmu_get_outputs(&container->fmu[i]);
        if (status != FMU_STATUS_OK) {
            logger(LOGGER_ERROR, "Container: FMU#%d failed doStep.", i);
            return FMU_STATUS_ERROR;
        }
    }
    
    return status;
}


static fmu_status_t container_do_step_parallel(container_t* container) {
    static int set_input = 0;
    fmu_status_t status = FMU_STATUS_OK;

    for (size_t i = 0; i < container->nb_fmu; i += 1) {          
        status = fmu_set_inputs(&container->fmu[i]);
        if (status != FMU_STATUS_OK) 
            return status;
    }

    for (size_t i = 0; i < container->nb_fmu; i += 1) {
        const fmu_t* fmu = &container->fmu[i];
        /* COMPUTATION */
        status = fmuDoStep(fmu, container->time, container->time_step);
        if (status != FMU_STATUS_OK) {
            logger(LOGGER_ERROR, "Container: FMU#%d failed doStep.", i);
            return status;
        }
    }

    for (size_t i = 0; i < container->nb_fmu; i += 1) {
        status = fmu_get_outputs(&container->fmu[i]);
        if (status != FMU_STATUS_OK)
            return status;
    }
    
    return status;
}


/*----------------------------------------------------------------------------
                 R E A D   C O N F I G U R A T I O N
----------------------------------------------------------------------------*/

#define CONFIG_FILE_SZ			4096
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


static int read_mt_flag(container_t* container, config_file_t* file) {
    int mt;

    if (get_line(file))
        return -1;
    if (sscanf(file->line, "%d", &mt) < 1)
        return -2;

    if (mt) {
        logger(LOGGER_WARNING, "Container use MULTI thread");
        container->do_step = container_do_step_parallel_mt;
    } else {   
        logger(LOGGER_WARNING, "Container use MONO thread");
        container->do_step = container_do_step_parallel;
    }
    return 0;
}


static int read_profiling_flag(container_t* container, config_file_t* file) {
    if (get_line(file)) {
        logger(LOGGER_ERROR, "Cannot read profiling flag.");
        return -1;
    }

    if (sscanf(file->line, "%d", &container->profiling) < 1) {
        logger(LOGGER_ERROR, "Cannot interpret profiling flag '%s'.", file->line);
        return -1;
    }

    if (container->profiling)
        logger(LOGGER_WARNING, "Container use PROFILING");

    return 0;
}


static int read_conf_time_step(container_t* container, config_file_t* file) {
    if (get_line(file)) {
        logger(LOGGER_ERROR, "Cannot read time_step.");
        return -1;
    }

    if (sscanf(file->line, "%le", &container->time_step) < 1) {
        logger(LOGGER_ERROR, "Cannort interpret time_step '%s'.", file->line);
        return -1;
    }

    logger(LOGGER_DEBUG, "Container time_step = %e", container->time_step);

    return 0;
}


static int read_conf_fmu(container_t *container, const char *dirname, config_file_t* file) {
    int nb_fmu;

    if (get_line(file)) {
        logger(LOGGER_ERROR, "Cannot read number of embedded FMUs.");
        return -1;
    }
 
    if (sscanf(file->line, "%d", &nb_fmu) < 1) {
        logger(LOGGER_ERROR, "Cannot read number of embedded FMUs '%s'.", file->line);
        return -1;
    }

    logger(LOGGER_DEBUG, "%d FMU's to be loaded", nb_fmu);
    if (!nb_fmu) {
        container->fmu = NULL;
        return 0;
    }

    container->fmu = malloc(nb_fmu * sizeof(*container->fmu));
    if (!container->fmu) {
        logger(LOGGER_ERROR, "Memory exhausted.");
        return -1;
    }

    for (unsigned long i = 0; i < nb_fmu; i += 1) {
        char directory[CONFIG_FILE_SZ];
        snprintf(directory, CONFIG_FILE_SZ, "%s/%02lx", dirname, i);

        if (get_line(file)) {
            logger(LOGGER_ERROR, "Cannot read embedded FMU%lu's name.", i);
            return -1;
        }

        char* name = strdup(file->line);
      
        if (get_line(file)) {
            logger(LOGGER_ERROR, "Cannot read embedded FMU%lu's identifier.", i);
            return -1;
        }
        char *identifier = strdup(file->line);

        if (get_line(file)) {
            logger(LOGGER_ERROR, "Cannot read embedded FMU%lu's uuid.", i);
            return -1;
        }
        const char *guid = file->line;

        int status = fmu_load_from_directory(container, i, directory, name, identifier, guid, FMU_2); /* TODO: dynamic */
        free(identifier);
        free(name);
        if (status) {
            logger(LOGGER_ERROR, "Cannot load from directory '%s' (status=%d)", directory, status);
            free(container->fmu);
            container->fmu = NULL; /* to allow freeInstance on container */
            container->nb_fmu = 0;
            return -1;
        }

        container->nb_fmu = i + 1;  /* in case of error, free only loaded FMU */
    }

    return 0;
}


static int read_conf_io(container_t* container, config_file_t* file) {
    if (get_line(file)) {
        logger(LOGGER_ERROR, "Cannot read container I/O.");
        return -1;
    }

    if (sscanf(file->line, "%lu %lu %lu %lu",
        &container->nb_local_reals64,
        &container->nb_local_integers32,
        &container->nb_local_booleans,
        &container->nb_local_strings) < 4) {
        logger(LOGGER_ERROR, "Cannort read container I/O '%s'.", file->line);
        return -1;
    }

#define ALLOC(type, value) \
    if (container->nb_local_ ## type) { \
        container-> type = malloc(container->nb_local_ ## type * sizeof(*container-> type)); \
        if (!container-> type) { \
            logger(LOGGER_ERROR, "Memory exhauseted."); \
            return -2; \
        } \
        for(unsigned long i=0; i < container->nb_local_ ## type; i += 1) \
            container-> type [i] = value; \
    } else \
        container-> type = NULL 
    
    ALLOC(reals64, 0.0);
    ALLOC(integers32, 0);
    ALLOC(booleans, 0);
    ALLOC(strings, NULL);

#undef ALLOC

    return 0;
}


#define READ_CONF_VR(type) \
static int read_conf_vr_ ## type (container_t* container, config_file_t* file) { \
    if (get_line(file)) { \
        logger(LOGGER_ERROR, "Cannot read I/O " #type "."); \
        return -1;\
    } \
\
    unsigned long nb_links; \
    if (sscanf(file->line, "%lu %lu", &container->nb_ports_ ## type, &nb_links) < 2) { \
        logger(LOGGER_ERROR, "Cannot read I/O " #type " '%s'.", file->line); \
        return -1; \
    } \
    if (container->nb_ports_ ## type > 0) { \
        container->vr_ ## type = malloc(nb_links * sizeof(*container->vr_ ## type)); \
        container->port_ ## type = malloc(container->nb_ports_ ## type * sizeof(*container->port_ ##type)); \
        if ((!container->vr_ ## type) || (!container->port_ ## type)) { \
            logger(LOGGER_ERROR, "Memory exhauseted."); \
            return -1; \
        } \
        int vr_counter = 0; \
        for (unsigned long i = 0; i < container->nb_ports_ ## type; i += 1) { \
            container_port_t port; \
            fmu_vr_t vr; \
            int offset; \
            int fmu_id; \
            fmu_vr_t fmu_vr; \
\
            if (get_line(file)) { \
                logger(LOGGER_ERROR, "Cannot read I/O " #type " details."); \
                return -1; \
            } \
\
            if (sscanf(file->line, "%d %ld%n", &vr, &port.nb, &offset) < 2) { \
                logger(LOGGER_ERROR, "Cannot read I/O " #type " details '%s'.", file->line); \
                return -1; \
            } \
            port.links = &container->vr_ ## type [vr_counter]; \
            for(int j=0; j < port.nb; j += 1) { \
                int read; \
                if (vr_counter >= nb_links) {\
                    logger(LOGGER_ERROR, "Read %d links for %d expected.", vr_counter, nb_links); \
                    return -1; \
                }\
\
                if (sscanf(file->line+offset, " %ld %d%n", &container->vr_ ## type [vr_counter].fmu_id, \
                                                          &container->vr_ ## type [vr_counter].fmu_vr, &read) < 2) { \
                    logger(LOGGER_ERROR, "Cannot read I/O " #type " link details '%s'.", file->line+offset); \
                    return -1; \
                } \
                offset += read; \
                vr_counter += 1; \
            } \
            if (vr < container->nb_ports_ ## type) \
                container->port_ ##type[vr] = port; \
            else { \
                logger(LOGGER_ERROR, "Cannot read I/O " #type ": to many links!"); \
                return -8; \
            } \
        } \
    } else { \
        container->vr_ ## type = NULL; \
        container->port_ ## type = NULL; \
    } \
    return 0; \
}


READ_CONF_VR(reals64);
READ_CONF_VR(integers32);
READ_CONF_VR(booleans);
READ_CONF_VR(strings);

#undef READ_CONF_VR


static int read_conf_vr(container_t* container, config_file_t* file) {
    if (read_conf_vr_reals64(container, file))
        return -1;

    if (read_conf_vr_integers32(container, file))
        return -2;
    
    if (read_conf_vr_booleans(container, file))
        return -3;
    
    if (read_conf_vr_strings(container, file))
        return -4;
    
    return 0;
}

#define READER_FMU_IO(type, causality) \
static int read_conf_fmu_io_ ## causality ## _ ## type (fmu_io_t *fmu_io, config_file_t* file) { \
    if (get_line(file)) \
        return -1; \
\
    fmu_io-> type . causality .translations = NULL; \
\
    if (sscanf(file->line, "%lu", &fmu_io-> type . causality .nb) < 1) \
        return -2; \
\
    if (fmu_io-> type . causality .nb == 0) \
        return 0; \
\
    fmu_io-> type . causality .translations = malloc(fmu_io-> type . causality .nb * sizeof(*fmu_io-> type . causality .translations)); \
    if (! fmu_io-> type . causality .translations) \
        return -3; \
\
    for(unsigned long i = 0; i < fmu_io-> type . causality .nb; i += 1) { \
        if (get_line(file)) \
            return -4; \
\
        if (sscanf(file->line, "%u %u", &fmu_io-> type . causality .translations[i].vr, \
         &fmu_io-> type . causality .translations[i].fmu_vr) < 2) \
            return -5; \
    } \
\
    return 0; \
}


#define READER_FMU_START_VALUES(type, format) \
static int read_conf_fmu_start_values_ ## type (fmu_io_t *fmu_io, config_file_t* file) { \
    if (get_line(file)) \
        return -1; \
\
    fmu_io->start_ ## type .start_values = NULL; \
    fmu_io->start_ ## type .nb = 0; \
\
    if (sscanf(file->line, "%lu", &fmu_io->start_ ## type .nb) < 1) \
        return -2; \
\
    if (fmu_io->start_ ## type .nb == 0) \
        return 0; \
\
    fmu_io->start_ ## type .start_values = malloc(fmu_io->start_ ## type .nb * sizeof(*fmu_io->start_ ## type .start_values)); \
    if (! fmu_io->start_ ## type .start_values) \
        return -3; \
\
    for (unsigned long i = 0; i < fmu_io->start_ ## type .nb; i += 1) { \
        if (get_line(file)) \
            return -4; \
\
       if (sscanf(file->line, "%u %d " format, \
         &fmu_io->start_ ## type .start_values[i].vr, \
         &fmu_io->start_ ## type .start_values[i].reset, \
         &fmu_io->start_ ## type .start_values[i].value) < 3) \
            return -5; \
    } \
\
    return 0; \
}


READER_FMU_IO(reals64, in);
READER_FMU_IO(integers32, in);
READER_FMU_IO(booleans, in);
READER_FMU_IO(strings, in);

READER_FMU_START_VALUES(reals64, "%lf");
READER_FMU_START_VALUES(integers32, "%d");
READER_FMU_START_VALUES(booleans, "%d");


static char* string_token(char* buffer) {
    int len = strlen(buffer);

    for (int i = 0; i < strlen(buffer); i += 1) {
        if (buffer[i] == ' ') {
            buffer[i] = '\0';
            return buffer + i + 1;
        }
    }
    return buffer + len;
}


static int read_conf_fmu_start_values_strings(fmu_io_t* fmu_io, config_file_t* file) {

    if (get_line(file))
        return -1;

    fmu_io->start_strings.start_values = NULL;
    fmu_io->start_strings.nb = 0;
    

    if (sscanf(file->line, "%lu", &fmu_io->start_strings.nb) < 1)
        return -2;
                
    if (fmu_io->start_strings.nb == 0)
        return 0;
                    
    fmu_io->start_strings.start_values = malloc(fmu_io->start_strings.nb * sizeof(*fmu_io->start_strings.start_values));
    if (!fmu_io->start_strings.start_values)
        return -3;
                            
    for (unsigned long i = 0; i < fmu_io->start_strings.nb; i += 1)
        fmu_io->start_strings.start_values[i].value = NULL; /* in case on ealry fmuFreeInstance() */

    for (unsigned long i = 0; i < fmu_io->start_strings.nb; i += 1) {
        char buffer[CONFIG_FILE_SZ];
        buffer[0] = '\0';

        if (get_line(file))
            return -4;
    
        char *value_string = string_token(file->line);
        if (sscanf(file->line, "%u %d", &fmu_io->start_strings.start_values[i].vr, &fmu_io->start_strings.start_values[i].reset) < 2) {
            return -5;
        }
        fmu_io->start_strings.start_values[i].value = strdup(value_string);
    }

    return 0;
}


READER_FMU_IO(reals64, out);
READER_FMU_IO(integers32, out);
READER_FMU_IO(booleans, out);
READER_FMU_IO(strings, out);

#undef READER_FMU_IO
#undef READER_FMU_START_VALUE


static int read_conf_fmu_io_in(fmu_io_t* fmu_io, config_file_t* file) {
    int status;

    status = read_conf_fmu_io_in_reals64(fmu_io, file);
    if (status)
        return status * 1;
    status = read_conf_fmu_io_in_integers32(fmu_io, file);
    if (status)
        return status * 10;
    status = read_conf_fmu_io_in_booleans(fmu_io, file);
    if (status)
        return status * 100;
    status = read_conf_fmu_io_in_strings(fmu_io, file);
    if (status)
        return status * 1000;

    return 0;
}


static int read_conf_fmu_start_values(fmu_io_t* fmu_io, config_file_t* file) {
    int status;

    status = read_conf_fmu_start_values_reals64(fmu_io, file);
    if (status)
        return status * 1;
    status = read_conf_fmu_start_values_integers32(fmu_io, file);
    if (status)
        return status * 10;
    status = read_conf_fmu_start_values_booleans(fmu_io, file);
    if (status)
        return status * 100;
    status = read_conf_fmu_start_values_strings(fmu_io, file);
    if (status)
        return status * 1000;

    return 0;
}


static int read_conf_fmu_io_out(fmu_io_t* fmu_io, config_file_t* file) {
    int status;

    status = read_conf_fmu_io_out_reals64(fmu_io, file);
    if (status)
        return status * 1;
    status = read_conf_fmu_io_out_integers32(fmu_io, file);
    if (status)
        return status * 10;
    status = read_conf_fmu_io_out_booleans(fmu_io, file);
    if (status)
        return status * 100;
    status = read_conf_fmu_io_out_strings(fmu_io, file);
    if (status)
        return status * 1000;

    return 0;
}


static int read_conf_fmu_io(fmu_io_t* fmu_io, config_file_t* file) {
    int status;

    status = read_conf_fmu_io_in(fmu_io, file);
    if (status)
        return status;

    status = read_conf_fmu_start_values(fmu_io, file);
    if (status)
        return status;

    status = read_conf_fmu_io_out(fmu_io, file);
    if (status)
        return status * 10;

    return 0;
}

int container_read_conf(container_t* container, const char* dirname) {
    config_file_t file;
    char filename[CONFIG_FILE_SZ];

    strncpy(filename, dirname, sizeof(filename) - 1);
    filename[sizeof(filename) - 1] = '\0';
    strncat(filename, "/container.txt", sizeof(filename) - strlen(filename) - 1);

    logger(LOGGER_DEBUG, "Reading '%s'...", filename);
    file.fp = fopen(filename, "rt");
    if (!file.fp) {
        logger(LOGGER_ERROR, "Cannot open '%s': %s.", filename, strerror(errno));
        return -1;
    }
    if (read_mt_flag(container, &file)) {
        fclose(file.fp);
        return -2;
    }

    if (read_profiling_flag(container, &file)) {
        fclose(file.fp);
        return -2;
    }

    if (read_conf_time_step(container, &file)) {
        fclose(file.fp);
        return -2;
    }

    if (read_conf_fmu(container, dirname, &file)) {
        fclose(file.fp);
        return -3;
    }

    if (read_conf_io(container, &file)) {
        fclose(file.fp);
        logger(LOGGER_ERROR, "Cannot allocate local variables.");
        return -4;
    }

    if (read_conf_vr(container, &file)) {
        fclose(file.fp);
        logger(LOGGER_ERROR, "Cannot read translation table.");
        return -5;
    }

    logger(LOGGER_DEBUG, "Real    : %d local variables and %d ports", container->nb_local_reals64, container->nb_ports_reals64);
    logger(LOGGER_DEBUG, "Integer : %d local variables and %d ports", container->nb_local_integers32, container->nb_ports_integers32);
    logger(LOGGER_DEBUG, "Boolean : %d local variables and %d ports", container->nb_local_booleans, container->nb_ports_booleans);
    logger(LOGGER_DEBUG, "String  : %d local variables and %d ports", container->nb_local_strings, container->nb_ports_strings);

    for (int i = 0; i < container->nb_fmu; i += 1) {
        if (read_conf_fmu_io(&container->fmu[i].fmu_io, &file)) {
            fclose(file.fp);
            return -6;
        }

        logger(LOGGER_DEBUG, "FMU#%d: IN     %d reals, %d integers, %d booleans, %d strings", i,
            container->fmu[i].fmu_io.reals64.in.nb,
            container->fmu[i].fmu_io.integers32.in.nb,
            container->fmu[i].fmu_io.booleans.in.nb,
            container->fmu[i].fmu_io.strings.in.nb);
        logger(LOGGER_DEBUG, "FMU#%d: START  %d reals, %d integers, %d booleans, %d strings", i,
            container->fmu[i].fmu_io.start_reals64.nb,
            container->fmu[i].fmu_io.start_integers32.nb,
            container->fmu[i].fmu_io.start_strings.nb,
            container->fmu[i].fmu_io.start_strings.nb);
        logger(LOGGER_DEBUG, "FMU#%d: OUT    %d reals, %d integers, %d booleans, %d strings", i,
            container->fmu[i].fmu_io.reals64.out.nb,
            container->fmu[i].fmu_io.integers32.out.nb,
            container->fmu[i].fmu_io.booleans.out.nb,
            container->fmu[i].fmu_io.strings.out.nb);
    }

    fclose(file.fp);

    return 0;
}


/*----------------------------------------------------------------------------
             C O N S T R U C T O R   /   D E S T R U C T O R
----------------------------------------------------------------------------*/

container_t *container_new(const char *instance_name, const char *fmu_uuid) {
    container_t *container = malloc(sizeof(*container));
    if (container) {
        container->instance_name = strdup(instance_name);
        container->uuid = strdup(fmu_uuid);

        container->nb_fmu = 0;
        container->fmu = NULL;

        container->nb_local_reals64 = 0;
        container->nb_local_integers32 = 0;
        container->nb_local_booleans = 0;
        container->nb_local_strings = 0;
        container->reals64 = NULL;
        container->integers32 = NULL;
        container->booleans = NULL;
        container->strings = NULL;

        container->nb_ports_reals64 = 0;
        container->nb_ports_integers32 = 0;
        container->nb_ports_booleans = 0;
        container->nb_ports_strings = 0;
        container->vr_reals64 = NULL;
        container->vr_integers32 = NULL;
        container->vr_booleans = NULL;
        container->vr_strings = NULL;

        container->time_step = 0.001;
        container->time = 0.0;
        container->tolerance = 1.0e-8;

        for (int i = 0; i < container->nb_fmu; i += 1)
            container->fmu[i].component = NULL;

        for(int i = 0; i < container->nb_fmu; i += 1) {
            fmu_status_t status = fmuInstantiateCoSimulation(&container->fmu[i],
                                                             container->instance_name);
            if (status != FMU_STATUS_OK) {
                logger(LOGGER_ERROR, "Cannot Instantiate FMU#%d", i);
                container_free(container);
                return NULL;
            }
        }
    }
    return container;
}

void container_free(container_t *container) {
    if (container->fmu) {
        for (int i = 0; i < container->nb_fmu; i += 1) {
            fmuFreeInstance(&container->fmu[i]);
            fmu_unload(&container->fmu[i]);

            free(container->fmu[i].fmu_io.reals64.in.translations);
            free(container->fmu[i].fmu_io.integers32.in.translations);
            free(container->fmu[i].fmu_io.booleans.in.translations);
            free(container->fmu[i].fmu_io.strings.in.translations);

            free(container->fmu[i].fmu_io.reals64.out.translations);
            free(container->fmu[i].fmu_io.integers32.out.translations);
            free(container->fmu[i].fmu_io.booleans.out.translations);
            free(container->fmu[i].fmu_io.strings.out.translations);

            free(container->fmu[i].fmu_io.start_reals64.start_values);
            free(container->fmu[i].fmu_io.start_integers32.start_values);
            free(container->fmu[i].fmu_io.start_booleans.start_values);

            for (int j = 0; j < container->fmu[i].fmu_io.start_strings.nb; j += 1)
                free((char *)container->fmu[i].fmu_io.start_strings.start_values[j].value);
            free(container->fmu[i].fmu_io.start_strings.start_values);
        }

        free(container->fmu);
    }

    free(container->instance_name);
    free(container->uuid);

    free(container->vr_reals64);
    free(container->port_reals64);
    free(container->vr_integers32);
    free(container->port_integers32);
    free(container->vr_booleans);
    free(container->port_booleans);
    free(container->vr_strings);
    free(container->port_strings);

    free(container->reals64);
    free(container->integers32);
    free(container->booleans);
    free((void*)container->strings);

    free(container);
}
