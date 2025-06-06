#include <errno.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "fmi2Functions.h"

#include "container.h"
#include "logger.h"
#include "fmu.h"

#pragma warning(disable : 4100)     /* no complain abourt unref formal param */
#pragma warning(disable : 4996)     /* no complain about strncpy/strncat */


/*----------------------------------------------------------------------------
                               U T I L I T I E S
----------------------------------------------------------------------------*/

/* unimplemented fmi2 functions */
#define __NOT_IMPLEMENTED__ \
    logger(fmi2Error, "Function '%s' is not implemented", __func__); \
    return fmi2Error;


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
    if (get_line(file))
        return -1;
    if (sscanf(file->line, "%d", &container->mt) < 1)
        return -2;

    if (container->mt)
        logger(fmi2Warning, "Container use MULTI thread");
    else   
        logger(fmi2Warning, "Container use MONO thread");

    return 0;
}


static int read_profiling_flag(container_t* container, config_file_t* file) {
    if (get_line(file))
        return -1;
    if (sscanf(file->line, "%d", &container->profiling) < 1)
        return -2;

    if (container->profiling)
        logger(fmi2Warning, "Container use PROFILING");

    return 0;
}


static int read_conf_time_step(container_t* container, config_file_t* file) {
    if (get_line(file))
        return -1;
    if (sscanf(file->line, "%le", &container->time_step) < 1)
        return -2;
    logger(fmi2OK, "Container time_step = %e", container->time_step);
    return 0;
}


static int read_conf_fmu(container_t *container, const char *dirname, config_file_t* file) {
    int nb_fmu;

    if (get_line(file))
        return -1;
    if (sscanf(file->line, "%d", &nb_fmu) < 1)
        return -2;

    logger(fmi2OK, "%d FMU's to be loaded", nb_fmu);
    if (!nb_fmu) {
        container->fmu = NULL;
        return 0;
    }

    container->fmu = malloc(nb_fmu * sizeof(*container->fmu));
    if (!container->fmu)
        return -3;


    for (int i = 0; i < nb_fmu; i += 1) {
        container->fmu[i].container = container;
        char directory[CONFIG_FILE_SZ];
        snprintf(directory, CONFIG_FILE_SZ, "%s/%02x", dirname, i);

        if (get_line(file))
            return -1;
        char* name = strdup(file->line);
      
        if (get_line(file))
            return -1;
        char *identifier = strdup(file->line);

        if (get_line(file))
            return -1;
        const char *guid = file->line;

        logger(fmi2OK, "Loading '%s.dll' from directory '%s'", identifier, directory);

        int status = fmu_load_from_directory(container, i, directory, name, identifier, guid);
        free(identifier);
        free(name);
        if (status) {
            logger(fmi2Error, "Cannot load from directory '%s' (status=%d)", directory, status);
            free(container->fmu);
            container->fmu = NULL; /* to allow freeInstance on container */
            return -4;
        }

        container->nb_fmu = i + 1;  /* in case of error, free only loaded FMU */
    }

    return 0;
}


