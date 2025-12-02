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

/*
 * Implementation of the fmu2Component/fmu3Instance depending on FMUContainer
 * configuration.
 */


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
        SET_START(Real32, reals32);
        SET_START(Integer8, integers8);
        SET_START(UInteger8, uintegers8);
        SET_START(Integer16, integers16);
        SET_START(UInteger16, uintegers16);
        SET_START(Integer32, integers32);
        SET_START(UInteger32, uintegers32);
        SET_START(Integer64, integers64);
        SET_START(UInteger64, uintegers64);
        SET_START(Boolean, booleans);
        SET_START(Boolean1, booleans1);
        SET_START(String, strings);
        /* binaries and clocks don't support start values here */
#undef SET_START
    }
    logger(LOGGER_DEBUG, "Start values are set.");
    return;
}


void container_init_values(container_t* container) {
    for (int i = 0; i < container->nb_fmu; i += 1) {
        fmu_get_outputs(&container->fmu[i]);
    }

    return;
}


static int is_close (const container_t *container, double r1, double r2) {
    return fabs(r1-r2) < container->tolerance;
}


static double container_get_next_clock_time(container_t *container, double timestep) {
    fmi3Float64 *event_time = container->local_clocks.buffer_time;
    fmi3IntervalQualifier *event_qualifier = container->local_clocks.buffer_qualifier;
    fmu_vr_t *fmu_vr = container->local_clocks.fmu_vr;

    const unsigned long *local_clock_index = container->local_clocks.local_clock_index;
    unsigned long nb_events = 0;
    double interval = timestep;

    /* Get all clocks intervals */
    for(int i = 0; i < container->local_clocks.nb_fmu; i += 1) {
        container_clock_counter_t *counter = &container->local_clocks.counter[i]; 
        const fmu_t *fmu = &container->fmu[counter->fmu_id];

        fmu->fmi_functions.version_3.fmi3GetIntervalDecimal(fmu->component, fmu_vr, counter->nb,
            event_time,
            event_qualifier);

        fmu_vr += counter->nb;
        event_time += counter->nb;
        event_qualifier += counter->nb;
    }

    /* get next defined events (may be several) */
    event_time = container->local_clocks.buffer_time;
    event_qualifier = container->local_clocks.buffer_qualifier;

    for(unsigned long i = 0; i < container->local_clocks.nb_local_clocks; i += 1) {
        if (event_qualifier[i] != fmi3IntervalNotYetKnown) {
            if (nb_events) {
                if (is_close(container, event_time[i], interval)) {
                    /* found a event on the same time */
                    container->local_clocks.next_clocks[nb_events++] = local_clock_index[i];
                } else if (event_time[i] < interval) {
                    /* found a event earlier */
                    nb_events = 0;
                    container->local_clocks.next_clocks[nb_events++] = local_clock_index[i];
                    interval = event_time[i];
                }
            } else {
                /* first event found */
                container->local_clocks.next_clocks[nb_events++] = local_clock_index[i];
                interval = event_time[i];
            }
        }
    }

    container->local_clocks.nb_next_clocks = nb_events;
    if (container->local_clocks.nb_next_clocks > 0)
        logger(LOGGER_ERROR, "**** %d EVENTS SCHEDULED: %e", container->local_clocks.nb_next_clocks, interval);

    return interval;
}


static fmu_status_t proceed_event(container_t *container) {
    int event_occured = 0;

    /* Reset all (local) clocks */
    for(unsigned long i = 0; i < container->local_clocks.nb_local_clocks; i += 1) {
        logger(LOGGER_ERROR, "* Deactivate clocks %lu", container->local_clocks.local_clock_index[i]);
        container->clocks[container->local_clocks.local_clock_index[i]] = fmi3ClockInactive;
    }

    /* Activate clocks of next event */
    for(unsigned long i = 0; i < container->local_clocks.nb_next_clocks; i += 1) {
        logger(LOGGER_ERROR, "* Activate clocks %lu", container->local_clocks.next_clocks[i]);
        container->clocks[container->local_clocks.next_clocks[i]] = fmi3ClockActive;
    }
    container->local_clocks.nb_next_clocks = 0;

    /* Progate data due to clocks */
    /*
    if (event_occured) {
        for (int i = 0; i < container->nb_fmu; i += 1) {
            fmu_t* fmu = &container->fmu[i];
            
            fmu_status_t status = fmu_set_inputs(fmu);
            if (status != FMU_STATUS_OK) {
                logger(LOGGER_ERROR, "Container: FMU#%d failed set inputs.", i);
                return status;
            }
        }
    }
    */
    return FMU_STATUS_OK;
}


