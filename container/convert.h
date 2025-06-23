#ifndef CONVERT_H
#define CONVERT_H

#	ifdef __cplusplus
extern "C" {
#	endif

#include "container.h"
#include "fmu.h"

/*----------------------------------------------------------------------------
                     C O N V E R T _ F U N C T I O N _ T
----------------------------------------------------------------------------*/

typedef void (*convert_function_t)(const container_t *,
	                               fmu_vr_t,
                    			   fmu_vr_t);


/*----------------------------------------------------------------------------
                        C O N V E R T _ T A B L E _ T
----------------------------------------------------------------------------*/

typedef struct {
	unsigned long 		nb;
	fmu_vr_t 			from;
	fmu_vr_t 			to;
	convert_function_t  function;
} convert_table_t;

typedef enum {
    CONVERT_F32_F64 = 0,
    CONVERT_D8_D16 = 1,
    CONVERT_D8_U16 = 2,
    CONVERT_D8_D32 = 3,
    CONVERT_D8_U32 = 4,
    CONVERT_D8_D64 = 5,
    CONVERT_D8_U64 = 6,
    CONVERT_U8_D16 = 7,
    CONVERT_U8_U16 = 8,
    CONVERT_U8_D32 = 9,
    CONVERT_U8_U32 = 10,
    CONVERT_U8_D64 = 11,
    CONVERT_U8_U64 = 12,
    CONVERT_D16_D32 = 13,
    CONVERT_D16_U32 = 14,
    CONVERT_D16_D64 = 15,
    CONVERT_D16_U64 = 16,
    CONVERT_U16_D32 = 17,
    CONVERT_U16_U32 = 18,
    CONVERT_U16_D64 = 19,
    CONVERT_U16_U64 = 20,
    CONVERT_D32_D64 = 21,
    CONVERT_D32_U64 = 22,
    CONVERT_U32_D64 = 23,
    CONVERT_U32_U64 = 24
} convert_function_id_t;

/*----------------------------------------------------------------------------
                            P R O T O T Y P E S
----------------------------------------------------------------------------*/

#	ifdef __cplusplus
}
#	endif
#endif
