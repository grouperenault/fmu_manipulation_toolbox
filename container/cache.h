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
 * writes the cache (cache_set_<type>); an FMU gets the values of its set when it is synchronized
 * (cache_sync_fmu), in the order of the calls of the importer. When a step becomes pending, every FMU is synchronized:
 * what enters the cache while it is pending is for after it, so nothing is synchronized before its end
 * (cache_end_pending_step writes then the local variables of the ports set meanwhile). Clocks are events: never
 * cached.
 */


 /*----------------------------------------------------------------------------
                          C A C H E _ T Y P E _ T
----------------------------------------------------------------------------*/
/* port->cache.offset of a port without link: it has no place in the cache. */
#define CACHE_NONE                  (~0UL)

/* Types of the cache. The types of this file are tagged: an analyzer that reads it twice in one translation unit
   (IntelliSense, C23) sees the same types. */
#define DECLARE_CACHE_TYPE(variable, fmi_type, c_type) CACHE_TYPE_ ## variable,
typedef enum cache_type_e {
	FOR_ALL_NUMERIC_TYPES(DECLARE_CACHE_TYPE)
	CACHE_TYPE_strings,
	CACHE_TYPE_binaries
} cache_type_t;
#undef DECLARE_CACHE_TYPE


/*----------------------------------------------------------------------------
                      C A C H E _ S E T _ E N T R Y _ T
----------------------------------------------------------------------------*/

typedef struct {
    cache_type_t                type;
    container_port_t            *port;
    container_vr_t              *link;      /* NULL in the set of the ports linked to local variables */
} cache_set_entry_t;


/*----------------------------------------------------------------------------
                          C A C H E _ S E T _ T
----------------------------------------------------------------------------*/
/* Set of the variables set by the importer: allocated with the cache, for all the entries it may hold. */
typedef struct {
    unsigned long               nb;
    unsigned long               size;
    cache_set_entry_t           *entries;
} cache_set_t;


/*----------------------------------------------------------------------------
                              C A C H E _ T
----------------------------------------------------------------------------*/

typedef struct cache_s {
    /* values set by the importer, at port->cache.offset (dimension values per port) */
#define DECLARE_VALUES(variable, fmi_type, c_type)  \
    unsigned long               nb_ ## variable;    \
    c_type                      *variable;

    FOR_ALL_NUMERIC_TYPES(DECLARE_VALUES)
    DECLARE_VALUES(strings, String, fmu_string_t)
    DECLARE_VALUES(binaries, Binary, fmu_binary_t)
#undef DECLARE_VALUES

    cache_set_t                 *sets;          /* for each embedded FMU: its links whose value is to set */
    unsigned long               nb_sets;
    cache_set_entry_t           *set_entries;   /* storage of the entries of all the sets of the FMUs */
    cache_set_t                 deferred;       /* ports linked to local variables set while a step is pending */

    /* arrays of the values of a string or binary port, to set or read them (size: largest dimension) */
    const char                  **strings_scratch;
    size_t                      *sizes_scratch;
    const uint8_t               **binaries_scratch;
} cache_t;


/*----------------------------------------------------------------------------
                            P R O T O T Y P E S
----------------------------------------------------------------------------*/

/* Once the ports and the start values of the embedded FMUs are read. NULL on an allocation failure. */
extern cache_t *cache_new(container_t *container);
extern void cache_free(cache_t *cache);
/* Reset of the container: no value set by the importer. */
extern void cache_reset(container_t *container);

/* fmi*Set of a port: stores its values (nvalues: number of values in value[], at most its dimension) and adds its
   links to embedded FMUs to the sets of their FMU. Returns 1 when the caller writes now the local variables of the
   port (it has some, and no step is pending), 0 otherwise, -1 on an allocation failure. */
#define DECLARE_CACHE_SET(variable, fmi_type, c_type) \
extern int cache_set_ ## variable(container_t *container, container_port_t *port, const c_type value[], \
                                  size_t nvalues);
FOR_ALL_NUMERIC_TYPES(DECLARE_CACHE_SET)
#undef DECLARE_CACHE_SET
extern int cache_set_strings(container_t *container, container_port_t *port, const char * const value[],
                             size_t nvalues);
extern int cache_set_binaries(container_t *container, container_port_t *port, const size_t size[],
                              const uint8_t * const value[], size_t nvalues);

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
