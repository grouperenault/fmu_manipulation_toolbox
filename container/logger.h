#ifndef LOGGER_H
#   define LOGGER_H

#	ifdef __cplusplus
extern "C" {
#	endif

#include "fmi2Functions.h"

#include "container.h"


/*----------------------------------------------------------------------------
                            P R O T O T Y P E S
----------------------------------------------------------------------------*/

void logger_init(const container_t *container);
void logger(fmi2Status status, const char *message, ...);
void logger_embedded_fmu(fmu_t *fmu,
                         fmi2String instanceName, fmi2Status status,
                         fmi2String category, fmi2String message, ...);

#	ifdef __cplusplus
}
#	endif
#endif
