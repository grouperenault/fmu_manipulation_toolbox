#include <errno.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "container.h"
#include "logger.h"
#include "fmu.h"
#include "version.h"

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
 
        SET_START(Real64, reals64);
        SET_START(Integer32, integers32);
        SET_START(Boolean, booleans);
        SET_START(String, strings);
#undef SET_START
    }
    logger(LOGGER_DEBUG, "Start values are set.");
    return;
}


static fmu_status_t container_do_step_sequential(container_t *container) {
    fmu_status_t status = FMU_STATUS_OK;
    double time = container->time_step * container->nb_steps + container->start_time;

    for (int i = 0; i < container->nb_fmu; i += 1) {
        fmu_t* fmu = &container->fmu[i];

        status = fmu_set_inputs(fmu);
        if (status != FMU_STATUS_OK)
            return status;
            
        /* COMPUTATION */
        status = fmuDoStep(fmu, time, container->time_step);
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

    double time = container->time_step * container->nb_steps + container->start_time;
    for (size_t i = 0; i < container->nb_fmu; i += 1) {
        const fmu_t* fmu = &container->fmu[i];
        /* COMPUTATION */
        status = fmuDoStep(fmu, time, container->time_step);
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


/*
 * # Container flags <MT> <Profiling> <Sequential>
 * 1 0 0 
 */
static int read_flags(container_t* container, config_file_t* file) {
    int mt, sequential;

    if (get_line(file)) {
        logger(LOGGER_ERROR, "Cannot read container flags.");
        return -1;
    }

    if (sscanf(file->line, "%d %d %d", &mt, &container->profiling, &sequential) < 3) {
        logger(LOGGER_ERROR, "Cannot interpret container flags '%s'.", file->line);
        return -1;
    }

    if (sequential) {
        logger(LOGGER_WARNING, "Container use SEQUENTIAL mode.");
        container->do_step = container_do_step_sequential;
    }
    else {
        if (mt) {
            logger(LOGGER_WARNING, "Container use PARALLEL mode with MULTI thread");
            container->do_step = container_do_step_parallel_mt;
        } else {
            logger(LOGGER_WARNING, "Container use PARALLEL mode with MONO thread.");
            container->do_step = container_do_step_parallel;
        }
    }

    if (container->profiling)
        logger(LOGGER_WARNING, "Container use PROFILING");

    return 0;
}


/*
 * # Internal time step in seconds
 * .001
 */
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


/*
 * # NB of embedded FMU's
 * 2
 * bb_position.fmu
 * bb_position
 * {8fbd9f16-ceaa-97ed-127f-987a60b25648}
 * bb_velocity.fmu
 * bb_velocity
 * {abf5f61d-b459-3641-3a2c-1e594b990280}
 */
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
        int fmi_version = 2;
        for(int i=0; i < strlen(name); i += 1) {
            if (name[i] == ' ') {
                name[i] = '\0';
                fmi_version = atoi(name+i+1);  
                break;
            } 
        }
      
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

        int status = fmu_load_from_directory(container, i, directory, name, identifier, guid, fmi_version);
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


/*
 * # NB local variables Real, Integer, Boolean, String
 * 1 0 1 0 
 */
static int read_conf_local(container_t* container, config_file_t* file) {
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
            logger(LOGGER_ERROR, "Read container I/O: Memory exhauseted."); \
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


/*
 * # CONTAINER I/O: <VR> <NB> <FMU_INDEX> <FMU_VR> [<FMU_INDEX> <FMU_VR>]
 * # Real
 * 3 3
 * 1 1 0 1
 * 2 1 1 0
 * 0 1 -1 0
 * # Integer
 * 0 0
 * # Boolean
 * 1 1
 * 0 1 -1 0
 * # String
 * 0 0
 */
static int read_conf_io(container_t* container, config_file_t* file) {
#define READ_CONF_IO(type) \
    if (get_line(file)) { \
        logger(LOGGER_ERROR, "Cannot read I/O " #type "."); \
        return -1;\
    } \
\
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
    }


    unsigned long nb_links;

    READ_CONF_IO(reals64);
    READ_CONF_IO(integers32);
    READ_CONF_IO(booleans);
    READ_CONF_IO(strings);

    return 0;
#undef READ_CONF_IO
}



/*
 * # Inputs of bb_position.fmu - Real: <VR> <FMU_VR>
 * 1
 * 0 0
 *
 * or
 * 
 * # Outputs of bb_position.fmu - Real: <VR> <FMU_VR>
 * 0
 */
#define READER_FMU_IO(type, causality) \
    if (get_line(file)) { \
        logger(LOGGER_ERROR, "Cannot get FMU description for '" #type "' (" #causality ")"); \
        return -1; \
    } \
\
    fmu_io-> type . causality .translations = NULL; \
\
    if (sscanf(file->line, "%lu", &fmu_io-> type . causality .nb) < 1) { \
        logger(LOGGER_ERROR, "Cannot interpret FMU description for '" #type "' (" #causality ")"); \
        return -2; \
    }\
\
    if (fmu_io-> type . causality .nb > 0) { \
        fmu_io-> type . causality .translations = malloc(fmu_io-> type . causality .nb * sizeof(*fmu_io-> type . causality .translations)); \
        if (! fmu_io-> type . causality .translations) { \
            logger(LOGGER_ERROR, "Read FMU I/O: Memory exhauseted."); \
            return -3; \
        } \
\
        for(unsigned long i = 0; i < fmu_io-> type . causality .nb; i += 1) { \
            if (get_line(file)) { \
                logger(LOGGER_ERROR, "Cannot get FMU I/O for '" #type "' (" #causality ")"); \
                return -4; \
        } \
\
            if (sscanf(file->line, "%u %u", &fmu_io-> type . causality .translations[i].vr, \
             &fmu_io-> type . causality .translations[i].fmu_vr) < 2) { \
                logger(LOGGER_ERROR, "Cannot interpret FMU I/O for '" #type "' (" #causality ")"); \
                return -5; \
            } \
        } \
    }

/*
 * # Start values of bb_velocity.fmu - Real: <FMU_VR> <RESET> <VALUE>
 * 0
 */
#define READER_FMU_START_VALUES(type, format) \
    if (get_line(file)) \
        return -1; \
\
    fmu_io->start_ ## type .start_values = NULL; \
    fmu_io->start_ ## type .nb = 0; \
\
    if (sscanf(file->line, "%lu", &fmu_io->start_ ## type .nb) < 1) \
        return -2; \
\
    if (fmu_io->start_ ## type .nb > 0) { \
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
    }

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


static int read_conf_fmu_io(fmu_io_t* fmu_io, config_file_t* file) {
    READER_FMU_IO(reals64,    in);
    READER_FMU_IO(integers32, in);
    READER_FMU_IO(booleans,   in);
    READER_FMU_IO(strings,    in);

    READER_FMU_START_VALUES(reals64,    "%lf");
    READER_FMU_START_VALUES(integers32, "%d");
    READER_FMU_START_VALUES(booleans,   "%d");
    int status = read_conf_fmu_start_values_strings(fmu_io, file);
    if (status)
        return status;

    READER_FMU_IO(reals64,    out);
    READER_FMU_IO(integers32, out);
    READER_FMU_IO(booleans,   out);
    READER_FMU_IO(strings,    out);

    return 0;

#undef READER_FMU_IO
#undef READER_FMU_START_VALUE
}


int container_configure(container_t* container, const char* dirname) {
    config_file_t file;
    char filename[CONFIG_FILE_SZ];

    logger(LOGGER_WARNING, "FMUContainer '" VERSION_TAG "'");
    strncpy(filename, dirname, sizeof(filename) - 1);
    filename[sizeof(filename) - 1] = '\0';
    strncat(filename, "/container.txt", sizeof(filename) - strlen(filename) - 1);

    logger(LOGGER_DEBUG, "Reading '%s'...", filename);
    file.fp = fopen(filename, "rt");
    if (!file.fp) {
        logger(LOGGER_ERROR, "Cannot open '%s': %s.", filename, strerror(errno));
        return -1;
    }
    if (read_flags(container, &file)) {
        fclose(file.fp);
        return -2;
    }

    if (read_conf_time_step(container, &file)) {
        fclose(file.fp);
        return -3;
    }

    if (read_conf_fmu(container, dirname, &file)) {
        fclose(file.fp);
        return -4;
    }

    if (read_conf_local(container, &file)) {
        fclose(file.fp);
        logger(LOGGER_ERROR, "Cannot allocate local variables.");
        return -5;
    }

    if (read_conf_io(container, &file)) {
        fclose(file.fp);
        logger(LOGGER_ERROR, "Cannot read translation table.");
        return -6;
    }

#define LOG_IO(type) \
    logger(LOGGER_DEBUG, "%-15s: %d local variables and %d ports", #type, container->nb_local_ ## type, container->nb_ports_ ## type)

    LOG_IO(reals64);
    LOG_IO(integers32);
    LOG_IO(booleans);
    LOG_IO(strings);
#undef LOG_IO

    for (int i = 0; i < container->nb_fmu; i += 1) {
        if (read_conf_fmu_io(&container->fmu[i].fmu_io, &file)) {
            fclose(file.fp);
            logger(LOGGER_ERROR, "Cannot read I/O table for FMU#%d", i);
            return -7;
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

    logger(LOGGER_DEBUG, "Instanciate embedded FMUs...");
    for (int i = 0; i < container->nb_fmu; i += 1) {
        logger(LOGGER_DEBUG, "FMU#%d: Instanciate for CoSimulation");
        fmu_status_t status = fmuInstantiateCoSimulation(&container->fmu[i], container->instance_name);
        if (status != FMU_STATUS_OK) {
            logger(LOGGER_ERROR, "Cannot Instantiate FMU#%d", i);
            container_free(container);
            return -8;
        }
    }

    logger(LOGGER_DEBUG, "Container is configured.");

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

#define INIT(type) \
        container->nb_local_ ## type = 0; \
        container-> type = NULL; \
        container->nb_ports_ ## type = 0; \
        container->vr_ ## type = NULL; \
        container->port_ ## type = NULL

        INIT(reals64);
        INIT(integers32);
        INIT(booleans);
        INIT(strings);
#undef INIT

        container->time_step = 0.001;
        container->nb_steps = 0;
        container->tolerance = 1.0e-8;
    }
    return container;
}


void container_free(container_t *container) {
    if (container->fmu) {
        for (int i = 0; i < container->nb_fmu; i += 1) {
            fmuFreeInstance(&container->fmu[i]);
            fmu_unload(&container->fmu[i]);
        }

        free(container->fmu);
    }

    
    free(container->instance_name);
    free(container->uuid);

#define FREE(type) \
    free(container->vr_ ## type); \
    free(container->port_ ## type); \
    free(container-> type)

    FREE(reals64);
    FREE(integers32);
    FREE(booleans);
    FREE(strings);
#undef FREE

    free(container);
}
