#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "fmi2Functions.h"

#include "container.h"

static const container_t *logger_container = NULL;

void logger_init(const container_t *container) {
    logger_container = container;
}

void logger(fmi2Status status, const char *message, ...) {
    va_list ap;
    va_start(ap, message);
    if (logger_container) {
        char buffer[4096];

        vsnprintf(buffer, sizeof(buffer), message, ap);
        va_end(ap);

        if ((status != fmi2OK) || (logger_container->debug)) {
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
                         fmi2String instanceName, fmi2Status status,
                         fmi2String category, fmi2String message, ...) {
    const container_t *container = fmu->container;
    char buffer[4096];
    va_list ap;
    va_start(ap, message);
    vsnprintf(buffer, sizeof(buffer), message, ap);
    va_end(ap);

    if ((status != fmi2OK) || (container->debug))
        container->logger(container->environment, container->instance_name, status, NULL, "%s: %s", fmu->identifier, buffer);
    /*logger(fmu->container, status, "logger_embedded(%s, %s)", fmu->identifier, instanceName);*/

    return;
}
