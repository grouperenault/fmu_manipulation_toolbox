#ifndef CONVERT_H
#define CONVERT_H

#	ifdef __cplusplus
extern "C" {
#	endif

#include "container.h"
#include "fmu.h"


typedef void (*convert_function_t)(const container_t *,
	                               fmu_vr_t,
                    			   fmu_vr_t);

typedef struct {
	unsigned long 		nb;
	fmu_vr_t 			from;
	fmu_vr_t 			to;
	convert_function_t  function;
} convert_table_t;

#	ifdef __cplusplus
}
#	endif
#endif
