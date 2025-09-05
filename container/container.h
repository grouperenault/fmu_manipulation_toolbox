#ifndef CONTAINER_H
#define CONTAINER_H

#	ifdef __cplusplus
extern "C" {
#	endif

#include "convert.h"
#include "fmu.h"
#include "library.h"
#include "logger.h"

/*----------------------------------------------------------------------------
                      C O N T A I N E R _ V R _ T
----------------------------------------------------------------------------*/
typedef struct {
	fmu_vr_t			fmu_vr;
	long				fmu_id;
} container_vr_t;


/*----------------------------------------------------------------------------
                      C O N T A I N E R _ P O R T _ T
----------------------------------------------------------------------------*/
typedef struct {
    unsigned long               nb;	 /* number of connected FMU from a container port */
    container_vr_t              *links;
} container_port_t;


typedef fmu_status_t (*container_do_step_function_t)(struct container_s *container);

/*----------------------------------------------------------------------------
                            C O N T A I N E R _ T
----------------------------------------------------------------------------*/
typedef struct container_s {
	/* configuration */
	int							profiling;
	int							nb_fmu;
	fmu_t						*fmu;		/* embedded FMUs */
	char						*instance_name;
	char						*uuid;

	/* storage of local variables (conveyed from one FMU to an other) */
#define DECLARE_LOCAL(name, type) \
	unsigned long				nb_local_ ## name; \
	type						* name

	DECLARE_LOCAL(reals64, double);
	DECLARE_LOCAL(reals32, float);
	DECLARE_LOCAL(integers8, int8_t);
	DECLARE_LOCAL(uintegers8, uint8_t);
	DECLARE_LOCAL(integers16, int16_t);
	DECLARE_LOCAL(uintegers16, uint16_t);
	DECLARE_LOCAL(integers32, int32_t);
	DECLARE_LOCAL(uintegers32, uint32_t);
	DECLARE_LOCAL(integers64, int64_t);
	DECLARE_LOCAL(uintegers64, uint64_t);
	DECLARE_LOCAL(booleans, int);
	DECLARE_LOCAL(booleans1, bool);
	DECLARE_LOCAL(strings, char *);
#undef DECLARE_LOCAL

	/* container ports definition */
#define DECLARE_PORT(type) \
    unsigned long	   			nb_ports_ ## type; \
    container_vr_t				*vr_ ## type; /* used as buffer to optimize malloc() operations */ \
    container_port_t            *port_ ## type

    DECLARE_PORT(reals64);
	DECLARE_PORT(reals32);
    DECLARE_PORT(integers8);
    DECLARE_PORT(uintegers8);
    DECLARE_PORT(integers16);
    DECLARE_PORT(uintegers16);
    DECLARE_PORT(integers32);
    DECLARE_PORT(uintegers32);
    DECLARE_PORT(integers64);
    DECLARE_PORT(uintegers64);
    DECLARE_PORT(booleans);
    DECLARE_PORT(booleans1);
    DECLARE_PORT(strings);
#undef DECLARE_PORT

	convert_table_t				conversions;

	/* Simulation */
	container_do_step_function_t do_step;
	double						time_step;
	long long					nb_steps;
	double						tolerance;
	double						start_time;
	double						stop_time;
	int							tolerance_defined;
	int							stop_time_defined;

	fmi2CallbackAllocateMemory	allocate_memory;		/* used to embed FMU-2.0 */
	fmi2CallbackFreeMemory      free_memory;			/* used to embed FMU-2.0 */
} container_t;



/*----------------------------------------------------------------------------
                            P R O T O T Y P E S
----------------------------------------------------------------------------*/

extern container_t *container_new(const char *instance_name, const char *fmu_uuid);
extern int container_configure(container_t* container, const char* dirname);
extern void container_free(container_t *container);

extern void container_set_start_values(container_t* container, int early_set);
extern void container_init_values(container_t* container);

#	ifdef __cplusplus
}
#	endif
#endif