static fmu_status_t container_do_step_sequential(container_t *container) {
    fmu_status_t status = FMU_STATUS_OK;
    double time = container->time_step * container->nb_steps + container->start_time;
    double target_time = time + container->time_step;

    logger(LOGGER_ERROR, "****");
    logger(LOGGER_ERROR, "**** TIME = %e", time);
    logger(LOGGER_ERROR, "****");

    while(! is_close(container, time, target_time)) {
        double time_step = target_time - time;
        double event_interval = container_get_next_clock_time(container, time_step);
        if (event_interval < time_step)
            time_step = event_interval;

        logger(LOGGER_ERROR, "* doStep(time=%e -> timestep=%e)", time, time+time_step);

        for (int i = 0; i < container->nb_fmu; i += 1) {
            fmu_t* fmu = &container->fmu[i];
            
            if (! container->inputs_set) {
                status = fmu_set_inputs(fmu);
                if (status != FMU_STATUS_OK) {
                    logger(LOGGER_ERROR, "Container: FMU#%d failed set inputs.", i);
                    return status;
                }
            }
                
            /* COMPUTATION */
            status = fmuDoStep(fmu, time, time_step);
            if (status != FMU_STATUS_OK)
                return status;

            status = fmu_get_outputs(fmu);
            if (status != FMU_STATUS_OK) {
                logger(LOGGER_ERROR, "Container: FMU#%d failed getting outputs.", i);
                return status;
            }
        }
        logger(LOGGER_ERROR, "** doStep ok.");
 
        int need_event_update = 0;
        for (int i = 0; i < container->nb_fmu; i += 1) {
            fmu_t* fmu = &container->fmu[i];
            if (fmu->need_event_udpate) {
                need_event_update = 1;
                break;
            }
        }

        proceed_event(container);
        if (need_event_update) {
            logger(LOGGER_ERROR, "** Event mode...");
            for(int i = 0; i < container->nb_fmu; i += 1) {
                fmu_t* fmu = &container->fmu[i];

                if (fmu->support_event) {
                    fmi3Status status = fmu->fmi_functions.version_3.fmi3EnterEventMode(fmu->component);
                    if (status != fmi3OK) {
                        logger(LOGGER_ERROR, "Cannot enter in Event mode for fmu %s", fmu->name);
                        return FMU_STATUS_ERROR;
                    }
                    fmuUpdateDiscreteStates(fmu);
                }
            }
            container->inputs_set = 1;
        } else
            container->inputs_set = 0;
            
        logger(LOGGER_ERROR, "** Event mode ok.");

        time += time_step;
    }

 
    container->nb_steps += 1;

    logger(LOGGER_ERROR, "container_do_step_sequential()- DONE");
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
            logger(LOGGER_ERROR, "Container: FMU#%d failed getting outputs.", i);
            return FMU_STATUS_ERROR;
        }
    }
    container->nb_steps += 1;
    return status;
}


