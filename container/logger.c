#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "container.h"
#include "logger.h"

static const container_t *logger_container = NULL;

void logger_init(const container_t *container) {
    logger_container = container;
}

void logger(int status, const char *message, ...) {
    va_list ap;
    va_start(ap, message);
    if (logger_container) {
        char buffer[4096];

        vsnprintf(buffer, sizeof(buffer), message, ap);
        va_end(ap);

        if ((status != LOGGER_DEBUG) || (logger_container->debug)) {
            logger_container->logger(logger_container->environment,
                                     logger_container->instance_name,
                                     status, NULL, "%s", buffer);
        }
    } else {
        vprintf(message, ap);
    }

    return;
}


void logger_embedded_fmu(fmu_t *fmu,
                         const char *instanceName, int status,
                         const char *category, const char *message, ...) {
    const container_t *container = fmu->container;
    char buffer[4096];
    va_list ap;
    va_start(ap, message);
    vsnprintf(buffer, sizeof(buffer), message, ap);
    va_end(ap);

    if ((status != 0) || (container->debug))
        container->logger(container->environment, container->instance_name, status, NULL, "%s: %s",
                          fmu->name, buffer);
    /*logger(status, "logger_embedded(name=%s, instance=%s, status=%d msg=%s",
           fmu->name, instanceName, status, buffer);*/

    return;
}
