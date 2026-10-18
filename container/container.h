#ifndef CONTAINER_H
#define CONTAINER_H

#	ifdef __cplusplus
extern "C" {
#	endif

#include "convert.h"
#include "fmu.h"
#include "library.h"
#include "logger.h"

/* Format version of container.txt: the only one read by the runtime. Must be equal to CONTAINER_TXT_VERSION of
 * fmu_manipulation_toolbox/container/types.py. */
#define CONTAINER_TXT_VERSION		7

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

#define CONTAINER_NO_CACHE			(~0UL)

typedef struct {
	unsigned long				dimension; /* dimension of variable */
	unsigned long               nb;	 /* number of connected FMU from a container port */
    container_vr_t              *links;
	unsigned long				cache_offset; /* in container->cache_<type>, CONTAINER_NO_CACHE if no link */
	unsigned long				nb_cached;	/* number of values set by the importer, 0 if none yet */
	bool						deferred;	/* set by the importer while a step was pending: to apply after it */
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
	double                      *buffer_previous;	/* for getIntervalDecimal and fmi3IntervalUnchanged */
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


typedef enum {
	CONTAINER_STATE_INSTANTIATED,
    CONTAINER_STATE_INITIALIZATION_MODE,
    CONTAINER_STATE_CONFIGURATION_MODE,
    CONTAINER_STATE_STEP_MODE,
    CONTAINER_STATE_EVENT_MODE,
    CONTAINER_STATE_TERMINATED
} container_state_t;

/*----------------------------------------------------------------------------
                            C O N T A I N E R _ T
----------------------------------------------------------------------------*/

typedef struct container_s {
	logger_t					logger;		/* logger of this instance, given by its importer */

	/* configuration */
	int							profiling;
	int							nb_fmu;
	fmu_t						*fmu;		/* embedded FMUs (master registry) */

	/* CS working set: pointers to the CS FMUs of fmu[]. Avoids testing 'kind'
	   in the hot loops. Sized to feed thread_barrier_init() directly. */
	unsigned int				nb_cs;
	fmu_t						**cs_fmu;

	/* Indexes of fmu[] in the order of the propagation of the links during the initialization (nb_fmu entries). */
	int							*init_order;

	/* An internal step of the container started before the end of the last communication step and is not done
	   yet (communication step not a multiple of the internal step): the values set by the importer meanwhile are
	   deferred, the step uses the inputs of its beginning. */
	bool						step_pending;

	/* ME working set (states, derivatives, event indicators, flat buffers). */
	struct solver_s				*solver;

	char						*instance_name;
	char						*uuid;
	int							fmi_version;	/* 2 or 3: API used to instantiate the container */
	container_state_t			state;		/* managed in fmi2.c and fmi3.c */

	/* storage of local variables (conveyed from one FMU to an other) */
#define DECLARE_LOCAL(variable, fmi_type, c_type) 	\
	unsigned long				nb_local_ ## variable;	\
	c_type						* variable;

	FOR_ALL_NUMERIC_TYPES(DECLARE_LOCAL)
	DECLARE_LOCAL(strings, String, char *)
	DECLARE_LOCAL(binaries, Binary, fmu_binary_t)
	DECLARE_LOCAL(clocks, Clock, bool)

	const uint8_t 				**binaries_tmp;
	size_t 						*binaries_size_tmp;
	const char					**strings_tmp;

#undef DECLARE_LOCAL

	/* container ports definition */
#define DECLARE_PORT(variable, fmi_type, c_type)	\
    unsigned long	   			nb_ports_ ## variable;	\
    container_vr_t				*vr_ ## variable; /* used as buffer to optimize malloc() operations */ \
    container_port_t            *port_ ## variable;

	FOR_ALL_NUMERIC_TYPES(DECLARE_PORT)
	DECLARE_PORT(strings, String, char *)
	DECLARE_PORT(binaries, Binary, fmu_binary_t)
	DECLARE_PORT(clocks, Clock, bool)
#undef DECLARE_PORT

	/* values set by the importer on the ports forwarded to embedded FMUs, set again after the reset of an FMU
	   (clocks are events: never cached) */
#define DECLARE_CACHE(variable, fmi_type, c_type)	\
	unsigned long				nb_cache_ ## variable;	\
	c_type						*cache_ ## variable;

	FOR_ALL_NUMERIC_TYPES(DECLARE_CACHE)
	DECLARE_CACHE(strings, String, char *)
	DECLARE_CACHE(binaries, Binary, fmu_binary_t)
#undef DECLARE_CACHE

	convert_table_t				conversions;

	/* Simulation */
	container_do_step_function_t do_step;
	double						time_step;				/* fundamental timestep */
	double						next_step;				/* in case of event */
	long long					nb_steps;				/* incremental counter */
	double						start_time;				/* used for initialization */
	double						time;					/* used internally during simulation */
	bool						stop_time_defined;	
	double						stop_time;				/* used for initialization */
	bool						tolerance_defined;
	double						tolerance;				/* used for comparisons */
	container_clock_list_t		clocks_list;
	bool						need_event_update;

	bool						mt;						/* true if FMUs are executed in parallel */
	bool						cancel;					/* set once to stop all FMU worker threads */

	thread_barrier_t			barrier_start;			/* used for parallel execution of FMUs */
	thread_barrier_t			barrier_end;			/* used for parallel execution of FMUs */
	bool						barriers_ready;			/* barrier_start and barrier_end are initialized */
	thread_gate_t				threads_gate;			/* opened once every worker thread is launched */
	bool						threads_gate_ready;		/* threads_gate is initialized */
	unsigned int				nb_threads;				/* worker threads launched: cs_fmu[0 .. nb_threads-1] */

	struct datalog_s			*datalog;

	fmi2CallbackAllocateMemory	allocate_memory;		/* used to embed FMU-2.0 */
	fmi2CallbackFreeMemory      free_memory;			/* used to embed FMU-2.0 */
} container_t;


/*----------------------------------------------------------------------------
                            P R O T O T Y P E S
----------------------------------------------------------------------------*/

extern container_t *container_new(const char *instance_name, const char *fmu_uuid, int fmi_version);
extern int container_configure(container_t* container, const char* resource_location);
extern void container_free(container_t *container);
extern fmu_status_t container_setup_experiment(container_t* container, bool toleranceDefined, double tolerance,
                                               double startTime, bool stopTimeDefined, double stopTime);
extern fmu_status_t container_enter_initialization_mode(container_t* container);
extern fmu_status_t container_exit_initialization_mode(container_t* container);
extern fmu_status_t container_terminate(container_t* container);
extern fmu_status_t container_reset(container_t* container);
extern fmu_status_t container_enter_event_mode(container_t *container);
extern fmu_status_t container_enter_step_mode(container_t *container);
extern fmu_status_t container_do_step(container_t* container, double currentCommunicationPoint, double communicationStepSize);

/* cache of the values set by the importer (see DECLARE_CACHE). nvalues: number of values in value[]. */
#define DECLARE_CACHE_FUNCTION(variable, fmi_type, c_type)                                                 \
extern int container_cache_ ## variable(container_t *container, container_port_t *port, const c_type value[], \
                                        size_t nvalues);

FOR_ALL_NUMERIC_TYPES(DECLARE_CACHE_FUNCTION)
#undef DECLARE_CACHE_FUNCTION
extern int container_cache_strings(container_t *container, container_port_t *port, const char * const value[],
                                   size_t nvalues);
extern int container_cache_binaries(container_t *container, container_port_t *port, const size_t size[],
                                    const uint8_t * const value[], size_t nvalues);
/* Set again the cached values of the ports forwarded to the FMU of index fmu_id. */
extern fmu_status_t container_set_fmu_cache(container_t *container, unsigned long fmu_id);

/* for datalog facilities. */
extern void container_clocks_activate(container_t *container);
extern void container_clocks_deactivate(container_t *container);

#	ifdef __cplusplus
}
#	endif
#endif
