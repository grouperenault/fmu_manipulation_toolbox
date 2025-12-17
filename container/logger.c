#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "container.h"
#include "logger.h"

/*
 * logger facilities conforming to FMI-2.0 and 3.0 specifications.
 */

 static struct {
    fmu_version_t       version;
    logger_function_t   callback;
    void                *environment;
    const char          *instance_name;
    int                 debug;
} logger_config = { 0, {NULL}, NULL, NULL, 0};

void logger_init(fmu_version_t  version, logger_function_t callback, void *environment, const char *instance_name, int debug) {
    logger_config.version = version;
    logger_config.callback = callback;
    logger_config.environment = environment;
    logger_config.instance_name = instance_name;
    logger_config.debug = debug;

    return;
}

void logger_set_debug(int debug)  {
    logger_config.debug = debug;

    return;
}


int logger_get_debug(void) {
    return logger_config.debug;
}


static void logger_log(int status, const char *message) {
	const char* category = "Error";
	if (status == LOGGER_DEBUG)
		category = "Info";
	
    switch(logger_config.version) {
    case FMU_2:
        logger_config.callback.logger_fmi2(logger_config.environment,
                                    logger_config.instance_name,
                                    status, category, "%s", message);
        break;

    case FMU_3:
        logger_config.callback.logger_fmi3(logger_config.environment,
                                status, category, message);
        break;

    default: /* Normally never reached. */
        printf("%s\n", message);

    }

    return;
}


void logger(int status, const char *message, ...) {
    if ((status != LOGGER_DEBUG) || (logger_config.debug)) {
        va_list ap;
        va_start(ap, message);
        char buffer[4096];

        vsnprintf(buffer, sizeof(buffer), message, ap);
        va_end(ap);
        logger_log(status, buffer);                
    }

    return;
}


void logger_embedded_fmu2(fmu_t *fmu,
                         const char *instanceName, int status,
                         const char *category, const char *message, ...) {
    if ((status != 0) || (logger_config.debug)) {
        char buffer[4096];
        va_list ap;
        va_start(ap, message);
        snprintf(buffer, sizeof(buffer), "%s: ", fmu->name);
        vsnprintf(buffer+strlen(buffer), sizeof(buffer)-strlen(buffer), message, ap);
        va_end(ap);

        logger_log(status, buffer);
    }
    return;
}


void logger_embedded_fmu3(fmu_t* fmu, int status, const char* category, const char* message) {
    if ((status != 0) || (logger_config.debug)) {
        char buffer[4096];
        snprintf(buffer, sizeof(buffer), "%s: %s", fmu->name, message);

        logger_log(status, buffer);
    }
    return;
}
