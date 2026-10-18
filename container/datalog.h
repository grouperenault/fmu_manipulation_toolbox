#ifndef DATALOG_H
#define DATALOG_H

#	ifdef __cplusplus
extern "C" {
#	endif

#include "container.h"

/*----------------------------------------------------------------------------
                            D A T A L O G _ T
----------------------------------------------------------------------------*/
#define DECLARE(variable, fmi_type, c_type)             \
    unsigned long                   nb_ ## variable;    \
    fmu_vr_t                        *vr_ ## variable;   \
    c_type                          *values_ ## variable;

typedef struct datalog_s {
    FILE                            *file;
    config_c_locale_t               c_locale;   /* rows written with a decimal dot */
    bool                            c_locale_ready;
    FOR_ALL_NUMERIC_TYPES(DECLARE)
    DECLARE(strings, String, const char *)
    DECLARE(binaries, Binary, const uint8_t *)
    size_t                          *size_binaries;
    DECLARE(clocks, Clock, bool)
} datalog_t;

#undef DECLARE


/*----------------------------------------------------------------------------
                            P R O T O T Y P E S
----------------------------------------------------------------------------*/

extern void datalog_log(container_t* container);
struct logger_s;
extern datalog_t *datalog_new(const struct logger_s *logger, const char *dirname);
extern int datalog_configure(config_file_t *config, datalog_t *datalog);
extern void datalog_free(datalog_t *datalog);

#	ifdef __cplusplus
}
#	endif
#endif
