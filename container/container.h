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
	fmu_vr_t					fmu_vr;
	unsigned long				fmu_id;
} container_vr_t;


/*----------------------------------------------------------------------------
                      C O N T A I N E R _ P O R T _ T
----------------------------------------------------------------------------*/

typedef struct {
    unsigned long               nb;	 /* number of connected FMU from a container port */
    container_vr_t              *links;
} container_port_t;


/*----------------------------------------------------------------------------
                       C O N T A I N E R _ C L O C K _ T
----------------------------------------------------------------------------*/

typedef struct {
	unsigned long				fmu_id;
	unsigned long				nb;

} container_clock_counter_t;

typedef struct {
	unsigned long				fmu_id;
	fmu_vr_t					fmu_vr;
	unsigned long				local_vr;
} container_clock_t;


/*----------------------------------------------------------------------------
                C O N T A I N E R _ C L O C K _ L I S T _ T
----------------------------------------------------------------------------*/

typedef struct {
	unsigned long				nb_fmu;
	container_clock_counter_t	*counter;

	double						*buffer_interval;	/* for getIntervalDecimal */
	int							*buffer_qualifier;  /* for getIntervalDecimal */

	unsigned long				nb_local_clocks;
	fmu_vr_t					*fmu_vr;            /* ordered clock VR */
	unsigned long				*clock_index;
	unsigned long				*fmu_id;		

	unsigned long				nb_next_clocks;
	container_clock_t			*next_clocks;
} container_clock_list_t;


/*----------------------------------------------------------------------------
            C O N T A I N E R _ D O _ S T E P _ F U N C T I O N _ T
----------------------------------------------------------------------------*/

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
	DECLARE_LOCAL(binaries, fmu_binary_t);
	DECLARE_LOCAL(clocks, bool);
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
	DECLARE_PORT(binaries);
	DECLARE_PORT(clocks);
#undef DECLARE_PORT

	convert_table_t				conversions;

	/* Simulation */
	container_do_step_function_t do_step;
	double						time_step;				/* fundamental timestep */
	double						next_step;				/* in case of event */
	long long					nb_steps;				/* incremental counter */
	double						start_time;				/* used for initialization */
	int							stop_time_defined;	
	double						stop_time;				/* used for initialization */
	int							tolerance_defined;
	double						tolerance;				/* used for comparisons */
	container_clock_list_t		clocks_list;

	struct datalog_s			*datalog;

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
extern fmu_status_t container_update_discrete_state(container_t *container);
extern fmu_status_t container_enter_step_mode(container_t *container);
extern fmu_status_t container_do_step(container_t* container, double currentCommunicationPoint, double communicationStepSize);

#	ifdef __cplusplus
}
#	endif
#endif
