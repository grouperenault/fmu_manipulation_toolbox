#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cache.h"
#include "container.h"
#include "datalog.h"
#include "logger.h"
#include "fmu.h"
#include "solver.h"

// #define DEBUG


/*
 * Implementation of the fmu2Component/fmu3Instance depending on FMUContainer
 * configuration.
 */


/* Safety net against a non-converging event iteration. */
#define CONTAINER_MAX_EVENT_ITER    100

static inline bool container_is_close(const container_t *container, double r1, double r2) {
    return fabs(r1-r2) < container->tolerance;
}


/*----------------------------------------------------------------------------
                              C L O C K S
----------------------------------------------------------------------------*/

static inline bool container_clock_is_periodic(const container_clock_t *clock) {
    return clock->kind == CONTAINER_CLOCK_CONSTANT || clock->kind == CONTAINER_CLOCK_FIXED ||
           clock->kind == CONTAINER_CLOCK_TUNABLE;
}


static void container_clock_set_period(container_clock_t *clock, double origin, double period, unsigned long nb_ticks) {
    clock->origin = origin;
    clock->period = period;
    clock->nb_ticks = nb_ticks;
    clock->next_tick = origin + period * (double)nb_ticks;  /* Not a sum of periods: no drift of the ticks. */
    clock->next_known = true;
}


static fmu_status_t container_clock_get_interval(const container_t *container, const container_clock_t *clock,
                                                 double *interval, int *qualifier) {
    const logger_t *logger = &container->logger;
    const fmu_t *fmu = &container->fmu[clock->fmu_id];

    /* An FMU that writes neither of them announces nothing, and a new interval without its value is refused. */
    *interval = -1.0;
    *qualifier = fmi3IntervalNotYetKnown;
    if (fmuGetIntervalDecimal(fmu, &clock->fmu_vr, 1, interval, qualifier) != FMU_STATUS_OK) {
        LOGGER_ERROR("FMU '%s' Cannot get the interval of clock vr=%u", fmu->name, clock->fmu_vr);
        return FMU_STATUS_ERROR;
    }

    if ((*qualifier == fmi3IntervalChanged) && (*interval < 0.0)) {
        LOGGER_ERROR("FMU '%s': clock vr=%u has an invalid interval %e", fmu->name, clock->fmu_vr, *interval);
        return FMU_STATUS_ERROR;
    }

    return FMU_STATUS_OK;
}


/* Schedule known at the end of the Initialization Mode (FMI-3.0 2.2.8): the interval and the shift declared by the
   modelDescription.xml are used as they are, the others are read from the FMU. */
static fmu_status_t container_clocks_init_schedule(container_t *container) {
    const logger_t *logger = &container->logger;

    for (unsigned long i = 0; i < container->clocks_list.nb_local_clocks; i += 1) {
        container_clock_t *clock = &container->clocks_list.clocks[i];
        const fmu_t *fmu = &container->fmu[clock->fmu_id];
        double interval = clock->declared_interval;
        int qualifier;

        clock->ticked = false;
        clock->tick_to_log = false;
        clock->has_ticked = false;
        clock->next_known = false;

        if (container_clock_is_periodic(clock)) {
            double shift = clock->declared_shift;

            if (interval < 0.0) {
                if (container_clock_get_interval(container, clock, &interval, &qualifier) != FMU_STATUS_OK)
                    return FMU_STATUS_ERROR;
                if ((shift < 0.0) && (fmuGetShiftDecimal(fmu, &clock->fmu_vr, 1, &shift) != FMU_STATUS_OK))
                    return FMU_STATUS_ERROR;
            }
            if (interval < container->tolerance) {
                LOGGER_ERROR("FMU '%s': periodic clock vr=%u has an invalid interval %e", fmu->name, clock->fmu_vr,
                             interval);
                return FMU_STATUS_ERROR;
            }
            container_clock_set_period(clock, container->time + ((shift < 0.0) ? 0.0 : shift), interval, 0);
        } else {
            if (container_clock_get_interval(container, clock, &interval, &qualifier) != FMU_STATUS_OK)
                return FMU_STATUS_ERROR;
            if ((qualifier == fmi3IntervalChanged) || ((qualifier == fmi3IntervalUnchanged) && (interval >= 0.0))) {
                clock->next_tick = container->time + interval;
                clock->next_known = true;
            }
        }
    }

    return FMU_STATUS_OK;
}


/* In Event Mode, read what the FMUs may have changed in the schedule. A new interval is relative to the current
   time (FMI-3.0 2.2.8), fmi3IntervalUnchanged keeps the known tick. fmi3IntervalNotYetKnown only happens when no tick
   is known: if an FMU answers it about a tick it has announced, this tick is kept. */
static fmu_status_t container_clocks_read_schedule(container_t *container) {
    const logger_t *logger = &container->logger;

    for (unsigned long i = 0; i < container->clocks_list.nb_local_clocks; i += 1) {
        container_clock_t *clock = &container->clocks_list.clocks[i];
        const bool ticked = clock->ticked;
        const bool tunable = (clock->kind == CONTAINER_CLOCK_TUNABLE) && (clock->declared_interval < 0.0);
        double interval;
        int qualifier;

        clock->ticked = false;

        /* FMI-3.0: fmi3GetInterval of a changing clock is only allowed if it ticked. */
        if (!tunable && (clock->kind != CONTAINER_CLOCK_COUNTDOWN) &&
            !((clock->kind == CONTAINER_CLOCK_CHANGING) && ticked))
            continue;

        if (container_clock_get_interval(container, clock, &interval, &qualifier) != FMU_STATUS_OK)
            return FMU_STATUS_ERROR;

        if (qualifier == fmi3IntervalChanged) {
            if (tunable) {
                if (interval < container->tolerance) {
                    LOGGER_ERROR("FMU '%s': tunable clock vr=%u has an invalid interval %e",
                                 container->fmu[clock->fmu_id].name, clock->fmu_vr, interval);
                    return FMU_STATUS_ERROR;
                }
                container_clock_set_period(clock, container->time, interval, 1);
            } else {
                clock->next_tick = container->time + interval;
                clock->next_known = true;
            }
        } else if ((qualifier == fmi3IntervalUnchanged) && !tunable && !clock->next_known) {
            LOGGER_ERROR("Clock '%s' vr=%u has no previous interval and fmi3IntervalUnchanged was set.",
                         container->fmu[clock->fmu_id].name, clock->fmu_vr);
        }
    }

    return FMU_STATUS_OK;
}


static inline bool container_clock_is_due(const container_clock_t *clock, double time) {
    return clock->next_known && (clock->next_tick <= time);
}


/* A clock ticks at most once per time instant: an FMU that announces a new tick right after the current one may wait
   for a step to go on, so that ticking it again in this Event Mode would never end. */
static inline bool container_clock_has_ticked_now(const container_t *container, const container_clock_t *clock) {
    return clock->has_ticked && container_is_close(container, clock->last_tick, container->time);
}


static fmu_status_t container_set_next_event_time(container_t *container) {
    if (container_clocks_read_schedule(container) != FMU_STATUS_OK)
        return FMU_STATUS_ERROR;

    for (unsigned long i = 0; i < container->clocks_list.nb_local_clocks; i += 1) {
        const container_clock_t *clock = &container->clocks_list.clocks[i];

        if (container_clock_has_ticked_now(container, clock) && container_clock_is_due(clock, container->time)) {
            /* The smallest step that is not within the tolerance of the current time. */
            if (2.0 * container->tolerance < container->next_step)
                container->next_step = 2.0 * container->tolerance;
        } else if (clock->next_known && !container_clock_is_due(clock, container->time)) {
            const double interval = clock->next_tick - container->time;

            if (interval + container->tolerance < container->next_step)
                container->next_step = interval;
        }
    }

#ifdef DEBUG
    const logger_t *logger = &container->logger;
    LOGGER_DEBUG("[DEBUG] time=%e | next step=%e", container->time, container->next_step);
#endif

    return FMU_STATUS_OK;
}


/* The scheduled clocks are reset as soon as their inputs are delivered: for the datalog, show the ones that ticked
   since its last row. */
void container_clocks_activate_ticked(container_t *container) {
    for(unsigned long i = 0; i < container->clocks_list.nb_local_clocks; i += 1) {
        if (container->clocks_list.clocks[i].tick_to_log)
            container->clocks.locals[container->clocks_list.clocks[i].local_vr] = true;
    }
}


