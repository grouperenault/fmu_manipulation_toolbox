#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "container.h"
#include "logger.h"

/*
 * logger facilities conforming to FMI-2.0 and 3.0 specifications. Each instance of the container has its own
 * logger (container_t.logger).
 */

void logger_init(logger_t *logger, fmu_version_t version, logger_function_t callback, void *environment,
                 const char *instance_name, int debug) {
    logger->version = version;
    logger->callback = callback;
    logger->environment = environment;
    logger->instance_name = instance_name;
    logger->debug = debug;

    return;
}


static void logger_log(const logger_t *logger, int level, const char *message) {
	const char* category = "Error";
	if (level == LOGGER_LEVEL_DEBUG)
		category = "Info";
	
    switch(logger->version) {
    case FMU_2:
        if (logger->callback.logger_fmi2)
            logger->callback.logger_fmi2(logger->environment, logger->instance_name, level, category, "%s",
                                         message);
        break;

    case FMU_3:
        if (logger->callback.logger_fmi3)
            logger->callback.logger_fmi3(logger->environment, level, category, message);
        break;

    default: /* not initialized yet (native tests) */
        printf("%s\n", message);
    }

    return;
}


void logger_message(const logger_t *logger, int level, const char *message, ...) {
    if (logger && ((level != LOGGER_LEVEL_DEBUG) || (logger->debug))) {
        va_list ap;
        va_start(ap, message);
        char buffer[4096];

        vsnprintf(buffer, sizeof(buffer), message, ap);
        va_end(ap);
        logger_log(logger, level, buffer);
    }

    return;
}


/*
 * These two funcions are given to loaded FMU's to use the logger of their container
 */
void logger_embedded_fmu2(void *fmu, fmi2String instanceName, fmi2Status status,
                          fmi2String category, fmi2String message, ...) {
    (void)instanceName; /* unused parameter */
    (void)category; /* unused parameter */
    const logger_t *logger = &((fmu_t *)fmu)->container->logger;

    if ((status != 0) || (logger->debug)) {
        char buffer[4096];
        va_list ap;
        va_start(ap, message);
        snprintf(buffer, sizeof(buffer), "%s: ", ((fmu_t *)fmu)->name);
        vsnprintf(buffer+strlen(buffer), sizeof(buffer)-strlen(buffer), message, ap);
        va_end(ap);

        logger_log(logger, status, buffer);
    }
    return;
}


void logger_embedded_fmu3(void * fmu, fmi3Status status, fmi3String category, fmi3String message) {
    (void)category; /* unused parameter */
    const logger_t *logger = &((fmu_t *)fmu)->container->logger;

    if ((status != 0) || (logger->debug)) {
        char buffer[4096];
        snprintf(buffer, sizeof(buffer), "%s: %s", ((fmu_t *)fmu)->name, message);

        logger_log(logger, status, buffer);
    }
    return;
}
