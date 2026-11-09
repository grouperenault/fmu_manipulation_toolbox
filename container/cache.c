#include <inttypes.h>
#include <stdlib.h>
#include <string.h>

#include "cache.h"
#include "container.h"
#include "logger.h"


/*----------------------------------------------------------------------------
                    A L L O C A T I O N   A N D   R E S E T
----------------------------------------------------------------------------*/

#define CACHE_ALLOC(ptr, nb_elem)                                           \
    if ((nb_elem) > 0) {                                                    \
        ptr = calloc((nb_elem), sizeof(*ptr));                              \
        if (!ptr) {                                                         \
            LOGGER_ERROR("Cannot allocate memory for the cache (" #ptr ")."); \
            cache_free(cache);                                              \
            return NULL;                                                    \
        }                                                                   \
    }


cache_t *cache_new(container_t *container) {
    const logger_t *logger = &container->logger;
    cache_t *cache = calloc(1, sizeof(*cache));
    if (!cache) {
        LOGGER_ERROR("Cannot allocate memory for the cache.");
        return NULL;
    }

    /* Values: one place per value of each linked port. Links: <RESET> of the start value of their variable. */
    size_t max_strings = 0;
    size_t max_binaries = 0;
#define SETUP_VALUES(variable, fmi_type, c_type, reset_of_link)                                                   \
    for (unsigned long i = 0; i < container->nb_ports_ ## variable; i += 1) {                                   \
        container_port_t *port = &container->port_ ## variable [i];                                             \
        port->cache.nb = 0;                                                                                     \
        port->cache.deferred = false;                                                                           \
        port->cache.offset = CONTAINER_NO_CACHE;                                                                \
        if (port->nb > 0) {                                                                                     \
            port->cache.offset = cache->nb_ ## variable;                                                        \
            cache->nb_ ## variable += port->dimension;                                                          \
        }                                                                                                       \
        for (unsigned long j = 0; j < port->nb; j += 1) {                                                       \
            container_vr_t *link = &port->links[j];                                                             \
            link->cache.in_set = false;                                                                         \
            link->cache.start_reset = (long)link->fmu_id >= 0 ? (reset_of_link) : -1;                           \
        }                                                                                                       \
    }                                                                                                           \
    CACHE_ALLOC(cache->variable, cache->nb_ ## variable)

#define SETUP_NUMERIC(variable, fmi_type, c_type) \
    SETUP_VALUES(variable, fmi_type, c_type, fmu_start_reset_ ## variable(&container->fmu[link->fmu_id], link->fmu_vr))

    FOR_ALL_NUMERIC_TYPES(SETUP_NUMERIC)
    SETUP_VALUES(strings, String, fmu_string_t,
                 fmu_start_reset_strings(&container->fmu[link->fmu_id], link->fmu_vr))
    SETUP_VALUES(binaries, Binary, fmu_binary_t, -1)
#undef SETUP_NUMERIC
#undef SETUP_VALUES

    /* Sets: one entry per link to an embedded FMU in the set of this FMU, one entry per port linked to a local
       variable in the set of the deferred ports. Never reallocated. */
    unsigned long nb_entries = 0;
    unsigned long nb_deferred = 0;
    cache->nb_sets = (unsigned long)container->nb_fmu;
    CACHE_ALLOC(cache->sets, cache->nb_sets)
#define COUNT_LINKS(variable, fmi_type, c_type)                                                                 \
    for (unsigned long i = 0; i < container->nb_ports_ ## variable; i += 1) {                                   \
        const container_port_t *port = &container->port_ ## variable [i];                                       \
        bool has_local = false;                                                                                 \
        for (unsigned long j = 0; j < port->nb; j += 1) {                                                       \
            if ((long)port->links[j].fmu_id < 0)                                                                \
                has_local = true;                                                                               \
            else {                                                                                              \
                cache->sets[port->links[j].fmu_id].size += 1;                                                   \
                nb_entries += 1;                                                                                \
            }                                                                                                   \
        }                                                                                                       \
        nb_deferred += has_local ? 1 : 0;                                                                       \
    }

    FOR_ALL_NUMERIC_TYPES(COUNT_LINKS)
    COUNT_LINKS(strings, String, char *)
    COUNT_LINKS(binaries, Binary, fmu_binary_t)
#undef COUNT_LINKS

    CACHE_ALLOC(cache->set_entries, nb_entries)
    unsigned long offset = 0;
    for (unsigned long i = 0; i < cache->nb_sets; i += 1) {
        cache->sets[i].entries = cache->set_entries + offset;
        offset += cache->sets[i].size;
    }
    CACHE_ALLOC(cache->deferred.entries, nb_deferred)
    cache->deferred.size = nb_deferred;

    for (unsigned long i = 0; i < container->nb_ports_strings; i += 1) {
        if (container->port_strings[i].dimension > max_strings)
            max_strings = container->port_strings[i].dimension;
    }
    for (unsigned long i = 0; i < container->nb_ports_binaries; i += 1) {
        if (container->port_binaries[i].dimension > max_binaries)
            max_binaries = container->port_binaries[i].dimension;
    }
    CACHE_ALLOC(cache->strings_scratch, max_strings)
    CACHE_ALLOC(cache->sizes_scratch, max_binaries)
    CACHE_ALLOC(cache->binaries_scratch, max_binaries)

    return cache;
}
#undef CACHE_ALLOC


void cache_free(cache_t *cache) {
    if (!cache)
        return;

#define FREE_VALUES(variable, fmi_type, c_type) \
    free(cache->variable);

    FOR_ALL_NUMERIC_TYPES(FREE_VALUES)
#undef FREE_VALUES
    for (unsigned long i = 0; i < cache->nb_strings && cache->strings; i += 1)
        free(cache->strings[i].data);
    free(cache->strings);
    for (unsigned long i = 0; i < cache->nb_binaries && cache->binaries; i += 1)
        free(cache->binaries[i].data);
    free(cache->binaries);

    free(cache->sets);
    free(cache->set_entries);
    free(cache->deferred.entries);
    free(cache->strings_scratch);
    free(cache->sizes_scratch);
    free(cache->binaries_scratch);
    free(cache);
}


void cache_reset(container_t *container) {
    cache_t *cache = container->cache;

#define RESET_PORTS(variable, fmi_type, c_type)                                 \
    for (unsigned long i = 0; i < container->nb_ports_ ## variable; i += 1) {   \
        container_port_t *port = &container->port_ ## variable [i];             \
        port->cache.nb = 0;                                                     \
        port->cache.deferred = false;                                           \
        for (unsigned long j = 0; j < port->nb; j += 1)                         \
            port->links[j].cache.in_set = false;                                \
    }

    FOR_ALL_NUMERIC_TYPES(RESET_PORTS)
    RESET_PORTS(strings, String, char *)
    RESET_PORTS(binaries, Binary, fmu_binary_t)
#undef RESET_PORTS

    for (unsigned long i = 0; i < cache->nb_sets; i += 1)
        cache->sets[i].nb = 0;
    cache->deferred.nb = 0;
}


/*----------------------------------------------------------------------------
                    V A L U E S   S E T   B Y   T H E   I M P O R T E R
----------------------------------------------------------------------------*/

#define CACHE_STORE(type, c_type, format, cast)                                                                 \
int cache_store_ ## type(container_t *container, container_port_t *port, const c_type value[],                  \
                         size_t nvalues) {                                                                      \
    const logger_t *logger = &container->logger;                                                                \
    if (port->cache.offset == CONTAINER_NO_CACHE)                                                               \
        return 0;                                                                                               \
    if (nvalues > port->dimension)                                                                              \
        nvalues = port->dimension;                                                                              \
    for (size_t k = 0; k < nvalues; k += 1)                                                                     \
        container->cache-> type [port->cache.offset + k] = value[k];                                            \
    port->cache.nb = (unsigned long)nvalues;   /* at most the dimension of the port */                         \
    LOGGER_DEBUG("[DEBUG] Cache " #type " [%lu] = " format " (%zu value(s))", port->cache.offset,               \
                 (cast)value[0], nvalues);                                                                      \
    return 0;                                                                                                   \
}

CACHE_STORE(reals64,     double,     "%g",           double)
CACHE_STORE(reals32,     float,      "%g",           double)
CACHE_STORE(integers8,   int8_t,     "%" PRId8,      int8_t)
CACHE_STORE(uintegers8,  uint8_t,    "%" PRIu8,      uint8_t)
CACHE_STORE(integers16,  int16_t,    "%" PRId16,     int16_t)
CACHE_STORE(uintegers16, uint16_t,   "%" PRIu16,     uint16_t)
CACHE_STORE(integers32,  int32_t,    "%" PRId32,     int32_t)
CACHE_STORE(uintegers32, uint32_t,   "%" PRIu32,     uint32_t)
CACHE_STORE(integers64,  int64_t,    "%" PRId64,     int64_t)
CACHE_STORE(uintegers64, uint64_t,   "%" PRIu64,     uint64_t)
CACHE_STORE(booleans,    int,        "%d",           int)
CACHE_STORE(booleans1,   bool,       "%d",           int)
#undef CACHE_STORE


int cache_store_strings(container_t *container, container_port_t *port, const char * const value[],
                        size_t nvalues) {
    const logger_t *logger = &container->logger;
    if (port->cache.offset == CONTAINER_NO_CACHE)
        return 0;
    if (nvalues > port->dimension)
        nvalues = port->dimension;
    for (size_t k = 0; k < nvalues; k += 1) {
        if (fmu_string_copy(&container->cache->strings[port->cache.offset + k], value[k])) {
            LOGGER_ERROR("Cannot allocate memory to cache a string.");
            port->cache.nb = 0;
            return -1;
        }
    }
    port->cache.nb = (unsigned long)nvalues;   /* at most the dimension of the port */
    LOGGER_DEBUG("[DEBUG] Cache strings [%lu] = %s (%zu value(s))", port->cache.offset, value[0], nvalues);
    return 0;
}


int cache_store_binaries(container_t *container, container_port_t *port, const size_t size[],
                         const uint8_t * const value[], size_t nvalues) {
    const logger_t *logger = &container->logger;
    if (port->cache.offset == CONTAINER_NO_CACHE)
        return 0;
    if (nvalues > port->dimension)
        nvalues = port->dimension;
    for (size_t k = 0; k < nvalues; k += 1) {
        if (fmu_binary_copy(&container->cache->binaries[port->cache.offset + k], value[k], size[k])) {
            LOGGER_ERROR("Cannot allocate memory to cache a binary.");
            port->cache.nb = 0;
            return -1;
        }
    }
    port->cache.nb = (unsigned long)nvalues;   /* at most the dimension of the port */
    LOGGER_DEBUG("[DEBUG] Cache binaries [%lu] = %zu byte(s) (%zu value(s))", port->cache.offset, size[0],
                 nvalues);
    return 0;
}


/* Whether the port has all its values in the cache. */
static bool cache_has_values(const container_port_t *port) {
    return port->cache.offset != CONTAINER_NO_CACHE && port->cache.nb == port->dimension;
}


#define CACHE_READ(variable, fmi_type, c_type)                                                                  \
bool cache_read_ ## variable(const container_t *container, const container_port_t *port, c_type value[]) {      \
    if (!cache_has_values(port))                                                                                \
        return false;                                                                                           \
    for (unsigned long k = 0; k < port->dimension; k += 1)                                                      \
        value[k] = container->cache-> variable [port->cache.offset + k];                                        \
    return true;                                                                                                \
}

FOR_ALL_NUMERIC_TYPES(CACHE_READ)
#undef CACHE_READ


bool cache_read_strings(const container_t *container, const container_port_t *port, const char *value[]) {
    if (!cache_has_values(port))
        return false;
    for (unsigned long k = 0; k < port->dimension; k += 1)
        value[k] = container->cache->strings[port->cache.offset + k].data;
    return true;
}


bool cache_read_binaries(const container_t *container, const container_port_t *port, size_t size[],
                         const uint8_t *value[]) {
    if (!cache_has_values(port))
        return false;
    for (unsigned long k = 0; k < port->dimension; k += 1) {
        size[k] = container->cache->binaries[port->cache.offset + k].size;
        value[k] = container->cache->binaries[port->cache.offset + k].data;
    }
    return true;
}


/*----------------------------------------------------------------------------
                                  S E T S
----------------------------------------------------------------------------*/

static void cache_set_add(cache_set_t *set, cache_type_t type, container_port_t *port, container_vr_t *link) {
    /* The set holds at most one entry per link (or per port): allocated for all of them */
    set->entries[set->nb].type = type;
    set->entries[set->nb].port = port;
    set->entries[set->nb].link = link;
    set->nb += 1;
}


static void cache_mark_link(cache_t *cache, cache_type_t type, container_port_t *port, container_vr_t *link) {
    if (!link->cache.in_set) {
        link->cache.in_set = true;
        cache_set_add(&cache->sets[link->fmu_id], type, port, link);
    }
}


bool cache_port_set(container_t *container, cache_type_t type, container_port_t *port) {
    bool has_local = false;

    for (unsigned long j = 0; j < port->nb; j += 1) {
        if ((long)port->links[j].fmu_id < 0)
            has_local = true;
        else
            cache_mark_link(container->cache, type, port, &port->links[j]);
    }
    if (has_local && container->step_pending && !port->cache.deferred) {
        port->cache.deferred = true;
        cache_set_add(&container->cache->deferred, type, port, NULL);
    }

    return !container->step_pending;
}


/* Goes through all the ports: once per initialization, configuration or reset. */
void cache_mark_fmu(container_t *container, unsigned long fmu_id, int reset) {
#define MARK_FMU(variable, fmi_type, c_type)                                                                    \
    for (unsigned long i = 0; i < container->nb_ports_ ## variable; i += 1) {                                   \
        container_port_t *port = &container->port_ ## variable [i];                                             \
        for (unsigned long j = 0; j < port->nb && port->cache.nb > 0; j += 1) {                                 \
            container_vr_t *link = &port->links[j];                                                             \
            if (link->fmu_id == fmu_id && (reset < 0 || link->cache.start_reset == reset))                      \
                cache_mark_link(container->cache, CACHE_TYPE_ ## variable, port, link);                         \
        }                                                                                                       \
    }

    FOR_ALL_NUMERIC_TYPES(MARK_FMU)
    MARK_FMU(strings, String, char *)
    MARK_FMU(binaries, Binary, fmu_binary_t)
#undef MARK_FMU
}


/*----------------------------------------------------------------------------
                         S Y N C H R O N I Z A T I O N
----------------------------------------------------------------------------*/

typedef enum {
    CACHE_SYNC_SET,     /* set the value now */
    CACHE_SYNC_KEEP,    /* keep the entry in the set */
    CACHE_SYNC_DROP     /* remove the entry from the set without setting the value */
} cache_sync_action_t;


/* A structural parameter is set in Configuration Mode only, the other variables out of it; in Continuous Time Mode,
   the real variables only. A structural parameter set after the configuration of its FMU waits for its next
   configuration (reset), where the cache is marked again. */
static cache_sync_action_t cache_sync_action(const container_t *container, const cache_set_entry_t *entry,
                                             bool continuous_only) {
    const logger_t *logger = &container->logger;
    const fmu_t *fmu = &container->fmu[entry->link->fmu_id];
    const bool structural = entry->link->cache.start_reset == 2;

    if (continuous_only && entry->type != CACHE_TYPE_reals64 && entry->type != CACHE_TYPE_reals32)
        return CACHE_SYNC_KEEP;
    if (structural == fmu->in_configuration_mode)
        return CACHE_SYNC_SET;
    if (structural && fmu->configured) {
        LOGGER_WARNING("Container: FMU '%s' is configured: the structural parameter vr=%u set on the container is set "
                       "at its next configuration.", fmu->name, entry->link->fmu_vr);
        return CACHE_SYNC_DROP;
    }
    return CACHE_SYNC_KEEP;
}


/* Sets on its FMU the cached value of an entry of its set. */
static fmu_status_t cache_sync_entry(container_t *container, const cache_set_entry_t *entry) {
    cache_t *cache = container->cache;
    const fmu_t *fmu = &container->fmu[entry->link->fmu_id];
    const container_port_t *port = entry->port;
    const fmu_vr_t *vr = &entry->link->fmu_vr;

    switch (entry->type) {
#define CASE_SET(variable, fmi_type, c_type)                                                                \
    case CACHE_TYPE_ ## variable:                                                                           \
        return fmuSet ## fmi_type(fmu, vr, 1, &cache-> variable [port->cache.offset], port->cache.nb);
    FOR_ALL_NUMERIC_TYPES(CASE_SET)
#undef CASE_SET
    case CACHE_TYPE_strings:
        for (unsigned long k = 0; k < port->cache.nb; k += 1)
            cache->strings_scratch[k] = cache->strings[port->cache.offset + k].data;
        return fmuSetString(fmu, vr, 1, cache->strings_scratch, port->cache.nb);
    case CACHE_TYPE_binaries:
        for (unsigned long k = 0; k < port->cache.nb; k += 1) {
            cache->sizes_scratch[k] = cache->binaries[port->cache.offset + k].size;
            cache->binaries_scratch[k] = cache->binaries[port->cache.offset + k].data;
        }
        return fmuSetBinary(fmu, vr, 1, cache->sizes_scratch, cache->binaries_scratch, port->cache.nb);
    }
    return FMU_STATUS_ERROR;
}


fmu_status_t cache_sync_fmu(container_t *container, unsigned long fmu_id, bool continuous_only) {
    const logger_t *logger = &container->logger;
    cache_set_t *set = &container->cache->sets[fmu_id];
    unsigned long kept = 0;

    for (unsigned long i = 0; i < set->nb; i += 1) {
        cache_set_entry_t *entry = &set->entries[i];
        const cache_sync_action_t action = cache_sync_action(container, entry, continuous_only);

        if (action == CACHE_SYNC_KEEP) {
            set->entries[kept++] = *entry;
            continue;
        }
        entry->link->cache.in_set = false;
        if (action == CACHE_SYNC_SET && cache_sync_entry(container, entry) != FMU_STATUS_OK) {
            LOGGER_ERROR("Container: FMU '%s' refused the value set on the container for vr=%u.",
                         container->fmu[fmu_id].name, entry->link->fmu_vr);
            /* the entries not processed yet stay in the set */
            for (unsigned long j = i + 1; j < set->nb; j += 1)
                set->entries[kept++] = set->entries[j];
            set->nb = kept;
            return FMU_STATUS_ERROR;
        }
    }
    set->nb = kept;

    return FMU_STATUS_OK;
}


fmu_status_t cache_sync_fmu_now(container_t *container, unsigned long fmu_id, bool continuous_only) {
    if (container->step_pending)
        return FMU_STATUS_OK;
    return cache_sync_fmu(container, fmu_id, continuous_only);
}


fmu_status_t cache_sync_fmus(container_t *container) {
    for (int i = 0; i < container->nb_fmu; i += 1) {
        if (cache_sync_fmu(container, (unsigned long)i, false) != FMU_STATUS_OK)
            return FMU_STATUS_ERROR;
    }
    return FMU_STATUS_OK;
}


fmu_status_t cache_end_pending_step(container_t *container) {
    const logger_t *logger = &container->logger;
    cache_t *cache = container->cache;

    for (unsigned long i = 0; i < cache->deferred.nb; i += 1) {
        const cache_set_entry_t *entry = &cache->deferred.entries[i];
        container_port_t *port = entry->port;
        port->cache.deferred = false;

        for (unsigned long j = 0; j < port->nb; j += 1) {
            const container_vr_t *link = &port->links[j];
            if ((long)link->fmu_id >= 0)
                continue;
            switch (entry->type) {
#define CASE_WRITE(variable, fmi_type, c_type)                                                                  \
            case CACHE_TYPE_ ## variable:                                                                       \
                for (unsigned long k = 0; k < port->cache.nb; k += 1)                                           \
                    container-> variable [link->fmu_vr + k] = cache-> variable [port->cache.offset + k];        \
                break;
            FOR_ALL_NUMERIC_TYPES(CASE_WRITE)
#undef CASE_WRITE
            case CACHE_TYPE_strings:
                for (unsigned long k = 0; k < port->cache.nb; k += 1) {
                    if (fmu_string_copy(&container->strings[link->fmu_vr + k],
                                        cache->strings[port->cache.offset + k].data)) {
                        LOGGER_ERROR("Cannot allocate memory to set a deferred string.");
                        return FMU_STATUS_ERROR;
                    }
                }
                break;
            case CACHE_TYPE_binaries:
                for (unsigned long k = 0; k < port->cache.nb; k += 1) {
                    const fmu_binary_t *cached = &cache->binaries[port->cache.offset + k];
                    if (fmu_binary_copy(&container->binaries[link->fmu_vr + k], cached->data, cached->size)) {
                        LOGGER_ERROR("Cannot allocate memory to set a deferred binary.");
                        return FMU_STATUS_ERROR;
                    }
                }
                break;
            }
        }
    }
    cache->deferred.nb = 0;

    return FMU_STATUS_OK;
}