static void container_clocks_deactivate(container_t *container) {
    /* Reset all (local) clocks */
    for(unsigned long i = 0; i < container->clocks_list.nb_local_clocks; i += 1) {
        container->clocks.locals[container->clocks_list.clocks[i].local_vr] = false;
    }

    return;
}


/* Every local clock inactive: the clocks read during an event iteration are delivered. */
static void container_clocks_clear(container_t *container) {
    for (unsigned long i = 0; i < container->clocks.nb_locals; i += 1)
        container->clocks.locals[i] = false;
}


static bool container_clocks_are_active(const container_t *container) {
    for (unsigned long i = 0; i < container->clocks.nb_locals; i += 1) {
        if (container->clocks.locals[i])
            return true;
    }
    return false;
}


void container_clocks_logged(container_t *container) {
    container_clocks_deactivate(container);
    for(unsigned long i = 0; i < container->clocks_list.nb_local_clocks; i += 1)
        container->clocks_list.clocks[i].tick_to_log = false;
}


static bool container_clocks_are_due(const container_t *container) {
    for (unsigned long i = 0; i < container->clocks_list.nb_local_clocks; i += 1) {
        const container_clock_t *clock = &container->clocks_list.clocks[i];

        if (container_clock_is_due(clock, container->time) && !container_clock_has_ticked_now(container, clock))
            return true;
    }

    return false;
}


/*----------------------------------------------------------------------------
                        E V E N T   M O D E
----------------------------------------------------------------------------*/

fmu_status_t container_enter_event_mode(container_t *container) {
#ifdef DEBUG
    const logger_t *logger = &container->logger;
    LOGGER_DEBUG("[DEBUG] time=%e| Container entering in EVENT mode", container->time);
#endif
    for (int i = 0; i < container->nb_fmu; i += 1) {
        if (fmuEnterEventMode(&container->fmu[i]) != FMU_STATUS_OK)
                return FMU_STATUS_ERROR;
    }
    return FMU_STATUS_OK;
}


fmu_status_t container_enter_step_mode(container_t *container) {
#ifdef DEBUG
    const logger_t *logger = &container->logger;
    LOGGER_DEBUG("[DEBUG] time=%e: Container entering in STEP mode", container->time);
#endif
    for (unsigned int i = 0; i < container->nb_cs; i += 1) {
        if (fmuEnterStepMode(container->cs_fmu[i]) != FMU_STATUS_OK)
                return FMU_STATUS_ERROR;
    }
    return FMU_STATUS_OK;
}


/* An FMU may evaluate its discrete states when its outputs are read, and then refuse any input until
   fmi3UpdateDiscreteStates(): outputs and inputs are exchanged in two super-dense time instants. The event iteration
   which follows calls the update again, and tells if another one is needed. */
static fmu_status_t container_close_instant(container_t *container) {
    for (unsigned int i = 0; i < container->nb_cs; i += 1) {
        bool more_event;

        if (fmuUpdateDiscreteStates(container->cs_fmu[i], &more_event) != FMU_STATUS_OK)
            return FMU_STATUS_ERROR;
    }
    return FMU_STATUS_OK;
}


/* The event iteration reads the output clocks again: the clocks and the inputs they clock reach all the FMUs before
   it. */
static fmu_status_t container_deliver_clocked_inputs(container_t *container) {
    for (unsigned int i = 0; i < container->nb_cs; i += 1) {
        fmu_t *fmu = container->cs_fmu[i];

        if (fmu_set_clocks_after_outputs(fmu) != FMU_STATUS_OK)
            return FMU_STATUS_ERROR;

        if (fmu_set_clocked_inputs(fmu) != FMU_STATUS_OK)
            return FMU_STATUS_ERROR;
    }
    return FMU_STATUS_OK;
}


static fmu_status_t container_proceed_event(container_t *container, double time) {
    const logger_t *logger = &container->logger;

    /* Activate the clocks due now and notify FMU */
    for (unsigned long i = 0; i < container->clocks_list.nb_local_clocks; i += 1) {
        container_clock_t *clock = &container->clocks_list.clocks[i];
        const bool value = true;

        if (!container_clock_is_due(clock, time) || container_clock_has_ticked_now(container, clock))
            continue;

#ifdef DEBUG
        LOGGER_DEBUG("[DEBUG] time=%e | Activate Clock '%s' vr=%u",
            container->time, container->fmu[clock->fmu_id].name, clock->fmu_vr);
#endif
        container->clocks.locals[clock->local_vr] = true;
        container->clocks_list.active[clock->local_vr] = true;
        clock->ticked = true;
        clock->tick_to_log = true;
        clock->has_ticked = true;
        clock->last_tick = container->time;
        if (container_clock_is_periodic(clock))
            container_clock_set_period(clock, clock->origin, clock->period, clock->nb_ticks + 1);
        else
            clock->next_known = false;

        /* The clock of an input comes with this input, in the second instant. */
        if (fmu_clock_has_inputs(&container->fmu[clock->fmu_id], clock->local_vr))
            continue;

        if (fmuSetClock(&container->fmu[clock->fmu_id], &clock->fmu_vr, 1, &value) != FMU_STATUS_OK) {
            LOGGER_ERROR("FMU '%s': cannot activate clock vr=%u", container->fmu[clock->fmu_id].name, clock->fmu_vr);
            return FMU_STATUS_ERROR;
        }
    }

    /* First instant: the outputs (LS-BUS: input clocks could be shared) */
    for (unsigned int i = 0; i < container->nb_cs; i += 1) {
        fmu_t *fmu = container->cs_fmu[i];

        if (fmu_set_clocks_before_outputs(fmu) != FMU_STATUS_OK)
            return FMU_STATUS_ERROR;

        if (fmu_get_clocked_outputs(fmu) != FMU_STATUS_OK)
            return FMU_STATUS_ERROR;
    }

    if (container_close_instant(container) != FMU_STATUS_OK)
        return FMU_STATUS_ERROR;

    /* Second instant: the inputs, with their clocks. */
    for (unsigned long i = 0; i < container->clocks_list.nb_local_clocks; i += 1) {
        const container_clock_t *clock = &container->clocks_list.clocks[i];
        const bool value = true;

        if (container->clocks_list.active[clock->local_vr] &&
            fmu_clock_has_inputs(&container->fmu[clock->fmu_id], clock->local_vr) &&
            fmuSetClock(&container->fmu[clock->fmu_id], &clock->fmu_vr, 1, &value) != FMU_STATUS_OK) {
            LOGGER_ERROR("FMU '%s': cannot activate clock vr=%u", container->fmu[clock->fmu_id].name, clock->fmu_vr);
            return FMU_STATUS_ERROR;
        }
    }

    if (container_deliver_clocked_inputs(container) != FMU_STATUS_OK)
        return FMU_STATUS_ERROR;

    /* reset internal clocks */
    container_clocks_deactivate(container);
    for (unsigned long i = 0; i < container->clocks_list.nb_local_clocks; i += 1)
        container->clocks_list.active[container->clocks_list.clocks[i].local_vr] = false;

    return FMU_STATUS_OK;
}


/* Step used when no event shortens it. A TS_MULTIPLIER below 1 counts as 1, as in container_do_step(). */
static double container_nominal_step(const container_t *container) {
    const int ts_multiplier = container->integers32.locals[0];
    return container->time_step * (ts_multiplier < 1 ? 1 : ts_multiplier);
}


/* Shorten the step so it lands on the earliest announced time event. */
static void container_bound_next_step(container_t *container) {
    const logger_t *logger = &container->logger;
    for (int i = 0; i < container->nb_fmu; i += 1) {
        const fmu_t *fmu = &container->fmu[i];

        if (! fmu->have_next_event_time)
            continue;

        const double dt = fmu->next_event_time - container->time;

        /* Event at or before the current instant: already handled, and shortening
           to zero would stall the container loop. */
        if (dt < container->tolerance)
            continue;

        if (dt + container->tolerance < container->next_step) {
            container->next_step = dt;
            LOGGER_DEBUG("%s: next event time %g, updating next step to %g.",
                         fmu->name, fmu->next_event_time, container->next_step);
        }
    }
}


/*
 * Event iteration. `delivered`: the clocks and the clocked inputs already reached the FMUs in this instant.
 *
 * The values go from an FMU to the next ones within a pass (Gauss-Seidel sweep in configuration order): each FMU is
 * driven Set inputs -> fmi3UpdateDiscreteStates -> Get outputs (FMI-3.0), so the outputs read back reflect its
 * updated discrete states. The clocks go from a pass to the next one: an output clock that ticks in a pass (e.g. in
 * fmi3UpdateDiscreteStates, in reaction to an input clock) makes another pass, which starts by delivering it, with
 * the inputs it clocks, to all the FMUs, whatever their order. The local clocks are then cleared: none stays active
 * after the iteration.
 */
