#ifndef LOGGER_H
#   define LOGGER_H

#	ifdef __cplusplus
extern "C" {
#	endif


#include "container.h"


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