static int read_conf_io(container_t* container, config_file_t* file) {
    if (get_line(file))
        return -1;

    if (sscanf(file->line, "%d %d %d %d",
        &container->nb_local_reals,
        &container->nb_local_integers,
        &container->nb_local_booleans,
        &container->nb_local_strings) < 4)
        return -1;

#define ALLOC(type, value) \
    if (container->nb_local_ ## type) { \
        container-> type = malloc(container->nb_local_ ## type * sizeof(*container-> type)); \
        if (!container-> type) \
            return -2; \
        for(fmi2ValueReference i=0; i < container->nb_local_ ## type; i += 1) \
            container-> type [i] = value; \
    } else \
        container-> type = NULL 
    
    ALLOC(reals, 0.0);
    ALLOC(integers, 0);
    ALLOC(booleans, 0);
    ALLOC(strings, NULL);

#undef ALLOC

    return 0;
}


#define READ_CONF_VR(type) \
static int read_conf_vr_ ## type (container_t* container, config_file_t* file) { \
    if (get_line(file)) \
        return -1;\
\
    fmi2ValueReference nb_links; \
    if (sscanf(file->line, "%d %d", &container->nb_ports_ ## type, &nb_links) < 2) \
        return -1; \
    if (container->nb_ports_ ## type > 0) { \
        container->vr_ ## type = malloc(nb_links * sizeof(*container->vr_ ## type)); \
        container->port_ ## type = malloc(container->nb_ports_ ## type * sizeof(*container->port_ ##type)); \
        if ((!container->vr_ ## type) || (!container->port_ ## type)) \
            return -2; \
        int vr_counter = 0; \
        for (fmi2ValueReference i = 0; i < container->nb_ports_ ## type; i += 1) { \
            container_port_t port; \
            fmi2ValueReference vr; \
            int offset; \
            int fmu_id; \
            fmi2ValueReference fmu_vr; \
\
            if (get_line(file)) \
                return -3; \
\
            if (sscanf(file->line, "%d %d%n", &vr, &port.nb, &offset) < 2) \
                return -4; \
            port.links = &container->vr_ ## type [vr_counter]; \
            for(int j=0; j < port.nb; j += 1) { \
                int read; \
                if (vr_counter >= nb_links) {\
                    logger(fmi2Fatal, "Read %d links for %d expected.", vr_counter, nb_links); \
                    return -7; \
                }\
\
                if (sscanf(file->line+offset, " %d %d%n", &container->vr_ ## type [vr_counter].fmu_id, \
                                                          &container->vr_ ## type [vr_counter].fmu_vr, &read) < 2) \
                    return -5; \
                offset += read; \
                vr_counter += 1; \
            } \
            if (vr < container->nb_ports_ ## type) \
                container->port_ ##type[vr] = port; \
            else \
                return -8; \
        } \
    } else { \
        container->vr_ ## type = NULL; \
        container->port_ ## type = NULL; \
    } \
    return 0; \
}


READ_CONF_VR(reals);
READ_CONF_VR(integers);
READ_CONF_VR(booleans);
READ_CONF_VR(strings);

#undef READ_CONF_VR


static int read_conf_vr(container_t* container, config_file_t* file) {
    int status;

    status = read_conf_vr_reals(container, file);
    if (status)
        return status * 1;

    status = read_conf_vr_integers(container, file);
    if (status)
        return status * 10;

    status = read_conf_vr_booleans(container, file);
    if (status)
        return status * 100;

    status = read_conf_vr_strings(container, file);
    if (status)
        return status * 1000;

    return 0;
}

#define READER_FMU_IO(type, causality) \
static int read_conf_fmu_io_ ## causality ## _ ## type (fmu_io_t *fmu_io, config_file_t* file) { \
    if (get_line(file)) \
        return -1; \
\
    fmu_io-> type . causality .translations = NULL; \
\
    if (sscanf(file->line, "%d", &fmu_io-> type . causality .nb) < 1) \
        return -2; \
\
    if (fmu_io-> type . causality .nb == 0) \
        return 0; \
\
    fmu_io-> type . causality .translations = malloc(fmu_io-> type . causality .nb * sizeof(*fmu_io-> type . causality .translations)); \
    if (! fmu_io-> type . causality .translations) \
        return -3; \
\
    for(fmi2ValueReference i = 0; i < fmu_io-> type . causality .nb; i += 1) { \
        if (get_line(file)) \
            return -4; \
\
        if (sscanf(file->line, "%d %d", &fmu_io-> type . causality .translations[i].vr, \
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
    if (sscanf(file->line, "%d", &fmu_io->start_ ## type .nb) < 1) \
        return -2; \
\
    if (fmu_io->start_ ## type .nb == 0) \
        return 0; \
\
    fmu_io->start_ ## type .start_values = malloc(fmu_io->start_ ## type .nb * sizeof(*fmu_io->start_ ## type .start_values)); \
    if (! fmu_io->start_ ## type .start_values) \
        return -3; \
\
    for (fmi2ValueReference i = 0; i < fmu_io->start_ ## type .nb; i += 1) { \
        if (get_line(file)) \
            return -4; \
\
       if (sscanf(file->line, "%d %d " format, \
         &fmu_io->start_ ## type .start_values[i].vr, \
         &fmu_io->start_ ## type .start_values[i].reset, \
         &fmu_io->start_ ## type .start_values[i].value) < 3) \
            return -5; \
    } \
\
    return 0; \
}


READER_FMU_IO(reals, in);
READER_FMU_IO(integers, in);
READER_FMU_IO(booleans, in);
READER_FMU_IO(strings, in);

READER_FMU_START_VALUES(reals, "%lf");
READER_FMU_START_VALUES(integers, "%d");
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
    

    if (sscanf(file->line, "%d", &fmu_io->start_strings.nb) < 1)
        return -2;
                
    if (fmu_io->start_strings.nb == 0)
        return 0;
                    
    fmu_io->start_strings.start_values = malloc(fmu_io->start_strings.nb * sizeof(*fmu_io->start_strings.start_values));
    if (!fmu_io->start_strings.start_values)
        return -3;
                            
    for (fmi2ValueReference i = 0; i < fmu_io->start_strings.nb; i += 1)
        fmu_io->start_strings.start_values[i].value = NULL; /* in case on ealry fmuFreeInstance() */

    for (fmi2ValueReference i = 0; i < fmu_io->start_strings.nb; i += 1) {
        char buffer[CONFIG_FILE_SZ];
        buffer[0] = '\0';

        if (get_line(file))
            return -4;
    
        char *value_string = string_token(file->line);
        if (sscanf(file->line, "%d %d", &fmu_io->start_strings.start_values[i].vr, &fmu_io->start_strings.start_values[i].reset) < 2) {
            return -5;
        }
        fmu_io->start_strings.start_values[i].value = strdup(value_string);
    }

    return 0;
}


READER_FMU_IO(reals, out);
READER_FMU_IO(integers, out);
READER_FMU_IO(booleans, out);
READER_FMU_IO(strings, out);

#undef READER_FMU_IO
#undef READER_FMU_START_VALUE


static int read_conf_fmu_io_in(fmu_io_t* fmu_io, config_file_t* file) {
    int status;

    status = read_conf_fmu_io_in_reals(fmu_io, file);
    if (status)
        return status * 1;
    status = read_conf_fmu_io_in_integers(fmu_io, file);
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

    status = read_conf_fmu_start_values_reals(fmu_io, file);
    if (status)
        return status * 1;
    status = read_conf_fmu_start_values_integers(fmu_io, file);
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

    status = read_conf_fmu_io_out_reals(fmu_io, file);
    if (status)
        return status * 1;
    status = read_conf_fmu_io_out_integers(fmu_io, file);
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


static int read_conf(container_t* container, const char* dirname) {
    config_file_t file;
    char filename[CONFIG_FILE_SZ];

    strncpy(filename, dirname, sizeof(filename) - 1);
    filename[sizeof(filename) - 1] = '\0';
    strncat(filename, "/container.txt", sizeof(filename) - strlen(filename) - 1);

    logger(fmi2OK, "Reading '%s'...", filename);
    file.fp = fopen(filename, "rt");
    if (!file.fp) {
        logger(fmi2Error, "Cannot open '%s': %s.", filename, strerror(errno));
        return -1;
    }
    if (read_mt_flag(container, &file)) {
        fclose(file.fp);
        logger(fmi2Error, "Cannot configure MT flag.");
        return -2;
    }

    if (read_profiling_flag(container, &file)) {
        fclose(file.fp);
        logger(fmi2Error, "Cannot configure PROFILING flag.");
        return -2;
    }

    if (read_conf_time_step(container, &file)) {
        fclose(file.fp);
        logger(fmi2Error, "Cannot set time step.");
        return -2;
    }

    if (read_conf_fmu(container, dirname, &file)) {
        fclose(file.fp);
        logger(fmi2Error, "Cannot load embedded FMU's.");
        return -3;
    }

    if (read_conf_io(container, &file)) {
        fclose(file.fp);
        logger(fmi2Error, "Cannot allocate local variables.");
        return -4;
    }

    if (read_conf_vr(container, &file)) {
        fclose(file.fp);
        logger(fmi2Error, "Cannot read translation table.");
        return -5;
    }

    logger(fmi2OK, "Real    : %d local variables and %d ports", container->nb_local_reals, container->nb_ports_reals);
    logger(fmi2OK, "Integer : %d local variables and %d ports", container->nb_local_integers, container->nb_ports_integers);
    logger(fmi2OK, "Boolean : %d local variables and %d ports", container->nb_local_booleans, container->nb_ports_booleans);
    logger(fmi2OK, "String  : %d local variables and %d ports", container->nb_local_strings, container->nb_ports_strings);

    for (int i = 0; i < container->nb_fmu; i += 1) {
        if (read_conf_fmu_io(&container->fmu[i].fmu_io, &file)) {
            fclose(file.fp);
            return -6;
        }

        logger(fmi2OK, "FMU#%d: IN     %d reals, %d integers, %d booleans, %d strings", i,
            container->fmu[i].fmu_io.reals.in.nb,
            container->fmu[i].fmu_io.integers.in.nb,
            container->fmu[i].fmu_io.booleans.in.nb,
            container->fmu[i].fmu_io.strings.in.nb);
        logger(fmi2OK, "FMU#%d: START  %d reals, %d integers, %d booleans, %d strings", i,
            container->fmu[i].fmu_io.start_reals.nb,
            container->fmu[i].fmu_io.start_integers.nb,
            container->fmu[i].fmu_io.start_strings.nb,
            container->fmu[i].fmu_io.start_strings.nb);
        logger(fmi2OK, "FMU#%d: OUT    %d reals, %d integers, %d booleans, %d strings", i,
            container->fmu[i].fmu_io.reals.out.nb,
            container->fmu[i].fmu_io.integers.out.nb,
            container->fmu[i].fmu_io.booleans.out.nb,
            container->fmu[i].fmu_io.strings.out.nb);
    }

    fclose(file.fp);

    return 0;
}


/*----------------------------------------------------------------------------
               F M I 2   F U N C T I O N S   ( G E N E R A L )
----------------------------------------------------------------------------*/

const char* fmi2GetTypesPlatform(void) {
    return fmi2TypesPlatform;
}


const char* fmi2GetVersion(void) {
    return fmi2Version;
}


fmi2Status  fmi2SetDebugLogging(fmi2Component c,
    fmi2Boolean loggingOn,
    size_t nCategories,
    const fmi2String categories[]) {
    container_t* container = (container_t*)c;

    container->debug = loggingOn;

    return fmi2OK;
}


fmi2Component fmi2Instantiate(fmi2String instanceName,
    fmi2Type fmuType,
    fmi2String fmuGUID,
    fmi2String fmuResourceLocation,
    const fmi2CallbackFunctions* functions,
    fmi2Boolean visible,
    fmi2Boolean loggingOn) {
    container_t* container;

    container = malloc(sizeof(*container));
    if (container) {
        container->callback_functions = functions;
        container->environment = functions->componentEnvironment;
        container->instance_name = strdup(instanceName);
        container->uuid = strdup(fmuGUID);
        container->debug = loggingOn;
        container->logger = functions->logger;

        logger_init(container);  /* logger() is available starting this point ! */
        container->mt = 0;
        container->nb_fmu = 0;
        container->fmu = NULL;

        container->nb_local_reals = 0;
        container->nb_local_integers = 0;
        container->nb_local_booleans = 0;
        container->nb_local_strings = 0;
        container->reals = NULL;
        container->integers = NULL;
        container->booleans = NULL;
        container->strings = NULL;

        container->nb_ports_reals = 0;
        container->nb_ports_integers = 0;
        container->nb_ports_booleans = 0;
        container->nb_ports_strings = 0;
        container->vr_reals = NULL;
        container->vr_integers = NULL;
        container->vr_booleans = NULL;
        container->vr_strings = NULL;

        container->time_step = 0.001;
        container->time = 0.0;
        container->tolerance = 1.0e-8;

        logger(fmi2OK, "Container model loading...");
        if (read_conf(container, fmuResourceLocation + strlen("file:///"))) {
            logger(fmi2Error, "Cannot read container configuration.");
            fmi2FreeInstance(container);
            return NULL;
        }
        logger(fmi2OK, "Container configuration read.");

        for (int i = 0; i < container->nb_fmu; i += 1)
            container->fmu[i].component = NULL;

        for(int i=0; i < container->nb_fmu; i += 1) {
            fmi2Status status = fmuInstantiate(&container->fmu[i], 
                                               container->instance_name,
                                               fmi2CoSimulation,
                                               visible,
                                               container->debug);
            if (status != fmi2OK) {
                logger(fmi2Error, "Cannot Instantiate FMU#%d", i);
                fmi2FreeInstance(container);
                return NULL;
            }
        }
    }
    return container;
}


void fmi2FreeInstance(fmi2Component c) {
    container_t* container = (container_t*)c;

    if (container) {

        if (container->fmu) {
            for (int i = 0; i < container->nb_fmu; i += 1) {
                fmuFreeInstance(&container->fmu[i]);
                fmu_unload(&container->fmu[i]);

                free(container->fmu[i].fmu_io.reals.in.translations);
                free(container->fmu[i].fmu_io.integers.in.translations);
                free(container->fmu[i].fmu_io.booleans.in.translations);
                free(container->fmu[i].fmu_io.strings.in.translations);

                free(container->fmu[i].fmu_io.reals.out.translations);
                free(container->fmu[i].fmu_io.integers.out.translations);
                free(container->fmu[i].fmu_io.booleans.out.translations);
                free(container->fmu[i].fmu_io.strings.out.translations);

                free(container->fmu[i].fmu_io.start_reals.start_values);
                free(container->fmu[i].fmu_io.start_integers.start_values);
                free(container->fmu[i].fmu_io.start_booleans.start_values);

                for (int j = 0; j < container->fmu[i].fmu_io.start_strings.nb; j += 1)
                    free((char *)container->fmu[i].fmu_io.start_strings.start_values[j].value);
                free(container->fmu[i].fmu_io.start_strings.start_values);
            }

            free(container->fmu);
        }

        free(container->instance_name);
        free(container->uuid);

        free(container->vr_reals);
        free(container->port_reals);
        free(container->vr_integers);
        free(container->port_integers);
        free(container->vr_booleans);
        free(container->port_booleans);
        free(container->vr_strings);
        free(container->port_strings);

        free(container->reals);
        free(container->integers);
        free(container->booleans);
        free((void*)container->strings);

        free(container);
    }

    return;
}


static void container_set_start_values(container_t* container, int early_set) {
    if (early_set)
        logger(fmi2OK, "Setting start values...");
    else
        logger(fmi2OK, "Re-setting some start values...");
    for (int i = 0; i < container->nb_fmu; i += 1) {
#define SET_START(fmi_type, type) \
        for(fmi2ValueReference j=0; j<container->fmu[i].fmu_io.start_ ## type .nb; j ++) { \
            if (early_set || container->fmu[i].fmu_io.start_ ## type.start_values[j].reset) \
                fmuSet ## fmi_type(&container->fmu[i], &container->fmu[i].fmu_io.start_ ## type.start_values[j].vr, 1, \
                    &container->fmu[i].fmu_io.start_ ## type.start_values[j].value); \
        }
 
        SET_START(Real, reals);
        SET_START(Integer, integers);
        SET_START(Boolean, booleans);
        SET_START(String, strings);
#undef SET_START
    }
    logger(fmi2OK, "Start values are set.");
    return;
}


fmi2Status fmi2SetupExperiment(fmi2Component c,
    fmi2Boolean toleranceDefined,
    fmi2Real tolerance,
    fmi2Real startTime,
    fmi2Boolean stopTimeDefined,
    fmi2Real stopTime) {
    container_t* container = (container_t*)c;

    if (toleranceDefined)
       container->tolerance = tolerance;

    for(int i=0; i < container->nb_fmu; i += 1) {
        fmi2Status status = fmuSetupExperiment(&container->fmu[i],
                                               toleranceDefined, tolerance,
                                               startTime,
                                               fmi2False, stopTime);    /* stopTime can cause rounding issues. Disbale it.*/
        
        if (status != fmi2OK)
            return status;
    }

    container->time = startTime;
    container_set_start_values(container, 1);
    logger(fmi2OK, "fmi2SetupExperiment -- OK");

    return fmi2OK;
}


fmi2Status fmi2EnterInitializationMode(fmi2Component c) {
    container_t* container = (container_t*)c;

    for (int i = 0; i < container->nb_fmu; i += 1) {
        fmi2Status status = fmuEnterInitializationMode(&container->fmu[i]);
        if (status != fmi2OK)
            return status;
    }

    container_set_start_values(container, 0);

    return fmi2OK;
}


fmi2Status fmi2ExitInitializationMode(fmi2Component c) {
    container_t* container = (container_t*)c;

    for (int i = 0; i < container->nb_fmu; i += 1) {
        fmi2Status status = fmuExitInitializationMode(&container->fmu[i]);

        if (status != fmi2OK)
            return status;
    }
 
    return fmi2OK;
}


fmi2Status fmi2Terminate(fmi2Component c) {
    container_t* container = (container_t*)c;

    for (int i = 0; i < container->nb_fmu; i += 1) {
        fmi2Status status = fmuTerminate(&container->fmu[i]);

        if (status != fmi2OK)
            return status;
    }
 
    return fmi2OK;
}


fmi2Status fmi2Reset(fmi2Component c) {
    container_t* container = (container_t*)c;

    for (int i = 0; i < container->nb_fmu; i += 1) {
        fmi2Status status = fmuReset(&container->fmu[i]);

        if (status != fmi2OK)
            return status;
    }
 
    return fmi2OK;
}


/* Getting and setting variable values */
#define FMI_GETTER(type, fmi_type) \
fmi2Status fmi2Get ## fmi_type (fmi2Component c, const fmi2ValueReference vr[], size_t nvr, fmi2 ## fmi_type value[]) { \
    container_t* container = (container_t*)c; \
    fmi2Status status = fmi2OK; \
\
    for (size_t i = 0; i < nvr; i += 1) { \
        const container_port_t *port = &container->port_ ##type [vr[i]]; \
        const int fmu_id = port->links[0].fmu_id; \
\
        if (fmu_id < 0) { \
            value[i] = container-> type [vr[i]]; \
        } else { \
            const fmi2ValueReference fmu_vr = port->links[0].fmu_vr; \
            const fmu_t *fmu = &container->fmu[fmu_id]; \
\
            status = fmuGet ## fmi_type (fmu, &fmu_vr, 1, &value[i]); \
            if (status != fmi2OK) \
                break; \
        } \
    } \
\
    return status; \
}


FMI_GETTER(reals, Real);
FMI_GETTER(integers, Integer);
FMI_GETTER(booleans, Boolean);
FMI_GETTER(strings, String);
#undef FMI_GETTER

#define FMI_SETTER(type, fmi_type) \
fmi2Status fmi2Set ## fmi_type (fmi2Component c, const fmi2ValueReference vr[], size_t nvr, const fmi2 ## fmi_type value[]) { \
    container_t* container = (container_t*)c; \
    fmi2Status status = fmi2OK; \
\
    for (size_t i = 0; i < nvr; i += 1) { \
        const container_port_t *port = &container->port_ ##type [vr[i]]; \
        for(int j = 0; j < port->nb; j += 1) { \
            const int fmu_id = port->links[j].fmu_id; \
\
            if (fmu_id < 0) {\
                container-> type [vr[i]] = value[i]; \
            } else { \
                const fmu_t* fmu = &container->fmu[fmu_id]; \
                const fmi2ValueReference fmu_vr = port->links[j].fmu_vr; \
\
                status = fmuSet ## fmi_type (fmu, &fmu_vr, 1, &value[i]); \
                if (status != fmi2OK) \
                    break; \
            } \
        } \
    } \
\
    return status; \
}


FMI_SETTER(reals, Real);
FMI_SETTER(integers, Integer);
FMI_SETTER(booleans, Boolean);
FMI_SETTER(strings, String);

#undef FMI_SETTER


/* Getting and setting the internal FMU state */
fmi2Status fmi2GetFMUstate(fmi2Component c, fmi2FMUstate* FMUstate) {
    __NOT_IMPLEMENTED__
}


fmi2Status fmi2SetFMUstate(fmi2Component c, fmi2FMUstate  FMUstate) {
    __NOT_IMPLEMENTED__
}


fmi2Status fmi2FreeFMUstate(fmi2Component c, fmi2FMUstate* FMUstate) {
    __NOT_IMPLEMENTED__
}


fmi2Status fmi2SerializedFMUstateSize(fmi2Component c, fmi2FMUstate  FMUstate, size_t* size) {
    __NOT_IMPLEMENTED__
}


fmi2Status fmi2SerializeFMUstate(fmi2Component c, fmi2FMUstate  FMUstate, fmi2Byte serializedState[], size_t size) {
    __NOT_IMPLEMENTED__
}


fmi2Status fmi2DeSerializeFMUstate(fmi2Component c, const fmi2Byte serializedState[], size_t size, fmi2FMUstate* FMUstate) {
    __NOT_IMPLEMENTED__
}


/* Getting partial derivatives */
fmi2Status fmi2GetDirectionalDerivative(fmi2Component c,
    const fmi2ValueReference vUnknown_ref[], size_t nUnknown,
    const fmi2ValueReference vKnown_ref[], size_t nKnown,
    const fmi2Real dvKnown[],
    fmi2Real dvUnknown[]) {
    __NOT_IMPLEMENTED__
}


/*----------------------------------------------------------------------------
          F M I 2   F U N C T I O N S   ( C O S I M U L A T I O N )
----------------------------------------------------------------------------*/

fmi2Status fmi2SetRealInputDerivatives(fmi2Component c,
    const fmi2ValueReference vr[], size_t nvr,
    const fmi2Integer order[],
    const fmi2Real value[]) {
    __NOT_IMPLEMENTED__
}


fmi2Status fmi2GetRealOutputDerivatives(fmi2Component c,
    const fmi2ValueReference vr[], size_t nvr,
    const fmi2Integer order[],
    fmi2Real value[]) {
    __NOT_IMPLEMENTED__
}


static fmi2Status do_step_get_outputs(container_t* container, int fmu_id) {
    const fmu_t* fmu = &container->fmu[fmu_id];
    const fmu_io_t* fmu_io = &fmu->fmu_io;
    fmi2Status status = fmi2OK;

#define GETTER(type, fmi_type) \
    for (fmi2ValueReference i = 0; i < fmu_io-> type .out.nb; i += 1) { \
        const fmi2ValueReference fmu_vr = fmu_io-> type .out.translations[i].fmu_vr; \
        const fmi2ValueReference local_vr = fmu_io-> type .out.translations[i].vr; \
        status = fmuGet ## fmi_type (fmu, &fmu_vr, 1, &container-> type [local_vr]); \
        if (status != fmi2OK) \
            return status; \
    }

GETTER(reals, Real);
GETTER(integers, Integer);
GETTER(booleans, Boolean);
GETTER(strings, String);

#undef GETTER

    return status;
}


static fmi2Status do_internal_step_serie(container_t *container, fmi2Boolean noSetFMUStatePriorToCurrentPoint) {
    fmi2Status status = fmi2OK;;

    for (int i = 0; i < container->nb_fmu; i += 1) {
        fmu_t* fmu = &container->fmu[i];

        status = fmu_set_inputs(fmu);
        if ((status != fmi2OK) && (status != fmi2Warning))
            return status;
            
        /* COMPUTATION */
        status = fmuDoStep(fmu, container->time, container->time_step, noSetFMUStatePriorToCurrentPoint);
        if ((status != fmi2OK) && (status != fmi2Warning))
            return status;

        status = do_step_get_outputs(container, i);
        if ((status != fmi2OK) && (status != fmi2Warning))
            return status;
        
    }

    return status;
}


static fmi2Status do_internal_step_parallel_mt(container_t* container, fmi2Boolean noSetFMUStatePriorToCurrentPoint) {
    fmi2Status status = fmi2OK;

    /* Launch computation for all threads*/
    for (int i = 0; i < container->nb_fmu; i += 1) {
        container->fmu[i].status = fmi2Error;
        thread_mutex_unlock(&container->fmu[i].mutex_container);
    }

    /* Consolidate results */
    for (int i = 0; i < container->nb_fmu; i += 1) {
        thread_mutex_lock(&container->fmu[i].mutex_fmu);
        if ((container->fmu[i].status != fmi2OK) && (container->fmu[i].status != fmi2Warning))
            return container->fmu[i].status;
    }

    for (int i = 0; i < container->nb_fmu; i += 1) {
        status = do_step_get_outputs(container, i);
        if ((status != fmi2OK) && (status != fmi2Warning)) {
            logger(fmi2Error, "Container: FMU#%d failed doStep.", i);
            return status;
        }
    }
    
    return status;
}


static fmi2Status do_internal_step_parallel(container_t* container, fmi2Boolean noSetFMUStatePriorToCurrentPoint) {
    static int set_input = 0;
    fmi2Status status = fmi2OK;

    for (int i = 0; i < container->nb_fmu; i += 1) {          
        status = fmu_set_inputs(&container->fmu[i]);
        if ((status != fmi2OK) && (status != fmi2Warning))
            return status;
    }

    for (int i = 0; i < container->nb_fmu; i += 1) {
        const fmu_t* fmu = &container->fmu[i];
        /* COMPUTATION */
        status = fmuDoStep(fmu, container->time, container->time_step, noSetFMUStatePriorToCurrentPoint);
        if ((status != fmi2OK) && (status != fmi2Warning)) {
            logger(fmi2Error, "Container: FMU#%d failed doStep.", i);
            return status;
        }
    }

    for (int i = 0; i < container->nb_fmu; i += 1) {
        status = do_step_get_outputs(container, i);
        if ((status != fmi2OK) && (status != fmi2Warning))
            return status;
    }
    
    return status;
}


fmi2Status fmi2DoStep(fmi2Component c,
    fmi2Real currentCommunicationPoint,
    fmi2Real communicationStepSize,
    fmi2Boolean noSetFMUStatePriorToCurrentPoint) {
    container_t *container = (container_t*)c;
    const fmi2Real end_time = currentCommunicationPoint + communicationStepSize;
    fmi2Status status = fmi2OK;

    const int nb_step = (int)((end_time - container->time + container->tolerance) / container->time_step);
    
    /*
     * Early return if requested end_time is lower than next container time step.
     */
    if (nb_step == 0)
        return fmi2OK;

    container->noSetFMUStatePriorToCurrentPoint = noSetFMUStatePriorToCurrentPoint; /* for MT */
    
    for(int i = 0; i < nb_step; i += 1) {
#if 1
        if (container->mt)
            status = do_internal_step_parallel_mt(container, noSetFMUStatePriorToCurrentPoint);
        else
            status = do_internal_step_parallel(container, noSetFMUStatePriorToCurrentPoint);
        container->time += container->time_step;
        if ((status != fmi2OK) && (status != fmi2Warning)) {
            logger(fmi2Error, "Container cannot do_internal_step. Status=%d", status);
            return status;
        }
#else
        status = do_internal_step_serie(container, noSetFMUStatePriorToCurrentPoint);
        container->time = start_time + (i + 1) * container->time_step;
        if ((status != fmi2OK) && (status != fmi2Warning)) {
            logger(fmi2Error, "Container cannot do_internal_step. Status=%d", status);
            return status;
        }
#endif
    }

    if (fabs(end_time - container->time) > container->tolerance) {
        logger(fmi2Warning, "Container CommunicationStepSize should be divisible by %e. (currentCommunicationPoint=%e, container_time=%e, expected_time=%e, tolerance=%e, nb_step=%d)", 
            container->time_step, currentCommunicationPoint, container->time, end_time, container->tolerance, nb_step);
        return fmi2Warning;
    }

    return status;
}


fmi2Status fmi2CancelStep(fmi2Component c) {
    __NOT_IMPLEMENTED__
}


/*
 *  Can be called when the fmi2DoStep function returned 
 * fmi2Pending. The function delivers fmi2Pending if 
 * the computation is not finished. Otherwise the function 
 * returns the result of the asynchronously executed 
 * fmi2DoStep call.
 */
fmi2Status fmi2GetStatus(fmi2Component c, const fmi2StatusKind s, fmi2Status* value) {
    __NOT_IMPLEMENTED__
}


/*
 * Returns the end time of the last successfully completed 
 * communication step. Can be called after 
 * fmi2DoStep(..) returned fmi2Discard.
 */
fmi2Status fmi2GetRealStatus(fmi2Component c, const fmi2StatusKind s, fmi2Real* value) {
    container_t *container = (container_t*)c;

    if (s == fmi2LastSuccessfulTime) {
        *value = -1.0;
        fmi2Real last_time;
        for(int i = 0; i < container->nb_fmu; i += 1) {
            fmuGetRealStatus(&container->fmu[i], s, &last_time);
            if ((*value < 0) || (last_time < *value))
                *value = last_time;
        }
        return fmi2OK;
    }

    return fmi2Error;
}


fmi2Status fmi2GetIntegerStatus(fmi2Component c, const fmi2StatusKind s, fmi2Integer* value) {
    __NOT_IMPLEMENTED__
}


/*
 * Returns fmi2True, if the slave wants to terminate the 
 * simulation. Can be called after fmi2DoStep(..)
 * returned fmi2Discard. Use 
 * fmi2LastSuccessfulTime to determine the time 
 * instant at which the slave terminated.
 */
fmi2Status fmi2GetBooleanStatus(fmi2Component c, const fmi2StatusKind s, fmi2Boolean* value) {

    container_t *container = (container_t*)c;

    if (s == fmi2Terminated) {
        for(int i = 0; i < container->nb_fmu; i += 1) {
            fmuGetBooleanStatus(&container->fmu[i], s, value);
            if (value)
                break;
        }
        return fmi2OK;
    }

    return fmi2Error;
}


/*
 * Can be called when the fmi2DoStep function returned 
 * fmi2Pending. The function delivers a string which 
 * informs about the status of the currently running 
 * asynchronous fmi2DoStep computation.
 */
fmi2Status fmi2GetStringStatus(fmi2Component c, const fmi2StatusKind s, fmi2String* value) {
    __NOT_IMPLEMENTED__
}