static fmu_status_t container_update_discrete_state(container_t *container, bool delivered) {
    const logger_t *logger = &container->logger;
    bool more_event;
    int iter;

    container->next_step = container_nominal_step(container);
#ifdef DEBUG
    LOGGER_DEBUG("[DEBUG] time=%e | container_update_discrete_state()", container->time);
#endif
    for (iter = 0; iter < CONTAINER_MAX_EVENT_ITER; iter += 1) {
        more_event = false;

        /* The previous pass read the outputs: this one needs a new instant for its inputs. */
        if ((iter > 0) && (container_close_instant(container) != FMU_STATUS_OK))
            return FMU_STATUS_ERROR;

        /* The clocks read by the previous pass (or before the iteration), with the inputs they clock. */
        if ((iter > 0) || !delivered) {
            for (int i = 0; i < container->nb_fmu; i += 1) {
                if ((fmu_set_clocks(&container->fmu[i]) != FMU_STATUS_OK) ||
                    (fmu_set_clocked_inputs(&container->fmu[i]) != FMU_STATUS_OK))
                    return FMU_STATUS_ERROR;
            }
        }
        container_clocks_clear(container);

        for (int i = 0; i < container->nb_fmu; i += 1) {
            fmu_t *fmu = &container->fmu[i];
            bool fmu_more_event = false;

            if (fmu_set_inputs(fmu) != FMU_STATUS_OK)
                return FMU_STATUS_ERROR;

            /* Closing the super-dense time instant; a further iteration opens a new one. */
            if (fmuUpdateDiscreteStates(fmu, &fmu_more_event) != FMU_STATUS_OK)
                return FMU_STATUS_ERROR;

            more_event |= fmu_more_event;

            if (fmu_get_outputs(fmu) != FMU_STATUS_OK)
                return FMU_STATUS_ERROR;

            if (fmu_get_clocked_outputs(fmu) != FMU_STATUS_OK)
                return FMU_STATUS_ERROR;
        }

        datalog_log(container);

        if (!more_event && !container_clocks_are_active(container))
            break;
    }

    if (iter >= CONTAINER_MAX_EVENT_ITER) {
        LOGGER_ERROR("Container: event iteration did not converge after %d steps.", CONTAINER_MAX_EVENT_ITER);
        return FMU_STATUS_ERROR;
    }

    container_bound_next_step(container);

    return container_set_next_event_time(container);
}


/* A tick may be due at the current time: the first one with no shift, or an interval of zero. It is handled in the
   current Event Mode, since no step could reach it. */
static fmu_status_t container_handle_due_clocks(container_t *container) {
    const logger_t *logger = &container->logger;

    for (int iter = 0; container_clocks_are_due(container); iter += 1) {
        if (iter >= CONTAINER_MAX_EVENT_ITER) {
            LOGGER_ERROR("Container: clocks still tick at time=%e after %d iterations.", container->time,
                         CONTAINER_MAX_EVENT_ITER);
            return FMU_STATUS_ERROR;
        }
        /* The event iteration read the outputs. */
        if (container_close_instant(container) != FMU_STATUS_OK)
            return FMU_STATUS_ERROR;
        if (container_proceed_event(container, container->time) != FMU_STATUS_OK)
            return FMU_STATUS_ERROR;
        if (container_update_discrete_state(container, true) != FMU_STATUS_OK)
            return FMU_STATUS_ERROR;
    }

    return FMU_STATUS_OK;
}


static fmu_status_t container_handle_events(container_t *container) {
    fmu_status_t status;

    /* Event Mode is only required when an FMU reported eventHandlingNeeded or
       when a clock may tick (FMI-3.0 4.2.1). */
    if (!container->need_event_update && (container->clocks_list.nb_local_clocks == 0)) {
        container->next_step = container_nominal_step(container);
        datalog_log(container);
        return FMU_STATUS_OK;
    }

    /* Event loop */
    status = container_enter_event_mode(container);
    if (status != FMU_STATUS_OK)
        return status;

    status = container_proceed_event(container, container->time + container->tolerance);
    if (status != FMU_STATUS_OK)
        return status;
    
    datalog_log(container);
    status = container_update_discrete_state(container, true);
    if (status != FMU_STATUS_OK)
        return status;

    status = container_handle_due_clocks(container);
    if (status != FMU_STATUS_OK)
        return status;

    status = solver_leave_event_mode(container->solver);
    if (status != FMU_STATUS_OK)
        return status;

    status = container_enter_step_mode(container);
    if (status != FMU_STATUS_OK)
        return status;

    return FMU_STATUS_OK;
}


/*----------------------------------------------------------------------------
                           C O N F I G U R A T I O N
----------------------------------------------------------------------------*/

/* When the start values of an embedded FMU are set, according to their <RESET> in container.txt. */
typedef enum {
    START_VALUES_CONFIGURATION,     /* <RESET>=2: structural parameters, in Configuration Mode */
    START_VALUES_EARLY,             /* <RESET>=0 or 1: before the Initialization Mode */
    START_VALUES_INITIALIZATION,    /* <RESET>=1: set again in Initialization Mode */
} start_values_phase_t;


static bool container_start_value_phase(int reset, start_values_phase_t phase) {
    switch (phase) {
    case START_VALUES_CONFIGURATION:
        return reset == 2;
    case START_VALUES_EARLY:
        return reset != 2;
    case START_VALUES_INITIALIZATION:
        return reset == 1;
    }
    return false;
}


