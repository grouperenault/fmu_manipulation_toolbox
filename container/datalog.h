#ifndef DATALOG_H
#define DATALOG_H

#	ifdef __cplusplus
extern "C" {
#	endif

#include "container.h"

/*----------------------------------------------------------------------------
                            D A T A L O G _ T
----------------------------------------------------------------------------*/
#define DECLARE(type, c_type) \
    unsigned long                   nb_ ## type; \
    fmu_vr_t                        *vr_ ## type; \
    c_type                          *values_ ## type

typedef struct datalog_s {
    FILE                            *file;
	DECLARE(reals64, double);
	DECLARE(reals32, float);
	DECLARE(integers8, int8_t);
	DECLARE(uintegers8, uint8_t);
	DECLARE(integers16, int16_t);
	DECLARE(uintegers16, uint16_t);
	DECLARE(integers32, int32_t);
	DECLARE(uintegers32, uint32_t);
	DECLARE(integers64, int64_t);
	DECLARE(uintegers64, uint64_t);
	DECLARE(booleans, int);
	DECLARE(booleans1, bool);
	DECLARE(strings, const char *);
	DECLARE(binaries, const uint8_t *);
    size_t                          *size_binaries;
	DECLARE(clocks, bool);
} datalog_t;

#undef DECLARE


/*----------------------------------------------------------------------------
                            P R O T O T Y P E S
----------------------------------------------------------------------------*/

extern void datalog_log(container_t* container);
extern datalog_t *datalog_new(const char *dirname);
extern void datalog_free(datalog_t *datalog);

#	ifdef __cplusplus
}
#	endif
#endif
