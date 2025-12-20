#ifndef LOGGER_H
#   define LOGGER_H

#	ifdef __cplusplus
extern "C" {
#	endif


#include "fmu.h"

#define LOGGER_DEBUG        0   /* fmi2OK or fmi3OK */
#define LOGGER_WARNING      1   /* fmi2Warning or fmi3Warning */
#define LOGGER_ERROR        3   /* fmi2Error or fmi3Error */


/*---------------------------------------------------------------------------
             L O G G E R _ F U N C T I O N _ T Y P E _ T
---------------------------------------------------------------------------*/

typedef union {
    fmi2CallbackLogger          logger_fmi2;
    fmi3LogMessageCallback      logger_fmi3;
} logger_function_t;


/*----------------------------------------------------------------------------
                            P R O T O T Y P E S
----------------------------------------------------------------------------*/

extern void logger_init(fmu_version_t version, logger_function_t callback,
                        void *environment,
                        const char *instance_name, int debug);
extern void logger_set_debug(int debug);
extern int logger_get_debug(void);
extern void logger(int status, const char *message, ...);
extern void logger_embedded_fmu2(void *fmu, fmi2String instanceName,
                                 fmi2Status status, fmi2String category, fmi2String message, ...);
extern void logger_embedded_fmu3(void *fmu,
                                 fmi3Status status, fmi3String category, fmi3String message);
                                 
#	ifdef __cplusplus
}
#	endif
#endif
