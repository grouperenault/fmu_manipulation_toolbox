#ifndef LOGGER_H
#   define LOGGER_H

#	ifdef __cplusplus
extern "C" {
#	endif


#include "container.h"

#define LOGGER_DEBUG        0   /* fmi2OK or fmi3OK */
#define LOGGER_WARNING      1   /* fmi2Warning or fmi3Warning */
#define LOGGER_ERROR        3   /* fmi2Error or fmi3Error */

/*---------------------------------------------------------------------------
             L O G G E R _ F U N C T I O N _ T Y P E _ T
---------------------------------------------------------------------------*/

typedef void (*logger_function_t)(void *environement, const char *instanceName,
                                  int status, const char *category, const char *message, ...);

/*----------------------------------------------------------------------------
                            P R O T O T Y P E S
----------------------------------------------------------------------------*/

void logger_init(const container_t *container);
void logger(int status, const char *message, ...);
void logger_embedded_fmu(fmu_t *fmu,
                         const char *instanceName, int status,
                         const char *category, const char *message, ...);

#	ifdef __cplusplus
}
#	endif
#endif
