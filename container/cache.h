#ifndef CACHE_H
#   define CACHE_H

#	ifdef __cplusplus
extern "C" {
#	endif

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "container.h"

/*
 * Cache of the container: the state to come, set by the importer. It holds the values set on the ports linked to
 * embedded FMUs or to local variables, and for each embedded FMU the set of its links that got a value. fmi*Set only
 * writes the cache (cache_store_<type>, cache_port_set); an FMU gets the values of its set when it is synchronized
 * (cache_sync_fmu), in the order of the calls of the importer. When a step becomes pending, every FMU is synchronized:
 * what enters the cache while it is pending is for after it, so nothing is synchronized before its end
 * (cache_end_pending_step writes then the local variables of the ports set meanwhile). Clocks are events: never
 * cached.
 */

typedef struct cache_s cache_t;

/* Types of the cache. */
#define DECLARE_CACHE_TYPE(variable, fmi_type, c_type) CACHE_TYPE_ ## variable,
typedef enum {
	FOR_ALL_NUMERIC_TYPES(DECLARE_CACHE_TYPE)
	CACHE_TYPE_strings,
	CACHE_TYPE_binaries
} cache_type_t;
#undef DECLARE_CACHE_TYPE


/*----------------------------------------------------------------------------
                            P R O T O T Y P E S
----------------------------------------------------------------------------*/

/* Once the ports and the start values of the embedded FMUs are read. NULL on an allocation failure. */
extern cache_t *cache_new(container_t *container);
extern void cache_free(cache_t *cache);
/* Reset of the container: no value set by the importer. */
extern void cache_reset(container_t *container);

/* fmi*Set: stores the values of a port (nvalues: number of values in value[], at most its dimension). */
#define DECLARE_CACHE_STORE(variable, fmi_type, c_type) \
extern int cache_store_ ## variable(container_t *container, container_port_t *port, const c_type value[], \
                                    size_t nvalues);
FOR_ALL_NUMERIC_TYPES(DECLARE_CACHE_STORE)
#undef DECLARE_CACHE_STORE
extern int cache_store_strings(container_t *container, container_port_t *port, const char * const value[],
                               size_t nvalues);
extern int cache_store_binaries(container_t *container, container_port_t *port, const size_t size[],
                                const uint8_t * const value[], size_t nvalues);
/* fmi*Set, once the values are stored: adds the links of the port to embedded FMUs to the sets of their FMU. Returns
   true when the caller writes now its local variables (not while a step is pending). */
extern bool cache_port_set(container_t *container, cache_type_t type, container_port_t *port);

/* fmi*Get: the values of a port set by the importer (dimension values). False when the port has none. */
#define DECLARE_CACHE_READ(variable, fmi_type, c_type) \
extern bool cache_read_ ## variable(const container_t *container, const container_port_t *port, c_type value[]);
FOR_ALL_NUMERIC_TYPES(DECLARE_CACHE_READ)
#undef DECLARE_CACHE_READ
extern bool cache_read_strings(const container_t *container, const container_port_t *port, const char *value[]);
extern bool cache_read_binaries(const container_t *container, const container_port_t *port, size_t size[],
                                const uint8_t *value[]);

/* Adds again the cached values of the FMU to its set, so that they prevail over its start values: all of them
   (reset < 0), or those of the variables whose start value has this <RESET>. */
extern void cache_mark_fmu(container_t *container, unsigned long fmu_id, int reset);
/* Sets on the FMU of index fmu_id the values of its set (continuous_only: its real variables only, in Continuous
   Time Mode). */
extern fmu_status_t cache_sync_fmu(container_t *container, unsigned long fmu_id, bool continuous_only);
/* cache_sync_fmu() before a step or a read of the FMU: nothing while a step is pending. */
extern fmu_status_t cache_sync_fmu_now(container_t *container, unsigned long fmu_id, bool continuous_only);
/* Before a step becomes pending: every FMU gets the values set until now. */
extern fmu_status_t cache_sync_fmus(container_t *container);
/* End of a pending step: the local variables of the ports set meanwhile are written. */
extern fmu_status_t cache_end_pending_step(container_t *container);

#	ifdef __cplusplus
}
#	endif
#endif