static fmu_status_t container_do_step_parallel(container_t* container) {
    fmu_status_t status = FMU_STATUS_OK;

    for (size_t i = 0; i < container->nb_fmu; i += 1) {          
        status = fmu_set_inputs(&container->fmu[i]);
        if (status != FMU_STATUS_OK) {
            logger(LOGGER_ERROR, "Container: FMU#%d failed set inputs.", i);
            return status;
        }
    }

    double time = container->time_step * container->nb_steps + container->start_time;
    for (size_t i = 0; i < container->nb_fmu; i += 1) {
        fmu_t* fmu = &container->fmu[i];
        /* COMPUTATION */
        status = fmuDoStep(fmu, time, container->time_step);
        if (status != FMU_STATUS_OK) {
            logger(LOGGER_ERROR, "Container: FMU#%d failed doStep.", i);
            return status;
        }
    }

    for (size_t i = 0; i < container->nb_fmu; i += 1) {
        status = fmu_get_outputs(&container->fmu[i]);
        if (status != FMU_STATUS_OK) {
            logger(LOGGER_ERROR, "Container: FMU#%d failed get outputs.", i);
            return status;
        }
    }
    container->nb_steps += 1;
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

    container->fmu = calloc(nb_fmu, sizeof(*container->fmu));
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
        int support_event = 0;
        for(int i=0; i < strlen(name); i += 1) {
            if (name[i] == ' ') {
                name[i] = '\0';
                if (sscanf(name+i+1, "%d %d", &fmi_version, &support_event) < 2) {
                    logger(LOGGER_ERROR, "Cannot read FMU flags from %s", name+i+1);
                    return -2;
                }
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

        int status = fmu_load_from_directory(container, i, directory, name, identifier, guid, fmi_version, support_event);
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

    if (sscanf(file->line, "%lu %lu %lu %lu %lu %lu %lu %lu %lu %lu %lu %lu %lu %lu %lu",
        &container->nb_local_reals64,
        &container->nb_local_reals32,
        &container->nb_local_integers8,
        &container->nb_local_uintegers8,
        &container->nb_local_integers16,
        &container->nb_local_uintegers16,
        &container->nb_local_integers32,
        &container->nb_local_uintegers32,
        &container->nb_local_integers64,
        &container->nb_local_uintegers64,
        &container->nb_local_booleans,
        &container->nb_local_booleans1,
        &container->nb_local_strings,
        &container->nb_local_binaries,
        &container->nb_local_clocks) < 15) {
        logger(LOGGER_ERROR, "Cannort read container I/O '%s'.", file->line);
        return -1;
    }

#define ALLOC(type, value) \
    if (container->nb_local_ ## type) { \
        container-> type = malloc(container->nb_local_ ## type * sizeof(*container-> type)); \
        if (!container-> type) { \
            logger(LOGGER_ERROR, "Read container local: Memory exhauseted."); \
            return -2; \
        } \
        for(unsigned long i=0; i < container->nb_local_ ## type; i += 1) \
            container-> type [i] = value; \
    } else \
        container-> type = NULL
    
    ALLOC(reals64, 0.0);
    ALLOC(reals32, 0.0);
    ALLOC(integers8, 0);
    ALLOC(uintegers8, 0);
    ALLOC(integers16, 0);
    ALLOC(uintegers16, 0);
    ALLOC(integers32, 0);
    ALLOC(uintegers32, 0);
    ALLOC(integers64, 0);
    ALLOC(uintegers64, 0);
    ALLOC(booleans, 0);
    ALLOC(booleans1, false);
    ALLOC(strings, NULL);
    /* Strings cannot be NULL */
    for (unsigned long i = 0; i < container->nb_local_strings; i += 1)
        container->strings[i] = strdup("");
    
    if (container->nb_local_binaries) {
        container->binaries = malloc(container->nb_local_binaries * sizeof(*container->binaries));
        if (!container->binaries) {
            logger(LOGGER_ERROR, "Read container local: Memory exhauseted."); \
            return -2;
        }
        for(unsigned long i=0; i < container->nb_local_binaries; i += 1) {
            container->binaries[i].max_size = 0;
            container->binaries[i].max_size = 0;
            container->binaries[i].data = NULL;
        }
    } else
        container->binaries = NULL;

    ALLOC(clocks, false);
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
            logger(LOGGER_ERROR, "Memory exhausted."); \
            return -1; \
        } \
        int vr_counter = 0; \
        for (unsigned long i = 0; i < container->nb_ports_ ## type; i += 1) { \
            container_port_t port; \
            fmu_vr_t vr; \
            int offset; \
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
            vr &= 0xFFFFFF; \
            if (vr < container->nb_ports_ ## type) \
                container->port_ ##type[vr] = port; \
            else { \
                logger(LOGGER_ERROR, "Cannot read I/O " #type ": too many links!"); \
                return -8; \
            } \
        } \
    } else { \
        container->vr_ ## type = NULL; \
        container->port_ ## type = NULL; \
    }


    unsigned long nb_links;

    READ_CONF_IO(reals64);
    READ_CONF_IO(reals32);
    READ_CONF_IO(integers8);
    READ_CONF_IO(uintegers8);
    READ_CONF_IO(integers16);
    READ_CONF_IO(uintegers16);
    READ_CONF_IO(integers32);
    READ_CONF_IO(uintegers32);
    READ_CONF_IO(integers64);
    READ_CONF_IO(uintegers64);
    READ_CONF_IO(booleans);
    READ_CONF_IO(booleans1);
    READ_CONF_IO(strings);
    READ_CONF_IO(binaries);
    READ_CONF_IO(clocks);

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
            fmu_io-> type . causality .translations[i].vr &= 0xFFFFFF; \
        } \
    }

#define READER_FMU_CLOCKED_IO(type, causality) \
    if (get_line(file)) { \
        logger(LOGGER_ERROR, "Cannot get FMU description for 'clocked " #type "' (" #causality ")"); \
        return -1; \
    } \
    fmu_io->clocked_ ## type . causality = NULL; \
\
    if (sscanf(file->line, "%lu %lu", \
               &fmu_io->clocked_ ## type .nb_ ## causality, \
               &nb_clocked) < 2) { \
        logger(LOGGER_ERROR, "Cannot interpret FMU description for 'clocked " #type "' (" #causality ")"); \
        return -2; \
    }\
\
    if (fmu_io->clocked_ ## type .nb_ ## causality > 0) { \
        fmu_io->clocked_ ## type . causality  = malloc(fmu_io->clocked_ ## type .nb_ ## causality * sizeof(*fmu_io->clocked_ ## type . causality)); \
        if (! fmu_io->clocked_ ## type . causality) { \
            logger(LOGGER_ERROR, "Read FMU I/O: Memory exhauseted."); \
            return -3; \
        } \
\
        for(unsigned long i = 0; i < fmu_io->clocked_ ## type .nb_ ## causality; i += 1) { \
            if (get_line(file)) { \
                logger(LOGGER_ERROR, "Cannot get FMU I/O for 'clocked " #type "' (" #causality ")"); \
                return -4; \
            } \
\
            int offset = 0; \
            if (sscanf(file->line, "%u %ld%n", \
                &fmu_io->clocked_ ## type . causality [i].clock_vr, \
                &fmu_io->clocked_ ## type . causality [i].translations_list.nb, &offset) < 2) { \
                logger(LOGGER_ERROR, "Cannot interpret FMU I/O for 'clocked " #type "' (" #causality ")"); \
                return -5; \
            } \
            fmu_io->clocked_ ## type . causality [i].clock_vr &= 0xFFFFFF; \
            fmu_io->clocked_ ## type . causality [i].translations_list.translations = malloc( \
                fmu_io->clocked_ ## type . causality [i].translations_list.nb * sizeof(*fmu_io->clocked_ ## type . causality [i].translations_list.translations)); \
            if (!fmu_io->clocked_ ## type . causality [i].translations_list.translations) { \
                logger(LOGGER_ERROR, "Read FMU I/O: Memory exhauseted."); \
                return -5; \
            } \
            for(unsigned long j = 0; j < fmu_io->clocked_ ## type . causality [i].translations_list.nb; j += 1) { \
                int read; \
                if (sscanf(file->line+offset, "%u %u%n", \
                    &fmu_io->clocked_ ## type . causality [i].translations_list.translations[j].vr, \
                    &fmu_io->clocked_ ## type . causality [i].translations_list.translations[j].fmu_vr, \
                    &read) < 2) { \
                    logger(LOGGER_ERROR, "Cannot interpret details of FMU I/O for 'clocked " #type "' (" #causality ")"); \
                } \
                offset += read; \
                fmu_io->clocked_ ## type . causality [i].translations_list.translations[j].vr &= 0xFFFFFF; \
            }\
        } \
    }



static int read_conf_fmu_io_in(fmu_io_t* fmu_io, config_file_t* file) {
    unsigned long nb_clocked;

#define READER_FMU_IN(type) \
    READER_FMU_IO(type, in); \
    READER_FMU_CLOCKED_IO(type, in)

    READER_FMU_IN(reals64);
    READER_FMU_IN(reals32);
    READER_FMU_IN(integers8);
    READER_FMU_IN(uintegers8);
    READER_FMU_IN(integers16);
    READER_FMU_IN(uintegers16);
    READER_FMU_IN(integers32);
    READER_FMU_IN(uintegers32);    
    READER_FMU_IN(integers64);
    READER_FMU_IN(uintegers64);
    READER_FMU_IN(booleans);
    READER_FMU_IN(booleans1);
    READER_FMU_IN(strings);
    READER_FMU_IN(binaries);
    READER_FMU_IO(clocks, in); /* clock variables cannot be clocked ! */

#undef READER_FMU_IN

    return 0;
}


static int read_conf_fmu_io_out(fmu_io_t* fmu_io, config_file_t* file) {
    unsigned long nb_clocked;

#define READER_FMU_OUT(type) \
    READER_FMU_IO(type, out); \
    READER_FMU_CLOCKED_IO(type, out)


    READER_FMU_OUT(reals64);
    READER_FMU_OUT(reals32);
    READER_FMU_OUT(integers8);
    READER_FMU_OUT(uintegers8);
    READER_FMU_OUT(integers16);
    READER_FMU_OUT(uintegers16);
    READER_FMU_OUT(integers32);
    READER_FMU_OUT(uintegers32);    
    READER_FMU_OUT(integers64);
    READER_FMU_OUT(uintegers64);
    READER_FMU_OUT(booleans);
    READER_FMU_OUT(booleans1);
    READER_FMU_OUT(strings);
    READER_FMU_OUT(binaries);
    READER_FMU_IO(clocks, out); /* clock variables cannot be clocked ! */

#undef READER_FMU_OUT

    return 0;
}
#undef READER_FMU_IO


static int read_conf_fmu_start_values_booleans1(fmu_io_t* fmu_io, config_file_t* file) {

    if (get_line(file))
        return -1;

    fmu_io->start_booleans1.start_values = NULL;
    fmu_io->start_booleans1.nb = 0;
    

    if (sscanf(file->line, "%lu", &fmu_io->start_booleans1.nb) < 1)
        return -2;
                
    if (fmu_io->start_booleans1.nb == 0)
        return 0;
                    
    fmu_io->start_booleans1.start_values = malloc(fmu_io->start_booleans1.nb * sizeof(*fmu_io->start_booleans1.start_values));
    if (!fmu_io->start_booleans1.start_values)
        return -3;

    for (unsigned long i = 0; i < fmu_io->start_booleans1.nb; i += 1) {
        if (get_line(file))
            return -4;
        int boolean;

        if (sscanf(file->line, "%u %d %d", &fmu_io->start_booleans1.start_values[i].vr, &fmu_io->start_booleans1.start_values[i].reset, &boolean) < 3)
            return -5;
        fmu_io->start_booleans1.start_values[i].value = boolean;
    }

    return 0;
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


/*
 * # Start values of bb_velocity.fmu - Real: <FMU_VR> <RESET> <VALUE>
 * 0
 */
static int read_conf_fmu_start_values(fmu_io_t* fmu_io, config_file_t* file) {
    READER_FMU_START_VALUES(reals64,     "%lf");
    READER_FMU_START_VALUES(reals32,     "%f");
    READER_FMU_START_VALUES(integers8,   "%hhd");
    READER_FMU_START_VALUES(uintegers8,  "%hhu");
    READER_FMU_START_VALUES(integers16,  "%hd");
    READER_FMU_START_VALUES(uintegers16, "%hu");
    READER_FMU_START_VALUES(integers32,  "%d");
    READER_FMU_START_VALUES(uintegers32, "%d");
    READER_FMU_START_VALUES(integers64,  "%lld");
    READER_FMU_START_VALUES(uintegers64, "%llu");
    READER_FMU_START_VALUES(booleans,    "%d");

    int status;

    status = read_conf_fmu_start_values_booleans1(fmu_io, file);
    if (status)
        return status;

    status = read_conf_fmu_start_values_strings(fmu_io, file);
    if (status)
        return status;

    return 0;
}
#undef READER_FMU_START_VALUE


static int read_conf_fmu_conversion(fmu_t *fmu, config_file_t* file) {
    unsigned long nb;

    if (get_line(file)) {
        logger(LOGGER_ERROR, "Cannot read conversion table.");
        return -1;
    }

    if (sscanf(file->line, "%lu", &nb) < 1) {
        logger(LOGGER_ERROR, "Cannot get size of conversion table.");
        return -2;
    }

    fmu->conversions = convert_new(nb);
    if (nb && !fmu->conversions) {
        logger(LOGGER_ERROR, "Cannot allocate conversion table for %lu entries.", nb);
        return -3;
    }

    for(unsigned long i = 0; i < nb; i += 1) {
        int offset;
        fmu_vr_t from;
        fmu_vr_t to;

        if (get_line(file)) {
            logger(LOGGER_ERROR, "Cannot read conversion table entries.");
            return -4;
        }
        

        if (sscanf(file->line, "%u %u %n", &from, &to, &offset) < 2) {
            logger(LOGGER_ERROR, "Cannot read conversion table entry %lu from '%s'", i, file->line);
            return -5;
        }
        fmu->conversions->entries[i].from = from & 0xFFFFFF;
        fmu->conversions->entries[i].to = to & 0xFFFFFF;

        fmu->conversions->entries[i].function = convert_function_get(file->line+offset);
        if (!fmu->conversions->entries[i].function) {
            logger(LOGGER_ERROR, "Cannot configure conversion entry %lu from '%s'", i, file->line+offset);
            return -6;
        }
    }

    return 0;
}


static int read_conf_fmu_io(fmu_t* fmu, config_file_t* file) {

    if (read_conf_fmu_io_in(&fmu->fmu_io, file))
        return -1;

    if (read_conf_fmu_start_values(&fmu->fmu_io, file))
        return -2;

    if (read_conf_fmu_io_out(&fmu->fmu_io, file))
        return -3;

    if (read_conf_fmu_conversion(fmu, file))
        return -4;

    return 0;
}


static int read_conf_clocks(container_t *container, config_file_t *file) {
    container->local_clocks.nb_fmu = 0;
    container->local_clocks.nb_local_clocks = 0;
    container->local_clocks.nb_next_clocks = 0;

    container->local_clocks.counter = NULL;             /* nb_fmu */
    container->local_clocks.fmu_vr = NULL;              /* nb_local_clocks */
    container->local_clocks.buffer_qualifier = NULL;    /* nb_local_clocks */
    container->local_clocks.buffer_time = NULL;         /* nb_local_clocks */
    container->local_clocks.next_clocks = NULL;         /* nb_local_clocks */
    container->local_clocks.local_clock_index = NULL;   /* nb_local_clocks */

    if (get_line(file)) {
        logger(LOGGER_ERROR, "Cannot clocks definitions.");
        return -1;
    }

    if (sscanf(file->line, "%lu %lu", &container->local_clocks.nb_fmu, &container->local_clocks.nb_local_clocks) < 1) {
        logger(LOGGER_ERROR, "Cannot get size of clocks defintions table.");
        return -2;
    }

    container->local_clocks.counter =           malloc(container->local_clocks.nb_fmu          *  sizeof(*container->local_clocks.counter));
    
    container->local_clocks.buffer_qualifier =  malloc(container->local_clocks.nb_local_clocks * sizeof(*container->local_clocks.buffer_qualifier));
    container->local_clocks.buffer_time =       malloc(container->local_clocks.nb_local_clocks * sizeof(*container->local_clocks.buffer_time));
    container->local_clocks.fmu_vr =            malloc(container->local_clocks.nb_local_clocks * sizeof(*container->local_clocks.fmu_vr));
    container->local_clocks.next_clocks =       malloc(container->local_clocks.nb_local_clocks * sizeof(*container->local_clocks.next_clocks));
    container->local_clocks.local_clock_index = malloc(container->local_clocks.nb_local_clocks * sizeof(*container->local_clocks.local_clock_index));

    if (!container->local_clocks.counter || 
        !container->local_clocks.buffer_qualifier ||
        !container->local_clocks.buffer_time ||
        !container->local_clocks.fmu_vr ||
        !container->local_clocks.next_clocks ||
        !container->local_clocks.local_clock_index) {
        logger(LOGGER_ERROR, "Cannot allocat clock buffers.");
        return -3;
    }

    unsigned long pos = 0;
    for(unsigned long i = 0; i < container->local_clocks.nb_fmu; i += 1) {
        int offset;

        if (get_line(file)) {
            logger(LOGGER_ERROR, "Cannot read clock table entries.");
            return -4;
        }
        if (sscanf(file->line, "%lu %lu %n",
            &container->local_clocks.counter[i].fmu_id,
            &container->local_clocks.counter[i].nb,
            &offset) < 2) {
            logger(LOGGER_ERROR, "Cannot interpret clock table entries.");
            return -5;
        }

        for(unsigned long j=0; j < container->local_clocks.counter[i].nb; j += 1) {
            unsigned long local_clock_index;
            int read;
            if (sscanf(file->line+offset, "%u %lu %n",
                &container->local_clocks.fmu_vr[pos],
                &local_clock_index,
                &read) < 2){
                logger(LOGGER_ERROR, "Cannot interpret clock table entries.");
                return -7;
            }
            offset += read;
            container->local_clocks.local_clock_index[pos] = local_clock_index & 0xFFFFFF;
            pos += 1;
        }
    }

    return 0;
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
    if ((container->nb_local_ ## type > 0) || (container->nb_ports_ ## type > 0)) \
        logger(LOGGER_DEBUG, "%-10s: %d local variables and %d ports", #type, container->nb_local_ ## type, container->nb_ports_ ## type)

    LOG_IO(reals64);
    LOG_IO(reals32);
    LOG_IO(integers8);
    LOG_IO(uintegers8);
    LOG_IO(integers16);
    LOG_IO(uintegers16);
    LOG_IO(integers32);
    LOG_IO(uintegers32);
    LOG_IO(integers64);
    LOG_IO(uintegers64);
    LOG_IO(booleans);
    LOG_IO(booleans1);
    LOG_IO(strings);
    LOG_IO(binaries);
    LOG_IO(clocks);
#undef LOG_IO

    for (int i = 0; i < container->nb_fmu; i += 1) {
        if (read_conf_fmu_io(&container->fmu[i], &file)) {
            fclose(file.fp);
            logger(LOGGER_ERROR, "Cannot read I/O table for FMU#%d", i);
            return -7;
        }

#define LOG_IO(orientation, type) \
    if ((container->fmu[i].fmu_io. type . orientation .nb > 0) || (container->fmu[i].fmu_io.clocked_ ## type .nb_ ## orientation > 0)) \
        logger(LOGGER_DEBUG, "FMU#%2d: %-10s: [" #orientation "] %d ports and %d clocked", i, #type, container->fmu[i].fmu_io. type . orientation .nb, container->fmu[i].fmu_io.clocked_ ## type .nb_ ## orientation);

#define LOG_IO_CLASSIC(orientation, type) \
    if (container->fmu[i].fmu_io. type . orientation .nb > 0)\
        logger(LOGGER_DEBUG, "FMU#%2d: %-10s: [" #orientation "] %d ports", i, #type, container->fmu[i].fmu_io. type . orientation .nb);
        
#define LOG_START(type) \
    if (container->fmu[i].fmu_io.start_ ## type .nb > 0) \
        logger(LOGGER_DEBUG, "FMU#%2d: %-10s: [start] %d ", i, #type, container->fmu[i].fmu_io.start_ ## type .nb);
    LOG_IO(in, reals64);
    LOG_IO(in, reals32);
    LOG_IO(in, integers8);
    LOG_IO(in, uintegers8);
    LOG_IO(in, integers16);
    LOG_IO(in, uintegers16);
    LOG_IO(in, integers32);
    LOG_IO(in, uintegers32);
    LOG_IO(in, integers64);
    LOG_IO(in, uintegers64);
    LOG_IO(in, booleans);
    LOG_IO(in, booleans1);
    LOG_IO(in, strings);
    LOG_IO(in, binaries);
    LOG_IO_CLASSIC(in, clocks);

    LOG_START(reals64);
    LOG_START(reals32);
    LOG_START(integers8);
    LOG_START(uintegers8);
    LOG_START(integers16);
    LOG_START(uintegers16);
    LOG_START(integers32);
    LOG_START(uintegers32);
    LOG_START(integers64);
    LOG_START(uintegers64);
    LOG_START(booleans);
    LOG_START(booleans1);
    LOG_START(strings);

    LOG_IO(out, reals64);
    LOG_IO(out, reals32);
    LOG_IO(out, integers8);
    LOG_IO(out, uintegers8);
    LOG_IO(out, integers16);
    LOG_IO(out, uintegers16);
    LOG_IO(out, integers32);
    LOG_IO(out, uintegers32);
    LOG_IO(out, integers64);
    LOG_IO(out, uintegers64);
    LOG_IO(out, booleans);
    LOG_IO(out, booleans1);
    LOG_IO(out, strings);
    LOG_IO(out, binaries);
    LOG_IO_CLASSIC(out, clocks);

#undef LOG_IO
#undef LOG_IO_CLASSIC
#undef LOG_START
    }

    read_conf_clocks(container, &file);
    if (container->local_clocks.nb_fmu)
        logger(LOGGER_DEBUG, "Container will tick for clocks from %lu FMUs", container->local_clocks.nb_fmu);

    fclose(file.fp);

    logger(LOGGER_DEBUG, "Instanciate embedded FMUs...");
    for (int i = 0; i < container->nb_fmu; i += 1) {
        logger(LOGGER_DEBUG, "FMU#%d: Instanciate for CoSimulation", i);
        fmu_status_t status = fmuInstantiateCoSimulation(&container->fmu[i], container->instance_name);
        if (status != FMU_STATUS_OK) {
            logger(LOGGER_ERROR, "Cannot Instantiate FMU#%d", i);
            return -8;
        }
    }

    container->integers32[0] = 1; /* TS multiplier */
    
    logger(LOGGER_DEBUG, "Container is configured.");
    return 0;
}


/*----------------------------------------------------------------------------
             C O N S T R U C T O R   /   D E S T R U C T O R
----------------------------------------------------------------------------*/

container_t *container_new(const char *instance_name, const char *fmu_uuid) {
    container_t *container = malloc(sizeof(*container));
    if (container) {
        container->allocate_memory = calloc;
        container->free_memory = free;
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
#undef INIT

        container->time_step = 0.001;
        container->nb_steps = 0;
        container->tolerance = 1.0e-8;
        container->inputs_set = 0;
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
    for (unsigned long i = 0; i < container->nb_local_strings; i += 1)
        free(container->strings[i]);
    FREE(strings);
    for (unsigned long i = 0; i < container->nb_local_binaries; i += 1)
        free(container->binaries[i].data);
    FREE(binaries);
    FREE(clocks);
#undef FREE

    free(container->local_clocks.counter);
    free(container->local_clocks.buffer_qualifier);
    free(container->local_clocks.buffer_time);
    free(container->local_clocks.fmu_vr);
    free(container->local_clocks.next_clocks);
    free(container->local_clocks.local_clock_index);

    free(container);

    return;
}
