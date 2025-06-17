#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "container.h"
#include "logger.h"

static struct {
    fmu_version_t       version;
    logger_function_t   callback;
    void                *environment;
    const char          *instance_name;
    int                 debug;
} _logger = { 0, NULL, NULL, NULL, 0};

void logger_init(fmu_version_t  version, logger_function_t callback, void *environment, const char *instance_name, int debug) {
    _logger.version = version;
    _logger.callback = callback;
    _logger.environment = environment;
    _logger.instance_name = instance_name;
    _logger.debug = debug;

    return;
}

void logger_set_debug(int debug)  {
    _logger.debug = debug;

    return;
}


int logger_get_debug(void) {
    return _logger.debug;
}

void logger(int status, const char *message, ...) {
    va_list ap;
    va_start(ap, message);
    if (_logger.version) {
        char buffer[4096];

        vsnprintf(buffer, sizeof(buffer), message, ap);
        va_end(ap);

        if ((status != LOGGER_DEBUG) || (_logger.debug)) {
            if (_logger.version == 2)
                _logger.callback.logger_fmi2(_logger.environment,
                                             _logger.instance_name,
                                             status, NULL, "%s", buffer);
            else
                _logger.callback.logger_fmi3(_logger.environment,
                                             status, NULL, buffer);
                    
        }
    } else {
        vprintf(message, ap);
    }

    return;
}


void logger_embedded_fmu(fmu_t *fmu,
                         const char *instanceName, int status,
                         const char *category, const char *message, ...) {
    char buffer[4096];
    va_list ap;
    va_start(ap, message);
    vsnprintf(buffer, sizeof(buffer), message, ap);
    va_end(ap);

    if ((status != 0) || (_logger.debug)) {
        if (_logger.version == 2)
            _logger.callback.logger_fmi2(_logger.environment, _logger.instance_name, status, NULL, "%s: %s",
                                         fmu->name, buffer);
        else {
            char buffer3[4096];
            snprintf(buffer3, sizeof(buffer3), "%s: %s", fmu->name, buffer);
            _logger.callback.logger_fmi3(_logger.environment, status, NULL, buffer);
        }
    }
    return;
}
