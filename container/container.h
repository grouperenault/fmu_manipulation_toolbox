#ifndef CONTAINER_H
#define CONTAINER_H


#include "fmu.h"
#include "library.h"

/*----------------------------------------------------------------------------
                      C O N T A I N E R _ V R _ T
----------------------------------------------------------------------------*/
typedef struct {
	fmi2ValueReference			fmu_vr;
	int							fmu_id;
} container_vr_t;


/*----------------------------------------------------------------------------
                            C O N T A I N E R _ T
----------------------------------------------------------------------------*/
typedef struct container_s {
	int							mt;
	int							profiling;
	int							nb_fmu;
	fmi2CallbackLogger			logger;
	fmi2ComponentEnvironment	environment;
	char						*instance_name;
	char						*uuid;
	fmi2Boolean					debug;
	const fmi2CallbackFunctions	*callback_functions;

	fmi2ValueReference		    nb_local_reals;
	fmi2ValueReference			nb_local_integers;
	fmi2ValueReference			nb_local_booleans;
	fmi2ValueReference			nb_local_strings;
	fmi2Real					*reals;
	fmi2Integer                 *integers;
	fmi2Boolean                 *booleans;
	fmi2String                  *strings;

	fmi2ValueReference   		nb_ports_reals;
	fmi2ValueReference			nb_ports_integers;
	fmi2ValueReference			nb_ports_booleans;
	fmi2ValueReference			nb_ports_strings;
	container_vr_t				*vr_reals;
	container_vr_t				*vr_integers;
	container_vr_t				*vr_booleans;
	container_vr_t				*vr_strings;

	fmi2Real					time_step;
	fmi2Real					time;
	fmi2Real					tolerance;

	fmu_t						*fmu;

	fmi2Boolean					noSetFMUStatePriorToCurrentPoint;

} container_t;


/*
 * No prototypes explicitly exposed here: this file implemenets FMI2 API !
 */

#endif
