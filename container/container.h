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
	fmu_version_t			   fmi_version;
	int							mt;
	int							profiling;
	size_t					    nb_fmu;
	fmu_t						*fmu;
	char						*instance_name;
	char						*uuid;


	/* storage of local variables (conveyed from one FMU to an other) */
	size_t		   				nb_local_reals;
	size_t						nb_local_integers;
	size_t						nb_local_booleans;
	size_t						nb_local_strings;

	double						*reals;
	int                 		*integers;
	int                 		*booleans;
	const char                  **strings;

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
