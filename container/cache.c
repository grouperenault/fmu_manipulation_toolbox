#include <inttypes.h>
#include <stdlib.h>
#include <string.h>

#include "cache.h"
#include "container.h"
#include "logger.h"


/*----------------------------------------------------------------------------
                    A L L O C A T I O N   A N D   R E S E T
----------------------------------------------------------------------------*/

/* In cache_new(): allocates nb_elem zeroed elements in ptr, nothing when nb_elem is 0. On a failure, logs, frees the
   cache being built and returns NULL from cache_new(). */
#define CACHE_ALLOC(ptr, nb_elem)                                             \
    if ((nb_elem) > 0) {                                                      \
        ptr = calloc((nb_elem), sizeof(*ptr));                                \
        if (!ptr) {                                                           \
            LOGGER_ERROR("Cannot allocate memory for the cache (" #ptr ")."); \
            cache_free(cache);                                                \
            return NULL;                                                      \
        }                                                                     \
    }


/* Creates the cache of a container, once its ports and the start values of its embedded FMUs are read: a place for
   each value of each linked port (port->cache.offset, CACHE_NONE without link), the <RESET> of the start value of each
   link (link->cache.start_reset), the sets of the FMUs (per category and type) and of the deferred ports (per type),
   allocated for all the entries they may hold, and the scratch arrays of the strings and binaries. Returns NULL on an allocation failure (logged). */
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
#define SETUP_VALUES(variable, fmi_type, c_type, reset_of_link)                       \
    for (unsigned long i = 0; i < container-> variable .nb_ports; i += 1) {           \
        container_port_t *port = &container-> variable .ports [i];                    \
        port->cache.nb = 0;                                                           \
        port->cache.deferred = false;                                                 \
        port->cache.offset = CACHE_NONE;                                              \
        if (port->nb > 0) {                                                           \
            port->cache.offset = cache->nb_ ## variable;                              \
            cache->nb_ ## variable += port->dimension;                                \
        }                                                                             \
        port->cache.has_local = false;                                                \
        for (unsigned long j = 0; j < port->nb; j += 1) {                             \
            container_vr_t *link = &port->links[j];                                   \
            link->cache.in_set = false;                                               \
            link->cache.start_reset = (long)link->fmu_id >= 0 ? (reset_of_link) : -1; \
            port->cache.has_local |= (long)link->fmu_id < 0;                          \
        }                                                                             \
    }                                                                                 \
    CACHE_ALLOC(cache->variable, cache->nb_ ## variable)

#define SETUP_NUMERIC(variable, fmi_type, c_type)                            \
    SETUP_VALUES(variable, fmi_type, c_type,                                 \
                 fmu_start_reset_ ## variable(&container->fmu[link->fmu_id], \
                 link->fmu_vr))

    FOR_ALL_NUMERIC_TYPES(SETUP_NUMERIC)
    SETUP_VALUES(strings, String, fmu_string_t,
                 fmu_start_reset_strings(&container->fmu[link->fmu_id],
                 link->fmu_vr))
    SETUP_VALUES(binaries, Binary, fmu_binary_t,
                 -1)
#undef SETUP_NUMERIC
#undef SETUP_VALUES

    /* Sets: one entry per link to an embedded FMU in the set of this FMU for its category and its type, one entry per
       port linked to a local variable in the set of the deferred ports of its type. Never reallocated. */
    unsigned long nb_entries = 0;
    cache->nb_fmus = (unsigned long)container->nb_fmu;
    CACHE_ALLOC(cache->fmus, cache->nb_fmus)
#define COUNT_LINKS(variable, fmi_type, c_type)                                                          \
    for (unsigned long i = 0; i < container-> variable .nb_ports; i += 1) {                              \
        const container_port_t *port = &container-> variable .ports [i];                                 \
        for (unsigned long j = 0; j < port->nb; j += 1) {                                                \
            const container_vr_t *link = &port->links[j];                                                \
            if ((long)link->fmu_id >= 0) {                                                               \
                cache->fmus[link->fmu_id].sets[link->cache.start_reset == 2][CACHE_TYPE_ ## variable].size += 1; \
                nb_entries += 1;                                                                         \
            }                                                                                            \
        }                                                                                                \
        if (port->cache.has_local) {                                                                     \
            cache->deferred[CACHE_TYPE_ ## variable].size += 1;                                          \
            nb_entries += 1;                                                                             \
        }                                                                                                \
    }

    FOR_ALL_NUMERIC_TYPES(COUNT_LINKS)
    COUNT_LINKS(strings, String, char *)
    COUNT_LINKS(binaries, Binary, fmu_binary_t)
#undef COUNT_LINKS

    CACHE_ALLOC(cache->set_entries, nb_entries)
    unsigned long offset = 0;
    for (unsigned long i = 0; i < cache->nb_fmus; i += 1) {
        for (int structural = 0; structural < 2; structural += 1) {
            for (int t = 0; t < CACHE_NB_TYPES; t += 1) {
                cache->fmus[i].sets[structural][t].entries = cache->set_entries + offset;
                offset += cache->fmus[i].sets[structural][t].size;
            }
        }
    }
    for (int t = 0; t < CACHE_NB_TYPES; t += 1) {
        cache->deferred[t].entries = cache->set_entries + offset;
        offset += cache->deferred[t].size;
    }

    for (unsigned long i = 0; i < container->strings.nb_ports; i += 1) {
        if (container->strings.ports[i].dimension > max_strings)
            max_strings = container->strings.ports[i].dimension;
    }
    for (unsigned long i = 0; i < container->binaries.nb_ports; i += 1) {
        if (container->binaries.ports[i].dimension > max_binaries)
            max_binaries = container->binaries.ports[i].dimension;
    }
    CACHE_ALLOC(cache->strings_scratch, max_strings)
    CACHE_ALLOC(cache->sizes_scratch, max_binaries)
    CACHE_ALLOC(cache->binaries_scratch, max_binaries)

    return cache;
}
#undef CACHE_ALLOC


/* Frees a cache and all it holds (values, strings and binaries, sets, scratch arrays). NULL is accepted. */
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

    free(cache->fmus);
    free(cache->set_entries);
    free(cache->strings_scratch);
    free(cache->sizes_scratch);
    free(cache->binaries_scratch);
    free(cache);
}


/* Reset of the container: no port has a value set by the importer anymore, no link and no port is in a set. The
   strings and binaries of the cache keep their capacity. */
void cache_reset(container_t *container) {
    cache_t *cache = container->cache;

#define RESET_PORTS(variable, fmi_type, c_type)                             \
    for (unsigned long i = 0; i < container-> variable .nb_ports; i += 1) { \
        container_port_t *port = &container-> variable .ports [i];          \
        port->cache.nb = 0;                                                 \
        port->cache.deferred = false;                                       \
        for (unsigned long j = 0; j < port->nb; j += 1)                     \
            port->links[j].cache.in_set = false;                            \
    }

    FOR_ALL_NUMERIC_TYPES(RESET_PORTS)
    RESET_PORTS(strings, String, char *)
    RESET_PORTS(binaries, Binary, fmu_binary_t)
#undef RESET_PORTS

    for (unsigned long i = 0; i < cache->nb_fmus; i += 1) {
        for (int structural = 0; structural < 2; structural += 1) {
            cache->fmus[i].types[structural] = 0;
            for (int t = 0; t < CACHE_NB_TYPES; t += 1)
                cache->fmus[i].sets[structural][t].nb = 0;
        }
    }
    for (int t = 0; t < CACHE_NB_TYPES; t += 1)
        cache->deferred[t].nb = 0;
    cache->deferred_types = 0;
}


/*----------------------------------------------------------------------------
                    V A L U E S   S E T   B Y   T H E   I M P O R T E R
----------------------------------------------------------------------------*/

/* Appends an entry to a set. link is NULL in the sets of the deferred ports. */
static void cache_set_add(cache_set_t *set, container_port_t *port, container_vr_t *link) {
    /* The set holds at most one entry per link (or per port): allocated for all of them */
    set->entries[set->nb].port = port;
    set->entries[set->nb].link = link;
    set->nb += 1;
}


/* Adds a link to the set of its FMU for its category (variable or structural parameter) and its type, unless it is
   already in it: its value is set at the next synchronization of the FMU. */
static void cache_mark_link(cache_t *cache, cache_type_t type, container_port_t *port, container_vr_t *link) {
    if (!link->cache.in_set) {
        cache_fmu_t *fmu_cache = &cache->fmus[link->fmu_id];
        const int structural = link->cache.start_reset == 2;

        link->cache.in_set = true;
        cache_set_add(&fmu_cache->sets[structural][type], port, link);
        fmu_cache->types[structural] |= 1u << type;
    }
}


/* Once the values of a port are stored: its links to embedded FMUs join the sets of their FMU. Returns 1 when the
   caller writes now its local variables; while a step is pending, a port linked to local variables joins the set of
   the deferred ports instead. */
static int cache_port_set(container_t *container, cache_type_t type, container_port_t *port) {
    for (unsigned long j = 0; j < port->nb; j += 1) {
        if ((long)port->links[j].fmu_id >= 0)
            cache_mark_link(container->cache, type, port, &port->links[j]);
    }
    if (!port->cache.has_local)
        return 0;
    if (container->step_pending) {
        if (!port->cache.deferred) {
            port->cache.deferred = true;
            cache_set_add(&container->cache->deferred[type], port, NULL);
            container->cache->deferred_types |= 1u << type;
        }
        return 0;
    }
    return 1;
}


/* cache_set_<type>(): fmi*Set of a numeric port. Copies its values in the cache (at most its dimension), records how
   many were set and adds its links to the sets (cache_port_set). A port without link (CACHE_NONE) is ignored. */
#define CACHE_STORE(type, c_type, format, cast)                                                   \
int cache_set_ ## type(container_t *container, container_port_t *port, const c_type value[],      \
                       size_t nvalues) {                                                          \
    const logger_t *logger = &container->logger;                                                  \
    if (port->cache.offset == CACHE_NONE)                                                         \
        return 0;                                                                                 \
    if (nvalues > port->dimension)                                                                \
        nvalues = port->dimension;                                                                \
    for (size_t k = 0; k < nvalues; k += 1)                                                       \
        container->cache-> type [port->cache.offset + k] = value[k];                              \
    port->cache.nb = (unsigned long)nvalues;   /* at most the dimension of the port */            \
    LOGGER_DEBUG("[DEBUG] Cache " #type " [%lu] = " format " (%zu value(s))", port->cache.offset, \
                 (cast)value[0], nvalues);                                                        \
    return cache_port_set(container, CACHE_TYPE_ ## type, port);                                  \
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


/* fmi*Set of a string port: copies its values in the cache, without allocation when they fit the capacity of their
   places, and adds its links to the sets. A port without link is ignored. -1 on an allocation failure (logged; the
   port has no value set anymore). */
int cache_set_strings(container_t *container, container_port_t *port, const char * const value[],
                      size_t nvalues) {
    const logger_t *logger = &container->logger;
    if (port->cache.offset == CACHE_NONE)
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
    return cache_port_set(container, CACHE_TYPE_strings, port);
}


/* fmi*Set of a binary port: copies its values (size[k] bytes from value[k]) in the cache, without allocation when they
   fit the capacity of their places, and adds its links to the sets. A port without link is ignored. -1 on an
   allocation failure (logged; the port has no value set anymore). */
int cache_set_binaries(container_t *container, container_port_t *port, const size_t size[],
                       const uint8_t * const value[], size_t nvalues) {
    const logger_t *logger = &container->logger;
    if (port->cache.offset == CACHE_NONE)
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
    return cache_port_set(container, CACHE_TYPE_binaries, port);
}


/* Whether the importer set all the values of the port (dimension values in the cache). */
static bool cache_has_values(const container_port_t *port) {
    return port->cache.offset != CACHE_NONE && port->cache.nb == port->dimension;
}


/* cache_read_<type>(): fmi*Get of a numeric port. When the importer set it, copies its values from the cache in
   value[] (dimension values) and returns true; otherwise returns false and the caller reads the FMU. */
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


/* fmi*Get of a string port set by the importer: value[] points to the strings of the cache (valid until the next
   fmi*Set of the port). False when the importer did not set it. */
bool cache_read_strings(const container_t *container, const container_port_t *port, const char *value[]) {
    if (!cache_has_values(port))
        return false;
    for (unsigned long k = 0; k < port->dimension; k += 1)
        value[k] = container->cache->strings[port->cache.offset + k].data;
    return true;
}


/* fmi*Get of a binary port set by the importer: size[] and value[] give the binaries of the cache (valid until the
   next fmi*Set of the port). False when the importer did not set it. */
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

/* Adds again to the set of an FMU the links that have a value set by the importer, so that these values prevail over
   the start values just set: all of them (reset < 0), or those of the variables whose start value has this <RESET>
   (1: set again in Initialization Mode). The structural parameters of an FMU configured and out of Configuration Mode
   are not added: they got their values at its configuration. Goes through all the ports: once per initialization,
   configuration or reset. */
void cache_mark_fmu(container_t *container, unsigned long fmu_id, int reset) {
    const fmu_t *fmu = &container->fmu[fmu_id];
    const bool structural_done = fmu->configured && !fmu->in_configuration_mode;
#define MARK_FMU(variable, fmi_type, c_type)                                                                    \
    for (unsigned long i = 0; i < container-> variable .nb_ports; i += 1) {                                     \
        container_port_t *port = &container-> variable .ports [i];                                              \
        for (unsigned long j = 0; j < port->nb && port->cache.nb > 0; j += 1) {                                 \
            container_vr_t *link = &port->links[j];                                                             \
            if (link->fmu_id != fmu_id || (reset >= 0 && link->cache.start_reset != reset))                     \
                continue;                                                                                       \
            if (!(structural_done && link->cache.start_reset == 2))                                             \
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

/* Types set in Continuous Time Mode */
#define CACHE_CONTINUOUS_TYPES      ((1u << CACHE_TYPE_reals64) | (1u << CACHE_TYPE_reals32))


/* Sets on an FMU the cached values of the entries of one of its sets, one call per link, and empties it. An entry
   whose port has no value anymore (allocation failure of a string or binary) is dropped. On a value refused by the
   FMU, logs it, keeps the entries not processed yet and returns FMU_STATUS_ERROR. */
static fmu_status_t cache_sync_set(container_t *container, const fmu_t *fmu, cache_type_t type, cache_set_t *set) {
    const logger_t *logger = &container->logger;
    cache_t *cache = container->cache;
    fmu_status_t status = FMU_STATUS_OK;
    unsigned long i = 0;

    switch (type) {
#define CASE_SET(variable, fmi_type, c_type)                                                                    \
    case CACHE_TYPE_ ## variable:                                                                               \
        while (i < set->nb && status == FMU_STATUS_OK) {                                                        \
            const cache_set_entry_t *entry = &set->entries[i++];                                                \
            entry->link->cache.in_set = false;                                                                  \
            if (entry->port->cache.nb == 0)                                                                     \
                continue;                                                                                       \
            status = fmuSet ## fmi_type(fmu, &entry->link->fmu_vr, 1,                                           \
                                        &cache-> variable [entry->port->cache.offset], entry->port->cache.nb);  \
        }                                                                                                       \
        break;
    FOR_ALL_NUMERIC_TYPES(CASE_SET)
#undef CASE_SET
    case CACHE_TYPE_strings:
        while (i < set->nb && status == FMU_STATUS_OK) {
            const cache_set_entry_t *entry = &set->entries[i++];
            const container_port_t *port = entry->port;
            entry->link->cache.in_set = false;
            if (port->cache.nb == 0)
                continue;
            for (unsigned long k = 0; k < port->cache.nb; k += 1)
                cache->strings_scratch[k] = cache->strings[port->cache.offset + k].data;
            status = fmuSetString(fmu, &entry->link->fmu_vr, 1, cache->strings_scratch, port->cache.nb);
        }
        break;
    case CACHE_TYPE_binaries:
        while (i < set->nb && status == FMU_STATUS_OK) {
            const cache_set_entry_t *entry = &set->entries[i++];
            const container_port_t *port = entry->port;
            entry->link->cache.in_set = false;
            if (port->cache.nb == 0)
                continue;
            for (unsigned long k = 0; k < port->cache.nb; k += 1) {
                cache->sizes_scratch[k] = cache->binaries[port->cache.offset + k].size;
                cache->binaries_scratch[k] = cache->binaries[port->cache.offset + k].data;
            }
            status = fmuSetBinary(fmu, &entry->link->fmu_vr, 1, cache->sizes_scratch, cache->binaries_scratch,
                                  port->cache.nb);
        }
        break;
    }

    if (status != FMU_STATUS_OK) {
        LOGGER_ERROR("Container: FMU '%s' refused the value set on the container for vr=%u.",
                     fmu->name, set->entries[i - 1].link->fmu_vr);
        /* the entries not processed yet stay in the set */
        memmove(set->entries, set->entries + i, (set->nb - i) * sizeof(*set->entries));
        set->nb -= i;
        return FMU_STATUS_ERROR;
    }
    set->nb = 0;

    return FMU_STATUS_OK;
}


/* Synchronization of an FMU: sets on it the cached values of its sets, type by type. A structural parameter is set in
   Configuration Mode only, the other variables out of it; in Continuous Time Mode, the real variables only (the other
   sets wait). A structural parameter set after the configuration of its FMU waits for its next configuration (reset),
   where the cache is marked again: it leaves its set. On a value refused by the FMU, returns FMU_STATUS_ERROR (the
   entries not processed yet stay in their sets). */
fmu_status_t cache_sync_fmu(container_t *container, unsigned long fmu_id, bool continuous_only) {
    const logger_t *logger = &container->logger;
    const fmu_t *fmu = &container->fmu[fmu_id];
    cache_fmu_t *fmu_cache = &container->cache->fmus[fmu_id];
    if (!(fmu_cache->types[0] | fmu_cache->types[1]))
        return FMU_STATUS_OK;   /* nothing to set: the common case at each step */
    const int structural = fmu->in_configuration_mode ? 1 : 0;

    if (!structural && fmu->configured && fmu_cache->types[1]) {
        for (int t = 0; t < CACHE_NB_TYPES; t += 1) {
            cache_set_t *set = &fmu_cache->sets[1][t];
            for (unsigned long i = 0; i < set->nb; i += 1) {
                LOGGER_WARNING("Container: FMU '%s' is configured: the structural parameter vr=%u set on the container "
                               "is set at its next configuration.", fmu->name, set->entries[i].link->fmu_vr);
                set->entries[i].link->cache.in_set = false;
            }
            set->nb = 0;
        }
        fmu_cache->types[1] = 0;
    }

    unsigned int types = fmu_cache->types[structural] & (continuous_only ? CACHE_CONTINUOUS_TYPES : ~0u);
    for (int t = 0; types; t += 1, types >>= 1) {
        if (types & 1u) {
            const fmu_status_t status = cache_sync_set(container, fmu, (cache_type_t)t,
                                                       &fmu_cache->sets[structural][t]);
            if (fmu_cache->sets[structural][t].nb == 0)
                fmu_cache->types[structural] &= ~(1u << t);
            if (status != FMU_STATUS_OK)
                return FMU_STATUS_ERROR;
        }
    }

    return FMU_STATUS_OK;
}


/* cache_sync_fmu() from a step or a read of the FMU (fmu_set_inputs, getters): nothing while a step is pending, the
   values set meanwhile being for the steps after it. */
fmu_status_t cache_sync_fmu_now(container_t *container, unsigned long fmu_id, bool continuous_only) {
    if (container->step_pending)
        return FMU_STATUS_OK;
    return cache_sync_fmu(container, fmu_id, continuous_only);
}


/* Synchronization of every FMU, when a step becomes pending: the pending step uses the values set until then. */
fmu_status_t cache_sync_fmus(container_t *container) {
    for (int i = 0; i < container->nb_fmu; i += 1) {
        if (cache_sync_fmu(container, (unsigned long)i, false) != FMU_STATUS_OK)
            return FMU_STATUS_ERROR;
    }
    return FMU_STATUS_OK;
}


/* Writes from the cache the local variable of a link of a port set by the importer. Returns non-zero on an allocation
   failure (logged). */
static int cache_write_local(container_t *container, cache_type_t type, const container_port_t *port,
                             const container_vr_t *link) {
    const logger_t *logger = &container->logger;
    const cache_t *cache = container->cache;

    switch (type) {
#define CASE_WRITE(variable, fmi_type, c_type)                                                                  \
    case CACHE_TYPE_ ## variable:                                                                               \
        for (unsigned long k = 0; k < port->cache.nb; k += 1)                                                   \
            container-> variable .locals [link->fmu_vr + k] = cache-> variable [port->cache.offset + k];        \
        break;
    FOR_ALL_NUMERIC_TYPES(CASE_WRITE)
#undef CASE_WRITE
    case CACHE_TYPE_strings:
        for (unsigned long k = 0; k < port->cache.nb; k += 1) {
            if (fmu_string_copy(&container->strings.locals[link->fmu_vr + k],
                                cache->strings[port->cache.offset + k].data)) {
                LOGGER_ERROR("Cannot allocate memory to set a deferred string.");
                return -1;
            }
        }
        break;
    case CACHE_TYPE_binaries:
        for (unsigned long k = 0; k < port->cache.nb; k += 1) {
            const fmu_binary_t *cached = &cache->binaries[port->cache.offset + k];
            if (fmu_binary_copy(&container->binaries.locals[link->fmu_vr + k], cached->data, cached->size)) {
                LOGGER_ERROR("Cannot allocate memory to set a deferred binary.");
                return -1;
            }
        }
        break;
    }
    return 0;
}


/* End of a pending step: writes the local variables of the ports set by the importer meanwhile (set of the deferred
   ports) from the cache, and empties these sets. The embedded FMUs get the values of their sets at their next
   synchronization. Returns FMU_STATUS_ERROR on an allocation failure (logged): the ports not written yet stay in their
   set, so that a port is never twice in it. */
fmu_status_t cache_end_pending_step(container_t *container) {
    cache_t *cache = container->cache;

    unsigned int types = cache->deferred_types;
    for (int t = 0; types; t += 1, types >>= 1) {
        if (!(types & 1u))
            continue;
        cache_set_t *deferred = &cache->deferred[t];
        for (unsigned long i = 0; i < deferred->nb; i += 1) {
            container_port_t *port = deferred->entries[i].port;

            for (unsigned long j = 0; j < port->nb; j += 1) {
                const container_vr_t *link = &port->links[j];
                if ((long)link->fmu_id < 0 && cache_write_local(container, (cache_type_t)t, port, link)) {
                    memmove(deferred->entries, deferred->entries + i, (deferred->nb - i) * sizeof(*deferred->entries));
                    deferred->nb -= i;
                    return FMU_STATUS_ERROR;
                }
            }
            port->cache.deferred = false;
        }
        deferred->nb = 0;
        cache->deferred_types &= ~(1u << t);
    }

    return FMU_STATUS_OK;
}
