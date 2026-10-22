#ifndef LOGGER_H
#   define LOGGER_H

#	ifdef __cplusplus
extern "C" {
#	endif

#include "config.h"
#include "fmu.h"

#define LOGGER_LEVEL_DEBUG      0   /* fmi2OK or fmi3OK */
#define LOGGER_LEVEL_WARNING    1   /* fmi2Warning or fmi3Warning */
#define LOGGER_LEVEL_ERROR      3   /* fmi2Error or fmi3Error */


/*---------------------------------------------------------------------------
             L O G G E R _ F U N C T I O N _ T Y P E _ T
---------------------------------------------------------------------------*/

typedef union {
    fmi2CallbackLogger          logger_fmi2;
    fmi3LogMessageCallback      logger_fmi3;
} logger_function_t;


/*---------------------------------------------------------------------------
                            L O G G E R _ T
---------------------------------------------------------------------------*/

/* Logger of one instance of the container: the callback given by its importer. */
typedef struct logger_s {
    fmu_version_t               version;        /* 0 until logger_init(): messages printed on stdout */
    logger_function_t           callback;       /* may be NULL (FMI-3.0): no message is sent */
    void                        *environment;
    const char                  *instance_name;
    int                         debug;
} logger_t;


/*----------------------------------------------------------------------------
                            P R O T O T Y P E S
----------------------------------------------------------------------------*/

extern void logger_init(logger_t *logger, fmu_version_t version, logger_function_t callback,
                        void *environment, const char *instance_name, int debug);
/* logger may be NULL: no message is sent. */
extern void logger_message(const logger_t *logger, int level, const char *message, ...)
    __attribute__((__format__(__printf__, 3, 4)));
extern void logger_embedded_fmu2(void *fmu, fmi2String instanceName,
                                 fmi2Status status, fmi2String category, fmi2String message, ...) __attribute__((__format__(__printf__, 5, 6)));
extern void logger_embedded_fmu3(void *fmu,
                                 fmi3Status status, fmi3String category, fmi3String message);

/*
 * Logging macros: they use the variable `logger` (const logger_t *) of the calling scope, e.g.
 *     const logger_t *logger = &container->logger;
 * LOGGER_DEBUG tests the debug flag inline: when it is off, neither logger_message() is called nor its arguments
 * evaluated, which matters in the per-value paths (getters, setters, cache of the importer values).
 */
#define LOGGER_DEBUG(...)       do { if (logger && logger->debug) \
                                         logger_message(logger, LOGGER_LEVEL_DEBUG, __VA_ARGS__); } while (0)
#define LOGGER_WARNING(...)     logger_message(logger, LOGGER_LEVEL_WARNING, __VA_ARGS__)
#define LOGGER_ERROR(...)       logger_message(logger, LOGGER_LEVEL_ERROR, __VA_ARGS__)

#	ifdef __cplusplus
}
#	endif
#endif
