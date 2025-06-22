#ifndef CONTAINER_H
#define CONTAINER_H

#	ifdef __cplusplus
extern "C" {
#	endif

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


/*----------------------------------------------------------------------------
                            C O N T A I N E R _ T
----------------------------------------------------------------------------*/
typedef struct container_s {
	int							mt;
	int							profiling;
	unsigned long				nb_fmu;
	fmu_t						*fmu;
	char						*instance_name;
	char						*uuid;


	/* storage of local variables (conveyed from one FMU to an other) */
	unsigned long		   		nb_local_reals;
	unsigned long				nb_local_integers;
	unsigned long				nb_local_booleans;
	unsigned long				nb_local_strings;

	double						*reals;
	float						*reals16;
	int                 		*integers;
	int                 		*booleans;
	const char                  **strings;

	/* container ports definition */
#define DECLARE_PORT(type) \
    unsigned long	   			nb_ports_ ## type; \
    container_vr_t				*vr_ ## type; /* used as buffer to optimize malloc() operations */ \
    container_port_t            *port_ ## type

    DECLARE_PORT(reals);
    DECLARE_PORT(integers);
    DECLARE_PORT(booleans);
    DECLARE_PORT(strings);
#undef DECLARE_PORT

	double						time_step;
	double						time;
	double						tolerance;
	double						start_time;
	double						stop_time;
	int							tolerance_defined;
	int							stop_time_defined;
} container_t;


/*----------------------------------------------------------------------------
                            P R O T O T Y P E S
----------------------------------------------------------------------------*/

extern int container_read_conf(container_t* container, const char* dirname);

#	ifdef __cplusplus
}
#	endif
#endif
