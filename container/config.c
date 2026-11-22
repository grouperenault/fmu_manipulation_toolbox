#include <errno.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cache.h"
#include "config.h"
#include "container.h"
#include "datalog.h"
#include "file.h"
#include "fmu.h"
#include "logger.h"
#include "path.h"
#include "solver.h"
#include "version.h"

/*
 * Configuration of the container: the reading of container.txt (one config_read_*() per section, as written by
 * fmu_manipulation_toolbox/container/builder.py, see docs/developer/container-txt-format.md), the embedded FMUs
 * instantiated, the buffers of the container allocated.
 */


/* The schedule reads the interval of a clock from its FMU (fmi3GetIntervalDecimal) unless it is periodic with an
   interval declared by the modelDescription.xml. */
static inline bool config_clock_needs_interval(const container_clock_t *clock) {
    const bool periodic = clock->kind == CONTAINER_CLOCK_CONSTANT || clock->kind == CONTAINER_CLOCK_FIXED ||
                          clock->kind == CONTAINER_CLOCK_TUNABLE;
    return !periodic || (clock->declared_interval < 0.0);
}


/*----------------------------------------------------------------------------
                 R E A D   C O N F I G U R A T I O N
----------------------------------------------------------------------------*/

#define CONFIG_ERROR(message, ...)                                          \
    file_error(file, __LINE__, message __VA_OPT__(,) __VA_ARGS__) 

#define CONFIG_GETLINE                                                      \
    if (file_get_line(file)) {                                              \
        CONFIG_ERROR("Cannot read config data.");                           \
        return -1;                                                          \
    }