/* Start values of one embedded FMU set in the phase `phase`. */
static fmu_status_t container_set_fmu_start_values(const fmu_t *fmu, start_values_phase_t phase) {
    const logger_t *logger = &fmu->container->logger;

#define SET_START(variable, fmi_type, c_type)                                                   \
    for(unsigned long j=0; j<fmu->fmu_io.start_ ## variable .nb; j ++) {                        \
        if (container_start_value_phase(fmu->fmu_io.start_ ## variable.start_values[j].reset, phase) && \
            fmuSet ## fmi_type(fmu,                                                             \
                &fmu->fmu_io.start_ ## variable.start_values[j].vr, 1,                          \
                fmu->fmu_io.start_ ## variable.start_values[j].value,                           \
                fmu->fmu_io.start_ ## variable.start_values[j].dimension) != FMU_STATUS_OK) {   \
            LOGGER_ERROR("Container: FMU '%s' refused the start value of " #variable " vr=%u.", \
                         fmu->name, fmu->fmu_io.start_ ## variable.start_values[j].vr);         \
            return FMU_STATUS_ERROR;                                                            \
        }                                                                                       \
    }

    FOR_ALL_NUMERIC_TYPES(SET_START)
    SET_START(strings, String, const char *)
    /* binaries and clocks don't support start values here */
#undef SET_START
    return FMU_STATUS_OK;
}


static fmu_status_t container_set_start_values(container_t* container, start_values_phase_t phase) {
    const logger_t *logger = &container->logger;
    LOGGER_DEBUG("Re-setting some start values...");
    for (int i = 0; i < container->nb_fmu; i += 1)
        if (container_set_fmu_start_values(&container->fmu[i], phase) != FMU_STATUS_OK)
            return FMU_STATUS_ERROR;
    LOGGER_DEBUG("Start values are set.");
    return FMU_STATUS_OK;
}


/* Configuration Mode of an FMU with structural parameters: its start values of Configuration Mode, then the values
   set on the container for its structural parameters (cache) are set. */
static fmu_status_t container_enter_fmu_configuration(container_t *container, int fmu_id) {
    const logger_t *logger = &container->logger;
    fmu_t *fmu = &container->fmu[fmu_id];

    if (fmuEnterConfigurationMode(fmu) != FMU_STATUS_OK) {
        LOGGER_ERROR("Container: FMU '%s' cannot enter Configuration Mode.", fmu->name);
        return FMU_STATUS_ERROR;
    }
    if (container_set_fmu_start_values(fmu, START_VALUES_CONFIGURATION) != FMU_STATUS_OK)
        return FMU_STATUS_ERROR;
    cache_mark_fmu(container, (unsigned long)fmu_id, -1);
    return cache_sync_fmu(container, (unsigned long)fmu_id, false);
}


static fmu_status_t container_exit_fmu_configuration(container_t *container, int fmu_id) {
    const logger_t *logger = &container->logger;
    fmu_t *fmu = &container->fmu[fmu_id];

    if (cache_sync_fmu(container, (unsigned long)fmu_id, false) != FMU_STATUS_OK)  /* set by the importer meanwhile */
        return FMU_STATUS_ERROR;
    if (fmuExitConfigurationMode(fmu) != FMU_STATUS_OK) {
        LOGGER_ERROR("Container: FMU '%s' cannot exit Configuration Mode.", fmu->name);
        return FMU_STATUS_ERROR;
    }
    return FMU_STATUS_OK;
}


/* Configuration of an FMU with structural parameters that its importer did not configure (fmi3EnterConfigurationMode
   of the container): FMI-2.0 container, or FMI-3.0 importer that does not use the Configuration Mode. */
static fmu_status_t container_configure_fmu(container_t *container, int fmu_id) {
    const fmu_t *fmu = &container->fmu[fmu_id];

    if (!fmu->has_configuration_mode || fmu->configured)
        return FMU_STATUS_OK;
    if (container_enter_fmu_configuration(container, fmu_id) != FMU_STATUS_OK)
        return FMU_STATUS_ERROR;
    return container_exit_fmu_configuration(container, fmu_id);
}


/* fmi3EnterConfigurationMode of the container: the FMUs with structural parameters enter their Configuration Mode,
   with their start values of Configuration Mode. */
fmu_status_t container_enter_configuration_mode(container_t* container) {
    for (int i = 0; i < container->nb_fmu; i += 1) {
        if (container->fmu[i].has_configuration_mode &&
            container_enter_fmu_configuration(container, i) != FMU_STATUS_OK)
            return FMU_STATUS_ERROR;
    }
    return FMU_STATUS_OK;
}


fmu_status_t container_exit_configuration_mode(container_t* container) {
    for (int i = 0; i < container->nb_fmu; i += 1) {
        if (container->fmu[i].in_configuration_mode &&
            container_exit_fmu_configuration(container, i) != FMU_STATUS_OK)
            return FMU_STATUS_ERROR;
    }
    return FMU_STATUS_OK;
}


/* Before fmi2SetupExperiment (the FMU may use its parameters there, e.g. an XCP service of FMI-LS-XCP): its
   structural parameters, its start values, then the values set on the container (cache), which prevail. */
static fmu_status_t container_prepare_fmu(container_t *container, int fmu_id) {
    fmu_t *fmu = &container->fmu[fmu_id];

    if (container_configure_fmu(container, fmu_id) != FMU_STATUS_OK)
        return FMU_STATUS_ERROR;
    if (container_set_fmu_start_values(fmu, START_VALUES_EARLY) != FMU_STATUS_OK)
        return FMU_STATUS_ERROR;
    cache_mark_fmu(container, (unsigned long)fmu_id, -1);
    if (cache_sync_fmu(container, (unsigned long)fmu_id, false) != FMU_STATUS_OK)
        return FMU_STATUS_ERROR;
    return fmuSetupExperiment(fmu, container->time);
}


fmu_status_t container_setup_experiment(container_t* container, bool toleranceDefined, double tolerance,
                                        double startTime, bool stopTimeDefined, double stopTime) {
    const logger_t *logger = &container->logger;
    (void)stopTimeDefined; /* unused parameter */

    container->tolerance_defined = toleranceDefined;
    if (toleranceDefined)
        container->tolerance = tolerance;
    container->start_time = startTime;
    container->stop_time_defined = false; /* stopTime can cause rounding issues: disable it. */
    container->stop_time = stopTime;
    container->time = container->start_time;

    LOGGER_DEBUG("Setting start values...");
    for(int i=0; i < container->nb_fmu; i += 1) {
        if (container_prepare_fmu(container, i) != FMU_STATUS_OK)
            return FMU_STATUS_ERROR;
    }
    LOGGER_DEBUG("Start values are set.");

    return FMU_STATUS_OK;
}


/*----------------------------------------------------------------------------
     P R O P A G A T I O N   D U R I N G   T H E   I N I T I A L I Z A T I O N
----------------------------------------------------------------------------*/

/*
 * Exit of the Initialization Mode of the embedded FMUs, with the propagation of their links, as Simulink does: in
 * the initialization order (topological order of the links, written by the builder), each FMU gets its linked inputs
 * from the local variables, leaves its Initialization Mode, then its outputs are read into the local variables for the
 * FMUs after it. No output is read in Initialization Mode (some FMUs compute them only when they leave it). An ME FMU
 * is in Event Mode after its exit: its outputs are read after its own event iteration, never before its first update
 * of the discrete states. In a loop of links, the first FMU of the loop gets the values the loop has before the propagation (the builder
 * warns). Clocks and clocked variables are not propagated.
 */
static fmu_status_t container_exit_fmus_initialization(container_t* container) {
    const logger_t *logger = &container->logger;
    for (int k = 0; k < container->nb_fmu; k += 1) {
        fmu_t *fmu = &container->fmu[container->init_order[k]];
        fmu_status_t status;

        status = fmu_set_inputs(fmu);
        if (status != FMU_STATUS_OK) {
            LOGGER_ERROR("Container: FMU '%s' failed to get its inputs at the initialization.", fmu->name);
            return status;
        }

        status = fmuExitInitializationMode(fmu);
        if (status != FMU_STATUS_OK)
            return status;

        if (fmu->kind == FMU_KIND_ME) {
            bool more_event = true;
            int iter;
            for (iter = 0; (iter < CONTAINER_MAX_EVENT_ITER) && more_event; iter += 1) {
                if (fmu_set_inputs(fmu) != FMU_STATUS_OK)
                    return FMU_STATUS_ERROR;
                if (fmuUpdateDiscreteStates(fmu, &more_event) != FMU_STATUS_OK)
                    return FMU_STATUS_ERROR;
            }
            if (more_event) {
                LOGGER_ERROR("Container: event iteration of FMU '%s' did not converge at the initialization.",
                             fmu->name);
                return FMU_STATUS_ERROR;
            }
        }

        status = fmu_get_outputs(fmu);
        if (status != FMU_STATUS_OK) {
            LOGGER_ERROR("Container: FMU '%s' failed to give its outputs at the initialization.", fmu->name);
            return status;
        }
    }
    return FMU_STATUS_OK;
}


fmu_status_t container_enter_initialization_mode(container_t* container) {
    for (int i = 0; i < container->nb_fmu; i += 1) {
        if (fmuEnterInitializationMode(&container->fmu[i], container->start_time) != FMU_STATUS_OK)
            return FMU_STATUS_ERROR;
    }

    if (container_set_start_values(container, START_VALUES_INITIALIZATION) != FMU_STATUS_OK)
        return FMU_STATUS_ERROR;
    /* The values set by the importer on these variables prevail: set at the next synchronization of each FMU */
    for (int i = 0; i < container->nb_fmu; i += 1)
        cache_mark_fmu(container, (unsigned long)i, 1);
    return FMU_STATUS_OK;
}


static fmu_status_t container_init_values(container_t* container) {
    const logger_t *logger = &container->logger;
    for (int i = 0; i < container->nb_fmu; i += 1) {
        /* Do NOT read ME FMU outputs here: they are still in the initial
           EventMode and the first fmi2NewDiscreteStates() has not been called
           yet. Reading outputs before that first event iteration makes some
           FMI 2.0 ME FMUs (e.g. Simulink generated) reset their continuous
           states to 0 on the next NewDiscreteStates() call. ME outputs are
           read after the event iteration (in container_update_discrete_state)
           and after solver_leave_event_mode(). */
        if (container->fmu[i].kind == FMU_KIND_ME)
            continue;
        if ((fmu_get_outputs(&container->fmu[i]) != FMU_STATUS_OK) ||
            (fmu_get_clocked_outputs(&container->fmu[i]) != FMU_STATUS_OK)) {
            LOGGER_ERROR("Container: FMU '%s' failed to give its outputs at the end of the initialization.",
                         container->fmu[i].name);
            return FMU_STATUS_ERROR;
        }
    }
    return FMU_STATUS_OK;
}

fmu_status_t container_exit_initialization_mode(container_t* container) {
    const logger_t *logger = &container->logger;
    fmu_status_t status;
    
    /* Resolve ME FMU pointers and allocate the solver's flat state buffers. */
    if (solver_configure(container->solver)) {
        LOGGER_ERROR("Cannot build ME solver.");
        return FMU_STATUS_ERROR;
    }

    status = container_clocks_init_schedule(container);
    if (status != FMU_STATUS_OK)
        return status;

    status = container_exit_fmus_initialization(container);
    if (status != FMU_STATUS_OK)
        return status;

    /* CS FMUs are in EventMode (or StepMode if support_event=0); ME FMUs are in
       EventMode: run one common event iteration before splitting the modes. */
    status = container_init_values(container);
    if (status != FMU_STATUS_OK)
        return status;
    /* As for each Event Mode: a row with the ticks of the clocks, e.g. the operations of FMI-LS-BUS prepared in
       Initialization Mode and sent in this first Event Mode. */
    datalog_log(container);

    /* The outputs were read just above. */
    status = container_close_instant(container);
    if (status != FMU_STATUS_OK)
        return status;

    status = container_deliver_clocked_inputs(container);
    if (status != FMU_STATUS_OK)
        return status;

    status = container_update_discrete_state(container, true);
    if (status != FMU_STATUS_OK)
        return status;

    status = container_handle_due_clocks(container);
    if (status != FMU_STATUS_OK)
        return status;

    status = solver_leave_event_mode(container->solver);
    if (status != FMU_STATUS_OK)
        return status;

    status = container_enter_step_mode(container);
    if (status != FMU_STATUS_OK)
        return status;

#ifdef DEBUG
    LOGGER_DEBUG("[DEBUG] time=%e | first container->next_step = %e", container->time, container->next_step);
#endif

    return status;
}


fmu_status_t container_terminate(container_t* container) {
    const logger_t *logger = &container->logger;
    fmu_status_t status = FMU_STATUS_OK;

    for (int i = 0; i < container->nb_fmu; i += 1) {
        fmu_status_t fmu_status = fmuTerminate(&container->fmu[i]);
        if (fmu_status != FMU_STATUS_OK) {
            LOGGER_ERROR("Container: FMU '%s' failed to terminate.", container->fmu[i].name);
            status = FMU_STATUS_ERROR;
        }
    }

    return status;
}


/*----------------------------------------------------------------------------
                           R E S E T
----------------------------------------------------------------------------*/

/* fmi2Reset / fmi3Reset of the container: every embedded FMU is reset, and the container goes back to its state
   right after its instantiation. The datalog goes on in the same file. In the multi-thread mode, the dispatch of the
   FMUs decided at the end of the warm-up is kept, with its worker threads: no new warm-up. */
fmu_status_t container_reset(container_t* container) {
    const logger_t *logger = &container->logger;
    for (int i = 0; i < container->nb_fmu; i += 1) {
        fmu_t *fmu = &container->fmu[i];

        if (fmuReset(fmu) != FMU_STATUS_OK) {
            LOGGER_ERROR("Container: FMU '%s' failed to reset.", fmu->name);
            return FMU_STATUS_ERROR;
        }
        fmu->need_event_update = false;
        fmu->have_next_event_time = false;
        fmu->reset_pending = false;
        fmu->in_configuration_mode = false;
        fmu->configured = false;
        if (fmu->profile) {
            fmu->profile->current_tic = 0;
            fmu->profile->total_elapsed = 0.0;
        }
    }

    /* Local variables, as allocated by config_read_local() (config.c) */
#define RESET_LOCAL(variable, fmi_type, c_type)                             \
    for (unsigned long i = 0; i < container-> variable .nb_locals; i += 1) \
        container-> variable .locals [i] = (c_type)0;

    FOR_ALL_NUMERIC_TYPES(RESET_LOCAL)
    RESET_LOCAL(clocks, Clock, bool)
#undef RESET_LOCAL
    for (unsigned long i = 0; i < container->strings.nb_locals; i += 1)
        container->strings.locals[i].data[0] = '\0';
    for (unsigned long i = 0; i < container->binaries.nb_locals; i += 1)
        container->binaries.locals[i].size = 0;

    /* Reserved variables, as set by config_container() (config.c) */
    container->integers32.locals[0] = 1;                /* Default: TS multiplier */
    container->integers32.locals[1] = 0;                /* Default: solver config (euler) */

    /* Values set by the importer */
    cache_reset(container);

    /* Clocks schedule */
    for (unsigned long i = 0; i < container->clocks_list.nb_local_clocks; i += 1) {
        container->clocks_list.clocks[i].next_known = false;
        container->clocks_list.clocks[i].ticked = false;
    }

    /* Simulation */
    container->step_pending = false;
    container->terminate_requested = false;
    container->nb_steps = 0;
    container->next_step = container->time_step; /* Default: no next event time */
    container->time = container->start_time;
    container->need_event_update = false;

    LOGGER_DEBUG("Container is reset.");

    return FMU_STATUS_OK;
}


static bool container_reset_requested(const container_t *container, const fmu_t *fmu) {
    if (fmu->reset_trigger < 0)
        return false;
    if (container->fmi_version == 2)
        return container->booleans.locals[fmu->reset_trigger] != 0;
    return container->booleans1.locals[fmu->reset_trigger];
}


static void container_clear_reset_trigger(container_t *container, const fmu_t *fmu) {
    if (container->fmi_version == 2)
        container->booleans.locals[fmu->reset_trigger] = 0;
    else
        container->booleans1.locals[fmu->reset_trigger] = false;
}


/* The schedule of the clocks is computed for all the FMUs at once, in Event Mode: it cannot be computed again
   for one FMU. */
static bool container_fmu_has_scheduled_clocks(const container_t *container, int fmu_id) {
    for (unsigned long i = 0; i < container->clocks_list.nb_local_clocks; i += 1) {
        if (container->clocks_list.clocks[i].fmu_id == (unsigned long)fmu_id)
            return true;
    }
    return false;
}


/* Reset the FMU and initialize it again at the current time, as the container does at its initialization. */
static fmu_status_t container_reset_fmu(container_t *container, int fmu_id) {
    const logger_t *logger = &container->logger;
    fmu_t *fmu = &container->fmu[fmu_id];

    LOGGER_DEBUG("Reset FMU '%s' at time=%e.", fmu->name, container->time);

    if (container_fmu_has_scheduled_clocks(container, fmu_id)) {
        LOGGER_ERROR("Container: FMU '%s' cannot be reset: the reset of an FMU with scheduled clocks is "
                     "not supported.", fmu->name);
        return FMU_STATUS_ERROR;
    }

    if (fmuReset(fmu) != FMU_STATUS_OK) {
        LOGGER_ERROR("Container: FMU '%s' cannot be reset (time=%e).", fmu->name, container->time);
        return FMU_STATUS_ERROR;
    }

    fmu->configured = false;
    if (container_prepare_fmu(container, fmu_id) != FMU_STATUS_OK)
        return FMU_STATUS_ERROR;

    if (fmuEnterInitializationMode(fmu, container->time) != FMU_STATUS_OK)
        return FMU_STATUS_ERROR;
    if (container_set_fmu_start_values(fmu, START_VALUES_INITIALIZATION) != FMU_STATUS_OK)
        return FMU_STATUS_ERROR;
    cache_mark_fmu(container, (unsigned long)fmu_id, 1);
    if (cache_sync_fmu(container, (unsigned long)fmu_id, false) != FMU_STATUS_OK)   /* even in a pending step */
        return FMU_STATUS_ERROR;
    if (fmu_set_inputs(fmu) != FMU_STATUS_OK)
        return FMU_STATUS_ERROR;
    if (fmu_set_clocked_inputs(fmu) != FMU_STATUS_OK)
        return FMU_STATUS_ERROR;

    if (fmuExitInitializationMode(fmu) != FMU_STATUS_OK)
        return FMU_STATUS_ERROR;

    /* The FMU is in Event Mode (ME, or CS with event mode): event iteration of this FMU only, as
       container_update_discrete_state() does for all of them. */
    bool more_event = true;
    int iter;
    for (iter = 0; (iter < CONTAINER_MAX_EVENT_ITER) && more_event; iter += 1) {
        if (fmu_set_clocks(fmu) != FMU_STATUS_OK)
            return FMU_STATUS_ERROR;
        if (fmu_set_inputs(fmu) != FMU_STATUS_OK)
            return FMU_STATUS_ERROR;
        if (fmu_set_clocked_inputs(fmu) != FMU_STATUS_OK)
            return FMU_STATUS_ERROR;
        if (fmuUpdateDiscreteStates(fmu, &more_event) != FMU_STATUS_OK)
            return FMU_STATUS_ERROR;
        if (fmu_get_outputs(fmu) != FMU_STATUS_OK)
            return FMU_STATUS_ERROR;
        if (fmu_get_clocked_outputs(fmu) != FMU_STATUS_OK)
            return FMU_STATUS_ERROR;
    }
    if (more_event) {
        LOGGER_ERROR("Container: event iteration of FMU '%s' did not converge after its reset.", fmu->name);
        return FMU_STATUS_ERROR;
    }

    if (fmu->kind == FMU_KIND_ME) {
        if (solver_leave_event_mode_fmu(container->solver, (unsigned long)fmu_id) != FMU_STATUS_OK)
            return FMU_STATUS_ERROR;
    } else {
        if (fmuEnterStepMode(fmu) != FMU_STATUS_OK)
            return FMU_STATUS_ERROR;
    }

    return FMU_STATUS_OK;
}


/* At the start of each internal step: reset the FMUs whose `container.<fmu>.reset` is true. All the triggers are
   read before the first reset (one trigger may drive several FMUs). A datalog row is written before, so that the
   trigger is visible even when the importer set it. The triggers stay true during the step: they are cleared by
   container_clear_reset_triggers() at its end. */
static fmu_status_t container_reset_fmus(container_t *container) {
    bool reset = false;

    for (int i = 0; i < container->nb_fmu; i += 1) {
        container->fmu[i].reset_pending = container_reset_requested(container, &container->fmu[i]);
        reset |= container->fmu[i].reset_pending;
    }

    if (! reset)
        return FMU_STATUS_OK;

    datalog_log(container);
    for (int i = 0; i < container->nb_fmu; i += 1) {
        if (container->fmu[i].reset_pending && (container_reset_fmu(container, i) != FMU_STATUS_OK))
            return FMU_STATUS_ERROR;
    }

    /* A reset FMU may announce a time event earlier than the planned step. */
    container_bound_next_step(container);

    return FMU_STATUS_OK;
}


/* At the end of the step: the triggers of the FMUs reset at its start go back to false, whoever set them (the
   importer or an embedded FMU). */
static void container_clear_reset_triggers(container_t *container) {
    for (int i = 0; i < container->nb_fmu; i += 1) {
        fmu_t *fmu = &container->fmu[i];

        if (fmu->reset_pending) {
            container_clear_reset_trigger(container, fmu);
            fmu->reset_pending = false;
        }
    }
}


/*----------------------------------------------------------------------------
                                D O   S T E P
----------------------------------------------------------------------------*/

/*
 * Model-Exchange part of an internal step, common to the three modes. It runs once the CS FMUs are stepped, so
 * that their discrete outputs are fresh when the ME solver runs (a discrete level coupled into an ME reset is
 * applied on a single clean edge).
 *
 * Only the continuous (real) inputs are pushed to the ME FMUs before the collective integration: discrete inputs
 * (e.g. a bounce "reset" flag) must not be set in Continuous Time Mode, that corrupts the target FMU's edge
 * detection (FMI-2.0 2.1.3). They are exchanged in Event Mode by solver_event_iteration() /
 * container_update_discrete_state(). The ME FMUs are then advanced together, so that their couplings stay
 * consistent within the step, and their outputs are read.
 */
static fmu_status_t container_step_me(container_t *container) {
    const logger_t *logger = &container->logger;
    fmu_status_t status = FMU_STATUS_OK;

    for (size_t i = 0; i < container->solver->nb_me; i += 1) {
        fmu_t *fmu = container->solver->me[i].fmu;
        status = fmu_set_continuous_inputs(fmu);
        if (status != FMU_STATUS_OK) {
            LOGGER_ERROR("Container: FMU '%s' failed set inputs.", fmu->name);
            return status;
        }
    }

    status = solver_do_step(container->solver, container->time, container->next_step);
    if (status != FMU_STATUS_OK)
        return status;

    for (size_t i = 0; i < container->solver->nb_me; i += 1) {
        fmu_t *fmu = container->solver->me[i].fmu;
        status = fmu_get_outputs(fmu);
        if (status != FMU_STATUS_OK) {
            LOGGER_ERROR("Container: FMU '%s' failed getting outputs.", fmu->name);
            return status;
        }
    }

    return status;
}


static fmu_status_t container_do_one_step_sequential(container_t *container) {
    const logger_t *logger = &container->logger;
    fmu_status_t status = FMU_STATUS_OK;

    container->need_event_update = false;

    /* CS FMUs first: set inputs -> doStep -> get outputs, one FMU after the other (Gauss-Seidel). */
    for (unsigned int i = 0; i < container->nb_cs; i += 1) {
        fmu_t *fmu = container->cs_fmu[i];

        status = fmu_set_inputs(fmu);
        if (status != FMU_STATUS_OK) {
            LOGGER_ERROR("Container: FMU '%s' failed set inputs.", fmu->name);
            return status;
        }

        status = fmuDoStep(fmu, container->time, container->next_step);
        if (status != FMU_STATUS_OK)
            return status;
        container->need_event_update |= fmu->need_event_update;

        status = fmu_get_outputs(fmu);
        if (status != FMU_STATUS_OK) {
            LOGGER_ERROR("Container: FMU '%s' failed getting outputs.", fmu->name);
            return status;
        }
    }

    return container_step_me(container);
}


static fmu_status_t container_do_one_step_parallel(container_t* container) {
    const logger_t *logger = &container->logger;
    fmu_status_t status = FMU_STATUS_OK;

    container->need_event_update = false;

    /* CS FMUs first: all the inputs, then all the steps, then all the outputs (Jacobi). */
    for (unsigned int i = 0; i < container->nb_cs; i += 1) {
        status = fmu_set_inputs(container->cs_fmu[i]);
        if (status != FMU_STATUS_OK) {
            LOGGER_ERROR("Container: FMU '%s' failed set inputs.", container->cs_fmu[i]->name);
            return status;
        }
    }
    for (unsigned int i = 0; i < container->nb_cs; i += 1) {
        fmu_t* fmu = container->cs_fmu[i];
        if (container->mt_warmup)
            profile_tic(&fmu->warmup);
        status = fmuDoStep(fmu, container->time, container->next_step);
        if (container->mt_warmup)
            profile_toc(&fmu->warmup, container->time);     /* the duration of the steps adds up in total_elapsed */
        if (status != FMU_STATUS_OK) {
            LOGGER_ERROR("Container: FMU '%s' failed doStep.", fmu->name);
            return status;
        }
        container->need_event_update |= fmu->need_event_update;
    }
    for (unsigned int i = 0; i < container->nb_cs; i += 1) {
        status = fmu_get_outputs(container->cs_fmu[i]);
        if (status != FMU_STATUS_OK) {
            LOGGER_ERROR("Container: FMU '%s' failed get outputs.", container->cs_fmu[i]->name);
            return status;
        }
    }

    return container_step_me(container);
}


fmu_status_t container_do_step(container_t* container, double currentCommunicationPoint, double communicationStepSize) {
    const logger_t *logger = &container->logger;
#ifdef DEBUG
    LOGGER_DEBUG("[DEBUG] time=%e | container_do_step(%e, %e)", container->time, currentCommunicationPoint,
                 communicationStepSize);
#endif
    fmu_status_t status = FMU_STATUS_OK;
    const double end_time = currentCommunicationPoint + communicationStepSize;

    if (container->terminate_requested) {
        LOGGER_ERROR("The simulation has been terminated at time=%e: no further step.", container->reals64.locals[0]);
        return FMU_STATUS_ERROR;
    }

    /*
     * Internal steps of the container (time_step x TS_MULTIPLIER, the multiplier read at the beginning of each
     * step) that end before end_time. A step that does not fit (communication step not a multiple of the internal
     * step) stays pending: it is done by the call that reaches its end, with the inputs of its beginning (the values
     * set by the importer meanwhile are deferred); its outputs are held until then, as an FMU of fixed step.
     */
    while (true) {
        container->time = container->start_time + container->time_step * container->nb_steps;
        int ts_multiplier = container->integers32.locals[0];
        if (ts_multiplier < 1)
            ts_multiplier = 1;
        const double ts = container->time_step * ts_multiplier;
        const double target_time = container->time + ts;

        if (target_time > end_time + container->tolerance)
            break;

#ifdef DEBUG
        LOGGER_DEBUG("[DEBUG] time=%e | container internal step ts=%e (end_time=%e)", container->time, ts, end_time);
#endif
        while(! container_is_close(container, container->time, target_time)) {
            /* RESET of embedded FMUs */
            status = container_reset_fmus(container);
            if (status != FMU_STATUS_OK) {
                LOGGER_ERROR("Container cannot reset FMUs (time=%e)", container->time);
                return status;
            }

            /* STEP MODE */
            if (container->time + container->next_step > target_time) {
                container->next_step = target_time - container->time;
            }
#ifdef DEBUG
            LOGGER_DEBUG("[DEBUG] time=%e | do_step ts=%e", container->time, container->next_step);
#endif
            status = container->do_step(container);
            if (status != FMU_STATUS_OK) {
                LOGGER_ERROR("Container cannot Do Step (time=%e)", container->time);
                return status;
            }
            container_clear_reset_triggers(container);
            container->time += container->next_step;

            /* EVENT MODE */
            status = container_handle_events(container);
            if ( status != FMU_STATUS_OK) {
                LOGGER_ERROR("Container cannot Handle Events (time=%e)", container->time);
                return status;
            }

            if (container->terminate_requested) {
                /* The importer gets the time reached: the rest of the communication step is not done. */
                LOGGER_WARNING("Container terminates the simulation at time=%e.", container->time);
                container->reals64.locals[0] = container->time;
                return FMU_STATUS_OK;
            }
        }
        container->nb_steps += ts_multiplier;

        /* The pending step is done: the values deferred meanwhile are for the next steps. */
        if (container->step_pending) {
            container->step_pending = false;
            status = cache_end_pending_step(container);
            if (status != FMU_STATUS_OK)
                return status;
        }
    }

    container->time = container->start_time + container->time_step * container->nb_steps;
    if (!container->step_pending && end_time - container->time > container->tolerance) {
        /* A step becomes pending: it uses the values set until now, those set meanwhile are deferred. */
        status = cache_sync_fmus(container);
        if (status != FMU_STATUS_OK)
            return status;
        container->step_pending = true;
    }

    container->reals64.locals[0] = end_time;
    
    return status;
}


/*----------------------------------------------------------------------------
                        M U L T I - T H R E A D
----------------------------------------------------------------------------*/

/*
 * Multi-thread mode, after the warm-up: the workers step the heavy FMUs while the main thread steps the light ones.
 * The exchanges stay on the main thread: all the inputs before the steps, all the outputs after (Jacobi). A worker
 * getting the outputs of its FMU would write local variables that another one may still read.
 */
static fmu_status_t container_do_one_step_hybrid(container_t* container) {
    const logger_t *logger = &container->logger;
    fmu_status_t status = FMU_STATUS_OK;

    container->need_event_update = false;

    for (unsigned int i = 0; i < container->nb_cs; i += 1) {
        fmu_t* fmu = container->cs_fmu[i];
        status = fmu_set_inputs(fmu);
        if (status != FMU_STATUS_OK) {
            LOGGER_ERROR("Container: FMU '%s' failed set inputs.", fmu->name);
            return status;
        }
    }

    thread_barrier_wait(&container->barrier_start);     /* the workers step the heavy FMUs */
    for (unsigned int i = 0; i < container->nb_light; i += 1) {
        fmu_t* fmu = container->light_fmu[i];
        fmu->status = fmuDoStep(fmu, container->time, container->next_step);
    }
    thread_barrier_wait(&container->barrier_end);       /* every CS FMU has done its step */

    for (unsigned int i = 0; i < container->nb_cs; i += 1) {
        fmu_t* fmu = container->cs_fmu[i];
        if (fmu->status != FMU_STATUS_OK) {
            LOGGER_ERROR("Container: FMU '%s' failed doStep (status %d).", fmu->name, fmu->status);
            return fmu->status;
        }
        container->need_event_update |= fmu->need_event_update;
    }
    for (unsigned int i = 0; i < container->nb_cs; i += 1) {
        status = fmu_get_outputs(container->cs_fmu[i]);
        if (status != FMU_STATUS_OK) {
            LOGGER_ERROR("Container: FMU '%s' failed get outputs.", container->cs_fmu[i]->name);
            return status;
        }
    }

    return container_step_me(container);
}


/*
 * Worker thread function: each worker executes the FMU steps assigned to it.
 */
static void *container_worker(container_worker_t *worker) {
    container_t *container = worker->container;

    /* barriers_ready is set before the gate is opened: false if the threads could not all be started */
    thread_gate_wait(&container->threads_gate);
    if (!container->barriers_ready)
        return NULL;

    while (true) {
        thread_barrier_wait(&container->barrier_start);   /* WAIT 1st SYNC */
        if (container->cancel)
            break;

        for (unsigned int i = 0; i < worker->nb_fmu; i += 1) {
            fmu_t *fmu = worker->fmu[i];
            fmu->status = fmuDoStep(fmu, container->time, container->next_step);   /* logged by the main thread */
        }

        thread_barrier_wait(&container->barrier_end);     /* WAIT 2nd SYNC */
    }

    return NULL;
}


/*
 * The worker threads wait on threads_gate until every one of them is launched and the barriers are initialized
 * for them: when one cannot be launched, the gate is opened without barriers_ready and those already launched end.
 */
static int container_start_threads(container_t *container) {
    const logger_t *logger = &container->logger;

    if (thread_gate_init(&container->threads_gate)) {
        LOGGER_ERROR("Cannot initialize the start of the threads.");
        return -1;
    }
    container->threads_gate_ready = true;

    int status = 0;
    for (unsigned int i = 0; i < container->nb_workers; i += 1) {
        container->workers[i].thread = thread_new((thread_function_t)container_worker, &container->workers[i]);
        if (!container->workers[i].thread) {
            LOGGER_ERROR("Cannot launch worker thread #%u.", i);
            status = -2;
            break;
        }
        container->nb_threads += 1;
    }

    if (!status) {
        LOGGER_DEBUG("Container barrier is configured with %u participants", container->nb_workers + 1);
        if (thread_barrier_init(&container->barrier_start, container->nb_workers + 1)) {
            LOGGER_ERROR("Cannot initialize thread barrier.");
            status = -1;
        } else if (thread_barrier_init(&container->barrier_end, container->nb_workers + 1)) {
            LOGGER_ERROR("Cannot initialize thread barrier.");
            thread_barrier_destroy(&container->barrier_start);
            status = -1;
        } else
            container->barriers_ready = true;
    }

    /* without barriers_ready, the launched threads end as soon as the gate is open */
    thread_gate_open(&container->threads_gate);

    return status;
}


/*
 * Stop all worker threads and clean up associated resources.
 */
static void container_stop_threads(container_t *container) {
    const logger_t *logger = &container->logger;
    if (!container->threads_gate_ready)
        return;

    LOGGER_DEBUG("Stopping threads...");
    if (container->barriers_ready) {
        container->cancel = true;
        thread_barrier_wait(&container->barrier_start);
    }

    for (unsigned int i = 0; i < container->nb_threads; i += 1) {
        LOGGER_DEBUG("Waiting for worker thread #%u to finish.", i);
        thread_join(container->workers[i].thread);
        container->workers[i].thread = NULL;
    }
    container->nb_threads = 0;

    if (container->barriers_ready) {
        thread_barrier_destroy(&container->barrier_start);
        thread_barrier_destroy(&container->barrier_end);
        container->barriers_ready = false;
    }
    thread_gate_destroy(&container->threads_gate);
    container->threads_gate_ready = false;

    return;
}


/* Heavy FMUs, the longest step first. */
static int container_compare_warmup(const void *a, const void *b) {
    const double ta = (*(fmu_t *const *)a)->warmup.total_elapsed, tb = (*(fmu_t *const *)b)->warmup.total_elapsed;
    return (ta < tb) - (ta > tb);
}


/*
 * End of the warm-up of the multi-thread mode: the CS FMUs whose mean fmuDoStep is at least mt_threshold_us are heavy.
 * They are given to min(heavy FMUs, cores - 1) workers, the longest first, each to the least loaded worker; the main
 * thread steps the light ones. Without heavy FMU, without a second core, or if the threads cannot be started, the
 * simulation goes on in the mono-thread parallel mode.
 */
static void container_dispatch(container_t *container) {
    const logger_t *logger = &container->logger;
    const double threshold = container->mt_threshold_us * 1e-6 * MT_WARMUP;      /* s, all the steps */
    fmu_t **heavy = malloc((container->nb_cs ? container->nb_cs : 1) * sizeof(*heavy));
    unsigned int nb_heavy = 0;

    container->do_step = container_do_one_step_parallel;
    container->light_fmu = malloc((container->nb_cs ? container->nb_cs : 1) * sizeof(*container->light_fmu));
    if (!heavy || !container->light_fmu) {
        LOGGER_WARNING("Container use PARALLEL mode with MONO thread: cannot allocate the dispatch of the FMUs.");
        free(heavy);
        return;
    }

    for (unsigned int i = 0; i < container->nb_cs; i += 1) {
        fmu_t *fmu = container->cs_fmu[i];
        if (fmu->warmup.total_elapsed >= threshold)
            heavy[nb_heavy++] = fmu;
        else
            container->light_fmu[container->nb_light++] = fmu;
    }

    const unsigned int nb_cores = thread_nb_cores();
    const unsigned int nb_workers = nb_heavy < nb_cores - 1 ? nb_heavy : nb_cores - 1;
    if (nb_workers == 0) {
        LOGGER_WARNING("Container use PARALLEL mode with MONO thread: %s.",
                       nb_heavy ? "the host has a single core" : "no FMU step takes the threshold");
        free(heavy);
        return;
    }

    container->workers = calloc(nb_workers, sizeof(*container->workers));
    if (!container->workers) {
        LOGGER_WARNING("Container use PARALLEL mode with MONO thread: cannot allocate the workers.");
        free(heavy);
        return;
    }
    
    container->nb_workers = nb_workers;
    for (unsigned int i = 0; i < nb_workers; i += 1) {
        container->workers[i].container = container;
        container->workers[i].fmu = malloc(nb_heavy * sizeof(*container->workers[i].fmu));
        if (!container->workers[i].fmu) {
            LOGGER_WARNING("Container use PARALLEL mode with MONO thread: cannot allocate the workers.");
            free(heavy);
            return;
        }
    }

    qsort(heavy, nb_heavy, sizeof(*heavy), container_compare_warmup);
    for (unsigned int i = 0; i < nb_heavy; i += 1) {
        container_worker_t *worker = &container->workers[0];
        for (unsigned int j = 1; j < nb_workers; j += 1)
            if (container->workers[j].load < worker->load)
                worker = &container->workers[j];
        worker->fmu[worker->nb_fmu++] = heavy[i];
        worker->load += heavy[i]->warmup.total_elapsed / MT_WARMUP;
    }
    free(heavy);

    if (container_start_threads(container)) {
        container_stop_threads(container);
        LOGGER_WARNING("Container use PARALLEL mode with MONO thread: cannot start the worker threads.");
        return;
    }

    container->do_step = container_do_one_step_hybrid;
    LOGGER_WARNING("Container use PARALLEL mode with MULTI thread: %u worker thread(s) for %u FMU(s), %u FMU(s) on "
                   "the main thread.", nb_workers, nb_heavy, container->nb_light);
    for (unsigned int i = 0; i < nb_workers; i += 1)
        for (unsigned int j = 0; j < container->workers[i].nb_fmu; j += 1)
            LOGGER_WARNING("FMU '%s' (step of %.1f us) on worker thread #%u.", container->workers[i].fmu[j]->name,
                           container->workers[i].fmu[j]->warmup.total_elapsed / MT_WARMUP * 1e6, i);
}


/* Multi-thread mode, first MT_WARMUP internal steps: the mono-thread parallel mode, which times the steps of the CS
   FMUs; the FMUs are then dispatched. */
static fmu_status_t container_do_one_step_warmup(container_t *container) {
    const fmu_status_t status = container_do_one_step_parallel(container);

    if (status == FMU_STATUS_OK) {
        container->mt_warmup -= 1;
        if (container->mt_warmup == 0)
            container_dispatch(container);
    }
    return status;
}


/*
 * The step of the container, given the flags of container.txt: sequential, parallel in the main thread, or parallel
 * with worker threads for the heavy FMUs after a warm-up of MT_WARMUP steps (mt_threshold_us is read before).
 */
void container_set_mode(container_t *container, bool sequential, bool mt) {
    const logger_t *logger = &container->logger;

    if (sequential) {
        LOGGER_WARNING("Container use SEQUENTIAL mode.");
        container->do_step = container_do_one_step_sequential;
    } else if (mt) {
        LOGGER_WARNING("Container use PARALLEL mode with MULTI thread, for the FMUs whose step takes %lu us or "
                       "more (measured over the first %d steps).", container->mt_threshold_us, MT_WARMUP);
        container->do_step = container_do_one_step_warmup;
        container->mt_warmup = MT_WARMUP;
        container->mt = true;
    } else {
        LOGGER_WARNING("Container use PARALLEL mode with MONO thread.");
        container->do_step = container_do_one_step_parallel;
    }
}


/*----------------------------------------------------------------------------
             C O N S T R U C T O R   /   D E S T R U C T O R
----------------------------------------------------------------------------*/

/* NULL if an argument is NULL or on an allocation failure. Every member not set below starts at zero. */
container_t *container_new(const char *instance_name, const char *fmu_uuid, int fmi_version) {
    if (!instance_name || !fmu_uuid)
        return NULL;

    container_t *container = calloc(1, sizeof(*container));
    if (container) {
        container->allocate_memory = calloc;
        container->free_memory = free;
        container->instance_name = strdup(instance_name);
        container->uuid = strdup(fmu_uuid);
        if (!container->instance_name || !container->uuid) {
            free(container->instance_name);
            free(container->uuid);
            free(container);
            return NULL;
        }
        container->fmi_version = fmi_version;

        container->nb_fmu = 0;
        container->fmu = NULL;
        container->init_order = NULL;
        container->step_pending = false;
        container->terminate_requested = false;
        container->cache = NULL;

        /* allocated at the end of the configuration: freed by container_free() even if it fails before */
        container->binaries_tmp = NULL;
        container->binaries_size_tmp = NULL;
        container->strings_tmp = NULL;

        container->nb_cs = 0;
        container->cs_fmu = NULL;
        container->solver = NULL;

#define INIT(variable, fmi_type, c_type)      \
        container-> variable .nb_locals = 0;  \
        container-> variable .locals = NULL;  \
        container-> variable .nb_ports = 0;   \
        container-> variable .links = NULL;   \
        container-> variable .ports = NULL;

        FOR_ALL_NUMERIC_TYPES(INIT)
        INIT(strings, String, char *)
        INIT(binaries, Binary, fmu_binary_t)
        INIT(clocks, Clock, bool)
#undef INIT


        container->time = 0.0;
        container->time_step = 0.001;
        container->start_time = 0.0;
        container->nb_steps = 0;
        container->tolerance = 1.0e-8;

        container->clocks_list.nb_fmu = 0;
        container->clocks_list.nb_local_clocks = 0;

        container->clocks_list.clocks = NULL;              /* nb_local_clocks */
        container->clocks_list.active = NULL;              /* container->clocks.nb_locals */

        container->datalog = NULL;

        container->need_event_update = false;

        container->mt = false;
        container->mt_threshold_us = 0;
        container->mt_warmup = 0;
        container->cancel = false;
        container->barriers_ready = false;
        container->threads_gate_ready = false;
        container->workers = NULL;
        container->nb_workers = 0;
        container->nb_threads = 0;
        container->light_fmu = NULL;
        container->nb_light = 0;
    }
    return container;
}


void container_free(container_t *container) {
    /* Stop threads before freeing FMUs */
    container_stop_threads(container);

    if (container->fmu) {
        for (int i = 0; i < container->nb_fmu; i += 1) {
            fmuFreeInstance(&container->fmu[i]);
            fmu_unload(&container->fmu[i]);
        }
        free(container->fmu);
    }

    solver_free(container->solver);
    for (unsigned int i = 0; i < container->nb_workers; i += 1)
        free(container->workers[i].fmu);
    free(container->workers);
    free(container->light_fmu);
    free(container->cs_fmu);
    free(container->init_order);

    free(container->instance_name);
    free(container->uuid);

#define FREE(variable, fmi_type, c_type)    \
    free(container-> variable .links);       \
    free(container-> variable .ports);     \
    free(container-> variable .locals);

    FOR_ALL_NUMERIC_TYPES(FREE)
    for (unsigned long i = 0; i < container->strings.nb_locals && container->strings.locals; i += 1)
        free(container->strings.locals[i].data);
    FREE(strings, String, fmu_string_t)
    for (unsigned long i = 0; i < container->binaries.nb_locals && container->binaries.locals; i += 1)
        free(container->binaries.locals[i].data);
    FREE(binaries, Binary, fmu_binary_t)
    FREE(clocks, Clock, bool)
#undef FREE

    cache_free(container->cache);
    free(container->binaries_tmp);
    free(container->binaries_size_tmp);
    free(container->strings_tmp);

    free(container->clocks_list.clocks);
    free(container->clocks_list.active);
    datalog_free(container->datalog);

    free(container);

    return;
}
