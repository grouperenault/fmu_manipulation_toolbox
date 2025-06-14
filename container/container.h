#ifndef CONTAINER_H
#define CONTAINER_H

#	ifdef __cplusplus
extern "C" {
#	endif

#include "fmu.h"
#include "library.h"

/*----------------------------------------------------------------------------
                      C O N T A I N E R _ V R _ T
----------------------------------------------------------------------------*/
typedef struct {
	fmu_vr_t			fmu_vr;
	int					fmu_id;
} container_vr_t;


/*----------------------------------------------------------------------------
                      C O N T A I N E R _ P O R T _ T
----------------------------------------------------------------------------*/
typedef struct {
    int                         nb;	 /* number of connected FMU from a container port */
    container_vr_t              *links;
} container_port_t;


/*----------------------------------------------------------------------------
                            C O N T A I N E R _ T
----------------------------------------------------------------------------*/
typedef struct container_s {
	int							fmi_version;
	int							mt;
	int							profiling;
	int							nb_fmu;
	fmu_t						*fmu;
	fmi2CallbackLogger			logger;
	fmi2ComponentEnvironment	environment;
	char						*instance_name;
	char						*uuid;
	int							debug;

	/* storage of local variables (conveyed from one FMU to an other) */
	fmi2ValueReference		    nb_local_reals;
	fmi2ValueReference			nb_local_integers;
	fmi2ValueReference			nb_local_booleans;
	fmi2ValueReference			nb_local_strings;

	fmi2Real					*reals;
	fmi2Integer                 *integers;
	fmi2Boolean                 *booleans;
	fmi2String                  *strings;

	/* container ports definition */
#define DECLARE_PORT(type) \
    int				   			nb_ports_ ## type; \
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
} container_t;


/*----------------------------------------------------------------------------
                            P R O T O T Y P E S
----------------------------------------------------------------------------*/

extern int container_read_conf(container_t* container, const char* dirname);

#	ifdef __cplusplus
}
#	endif
#endif