#define CONFIG_ALLOC(ptr, nb_elem)                                          \
    ptr = calloc(nb_elem, sizeof(*ptr));                                    \
    if (! ptr) {                                                            \
        CONFIG_ERROR("Virtual memory exhausted (" #ptr ").");               \
        return -2;                                                          \
    }


/*
 * # Version 7
 */
static int config_read_version(file_t* file) {
    int version;

    if (file_version(file, &version)) {
        CONFIG_ERROR("container.txt has no format version header: the container was built by an incompatible "
                     "version of FMU Manipulation Toolbox.");
        return -1;
    }

    if (version != CONTAINER_TXT_VERSION) {
        CONFIG_ERROR("container.txt format version %d, this runtime reads version %d: build the container again "
                     "with the version of FMU Manipulation Toolbox that provides this runtime.",
                     version, CONTAINER_TXT_VERSION);
        return -2;
    }

    return 0;
}


/*
 * # Container flags <MT> <Profiling> <Sequential>
 * 1 0 0 
 */
static int config_read_flags(container_t* container, file_t* file) {
    const logger_t *logger = &container->logger;
    int mt, sequential;
    long threshold_us;

    CONFIG_GETLINE;
    if (sscanf(file->line, "%d %d %d %ld", &mt, &container->profiling, &sequential, &threshold_us) < 4 ||
        threshold_us < 0) {
        CONFIG_ERROR("Cannot read container flags (<MT> <Profiling> <Sequential> <MT_THRESHOLD_US>).");
        return -1;
    }
    container->mt_threshold_us = (unsigned long)threshold_us;
    container_set_mode(container, sequential, mt);

    if (container->profiling)
        LOGGER_WARNING("Container uses the profiling.");

    return 0;
}


/*
 * # Internal time step in seconds
 * .001
 */
static int config_read_time_step(container_t* container, file_t* file) {
    const logger_t *logger = &container->logger;
    CONFIG_GETLINE;
    if (file_line_to_host_decimal_point(file) || sscanf(file->line, "%le", &container->time_step) < 1) {
        CONFIG_ERROR("Cannot read time_step.");
        return -1;
    }

    /*
     * paranoid check: time_step should be greater than tolerance to avoid rounding issues.
     */
    if (container->time_step < container->tolerance) {
        CONFIG_ERROR("Invalid step size: %e.", container->time_step);
        return -1;
    }

    LOGGER_DEBUG("Step size of the container: %es.", container->time_step);

    return 0;
}


/*
 * # NB of embedded FMU's: <nb_fmu_cs> <nb_fmu_me>
 * 2 1
 * # CS entries: <filename> <fmi_version> <has_event_mode> <has_configuration_mode> / <identifier> / <guid>
 * scalar2array.fmu 3 1 0
 * vec
 * {121d828d-d4dd-3c76-8227-7be1b268a801}
 * array2scalar.fmu 3 1 0
 * array
 * {e092864e-3b8e-7e1d-a4bf-ee0e4c648539}
 * # ME entries: <filename> <fmi_version> <nx> <nz> <has_configuration_mode> / <identifier> / <guid>
 * bouncing_ball.fmu 2 2 1 0
 * bb
 * {3f2a1c4e-6b8d-4f1a-9c7e-2d5b8a0f3e91}
 */

/* Returns -1 when the FMU could not be loaded (caller drops the whole array),
   -2 on a config syntax error. */
static int config_read_one_fmu(container_t *container, const char *dirname, file_t *file,
                             int index, fmu_kind_t kind) {
    const bool is_me = (kind == FMU_KIND_ME);
    char directory[FILE_SZ];
    char subdirectory[9];
    snprintf(subdirectory, sizeof(subdirectory), "%02x", index);
    directory[0] = '\0';
    if (path_join(directory, FILE_SZ, dirname, subdirectory, NULL)) {
        CONFIG_ERROR("Path of the directory of FMU#%d is too long.", index);
        return -1;
    }

    CONFIG_GETLINE;
    char *name = strdup(file->line);
    if (!name) {
        CONFIG_ERROR("Virtual memory exhausted (FMU name).");
        return -1;
    }
    int fmi_version = 2;
    int support_event = 0;
    int has_configuration_mode = 0;
    size_t nx = 0;
    size_t nz = 0;
    

    char *flags = strchr(name, ' ');
    if (flags)
        *flags++ = '\0';
    else {
        CONFIG_ERROR("Cannot read the flags of FMU '%s'.", name);
        free(name);
        return -1;
    }

    if (kind == FMU_KIND_CS) {
        /* "<filename> <fmi_version> <has_event_mode> <has_configuration_mode>": ME entries have no event flag. */
        if (sscanf(flags, "%d %d %d", &fmi_version, &support_event, &has_configuration_mode) < 3) {
            CONFIG_ERROR("Cannot read CS flags from FMU '%s'.", name);
            free(name);
            return -2;
        }
    } else {
        /* "<filename> <fmi_version> <nx> <nz> <has_configuration_mode>": ME entries carry nb continuous
           states and event indicators on the same line as the filename. */
        if (sscanf(flags, "%d %zu %zu %d", &fmi_version, &nx, &nz, &has_configuration_mode) < 4) {
            CONFIG_ERROR("Cannot read ME sizes (nb_states nb_event_indicators) for FMU '%s'.", name);
            free(name);
            return -2;
        }
    }
    if (has_configuration_mode && fmi_version != 3) {
        CONFIG_ERROR("FMU '%s': only an FMI-3 FMU has a Configuration Mode.", name);
        free(name);
        return -2;
    }

    if (file_get_line(file)) {
        CONFIG_ERROR("Cannot read config data.");
        free(name);
        return -1;
    }
    char *identifier = strdup(file->line);

    if (file_get_line(file)) {
        CONFIG_ERROR("Cannot read config data.");
        free(identifier);
        free(name);
        return -1;
    }
    char *guid = strdup(file->line); /* saved because next file_get_line would overwrite file->line */
    if (!identifier || !guid) {
        CONFIG_ERROR("Virtual memory exhausted (FMU identifier).");
        free(guid);
        free(identifier);
        free(name);
        return -1;
    }


    int status = fmu_load_from_directory(container, index, directory, name, identifier, guid,
                                         fmi_version, support_event, kind);
    free(guid);
    free(identifier);
    free(name);

    /* on a failure, the slot is released here: container_free() only releases the FMUs fully loaded */
    if (status) {
        CONFIG_ERROR("Cannot load FMU from directory '%s' (status=%d).", directory, status);
        fmu_unload(&container->fmu[index]);
        return -1;
    }

    container->fmu[index].has_configuration_mode = has_configuration_mode != 0;
    if (has_configuration_mode && (!container->fmu[index].fmi_functions.version_3.fmi3EnterConfigurationMode ||
                                   !container->fmu[index].fmi_functions.version_3.fmi3ExitConfigurationMode)) {
        CONFIG_ERROR("FMU '%s' has no API of the Configuration Mode.", container->fmu[index].name);
        fmu_unload(&container->fmu[index]);
        return -1;
    }

    if (is_me && solver_register_me(container->solver, index, nx, nz)) {
        CONFIG_ERROR("Cannot register ME dimensions for FMU '%s'.", container->fmu[index].name);
        fmu_unload(&container->fmu[index]);
        return -1;
    }

    return 0;
}


/*
 * # Initialization order of the embedded FMU's
 * <index> <index> ...      (every index of fmu[] once)
 */
static int config_read_init_order(container_t *container, file_t *file) {
    CONFIG_GETLINE;
    CONFIG_ALLOC(container->init_order, container->nb_fmu > 0 ? container->nb_fmu : 1);

    const char *cursor = file->line;
    for (int i = 0; i < container->nb_fmu; i += 1) {
        char *end;
        const long index = strtol(cursor, &end, 10);
        if ((end == cursor) || (index < 0) || (index >= container->nb_fmu)) {
            CONFIG_ERROR("Cannot read the %dth index of the initialization order.", i);
            return -1;
        }
        for (int j = 0; j < i; j += 1) {
            if (container->init_order[j] == (int)index) {
                CONFIG_ERROR("FMU#%ld is twice in the initialization order.", index);
                return -1;
            }
        }
        container->init_order[i] = (int)index;
        cursor = end;
    }
    return 0;
}


static int config_read_fmu(container_t *container, const char *dirname, file_t* file) {
    const logger_t *logger = &container->logger;
    int nb_cs, nb_me;

    CONFIG_GETLINE;
    if (sscanf(file->line, "%d %d", &nb_cs, &nb_me) < 2 || nb_cs < 0 || nb_me < 0) {
        CONFIG_ERROR("Cannot read number of embedded FMUs (<nb_fmu_cs> <nb_fmu_me>).");
        return -1;
    }

    const int nb_fmu = nb_cs + nb_me;
    LOGGER_DEBUG("%d FMUs to be loaded (%d CS, %d ME).", nb_fmu, nb_cs, nb_me);
    if (!nb_fmu) {
        container->fmu = NULL;
        return 0;
    }

    CONFIG_ALLOC(container->fmu, nb_fmu);

    /* CS entries come first, then ME entries. */
    for (int i = 0; i < nb_fmu; i += 1) {
        const fmu_kind_t kind = (i < nb_cs) ? FMU_KIND_CS : FMU_KIND_ME;
        const int status = config_read_one_fmu(container, dirname, file, i, kind);
        if (status)
            return status;  /* container_free() releases the FMUs 0 to i-1 */

        container->nb_fmu = i + 1;  /* in case of error, free only loaded FMU */
    }

    return 0;
}


/*
 * # NB local variables: real64, real32, integer8, uinteger8, integer16, uinteger16, integer32, uinteger32, integer64, uinteger64, boolean, boolean1, string, binary, clock
 * 3 0 0 0 0 0 1 0 0 0 0 0 0 0 0
 */
static int config_read_local(container_t* container, file_t* file) {
    CONFIG_GETLINE;
    if (sscanf(file->line, "%lu %lu %lu %lu %lu %lu %lu %lu %lu %lu %lu %lu %lu %lu %lu",
        &container->reals64.nb_locals,
        &container->reals32.nb_locals,
        &container->integers8.nb_locals,
        &container->uintegers8.nb_locals,
        &container->integers16.nb_locals,
        &container->uintegers16.nb_locals,
        &container->integers32.nb_locals,
        &container->uintegers32.nb_locals,
        &container->integers64.nb_locals,
        &container->uintegers64.nb_locals,
        &container->booleans.nb_locals,
        &container->booleans1.nb_locals,
        &container->strings.nb_locals,
        &container->binaries.nb_locals,
        &container->clocks.nb_locals) < 15) {
            CONFIG_ERROR("Cannot read number of local variables.");
        return -1;
    }

#define ALLOC(variable, fmi_type, c_type)                                            \
    if (container-> variable .nb_locals) {                                           \
        CONFIG_ALLOC(container-> variable .locals, container-> variable .nb_locals); \
        for(unsigned long i=0; i < container-> variable .nb_locals; i += 1)          \
            container-> variable .locals [i] = (c_type)0;                            \
    } else                                                                           \
        container-> variable .locals = NULL;
    
    FOR_ALL_NUMERIC_TYPES(ALLOC)

    /* Strings cannot be NULL */
    if (container->strings.nb_locals) {
        CONFIG_ALLOC(container->strings.locals, container->strings.nb_locals);
        for (unsigned long i = 0; i < container->strings.nb_locals; i += 1) {
            if (fmu_string_copy(&container->strings.locals[i], "")) {
                CONFIG_ERROR("Virtual memory exhausted (local strings).");
                return -2;
            }
        }
    } else
        container->strings.locals = NULL;

    /* Binaries have a complex type */
    if (container->binaries.nb_locals) {
        CONFIG_ALLOC(container->binaries.locals, container->binaries.nb_locals);
        for(unsigned long i=0; i < container->binaries.nb_locals; i += 1) {
            container->binaries.locals[i].size = 0;
            container->binaries.locals[i].max_size = 0;
            container->binaries.locals[i].data = NULL;
        }
    } else
        container->binaries.locals = NULL;

    ALLOC(clocks, Clock, bool)
#undef ALLOC

    return 0;
}


/*
 * # CONTAINER I/O: <VR> <DIM> <NB> <FMU_INDEX> <FMU_VR> [<FMU_INDEX> <FMU_VR>]
 * # Real
 * 3 3
 * 1 1 1 0 1
 * 2 1 1 1 0
 * 0 1 1 -1 0
 * # Integer
 * 0 0
 * # Boolean
 * 1 1
 * 0 1 1 -1 0
 * # String
 * 0 0
 */
static int config_read_io(container_t* container, file_t* file) {
    unsigned long nb_links;

#define READ_CONF_IO(variable, fmi_type, c_type)                                                                \
    CONFIG_GETLINE;                                                                                             \
    if (sscanf(file->line, "%lu %lu", &container-> variable .nb_ports, &nb_links) < 2) {                        \
        CONFIG_ERROR("Cannot read container I/O " #variable ".");                                               \
        return -1;                                                                                              \
    }                                                                                                           \
    if (container-> variable .nb_ports > 0) {                                                                   \
        CONFIG_ALLOC(container-> variable .links, nb_links);                                                    \
        CONFIG_ALLOC(container-> variable .ports, container-> variable .nb_ports);                              \
                                                                                                                \
        unsigned long vr_counter = 0;                                                                           \
        for (unsigned long i = 0; i < container-> variable .nb_ports; i += 1) {                                 \
            container_port_t port = { 0 };    /* its cache is set by cache_new() */                             \
            fmu_vr_t vr;                                                                                        \
            int offset;                                                                                         \
                                                                                                                \
            CONFIG_GETLINE;                                                                                     \
            if (sscanf(file->line, "%u %lu %lu%n", &vr, &port.dimension, &port.nb, &offset) < 3) {              \
                CONFIG_ERROR("Cannot read container I/O " #variable " %luth details.", i);                      \
                return -1;                                                                                      \
            }                                                                                                   \
            port.links = &container-> variable .links [vr_counter];                                             \
            for(unsigned long j=0; j < port.nb; j += 1) {                                                       \
                int read;                                                                                       \
                long fmu_id;                                                                                    \
                fmu_vr_t fmu_vr;                                                                                \
                if (vr_counter >= nb_links) {                                                                   \
                    CONFIG_ERROR("Read %lu links for %lu expected.", vr_counter, nb_links);                     \
                    return -1;                                                                                  \
                }                                                                                               \
                                                                                                                \
                if (sscanf(file->line+offset, " %ld %u%n", &fmu_id, &fmu_vr, &read) < 2) {                      \
                    CONFIG_ERROR("Cannot read container I/O " #variable " link details.");                      \
                    return -1;                                                                                  \
                }                                                                                               \
                if (fmu_id < 0) {   /* local (-1) or profiling (-2) variable: the values from fmu_vr */         \
                    if (fmu_id < -2 || fmu_vr + port.dimension > container-> variable .nb_locals) {             \
                        CONFIG_ERROR("Container I/O " #variable ": local variable %u (dimension %lu) is out of "\
                                     "range.", fmu_vr, port.dimension);                                         \
                        return -8;                                                                              \
                    }                                                                                           \
                } else if (fmu_id >= container->nb_fmu) {                                                       \
                    CONFIG_ERROR("Container I/O " #variable ": FMU index %ld is out of range.", fmu_id);        \
                    return -8;                                                                                  \
                }                                                                                               \
                container-> variable .links [vr_counter].fmu_id = (unsigned long)fmu_id;                        \
                container-> variable .links [vr_counter].fmu_vr = fmu_vr;                                       \
                container-> variable .links [vr_counter].cache.in_set = false;                                  \
                container-> variable .links [vr_counter].cache.start_reset = -1;                                \
                offset += read;                                                                                 \
                vr_counter += 1;                                                                                \
            }                                                                                                   \
            vr &= 0xFFFFFF;                                                                                     \
            if (vr < container-> variable .nb_ports)                                                            \
                container-> variable .ports[vr] = port;                                                         \
            else {                                                                                              \
                CONFIG_ERROR("Container I/O " #variable ": port %u is out of range.", vr);                      \
                return -8;                                                                                      \
            }                                                                                                   \
        }                                                                                                       \
    } else {                                                                                                    \
        container-> variable .links = NULL;                                                                     \
        container-> variable .ports = NULL;                                                                     \
    }

    FOR_ALL_NUMERIC_TYPES(READ_CONF_IO)
    READ_CONF_IO(strings, String, char *)
    READ_CONF_IO(binaries, Binary, fmu_binary_t)
    READ_CONF_IO(clocks, Clock, bool)
#undef READ_CONF_IO


    return 0;
}



/*
 * # Inputs of array2scalar.fmu - real64: <VR> <DIM> <FMU_VR>
 * 1
 * 1 2 0
 *
 * or
 * 
 * # Outputs of scalar2array.fmu - real64: <VR> <DIM> <FMU_VR>
 * 1
 * 1 2 1
 */
#define READER_FMU_IO(type, causality)                                                                               \
    fmu_io-> type . causality .translations = NULL;                                                                  \
                                                                                                                     \
    CONFIG_GETLINE;                                                                                                  \
    if (sscanf(file->line, "%lu", &fmu_io-> type . causality .nb) < 1) {                                             \
        CONFIG_ERROR("Cannot read the number of FMU I/O '" #type "' (" #causality ").");                             \
        return -2;                                                                                                   \
    }                                                                                                                \
                                                                                                                     \
    if (fmu_io-> type . causality .nb > 0) {                                                                         \
        CONFIG_ALLOC(fmu_io-> type . causality .translations, fmu_io-> type . causality .nb);                        \
                                                                                                                     \
        for(unsigned long i = 0; i < fmu_io-> type . causality .nb; i += 1) {                                        \
            CONFIG_GETLINE;                                                                                          \
            if (sscanf(file->line, "%u %u %u",                                                                       \
                &fmu_io-> type . causality .translations[i].vr,                                                      \
                &fmu_io-> type . causality .translations[i].dimension,                                               \
                &fmu_io-> type . causality .translations[i].fmu_vr) < 3) {                                           \
                CONFIG_ERROR("Cannot read FMU %luth I/O for '" #type "' (" #causality ").", i);                      \
                return -5;                                                                                           \
            }                                                                                                        \
            fmu_io-> type . causality .translations[i].vr &= 0xFFFFFF;                                               \
            if (fmu_io-> type . causality .translations[i].vr + fmu_io-> type . causality .translations[i].dimension \
                > container-> type .nb_locals) {                                                                     \
                CONFIG_ERROR("FMU %luth I/O for '" #type "' (" #causality "): local variable %u is out of range.",   \
                             i, fmu_io-> type . causality .translations[i].vr);                                      \
                return -5;                                                                                           \
            }                                                                                                        \
        }                                                                                                            \
    }

#define READER_FMU_CLOCKED_IO(type, causality)                                                                       \
    fmu_io->clocked_ ## type . causality = NULL;                                                                     \
                                                                                                                     \
    CONFIG_GETLINE;                                                                                                  \
    if (sscanf(file->line, "%lu %lu",                                                                                \
               &fmu_io->clocked_ ## type .nb_ ## causality,                                                          \
               &nb_clocked) < 2) {                                                                                   \
        CONFIG_ERROR("Cannot read FMU clocked I/O for '" #type "' (" #causality ").");                               \
        return -2;                                                                                                   \
    }                                                                                                                \
                                                                                                                     \
    if (fmu_io->clocked_ ## type .nb_ ## causality > 0) {                                                            \
        CONFIG_ALLOC(fmu_io->clocked_ ## type .causality, fmu_io->clocked_ ## type .nb_ ## causality);               \
                                                                                                                     \
        for(unsigned long i = 0; i < fmu_io->clocked_ ## type .nb_ ## causality; i += 1) {                           \
            int offset = 0;                                                                                          \
                                                                                                                     \
            CONFIG_GETLINE;                                                                                          \
            if (sscanf(file->line, "%u %lu%n",                                                                       \
                &fmu_io->clocked_ ## type . causality [i].clock_vr,                                                  \
                &fmu_io->clocked_ ## type . causality [i].translations_list.nb, &offset) < 2) {                      \
                CONFIG_ERROR("Cannot read FMU %luth clocked I/O for '" #type "' (" #causality ").", i);              \
                return -5;                                                                                           \
            }                                                                                                        \
            fmu_io->clocked_ ## type . causality [i].clock_vr &= 0xFFFFFF;                                           \
            if (fmu_io->clocked_ ## type . causality [i].clock_vr >= container->clocks.nb_locals) {                  \
                CONFIG_ERROR("FMU %luth clocked I/O for '" #type "' (" #causality "): clock %u is out of range.", i, \
                             fmu_io->clocked_ ## type . causality [i].clock_vr);                                     \
                return -5;                                                                                           \
            }                                                                                                        \
            CONFIG_ALLOC(fmu_io->clocked_ ## type . causality [i].translations_list.translations,                    \
                         fmu_io->clocked_ ## type . causality [i].translations_list.nb);                             \
            for(unsigned long j = 0; j < fmu_io->clocked_ ## type . causality [i].translations_list.nb; j += 1) {    \
                int read = 0;                                                                                        \
                if (sscanf(file->line + offset, "%u %u %u%n",                                                        \
                    &fmu_io->clocked_ ## type . causality [i].translations_list.translations[j].vr,                  \
                    &fmu_io->clocked_ ## type . causality [i].translations_list.translations[j].dimension,           \
                    &fmu_io->clocked_ ## type . causality [i].translations_list.translations[j].fmu_vr,              \
                    &read) < 3) {                                                                                    \
                    CONFIG_ERROR("Cannot interpret FMU %luth clocked I/O for '" #type "' (" #causality ").", i);     \
                    return -5;                                                                                       \
                }                                                                                                    \
                offset += read;                                                                                      \
                fmu_io->clocked_ ## type . causality [i].translations_list.translations[j].vr &= 0xFFFFFF;           \
                if (fmu_io->clocked_ ## type . causality [i].translations_list.translations[j].vr                    \
                    + fmu_io->clocked_ ## type . causality [i].translations_list.translations[j].dimension           \
                    > container-> type .nb_locals) {                                                                 \
                    CONFIG_ERROR("FMU %luth clocked I/O for '" #type "' (" #causality "): local variable is out of " \
                                 "range.", i);                                                                       \
                    return -5;                                                                                       \
                }                                                                                                    \
            }                                                                                                        \
        }                                                                                                            \
    }



static int config_read_fmu_io_in(const container_t *container, fmu_io_t* fmu_io, file_t* file) {
    unsigned long nb_clocked;

#define READER_FMU_IN(variable, fmi_type, c_type)   \
    READER_FMU_IO(variable, in)                     \
    READER_FMU_CLOCKED_IO(variable, in)

    FOR_ALL_NUMERIC_TYPES(READER_FMU_IN)
    READER_FMU_IN(strings, String, char *)
    READER_FMU_IN(binaries, Binary, fmu_binary_t)
    READER_FMU_IO(clocks, in) /* clock variables cannot be clocked ! */

#undef READER_FMU_IN

    return 0;
}


static int config_read_fmu_io_out(const container_t *container, fmu_io_t* fmu_io, file_t* file) {
    unsigned long nb_clocked;

#define READER_FMU_OUT(variable, fmi_type, c_type)   \
    READER_FMU_IO(variable, out)                     \
    READER_FMU_CLOCKED_IO(variable, out)

    FOR_ALL_NUMERIC_TYPES(READER_FMU_OUT)
    READER_FMU_OUT(strings, String, char *)
    READER_FMU_OUT(binaries, Binary, fmu_binary_t)
    READER_FMU_IO(clocks, out) /* clock variables cannot be clocked ! */

#undef READER_FMU_OUT

    return 0;
}
#undef READER_FMU_IO


static int config_read_fmu_start_values_booleans1(fmu_io_t* fmu_io, file_t* file) {
    unsigned long nb;
    unsigned long pos = 0;

    fmu_io->start_booleans1.start_values = NULL;
    fmu_io->start_booleans1.nb = 0;

    CONFIG_GETLINE;    
    if (sscanf(file->line, "%lu %lu", &fmu_io->start_booleans1.nb, &nb) < 2) {
        CONFIG_ERROR("Cannot read number of 'boolean1' start values.");
        return -2;
    }
                
    if (fmu_io->start_booleans1.nb == 0)
        return 0;
    
    CONFIG_ALLOC(fmu_io->start_booleans1.start_values, fmu_io->start_booleans1.nb);
    CONFIG_ALLOC(fmu_io->start_values_booleans1, nb);
 
    for (unsigned long i = 0; i < fmu_io->start_booleans1.nb; i += 1) {
        unsigned int dimension;
        int offset;

        CONFIG_GETLINE;
        if (sscanf(file->line, "%u %u %d%n",
            &fmu_io->start_booleans1.start_values[i].vr,
            &dimension,
            &fmu_io->start_booleans1.start_values[i].reset,
            &offset) < 3) {
            CONFIG_ERROR("Cannot read  %luth start value.", i);
            return -4;
        }
        fmu_io->start_booleans1.start_values[i].dimension = dimension;
        fmu_io->start_booleans1.start_values[i].value = &fmu_io->start_values_booleans1[pos];
        for(unsigned int j = 0; j < dimension; j += 1) {
            int read;
            int boolean;

            if (pos >= nb) {
                CONFIG_ERROR("Too many start values.");
                return -6;
            }
            if (sscanf(file->line + offset, "%d %n",
                &boolean, &read) < 1) {
                CONFIG_ERROR("Cannot decode %luth start value.", i);
                return -5;
            }
            fmu_io->start_values_booleans1[pos] = boolean;
            pos += 1;
            offset += read;
        }
    }

    return 0;
}


static int config_read_fmu_start_values_strings(fmu_io_t* fmu_io, file_t* file) {
    unsigned long nb;
    unsigned long pos = 0;
    
    fmu_io->start_strings.start_values = NULL;
    fmu_io->start_strings.nb = 0;
    
    CONFIG_GETLINE;
    if (sscanf(file->line, "%lu %lu", &fmu_io->start_strings.nb, &nb) < 2) {
        CONFIG_ERROR("Cannot read number of 'strings' start values.");
        return -2;
    }
                
    if (fmu_io->start_strings.nb == 0)
        return 0;
    
    CONFIG_ALLOC(fmu_io->start_strings.start_values, fmu_io->start_strings.nb);
    CONFIG_ALLOC(fmu_io->start_values_strings, nb);
    fmu_io->nb_start_values_strings = nb;

    for (unsigned long i = 0; i < fmu_io->start_strings.nb; i += 1) {
        unsigned int dimension;
        
        CONFIG_GETLINE;
        if (sscanf(file->line, "%u %u %d", 
            &fmu_io->start_strings.start_values[i].vr, 
            &dimension, 
            &fmu_io->start_strings.start_values[i].reset) < 3) {
            CONFIG_ERROR("Cannot read %luth start value.", i);
            return -5;
        }
        fmu_io->start_strings.start_values[i].dimension = dimension;
        fmu_io->start_strings.start_values[i].value = &fmu_io->start_values_strings[pos];
        for(unsigned long j = 0; j < dimension; j += 1) {
            if (pos >= nb) {
                CONFIG_ERROR("Too many start values.");
                return -6;
            }
            CONFIG_GETLINE;
            fmu_io->start_values_strings[pos] = strdup(file->line);
            if (!fmu_io->start_values_strings[pos]) {
                CONFIG_ERROR("Cannot allocate memory for a start value.");
                return -6;
            }
            pos += 1;
        }
    }

    return 0;
}


/*
 * # Start values of bb_velocity.fmu - Real: <FMU_VR> <DIM> <RESET> <VALUE> [, <VALUE>]
 * 0
 */
static int config_read_fmu_start_values(fmu_io_t* fmu_io, file_t* file) {
    int status;
    unsigned long nb;
    unsigned long pos;
    
#define READER_FMU_START_VALUES(type, format)                                                       \
    pos = 0;                                                                                        \
                                                                                                    \
    fmu_io->start_ ## type .start_values = NULL;                                                    \
    fmu_io->start_ ## type .nb = 0;                                                                 \
                                                                                                    \
    CONFIG_GETLINE;                                                                                 \
    if (sscanf(file->line, "%lu %lu", &fmu_io->start_ ## type .nb, &nb) < 2) {                      \
        CONFIG_ERROR("Cannot read number of start values.");                                        \
        return -2;                                                                                  \
    }                                                                                               \
                                                                                                    \
    if (fmu_io->start_ ## type .nb > 0) {                                                           \
        CONFIG_ALLOC(fmu_io->start_ ## type .start_values,fmu_io->start_ ## type .nb);              \
        CONFIG_ALLOC(fmu_io->start_values_ ## type, nb);                                            \
                                                                                                    \
        for (unsigned long i = 0; i < fmu_io->start_ ## type .nb; i += 1) {                         \
            int offset;                                                                             \
            unsigned int dimension;                                                                 \
                                                                                                    \
            CONFIG_GETLINE;                                                                         \
            if (file_line_to_host_decimal_point(file)) {                                            \
                CONFIG_ERROR("Cannot read %luth start value.", i);                                  \
                return -5;                                                                          \
            }                                                                                       \
            if (sscanf(file->line, "%u %u %d%n",                                                    \
                       &fmu_io->start_ ## type .start_values[i].vr,                                 \
                       &dimension,                                                                  \
                       &fmu_io->start_ ## type .start_values[i].reset,                              \
                       &offset) < 3) {                                                              \
                CONFIG_ERROR("Cannot read %luth start value.", i);                                  \
                return -5;                                                                          \
            }                                                                                       \
            fmu_io->start_ ##type .start_values[i].dimension = dimension;                           \
            fmu_io->start_ ##type .start_values[i].value = &fmu_io->start_values_ ##type[pos];      \
            for(unsigned long j = 0; j < dimension; j += 1) {                                       \
                int read;                                                                           \
                                                                                                    \
                if (pos >= nb) {                                                                    \
                    CONFIG_ERROR("Too many start values.");                                         \
                    return -6;                                                                      \
                }                                                                                   \
                if (sscanf(file->line + offset, format "%n",                                        \
                           &fmu_io->start_values_ ## type[pos],                                     \
                           &read) < 1) {                                                            \
                    CONFIG_ERROR("Cannot decode %luth start value.", i);                            \
                    return -6;                                                                      \
                }                                                                                   \
                                                                                                    \
                pos += 1;                                                                           \
                offset += read;                                                                     \
            }                                                                                       \
        }                                                                                           \
    }

    READER_FMU_START_VALUES(reals64,     "%lf");
    READER_FMU_START_VALUES(reals32,     "%f");
    READER_FMU_START_VALUES(integers8,   "%" SCNd8);
    READER_FMU_START_VALUES(uintegers8,  "%" SCNu8);
    READER_FMU_START_VALUES(integers16,  "%" SCNd16);
    READER_FMU_START_VALUES(uintegers16, "%" SCNu16);
    READER_FMU_START_VALUES(integers32,  "%" SCNd32);
    READER_FMU_START_VALUES(uintegers32, "%" SCNu32);
    READER_FMU_START_VALUES(integers64,  "%" SCNd64);
    READER_FMU_START_VALUES(uintegers64, "%" SCNu64);
    READER_FMU_START_VALUES(booleans,    "%d");

#undef READER_FMU_START_VALUES

    status = config_read_fmu_start_values_booleans1(fmu_io, file);
    if (status)
        return status;

    status = config_read_fmu_start_values_strings(fmu_io, file);
    if (status)
        return status;

    return 0;
}
#undef READER_FMU_START_VALUE


static int config_read_fmu_conversion(fmu_t *fmu, file_t* file) {
    unsigned long nb;

    CONFIG_GETLINE;
    if (sscanf(file->line, "%lu", &nb) < 1) {
        CONFIG_ERROR("Cannot read size of conversion table.");
        return -2;
    }

    fmu->conversions = convert_new(&fmu->container->logger, nb);
    if (nb && !fmu->conversions) {
        CONFIG_ERROR("Cannot allocate conversion table for %lu entries.", nb);
        return -3;
    }

    for(unsigned long i = 0; i < nb; i += 1) {
        int offset;
        fmu_vr_t from;
        fmu_vr_t to;

        CONFIG_GETLINE;
        if (sscanf(file->line, "%u %u %n", &from, &to, &offset) < 2) {
            CONFIG_ERROR("Cannot read conversion table %luth entry.", i);
            return -5;
        }
        fmu->conversions->entries[i].from = from & 0xFFFFFF;
        fmu->conversions->entries[i].to = to & 0xFFFFFF;

        fmu->conversions->entries[i].function = convert_function_get(file->line+offset);
        fmu->conversions->entries[i].to_real = convert_destination_real(file->line+offset);
        if (!fmu->conversions->entries[i].function) {
            CONFIG_ERROR("Cannot configure the conversion entry #%lu from '%s'.", i, file->line+offset);
            return -6;
        }
        if (convert_check_range(fmu->container, file->line+offset, fmu->conversions->entries[i].from,
                                fmu->conversions->entries[i].to)) {
            CONFIG_ERROR("Conversion %luth entry '%s': local variable out of range.", i, file->line+offset);
            return -6;
        }
    }

    return 0;
}


/*
 * # Reset trigger of bb_velocity.fmu: <LOCAL_OFFSET>
 * -1
 */
static int config_read_fmu_reset_trigger(fmu_t *fmu, file_t *file) {
    const container_t *container = fmu->container;

    CONFIG_GETLINE;
    if (sscanf(file->line, "%ld", &fmu->reset_trigger) < 1) {
        CONFIG_ERROR("Cannot read reset trigger.");
        return -1;
    }

    if (fmu->reset_trigger >= 0) {
        const unsigned long nb_local = (container->fmi_version == 2) ?
            container->booleans.nb_locals : container->booleans1.nb_locals;
        if ((unsigned long)fmu->reset_trigger >= nb_local) {
            CONFIG_ERROR("Reset trigger %ld is out of the local booleans storage.", fmu->reset_trigger);
            return -2;
        }
    }

    return 0;
}


static int config_read_fmu_io(fmu_t* fmu, file_t* file) {

    if (config_read_fmu_io_in(fmu->container, &fmu->fmu_io, file))
        return -1;

    if (config_read_fmu_start_values(&fmu->fmu_io, file))
        return -2;

    if (config_read_fmu_io_out(fmu->container, &fmu->fmu_io, file))
        return -3;

    if (config_read_fmu_conversion(fmu, file))
        return -4;

    if (config_read_fmu_reset_trigger(fmu, file))
        return -5;

    return 0;
}


static int config_clock_kind_from_name(const char *name, container_clock_kind_t *kind) {
    static const struct {
        const char              *name;
        container_clock_kind_t  kind;
    } kinds[] = {
        { "constant",   CONTAINER_CLOCK_CONSTANT },
        { "fixed",      CONTAINER_CLOCK_FIXED },
        { "tunable",    CONTAINER_CLOCK_TUNABLE },
        { "changing",   CONTAINER_CLOCK_CHANGING },
        { "countdown",  CONTAINER_CLOCK_COUNTDOWN }
    };

    for (size_t i = 0; i < sizeof(kinds) / sizeof(*kinds); i += 1) {
        if (strcmp(kinds[i].name, name) == 0) {
            *kind = kinds[i].kind;
            return 0;
        }
    }

    return -1;
}


static int config_read_clocks(container_t *container, file_t *file) {
    CONFIG_GETLINE;
    if (sscanf(file->line, "%lu %lu", &container->clocks_list.nb_fmu, &container->clocks_list.nb_local_clocks) < 2) {
        CONFIG_ERROR("Cannot get size of clocks defintions table.");
        return -2;
    }
    if (container->clocks_list.nb_fmu) {
        CONFIG_ALLOC(container->clocks_list.clocks, container->clocks_list.nb_local_clocks);
        CONFIG_ALLOC(container->clocks_list.active, container->clocks.nb_locals);

        unsigned long pos = 0;
        for(unsigned long i = 0; i < container->clocks_list.nb_fmu; i += 1) {
            unsigned long fmu_id;
            unsigned long nb;
            int offset;

            CONFIG_GETLINE;
            if (file_line_to_host_decimal_point(file)) {
                CONFIG_ERROR("Cannot interpret %luth clock table entries.", i);
                return -5;
            }
            if (sscanf(file->line, "%lu %lu %n", &fmu_id, &nb, &offset) < 2) {
                CONFIG_ERROR("Cannot interpret %luth clock table entries.", i);
                return -5;
            }
            if (fmu_id >= (unsigned long)container->nb_fmu) {
                CONFIG_ERROR("Clock table: FMU index %lu is out of range.", fmu_id);
                return -5;
            }

            for(unsigned long j=0; j < nb; j += 1) {
                container_clock_t *clock;
                unsigned long local_clock_index;
                char kind[16];
                int read;

                if (pos >= container->clocks_list.nb_local_clocks) {
                    CONFIG_ERROR("Clock table: more than %lu clocks.", container->clocks_list.nb_local_clocks);
                    return -7;
                }
                clock = &container->clocks_list.clocks[pos];
                if (sscanf(file->line+offset, "%u %lu %15s %lf %lf %n",
                    &clock->fmu_vr,
                    &local_clock_index,
                    kind,
                    &clock->declared_interval,
                    &clock->declared_shift,
                    &read) < 5){
                    CONFIG_ERROR("Cannot interpret the value #%lu of the clock table entry #%lu.", j, i);
                    return -7;
                }
                offset += read;
                local_clock_index &= 0xFFFFFF;
                if (local_clock_index >= container->clocks.nb_locals) {
                    CONFIG_ERROR("Clock table: clock %lu is out of range.", local_clock_index);
                    return -7;
                }
                if (config_clock_kind_from_name(kind, &clock->kind)) {
                    CONFIG_ERROR("Clock table: unknown clock variability '%s'.", kind);
                    return -7;
                }
                clock->local_vr = local_clock_index;
                clock->fmu_id = fmu_id;
                /* fmi3GetIntervalDecimal is optional when loading the FMU (FMI-3.0.1 2.5: an importer should not rely
                   on functions it does not need): it is required here, by the clocks that need it. */
                if (config_clock_needs_interval(clock) && (container->fmu[fmu_id].fmi_version == FMU_3) &&
                    !container->fmu[fmu_id].fmi_functions.version_3.fmi3GetIntervalDecimal) {
                    CONFIG_ERROR("Clock table: FMU '%s' does not export fmi3GetIntervalDecimal, needed by its %s clock "
                                 "vr=%u.", container->fmu[fmu_id].name, kind, clock->fmu_vr);
                    return -7;
                }
                pos += 1;
            }
        }
    }
    
    return 0;
}


/*----------------------------------------------------------------------------
                      C O N F I G U R A T I O N
----------------------------------------------------------------------------*/

int config_container(container_t* container, const char* resource_location) {
    const logger_t *logger = &container->logger;
    file_t file;
    char dirname[FILE_SZ];

    LOGGER_WARNING("FMUContainer version '" VERSION_TAG "'.");

    /* The config parser registers ME FMUs into the solver as it reads them. */
    container->solver = solver_new(container);
    if (!container->solver) {
        LOGGER_ERROR("Cannot allocate ME solver.");
        return -1;
    }

    if (!resource_location) {
        LOGGER_ERROR("No resource location: the container needs its resources.");
        return -1;
    }
    if (path_from_uri(resource_location, dirname, sizeof(dirname))) {
        LOGGER_ERROR("Resource location is too long: '%s'.", resource_location);
        return -1;
    }
    if (file_open(&file, logger, dirname, "container.txt")) {
        LOGGER_ERROR("Cannot open '%s/container.txt': %s.", dirname, strerror(errno));
        return -1;
    }

    if (config_read_version(&file)) {
        file_close(&file);
        return -2;
    }

    if (config_read_flags(container, &file)) {
        file_close(&file);
        return -2;
    }

    if (config_read_time_step(container, &file)) {
        file_close(&file);
        return -3;
    }

    if (config_read_fmu(container, dirname, &file)) {
        file_close(&file);
        return -4;
    }

    if (config_read_init_order(container, &file)) {
        file_close(&file);
        LOGGER_ERROR("Cannot read the initialization order.");
        return -4;
    }

    if (config_read_local(container, &file)) {
        file_close(&file);
        LOGGER_ERROR("Cannot allocate local variables.");
        return -5;
    }

    if (config_read_io(container, &file)) {
        file_close(&file);
        LOGGER_ERROR("Cannot read the translation table.");
        return -6;
    }

#define LOG_IO(variable, fmi_type, c_type)                                             \
    if ((container-> variable .nb_locals > 0) || (container-> variable .nb_ports > 0)) \
        LOGGER_DEBUG("%s: %lu local variable(s) and %lu port(s).", #variable, container-> variable .nb_locals, container-> variable .nb_ports);

    FOR_ALL_NUMERIC_TYPES(LOG_IO)
    LOG_IO(strings, String, char *)
    LOG_IO(binaries, Binary, fmu_binary_t)
    LOG_IO(clocks, Clock, bool)
#undef LOG_IO

    for (int i = 0; i < container->nb_fmu; i += 1) {
        if (config_read_fmu_io(&container->fmu[i], &file)) {
            file_close(&file);
            LOGGER_ERROR("Cannot read the I/O table of FMU #%d.", i);
            return -7;
        }

#define LOG_IO(orientation, type)                                                                \
    if ((container->fmu[i].fmu_io. type . orientation .nb > 0) ||                                \
        (container->fmu[i].fmu_io.clocked_ ## type .nb_ ## orientation > 0))                     \
        LOGGER_DEBUG("FMU #%d: %s " #orientation "puts: %lu port(s) and %lu clocked.", i, #type, \
                     container->fmu[i].fmu_io. type . orientation .nb,                           \
                     container->fmu[i].fmu_io.clocked_ ## type .nb_ ## orientation);

#define LOG_IO_CLASSIC(orientation, type)                     \
    if (container->fmu[i].fmu_io. type . orientation .nb > 0) \
        LOGGER_DEBUG("FMU #%d: %s " #orientation "puts: %lu port(s).", i, #type, container->fmu[i].fmu_io. type . orientation .nb);
        
#define LOG_START(variable, fmi_type, c_type)                \
    if (container->fmu[i].fmu_io.start_ ## variable .nb > 0) \
        LOGGER_DEBUG("FMU #%d: %s start values: %lu.", i, #variable, container->fmu[i].fmu_io.start_ ## variable .nb);

#define LOG_IO_IN(variable, fmi_type, c_type) LOG_IO(in, variable)
#define LOG_IO_OUT(variable, fmi_type, c_type) LOG_IO(out, variable)

    FOR_ALL_NUMERIC_TYPES(LOG_IO_IN)
    LOG_IO(in, strings);
    LOG_IO(in, binaries);
    LOG_IO_CLASSIC(in, clocks);

    FOR_ALL_NUMERIC_TYPES(LOG_START)
    LOG_START(strings, String, const char *)

    FOR_ALL_NUMERIC_TYPES(LOG_IO_OUT)
    LOG_IO(out, strings);
    LOG_IO(out, binaries);
    LOG_IO_CLASSIC(out, clocks);

#undef LOG_IO
#undef LOG_IO_CLASSIC
#undef LOG_IO_IN
#undef LOG_IO_OUT
#undef LOG_START
    }

    /* The cache of the values set by the importer, once the ports and the start values are read */
    container->cache = cache_new(container);
    if (!container->cache) {
        file_close(&file);
        return -12;
    }

    if (config_read_clocks(container, &file)) {
        file_close(&file);
        LOGGER_ERROR("Cannot read the clocks of the importer.");
        return -11;
    }
    if (container->clocks_list.nb_fmu)
        LOGGER_DEBUG("Container ticks the clocks of %lu FMU(s).", container->clocks_list.nb_fmu);

    file_close(&file);

    LOGGER_DEBUG("Instantiating the embedded FMUs.");
    for (int i = 0; i < container->nb_fmu; i += 1) {
        fmu_t *fmu = &container->fmu[i];
        const bool is_me = (fmu->kind == FMU_KIND_ME);

        /* Each embedded FMU gets its own instance name: two instances of one FMU must not share one. */
        const size_t len = strlen(container->instance_name) + 1 + strlen(fmu->name) + 1;
        fmu->instance_name = malloc(len);
        if (!fmu->instance_name) {
            LOGGER_ERROR("Cannot allocate the instance name of FMU '%s'.", fmu->name);
            return -8;
        }
        snprintf(fmu->instance_name, len, "%s.%s", container->instance_name, fmu->name);
        LOGGER_DEBUG("FMU #%d: '%s' instantiated as '%s' in %s.", i, fmu->name, fmu->instance_name,
                     is_me ? "ModelExchange" : "CoSimulation");

        fmu_status_t status = is_me ? fmuInstantiateModelExchange(fmu, fmu->instance_name)
                                    : fmuInstantiateCoSimulation(fmu, fmu->instance_name);
        if (status != FMU_STATUS_OK) {
            LOGGER_ERROR("Cannot instantiate FMU '%s'.", fmu->name);
            return -8;
        }
    }

    container->integers32.locals[0] = 1;                /* Default: TS multiplier */
    container->integers32.locals[1] = 0;                /* Default: solver config (euler) */
    container->next_step = container->time_step; /* Default: no next event time */
    container->time = container->start_time;
    
    container->datalog = datalog_new(logger, dirname);

    /* Buffers of fmu_get_outputs() for the arrays of strings and of binaries */
    if (container->strings.nb_locals) {
        container->strings_tmp = malloc(container->strings.nb_locals * sizeof(*container->strings_tmp));
        if (!container->strings_tmp) {
             LOGGER_ERROR("Cannot allocate the buffer of the strings.");
             return -9;
        }
    } else
        container->strings_tmp = NULL;

    if (container->binaries.nb_locals) {
        container->binaries_tmp = malloc(container->binaries.nb_locals * sizeof(*container->binaries_tmp));
        container->binaries_size_tmp = malloc(container->binaries.nb_locals * sizeof(*container->binaries_size_tmp));
        if (!container->binaries_tmp || !container->binaries_size_tmp) {
            LOGGER_ERROR("Cannot allocate the buffer of the binaries.");
             return -9;
        }
    } else {
        container->binaries_tmp = NULL;
        container->binaries_size_tmp = NULL;
    }


    /* Build the CS working set (pointers into container->fmu[]). */
    container->nb_cs = 0;
    if (container->nb_fmu > 0) {
        container->cs_fmu = malloc((size_t)container->nb_fmu * sizeof(*container->cs_fmu));
        if (!container->cs_fmu) {
            LOGGER_ERROR("Cannot allocate CS working set.");
            return -9;
        }
        for (int i = 0; i < container->nb_fmu; i += 1) {
            if (container->fmu[i].kind != FMU_KIND_ME)
                container->cs_fmu[container->nb_cs++] = &container->fmu[i];
        }
    }

    LOGGER_DEBUG("Container is configured.");

    return 0;
}
