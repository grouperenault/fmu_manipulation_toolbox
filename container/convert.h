#ifndef CONVERT_H
#define CONVERT_H

#	ifdef __cplusplus
extern "C" {
#	endif

#include "fmu.h"

/*----------------------------------------------------------------------------
                     C O N V E R T _ F U N C T I O N _ T
----------------------------------------------------------------------------*/

typedef void (*convert_function_t)(const struct container_s *,
	                               fmu_vr_t,
                    			   fmu_vr_t);


/*----------------------------------------------------------------------------
                    C O N V E R T _ T A B L E _ E N T R Y _ T
----------------------------------------------------------------------------*/

typedef struct {
	fmu_vr_t 			    from;
	fmu_vr_t 			    to;
	convert_function_t      function;
} convert_table_entry_t;


/*----------------------------------------------------------------------------
                        C O N V E R T _ T A B L E _ T
----------------------------------------------------------------------------*/

typedef struct convert_table_s {
	unsigned long 		    nb;
	convert_table_entry_t   *entries;
} convert_table_t;


/*----------------------------------------------------------------------------
                            P R O T O T Y P E S
----------------------------------------------------------------------------*/

extern convert_table_t *convert_new(unsigned long nb);
extern void convert_free(convert_table_t *table);
extern void convert_proceed(const struct container_s *container,
                            const convert_table_t *table);
extern convert_function_t convert_function_get(const char *function_name);

#	ifdef __cplusplus
}
#	endif
#endif
