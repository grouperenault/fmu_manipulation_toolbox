#include <errno.h>
#include <inttypes.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cache.h"
#include "config.h"
#include "container.h"
#include "datalog.h"
#include "logger.h"
#include "fmu.h"
#include "solver.h"
#include "version.h"

// #define DEBUG


/*
 * Implementation of the fmu2Component/fmu3Instance depending on FMUContainer
 * configuration.
 */

/* Safety net against a non-converging event iteration. */
#define CONTAINER_MAX_EVENT_ITER    100

/*----------------------------------------------------------------------------
                        E V E N T   M O D E
----------------------------------------------------------------------------*/

fmu_status_t container_enter_event_mode(container_t *container) {
#ifdef DEBUG
    const logger_t *logger = &container->logger;
#endif
#ifdef DEBUG
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
#endif
#ifdef DEBUG
    LOGGER_DEBUG("[DEBUG] time=%e: Container entering in STEP mode", container->time);
#endif
    for (unsigned int i = 0; i < container->nb_cs; i += 1) {
        if (fmuEnterStepMode(container->cs_fmu[i]) != FMU_STATUS_OK)
                return FMU_STATUS_ERROR;
    }
    return FMU_STATUS_OK;
}


static inline int is_close (const container_t *container, double r1, double r2) {
    return fabs(r1-r2) < container->tolerance;
}


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
    return clock->has_ticked && is_close(container, clock->last_tick, container->time);
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


/* The scheduled clocks are reset as soon as their inputs are delivered: for the datalog, show the ones that ticked since
   its last row. */
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


/* An FMU may evaluate its discrete states when its outputs are read, and then refuse any input until
   fmi3UpdateDiscreteStates(): outputs and inputs are exchanged in two super-dense time instants. The event iteration which
   follows calls the update again, and tells if another one is needed. */
static fmu_status_t container_close_instant(container_t *container) {
    for (unsigned int i = 0; i < container->nb_cs; i += 1) {
        bool more_event;

        if (fmuUpdateDiscreteStates(container->cs_fmu[i], &more_event) != FMU_STATUS_OK)
            return FMU_STATUS_ERROR;
    }
    return FMU_STATUS_OK;
}


/* The event iteration reads the output clocks again: the clocks and the inputs they clock reach all the FMUs before it. */
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


/* `delivered`: the clocks and the clocked inputs already reached the FMUs in this instant. */
static fmu_status_t container_update_discrete_state(container_t *container, bool delivered) {
    const logger_t *logger = &container->logger;
    bool more_event;
    int iter;

    container->next_step = container_nominal_step(container);
#ifdef DEBUG
    LOGGER_DEBUG("[DEBUG] time=%e | container_update_discrete_state()", container->time);
#endif
    for (iter = 0; iter < CONTAINER_MAX_EVENT_ITER; iter += 1) {
        /* Gauss-Seidel sweep in configuration order, so a value produced by FMU i
           reaches FMU i+1 within the same pass. Per FMI-3.0, each FMU is driven
           Set inputs -> fmi3UpdateDiscreteStates -> Get outputs, so the outputs
           read back reflect the freshly updated discrete state. */
        more_event = false;

        /* The previous pass read the outputs: this one needs a new instant for its inputs. */
        if ((iter > 0) && (container_close_instant(container) != FMU_STATUS_OK))
            return FMU_STATUS_ERROR;

        for (int i = 0; i < container->nb_fmu; i += 1) {
            fmu_t *fmu = &container->fmu[i];
            bool fmu_more_event = false;

            if (!(delivered && (iter == 0)) && (fmu_set_clocks(fmu) != FMU_STATUS_OK))
                return FMU_STATUS_ERROR;

            if (fmu_set_inputs(fmu) != FMU_STATUS_OK)
                return FMU_STATUS_ERROR;

            if (!(delivered && (iter == 0)) && (fmu_set_clocked_inputs(fmu) != FMU_STATUS_OK))
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

        if (!more_event)
            break;
    }

    if (iter >= CONTAINER_MAX_EVENT_ITER) {
        LOGGER_ERROR("Container: event iteration did not converge after %d steps.", CONTAINER_MAX_EVENT_ITER);
        return FMU_STATUS_ERROR;
    }

    /* All clock have been transmitted by now
       The following code is not necessary but could be used if paranoid

    for(unsigned long i=0; i < container->clocks.nb_locals; i += 1)
        container->clocks.locals[i] = false;
    */

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
    if (phase == START_VALUES_EARLY)
        LOGGER_DEBUG("Setting start values...");
    else
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
    container->stop_time_defined = 0; /* stopTime can cause rounding issues. Disbale it.*/
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
 * the initialization order (topological order of the links, written by the builder), each FMU gets its linked inputs from the local variables, leaves its
 * Initialization Mode, then its outputs are read into the local variables for the FMUs after it. No output is read
 * in Initialization Mode (some FMUs compute them only when they leave it). An ME FMU is in Event Mode after its exit:
 * its outputs are read after its own event iteration, never before its first update of the discrete states.
 * In a loop of links, the first FMU of the loop gets the values the loop has before the propagation (the builder
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


static void container_init_values(container_t* container) {
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
        fmu_get_outputs(&container->fmu[i]);
        fmu_get_clocked_outputs(&container->fmu[i]);
    }
    return;
}

fmu_status_t container_exit_initialization_mode(container_t* container) {
    const logger_t *logger = &container->logger;
    fmu_status_t status;
    
    /* Resolve ME FMU pointers and allocate the solver's flat state buffers. */
    if (solver_configure(container->solver)) {
        LOGGER_ERROR("Cannot build ME solver.");
        return -9;
    }

    status = container_clocks_init_schedule(container);
    if (status != FMU_STATUS_OK)
        return status;

    status = container_exit_fmus_initialization(container);
    if (status != FMU_STATUS_OK)
        return status;

    /* CS FMUs are in EventMode (or StepMode if support_event=0); ME FMUs are in
       EventMode: run one common event iteration before splitting the modes. */
    container_init_values(container);

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


/* fmi2Reset / fmi3Reset of the container: every embedded FMU is reset, and the container goes back to its state
   right after its instantiation. The datalog goes on in the same file. */
fmu_status_t container_reset(container_t* container) {
    const logger_t *logger = &container->logger;
    for (int i = 0; i < container->nb_fmu; i += 1) {
        fmu_t *fmu = &container->fmu[i];

        if (fmuReset(fmu) != FMU_STATUS_OK) {
            LOGGER_ERROR("Container: FMU '%s' failed to reset.", fmu->name);
            return FMU_STATUS_ERROR;
        }
        fmu->need_event_udpate = false;
        fmu->have_next_event_time = false;
        fmu->reset_pending = false;
        fmu->in_configuration_mode = false;
        fmu->configured = false;
        if (fmu->profile) {
            fmu->profile->current_tic = 0;
            fmu->profile->total_elapsed = 0.0;
        }
    }

    /* Local variables, as allocated by read_conf_local() */
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

    /* Reserved variables, as set by container_configure() */
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
    container->nb_steps = 0;
    container->next_step = container->time_step; /* Default: no next event time */
    container->time = container->start_time;
    container->need_event_update = false;

    LOGGER_DEBUG("Container is reset.");

    return FMU_STATUS_OK;
}


/*----------------------------------------------------------------------------
                                D O   S T E P
----------------------------------------------------------------------------*/

static fmu_status_t container_do_one_step_sequential(container_t *container) {
    const logger_t *logger = &container->logger;
    fmu_status_t status = FMU_STATUS_OK;

    container->need_event_update = false;

    /* CS FMUs are processed first (set inputs -> doStep -> get outputs) so that
       their discrete outputs are fresh when the ME solver runs. This ensures a
       discrete level coupled into an ME reset is applied on a single clean edge. */
    for (unsigned int i = 0; i < container->nb_cs; i += 1) {
        fmu_t *fmu = container->cs_fmu[i];

        status = fmu_set_inputs(fmu);
        if (status != FMU_STATUS_OK) {
            LOGGER_ERROR("Container: FMU '%s' failed set inputs.", fmu->name);
            return status;
        }

        /* COMPUTATION */

        status = fmuDoStep(fmu, container->time, container->next_step);
        if (status != FMU_STATUS_OK)
            return status;
        container->need_event_update |= fmu->need_event_udpate;

        status = fmu_get_outputs(fmu);
        if (status != FMU_STATUS_OK) {
            LOGGER_ERROR("Container: FMU '%s' failed getting outputs.", fmu->name);
            return status;
        }
    }

    /* Push only the continuous (real) inputs to every ME FMU before the
       collective integration. Discrete inputs (e.g. a bounce "reset" flag) must
       not be set in Continuous Time Mode: that corrupts the target FMU's edge
       detection (FMI-2.0 2.1.3). They are exchanged in Event Mode by
       solver_event_iteration()/container_update_discrete_state(). */
    for (size_t i = 0; i < container->solver->nb_me; i += 1) {
        fmu_t *fmu = container->solver->me[i].fmu;
        status = fmu_set_continuous_inputs(fmu);
        if (status != FMU_STATUS_OK) {
            LOGGER_ERROR("Container: FMU '%s' failed set inputs.", fmu->name);
            return status;
        }
    }

    /* Advance every ME FMU in a single Euler loop so their couplings stay
       consistent within the communication step. */
    status = solver_do_step(container->solver, container->time, container->next_step);
    if (status != FMU_STATUS_OK)
        return status;

    /* Read ME outputs. */
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


static fmu_status_t container_do_one_step_parallel_mt(container_t* container) {
    const logger_t *logger = &container->logger;
    fmu_status_t status = FMU_STATUS_OK;

    container->need_event_update = false;

    /* Set inputs for CS FMUs (worker threads will do the doStep). */
    for (unsigned int i = 0; i < container->nb_cs; i += 1) {
        fmu_t* fmu = container->cs_fmu[i];
        status = fmu_set_inputs(fmu);
        if (status != FMU_STATUS_OK) {
            LOGGER_ERROR("Container: FMU '%s' failed setting inputs. %d", fmu->name, fmu->status);
            return status;
        }
    }

    /* Step the CS FMUs first (worker threads run them in parallel), so their
       discrete outputs are fresh when the ME solver runs. This matches the mono
       mode ordering and delivers a discrete level coupled into an ME reset on a
       single clean edge. */
    thread_barrier_wait(&container->barrier_start); /* 1st SYNC point */
    /*
     * Each CS FMU worker thread will compute its step.
     * The main thread waits for all workers.
     */
    thread_barrier_wait(&container->barrier_end); /* 2nd SYNC point */

    for (unsigned int i = 0; i < container->nb_cs; i += 1) {
        fmu_t* fmu = container->cs_fmu[i];
        if (fmu->status != FMU_STATUS_OK)
            return FMU_STATUS_ERROR;
        container->need_event_update |= fmu->need_event_udpate;

        status = fmu_get_outputs(fmu);
        if (status != FMU_STATUS_OK) {
            LOGGER_ERROR("Container: FMU '%s' failed getting outputs.", fmu->name);
            return status;
        }
    }

    /* Advance ME FMUs collectively on the main thread, now that CS outputs are
       fresh. Only continuous inputs are pushed here; discrete inputs must not be
       set in Continuous Time Mode (FMI-2.0 2.1.3) and are exchanged in Event
       Mode. */
    for (size_t i = 0; i < container->solver->nb_me; i += 1) {
        fmu_t *fmu = container->solver->me[i].fmu;
        status = fmu_set_continuous_inputs(fmu);
        if (status != FMU_STATUS_OK) {
            LOGGER_ERROR("Container: FMU '%s' failed setting inputs.", fmu->name);
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


static fmu_status_t container_do_one_step_parallel(container_t* container) {
    const logger_t *logger = &container->logger;
    fmu_status_t status = FMU_STATUS_OK;

    /* STEP MODE */
    container->need_event_update = false;

    /* CS FMUs are stepped first (set inputs -> doStep -> get outputs) so their
       discrete outputs are fresh when the ME solver runs. This delivers a
       discrete level coupled into an ME reset on a single clean edge. */
    for (unsigned int i = 0; i < container->nb_cs; i += 1) {
        status = fmu_set_inputs(container->cs_fmu[i]);
        if (status != FMU_STATUS_OK) {
            LOGGER_ERROR("Container: FMU '%s' failed set inputs.", container->cs_fmu[i]->name);
            return status;
        }
    }
    for (unsigned int i = 0; i < container->nb_cs; i += 1) {
        fmu_t* fmu = container->cs_fmu[i];
        status = fmuDoStep(fmu, container->time, container->next_step);
        if (status != FMU_STATUS_OK) {
            LOGGER_ERROR("Container: FMU '%s' failed doStep.", fmu->name);
            return status;
        }
        container->need_event_update |= fmu->need_event_udpate;
    }
    for (unsigned int i = 0; i < container->nb_cs; i += 1) {
        status = fmu_get_outputs(container->cs_fmu[i]);
        if (status != FMU_STATUS_OK) {
            LOGGER_ERROR("Container: FMU '%s' failed get outputs.", container->cs_fmu[i]->name);
            return status;
        }
    }

    /* Advance all ME FMUs together. Only continuous inputs are pushed here;
       discrete inputs must not be set in Continuous Time Mode (it corrupts the
       target FMU's edge detection, FMI-2.0 2.1.3) and are exchanged in Event
       Mode by solver_event_iteration()/container_update_discrete_state(). */
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
            LOGGER_ERROR("Container: FMU '%s' failed get outputs.", fmu->name);
            return status;
        }
    }

    return status;
}


/*----------------------------------------------------------------------------
                         F M U   R E S E T
----------------------------------------------------------------------------*/

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

    LOGGER_DEBUG("[DEBUG] time=%e | Reset FMU '%s'", container->time, fmu->name);

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




fmu_status_t container_do_step(container_t* container, double currentCommunicationPoint, double communicationStepSize) {
    const logger_t *logger = &container->logger;
#ifdef DEBUG
    LOGGER_DEBUG("[DEBUG] time=%e | container_do_step(%e, %e)", container->time, currentCommunicationPoint, communicationStepSize);
#endif
    fmu_status_t status = FMU_STATUS_OK;
    const double end_time = currentCommunicationPoint + communicationStepSize;

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
        while(! is_close(container, container->time, target_time)) {
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
                    I M P O R T E R   V A L U E S   C A C H E
----------------------------------------------------------------------------*/

/* Values set by the importer on the ports forwarded to embedded FMUs: they are set again after the reset of an
   FMU. Returns 0, or -1 if a value cannot be stored. */




/*----------------------------------------------------------------------------
                 R E A D   C O N F I G U R A T I O N
----------------------------------------------------------------------------*/

#define CONFIG_ERROR(message, ...)                                          \
    config_file_error(file, __LINE__, message __VA_OPT__(,) __VA_ARGS__) 

#define CONFIG_GETLINE                                                      \
    if (get_line(file)) {                                                   \
        CONFIG_ERROR("Cannot read config data.");                           \
        return -1;                                                          \
    }

#define CONFIG_ALLOC(ptr, nb_elem)                                          \
    ptr = calloc(nb_elem, sizeof(*ptr));                                    \
    if (! ptr) {                                                            \
        CONFIG_ERROR("Virtual memory exhaust. (" #ptr ")");                 \
        return -2;                                                          \
    }


/*
 * # Version 7
 */
static int read_version(config_file_t* file) {
    int version;

    if (config_file_version(file, &version)) {
        CONFIG_ERROR("container.txt has no format version header: the container was built by an incompatible "
                     "version of FMU Manipulation Toolbox.");
        return -1;
    }

    if (version != CONTAINER_TXT_VERSION) {
        CONFIG_ERROR("container.txt format version %d, this runtime reads version %d: build the container again "
                     "with the version of FMU Manipulation Toolbox that provides this runtime.",
                     version, CONTAINER_TXT_VERSION);
        return -2;
    }

    return 0;
}


/*
 * # Container flags <MT> <Profiling> <Sequential>
 * 1 0 0 
 */
static int read_flags(container_t* container, config_file_t* file) {
    const logger_t *logger = &container->logger;
    int mt, sequential;

    CONFIG_GETLINE;
    if (sscanf(file->line, "%d %d %d", &mt, &container->profiling, &sequential) < 3) {
        CONFIG_ERROR("Cannot read container flags.");
        return -1;
    }
    
    if (sequential) {
        LOGGER_WARNING("Container use SEQUENTIAL mode.");
        container->do_step = container_do_one_step_sequential;
    } else {
        if (mt) {
            LOGGER_WARNING("Container use PARALLEL mode with MULTI thread");
            container->do_step = container_do_one_step_parallel_mt;
            container->mt = true;
        } else {
            LOGGER_WARNING("Container use PARALLEL mode with MONO thread.");
            container->do_step = container_do_one_step_parallel;
        }
    }

    if (container->profiling)
        LOGGER_WARNING("Container use PROFILING");

    return 0;
}


/*
 * # Internal time step in seconds
 * .001
 */
static int read_conf_time_step(container_t* container, config_file_t* file) {
    const logger_t *logger = &container->logger;
    CONFIG_GETLINE;
    if (config_line_to_host_decimal_point(file) || sscanf(file->line, "%le", &container->time_step) < 1) {
        CONFIG_ERROR("Cannot read time_step.");
        return -1;
    }

    /*
     * paranoid check: time_step should be greater than tolerance to avoid rounding issues.
     */
    if (container->time_step < container->tolerance) {
        CONFIG_ERROR("Invalid time_step value: %e", container->time_step);
        return -1;
    }

    LOGGER_DEBUG("Container time_step = %es", container->time_step);

    return 0;
}


/*
 * # NB of embedded FMU's: <nb_fmu_cs> <nb_fmu_me>
 * 2 1
 * # CS entries: <filename> <fmi_version> <has_event_mode> <has_configuration_mode> / <identifier> / <guid>
 * scalar2array.fmu 3 1 0
 * vec
 * {121d828d-d4dd-3c76-8227-7be1b268a801}
 * array2scalar.fmu 3 1 0
 * array
 * {e092864e-3b8e-7e1d-a4bf-ee0e4c648539}
 * # ME entries: <filename> <fmi_version> <nx> <nz> <has_configuration_mode> / <identifier> / <guid>
 * bouncing_ball.fmu 2 2 1 0
 * bb
 * {3f2a1c4e-6b8d-4f1a-9c7e-2d5b8a0f3e91}
 */

/* Returns -1 when the FMU could not be loaded (caller drops the whole array),
   -2 on a config syntax error. */
static int read_conf_one_fmu(container_t *container, const char *dirname, config_file_t *file,
                             int index, fmu_kind_t kind) {
    const bool is_me = (kind == FMU_KIND_ME);
    char directory[CONFIG_FILE_SZ];
    const int directory_len = snprintf(directory, CONFIG_FILE_SZ, "%s/%02x", dirname, index);
    if (directory_len < 0 || directory_len >= CONFIG_FILE_SZ) {
        CONFIG_ERROR("Path of the directory of FMU#%d is too long.", index);
        return -1;
    }

    CONFIG_GETLINE;
    char *name = strdup(file->line);
    if (!name) {
        CONFIG_ERROR("Virtual memory exhaust. (FMU name)");
        return -1;
    }
    int fmi_version = 2;
    int support_event = 0;
    int has_configuration_mode = 0;
    size_t nx = 0;
    size_t nz = 0;
    

    char *flags = strchr(name, ' ');
    if (flags)
        *flags++ = '\0';
    else {
        CONFIG_ERROR("Cannot read the flags of FMU '%s'.", name);
        free(name);
        return -1;
    }

    if (kind == FMU_KIND_CS) {
        /* "<filename> <fmi_version> <has_event_mode> <has_configuration_mode>": ME entries have no event flag. */
        if (sscanf(flags, "%d %d %d", &fmi_version, &support_event, &has_configuration_mode) < 3) {
            CONFIG_ERROR("Cannot read CS flags from FMU '%s'.", name);
            free(name);
            return -2;
        }
    } else {
        /* "<filename> <fmi_version> <nx> <nz> <has_configuration_mode>": ME entries carry nb continuous
           states and event indicators on the same line as the filename. */
        if (sscanf(flags, "%d %zu %zu %d", &fmi_version, &nx, &nz, &has_configuration_mode) < 4) {
            CONFIG_ERROR("Cannot read ME sizes (nb_states nb_event_indicators) for FMU '%s'.", name);
            free(name);
            return -2;
        }
    }
    if (has_configuration_mode && fmi_version != 3) {
        CONFIG_ERROR("FMU '%s': only an FMI-3.0 FMU has a Configuration Mode.", name);
        free(name);
        return -2;
    }

    if (get_line(file)) {
        CONFIG_ERROR("Cannot read config data.");
        free(name);
        return -1;
    }
    char *identifier = strdup(file->line);

    if (get_line(file)) {
        CONFIG_ERROR("Cannot read config data.");
        free(identifier);
        free(name);
        return -1;
    }
    char *guid = strdup(file->line); /* saved because next get_line would overwrite file->line */
    if (!identifier || !guid) {
        CONFIG_ERROR("Virtual memory exhaust. (FMU identifier)");
        free(guid);
        free(identifier);
        free(name);
        return -1;
    }


    int status = fmu_load_from_directory(container, index, directory, name, identifier, guid,
                                         fmi_version, support_event, kind);
    free(guid);
    free(identifier);
    free(name);

    /* on a failure, the slot is released here: container_free() only releases the FMUs fully loaded */
    if (status) {
        CONFIG_ERROR("Cannot load FMU from directory '%s' (status=%d).", directory, status);
        fmu_unload(&container->fmu[index]);
        return -1;
    }

    container->fmu[index].has_configuration_mode = has_configuration_mode != 0;
    if (has_configuration_mode && (!container->fmu[index].fmi_functions.version_3.fmi3EnterConfigurationMode ||
                                   !container->fmu[index].fmi_functions.version_3.fmi3ExitConfigurationMode)) {
        CONFIG_ERROR("FMU '%s' has no API of the Configuration Mode.", container->fmu[index].name);
        fmu_unload(&container->fmu[index]);
        return -1;
    }

    if (is_me && solver_register_me(container->solver, index, nx, nz)) {
        CONFIG_ERROR("Cannot register ME dimensions for FMU '%s'.", container->fmu[index].name);
        fmu_unload(&container->fmu[index]);
        return -1;
    }

    return 0;
}


/*
 * # Initialization order of the embedded FMU's
 * <index> <index> ...      (every index of fmu[] once)
 */
static int read_conf_init_order(container_t *container, config_file_t *file) {
    CONFIG_GETLINE;
    CONFIG_ALLOC(container->init_order, container->nb_fmu > 0 ? container->nb_fmu : 1);

    const char *cursor = file->line;
    for (int i = 0; i < container->nb_fmu; i += 1) {
        char *end;
        const long index = strtol(cursor, &end, 10);
        if ((end == cursor) || (index < 0) || (index >= container->nb_fmu)) {
            CONFIG_ERROR("Cannot read the %dth index of the initialization order.", i);
            return -1;
        }
        for (int j = 0; j < i; j += 1) {
            if (container->init_order[j] == (int)index) {
                CONFIG_ERROR("FMU#%ld is twice in the initialization order.", index);
                return -1;
            }
        }
        container->init_order[i] = (int)index;
        cursor = end;
    }
    return 0;
}


static int read_conf_fmu(container_t *container, const char *dirname, config_file_t* file) {
    const logger_t *logger = &container->logger;
    int nb_cs, nb_me;

    CONFIG_GETLINE;
    if (sscanf(file->line, "%d %d", &nb_cs, &nb_me) < 2 || nb_cs < 0 || nb_me < 0) {
        CONFIG_ERROR("Cannot read number of embedded FMUs (<nb_fmu_cs> <nb_fmu_me>).");
        return -1;
    }

    const int nb_fmu = nb_cs + nb_me;
    LOGGER_DEBUG("%d FMUs to be loaded (%d CS, %d ME).", nb_fmu, nb_cs, nb_me);
    if (!nb_fmu) {
        container->fmu = NULL;
        return 0;
    }

    CONFIG_ALLOC(container->fmu, nb_fmu);

    /* CS entries come first, then ME entries. */
    for (int i = 0; i < nb_fmu; i += 1) {
        const fmu_kind_t kind = (i < nb_cs) ? FMU_KIND_CS : FMU_KIND_ME;
        const int status = read_conf_one_fmu(container, dirname, file, i, kind);
        if (status)
            return status;  /* container_free() releases the FMUs 0 to i-1 */

        container->nb_fmu = i + 1;  /* in case of error, free only loaded FMU */
    }

    return 0;
}


/*
 * # NB local variables: real64, real32, integer8, uinteger8, integer16, uinteger16, integer32, uinteger32, integer64, uinteger64, boolean, boolean1, string, binary, clock
 * 3 0 0 0 0 0 1 0 0 0 0 0 0 0 0
 */
static int read_conf_local(container_t* container, config_file_t* file) {
    CONFIG_GETLINE;
    if (sscanf(file->line, "%lu %lu %lu %lu %lu %lu %lu %lu %lu %lu %lu %lu %lu %lu %lu",
        &container->reals64.nb_locals,
        &container->reals32.nb_locals,
        &container->integers8.nb_locals,
        &container->uintegers8.nb_locals,
        &container->integers16.nb_locals,
        &container->uintegers16.nb_locals,
        &container->integers32.nb_locals,
        &container->uintegers32.nb_locals,
        &container->integers64.nb_locals,
        &container->uintegers64.nb_locals,
        &container->booleans.nb_locals,
        &container->booleans1.nb_locals,
        &container->strings.nb_locals,
        &container->binaries.nb_locals,
        &container->clocks.nb_locals) < 15) {
            CONFIG_ERROR("Cannot read number of local variables.");
        return -1;
    }

#define ALLOC(variable, fmi_type, c_type)                                                       \
    if (container-> variable .nb_locals) {                                                     \
        CONFIG_ALLOC(container-> variable .locals, container-> variable .nb_locals);                   \
        for(unsigned long i=0; i < container-> variable .nb_locals; i += 1)                    \
            container-> variable .locals [i] = (c_type)0;                                               \
    } else                                                                                      \
        container-> variable .locals = NULL;
    
    FOR_ALL_NUMERIC_TYPES(ALLOC)

    /* Strings cannot be NULL */
    if (container->strings.nb_locals) {
        CONFIG_ALLOC(container->strings.locals, container->strings.nb_locals);
        for (unsigned long i = 0; i < container->strings.nb_locals; i += 1) {
            if (fmu_string_copy(&container->strings.locals[i], "")) {
                CONFIG_ERROR("Virtual memory exhaust. (local strings)");
                return -2;
            }
        }
    } else
        container->strings.locals = NULL;

    /* Binaries have a complex type */
    if (container->binaries.nb_locals) {
        CONFIG_ALLOC(container->binaries.locals, container->binaries.nb_locals);
        for(unsigned long i=0; i < container->binaries.nb_locals; i += 1) {
            container->binaries.locals[i].size = 0;
            container->binaries.locals[i].max_size = 0;
            container->binaries.locals[i].data = NULL;
        }
    } else
        container->binaries.locals = NULL;

    ALLOC(clocks, Clock, bool)
#undef ALLOC

    return 0;
}


/*
 * # CONTAINER I/O: <VR> <DIM> <NB> <FMU_INDEX> <FMU_VR> [<FMU_INDEX> <FMU_VR>]
 * # Real
 * 3 3
 * 1 1 1 0 1
 * 2 1 1 1 0
 * 0 1 1 -1 0
 * # Integer
 * 0 0
 * # Boolean
 * 1 1
 * 0 1 1 -1 0
 * # String
 * 0 0
 */
static int read_conf_io(container_t* container, config_file_t* file) {
    unsigned long nb_links;

#define READ_CONF_IO(variable, fmi_type, c_type)                                                                \
    CONFIG_GETLINE;                                                                                             \
    if (sscanf(file->line, "%lu %lu", &container-> variable .nb_ports, &nb_links) < 2) {                      \
        CONFIG_ERROR("Cannot read container I/O " #variable ".");                                               \
        return -1;                                                                                              \
    }                                                                                                           \
    if (container-> variable .nb_ports > 0) {                                                                 \
        CONFIG_ALLOC(container-> variable .links, nb_links);                                                     \
        CONFIG_ALLOC(container-> variable .ports, container-> variable .nb_ports);                           \
                                                                                                                \
        unsigned long vr_counter = 0;                                                                           \
        for (unsigned long i = 0; i < container-> variable .nb_ports; i += 1) {                               \
            container_port_t port;                                                                              \
            fmu_vr_t vr;                                                                                        \
            int offset;                                                                                         \
                                                                                                                \
            CONFIG_GETLINE;                                                                                     \
            if (sscanf(file->line, "%u %lu %lu%n", &vr, &port.dimension, &port.nb, &offset) < 3) {              \
                CONFIG_ERROR("Cannot read container I/O " #variable " %luth details.", i);                      \
                return -1;                                                                                      \
            }                                                                                                   \
            port.links = &container-> variable .links [vr_counter];                                              \
            port.cache.offset = CONTAINER_NO_CACHE;                                                             \
            port.cache.nb = 0;                                                                                 \
            port.cache.deferred = false;                                                                              \
            for(unsigned long j=0; j < port.nb; j += 1) {                                                       \
                int read;                                                                                       \
                long fmu_id;                                                                                    \
                fmu_vr_t fmu_vr;                                                                                \
                if (vr_counter >= nb_links) {                                                                   \
                    CONFIG_ERROR("Read %lu links for %lu expected.", vr_counter, nb_links);                     \
                    return -1;                                                                                  \
                }                                                                                               \
                                                                                                                \
                if (sscanf(file->line+offset, " %ld %u%n", &fmu_id, &fmu_vr, &read) < 2) {                      \
                    CONFIG_ERROR("Cannot read container I/O " #variable " link details.");                      \
                    return -1;                                                                                  \
                }                                                                                               \
                if (fmu_id < 0) {   /* local (-1) or profiling (-2) variable: the values from fmu_vr */         \
                    if (fmu_id < -2 || fmu_vr + port.dimension > container-> variable .nb_locals) {            \
                        CONFIG_ERROR("Container I/O " #variable ": local variable %u (dimension %lu) is out of "\
                                     "range.", fmu_vr, port.dimension);                                         \
                        return -8;                                                                              \
                    }                                                                                           \
                } else if (fmu_id >= container->nb_fmu) {                                                       \
                    CONFIG_ERROR("Container I/O " #variable ": FMU index %ld is out of range.", fmu_id);        \
                    return -8;                                                                                  \
                }                                                                                               \
                container-> variable .links [vr_counter].fmu_id = (unsigned long)fmu_id;                         \
                container-> variable .links [vr_counter].fmu_vr = fmu_vr;                                        \
                container-> variable .links [vr_counter].cache.in_set = false;                                   \
                container-> variable .links [vr_counter].cache.start_reset = -1;                                 \
                offset += read;                                                                                 \
                vr_counter += 1;                                                                                \
            }                                                                                                   \
            vr &= 0xFFFFFF;                                                                                     \
            if (vr < container-> variable .nb_ports)                                                          \
                container-> variable .ports[vr] = port;                                                        \
            else {                                                                                              \
                CONFIG_ERROR("Container I/O " #variable ": port %u is out of range.", vr);                      \
                return -8;                                                                                      \
            }                                                                                                   \
        }                                                                                                       \
    } else {                                                                                                    \
        container-> variable .links = NULL;                                                                      \
        container-> variable .ports = NULL;                                                                    \
    }

    FOR_ALL_NUMERIC_TYPES(READ_CONF_IO)
    READ_CONF_IO(strings, String, char *)
    READ_CONF_IO(binaries, Binary, fmu_binary_t)
    READ_CONF_IO(clocks, Clock, bool)
#undef READ_CONF_IO


    return 0;
}



/*
 * # Inputs of array2scalar.fmu - real64: <VR> <DIM> <FMU_VR>
 * 1
 * 1 2 0
 *
 * or
 * 
 * # Outputs of scalar2array.fmu - real64: <VR> <DIM> <FMU_VR>
 * 1
 * 1 2 1
 */
#define READER_FMU_IO(type, causality)                                                              \
    fmu_io-> type . causality .translations = NULL;                                                 \
                                                                                                    \
    CONFIG_GETLINE;                                                                                 \
    if (sscanf(file->line, "%lu", &fmu_io-> type . causality .nb) < 1) {                            \
        CONFIG_ERROR("Cannot read FMU I/O number'" #type "' (" #causality ").");                    \
        return -2;                                                                                  \
    }                                                                                               \
                                                                                                    \
    if (fmu_io-> type . causality .nb > 0) {                                                        \
        CONFIG_ALLOC(fmu_io-> type . causality .translations, fmu_io-> type . causality .nb);       \
                                                                                                    \
        for(unsigned long i = 0; i < fmu_io-> type . causality .nb; i += 1) {                       \
            CONFIG_GETLINE;                                                                         \
            if (sscanf(file->line, "%u %u %u",                                                      \
                &fmu_io-> type . causality .translations[i].vr,                                     \
                &fmu_io-> type . causality .translations[i].dimension,                              \
                &fmu_io-> type . causality .translations[i].fmu_vr) < 3) {                          \
                CONFIG_ERROR("Cannot read FMU %luth I/O for '" #type "' (" #causality ").", i);     \
                return -5;                                                                          \
            }                                                                                       \
            fmu_io-> type . causality .translations[i].vr &= 0xFFFFFF;                              \
            if (fmu_io-> type . causality .translations[i].vr + fmu_io-> type . causality .translations[i].dimension \
                > container-> type .nb_locals) {                                                   \
                CONFIG_ERROR("FMU %luth I/O for '" #type "' (" #causality "): local variable %u is out of range.", \
                             i, fmu_io-> type . causality .translations[i].vr);                     \
                return -5;                                                                          \
            }                                                                                       \
        }                                                                                           \
    }

#define READER_FMU_CLOCKED_IO(type, causality)                                                                      \
    fmu_io->clocked_ ## type . causality = NULL;                                                                    \
                                                                                                                    \
    CONFIG_GETLINE;                                                                                                 \
    if (sscanf(file->line, "%lu %lu",                                                                               \
               &fmu_io->clocked_ ## type .nb_ ## causality,                                                         \
               &nb_clocked) < 2) {                                                                                  \
        CONFIG_ERROR("Cannot read FMU clocked I/O for '" #type "' (" #causality ").");                              \
        return -2;                                                                                                  \
    }                                                                                                               \
                                                                                                                    \
    if (fmu_io->clocked_ ## type .nb_ ## causality > 0) {                                                           \
        CONFIG_ALLOC(fmu_io->clocked_ ## type .causality, fmu_io->clocked_ ## type .nb_ ## causality);              \
                                                                                                                    \
        for(unsigned long i = 0; i < fmu_io->clocked_ ## type .nb_ ## causality; i += 1) {                          \
            int offset = 0;                                                                                         \
                                                                                                                    \
            CONFIG_GETLINE;                                                                                         \
            if (sscanf(file->line, "%u %lu%n",                                                                      \
                &fmu_io->clocked_ ## type . causality [i].clock_vr,                                                 \
                &fmu_io->clocked_ ## type . causality [i].translations_list.nb, &offset) < 2) {                     \
                CONFIG_ERROR("Cannot read FMU %luth clocked I/O for '" #type "' (" #causality ").", i);             \
                return -5;                                                                                          \
            }                                                                                                       \
            fmu_io->clocked_ ## type . causality [i].clock_vr &= 0xFFFFFF;                                          \
            if (fmu_io->clocked_ ## type . causality [i].clock_vr >= container->clocks.nb_locals) {                  \
                CONFIG_ERROR("FMU %luth clocked I/O for '" #type "' (" #causality "): clock %u is out of range.", i,\
                             fmu_io->clocked_ ## type . causality [i].clock_vr);                                    \
                return -5;                                                                                          \
            }                                                                                                       \
            CONFIG_ALLOC(fmu_io->clocked_ ## type . causality [i].translations_list.translations,                   \
                         fmu_io->clocked_ ## type . causality [i].translations_list.nb);                            \
            for(unsigned long j = 0; j < fmu_io->clocked_ ## type . causality [i].translations_list.nb; j += 1) {   \
                int read = 0;                                                                                       \
                if (sscanf(file->line + offset, "%u %u %u%n",                                                       \
                    &fmu_io->clocked_ ## type . causality [i].translations_list.translations[j].vr,                 \
                    &fmu_io->clocked_ ## type . causality [i].translations_list.translations[j].dimension,          \
                    &fmu_io->clocked_ ## type . causality [i].translations_list.translations[j].fmu_vr,             \
                    &read) < 3) {                                                                                   \
                    CONFIG_ERROR("Cannot interpret FMU %luth clocked I/O for '" #type "' (" #causality ").", i);    \
                    return -5;                                                                                      \
                }                                                                                                   \
                offset += read;                                                                                     \
                fmu_io->clocked_ ## type . causality [i].translations_list.translations[j].vr &= 0xFFFFFF;          \
                if (fmu_io->clocked_ ## type . causality [i].translations_list.translations[j].vr                   \
                    + fmu_io->clocked_ ## type . causality [i].translations_list.translations[j].dimension          \
                    > container-> type .nb_locals) {                                                               \
                    CONFIG_ERROR("FMU %luth clocked I/O for '" #type "' (" #causality "): local variable is out of "\
                                 "range.", i);                                                                      \
                    return -5;                                                                                      \
                }                                                                                                   \
            }                                                                                                       \
        }                                                                                                           \
    }



static int read_conf_fmu_io_in(const container_t *container, fmu_io_t* fmu_io, config_file_t* file) {
    unsigned long nb_clocked;

#define READER_FMU_IN(variable, fmi_type, c_type)   \
    READER_FMU_IO(variable, in)                     \
    READER_FMU_CLOCKED_IO(variable, in)

    FOR_ALL_NUMERIC_TYPES(READER_FMU_IN)
    READER_FMU_IN(strings, String, char *)
    READER_FMU_IN(binaries, Binary, fmu_binary_t)
    READER_FMU_IO(clocks, in) /* clock variables cannot be clocked ! */

#undef READER_FMU_IN

    return 0;
}


static int read_conf_fmu_io_out(const container_t *container, fmu_io_t* fmu_io, config_file_t* file) {
    unsigned long nb_clocked;

#define READER_FMU_OUT(variable, fmi_type, c_type)   \
    READER_FMU_IO(variable, out)                     \
    READER_FMU_CLOCKED_IO(variable, out)

    FOR_ALL_NUMERIC_TYPES(READER_FMU_OUT)
    READER_FMU_OUT(strings, String, char *)
    READER_FMU_OUT(binaries, Binary, fmu_binary_t)
    READER_FMU_IO(clocks, out) /* clock variables cannot be clocked ! */

#undef READER_FMU_OUT

    return 0;
}
#undef READER_FMU_IO


static int read_conf_fmu_start_values_booleans1(fmu_io_t* fmu_io, config_file_t* file) {
    unsigned long nb;
    unsigned long pos = 0;

    fmu_io->start_booleans1.start_values = NULL;
    fmu_io->start_booleans1.nb = 0;

    CONFIG_GETLINE;    
    if (sscanf(file->line, "%lu %lu", &fmu_io->start_booleans1.nb, &nb) < 2) {
        CONFIG_ERROR("Cannot read number of 'boolean1' start values.");
        return -2;
    }
                
    if (fmu_io->start_booleans1.nb == 0)
        return 0;
    
    CONFIG_ALLOC(fmu_io->start_booleans1.start_values, fmu_io->start_booleans1.nb);
    CONFIG_ALLOC(fmu_io->start_values_booleans1, nb);
 
    for (unsigned long i = 0; i < fmu_io->start_booleans1.nb; i += 1) {
        unsigned int dimension;
        int offset;

        CONFIG_GETLINE;
        if (sscanf(file->line, "%u %u %d%n",
            &fmu_io->start_booleans1.start_values[i].vr,
            &dimension,
            &fmu_io->start_booleans1.start_values[i].reset,
            &offset) < 3) {
            CONFIG_ERROR("Cannot read  %luth start value.", i);
            return -4;
        }
        fmu_io->start_booleans1.start_values[i].dimension = dimension;
        fmu_io->start_booleans1.start_values[i].value = &fmu_io->start_values_booleans1[pos];
        for(unsigned int j = 0; j < dimension; j += 1) {
            int read;
            int boolean;

            if (pos >= nb) {
                CONFIG_ERROR("Too many start values.");
                return -6;
            }
            if (sscanf(file->line + offset, "%d %n",
                &boolean, &read) < 1) {
                CONFIG_ERROR("Cannot decode %luth start value.", i);
                return -5;
            }
            fmu_io->start_values_booleans1[pos] = boolean;
            pos += 1;
            offset += read;
        }
    }

    return 0;
}


static int read_conf_fmu_start_values_strings(fmu_io_t* fmu_io, config_file_t* file) {
    unsigned long nb;
    unsigned long pos = 0;
    
    fmu_io->start_strings.start_values = NULL;
    fmu_io->start_strings.nb = 0;
    
    CONFIG_GETLINE;
    if (sscanf(file->line, "%lu %lu", &fmu_io->start_strings.nb, &nb) < 2) {
        CONFIG_ERROR("Cannot read number of 'strings' start values.");
        return -2;
    }
                
    if (fmu_io->start_strings.nb == 0)
        return 0;
    
    CONFIG_ALLOC(fmu_io->start_strings.start_values, fmu_io->start_strings.nb);
    CONFIG_ALLOC(fmu_io->start_values_strings, nb);
    fmu_io->nb_start_values_strings = nb;

    for (unsigned long i = 0; i < fmu_io->start_strings.nb; i += 1) {
        unsigned int dimension;
        
        CONFIG_GETLINE;
        if (sscanf(file->line, "%u %u %d", 
            &fmu_io->start_strings.start_values[i].vr, 
            &dimension, 
            &fmu_io->start_strings.start_values[i].reset) < 3) {
            CONFIG_ERROR("Cannot read %luth start value.", i);
            return -5;
        }
        fmu_io->start_strings.start_values[i].dimension = dimension;
        fmu_io->start_strings.start_values[i].value = &fmu_io->start_values_strings[pos];
        for(unsigned long j = 0; j < dimension; j += 1) {
            if (pos >= nb) {
                CONFIG_ERROR("Too many start values.");
                return -6;
            }
            CONFIG_GETLINE;
            fmu_io->start_values_strings[pos] = strdup(file->line);
            if (!fmu_io->start_values_strings[pos]) {
                CONFIG_ERROR("Cannot allocate memory for a start value.");
                return -6;
            }
            pos += 1;
        }
    }

    return 0;
}


/*
 * # Start values of bb_velocity.fmu - Real: <FMU_VR> <DIM> <RESET> <VALUE> [, <VALUE>]
 * 0
 */
static int read_conf_fmu_start_values(fmu_io_t* fmu_io, config_file_t* file) {
    int status;
    unsigned long nb;
    unsigned long pos;
    
#define READER_FMU_START_VALUES(type, format)                                                       \
    pos = 0;                                                                                        \
                                                                                                    \
    fmu_io->start_ ## type .start_values = NULL;                                                    \
    fmu_io->start_ ## type .nb = 0;                                                                 \
                                                                                                    \
    CONFIG_GETLINE;                                                                                 \
    if (sscanf(file->line, "%lu %lu", &fmu_io->start_ ## type .nb, &nb) < 2) {                      \
        CONFIG_ERROR("Cannot read number of start values.");                                        \
        return -2;                                                                                  \
    }                                                                                               \
                                                                                                    \
    if (fmu_io->start_ ## type .nb > 0) {                                                           \
        CONFIG_ALLOC(fmu_io->start_ ## type .start_values,fmu_io->start_ ## type .nb);              \
        CONFIG_ALLOC(fmu_io->start_values_ ## type, nb);                                            \
                                                                                                    \
        for (unsigned long i = 0; i < fmu_io->start_ ## type .nb; i += 1) {                         \
            int offset;                                                                             \
            unsigned int dimension;                                                                 \
                                                                                                    \
            CONFIG_GETLINE;                                                                         \
            if (config_line_to_host_decimal_point(file)) {                                          \
                CONFIG_ERROR("Cannot read %luth start value.", i);                                  \
                return -5;                                                                          \
            }                                                                                       \
            if (sscanf(file->line, "%u %u %d%n",                                                    \
                       &fmu_io->start_ ## type .start_values[i].vr,                                 \
                       &dimension,                                                                  \
                       &fmu_io->start_ ## type .start_values[i].reset,                              \
                       &offset) < 3) {                                                              \
                CONFIG_ERROR("Cannot read %luth start value.", i);                                  \
                return -5;                                                                          \
            }                                                                                       \
            fmu_io->start_ ##type .start_values[i].dimension = dimension;                           \
            fmu_io->start_ ##type .start_values[i].value = &fmu_io->start_values_ ##type[pos];      \
            for(unsigned long j = 0; j < dimension; j += 1) {                                       \
                int read;                                                                           \
                                                                                                    \
                if (pos >= nb) {                                                                    \
                    CONFIG_ERROR("Too many start values.");                                         \
                    return -6;                                                                      \
                }                                                                                   \
                if (sscanf(file->line + offset, format "%n",                                        \
                           &fmu_io->start_values_ ## type[pos],                                     \
                           &read) < 1) {                                                            \
                    CONFIG_ERROR("Cannot decode %luth start value.", i);                            \
                    return -6;                                                                      \
                }                                                                                   \
                                                                                                    \
                pos += 1;                                                                           \
                offset += read;                                                                     \
            }                                                                                       \
        }                                                                                           \
    }

    READER_FMU_START_VALUES(reals64,     "%lf");
    READER_FMU_START_VALUES(reals32,     "%f");
    READER_FMU_START_VALUES(integers8,   "%" SCNd8);
    READER_FMU_START_VALUES(uintegers8,  "%" SCNu8);
    READER_FMU_START_VALUES(integers16,  "%" SCNd16);
    READER_FMU_START_VALUES(uintegers16, "%" SCNu16);
    READER_FMU_START_VALUES(integers32,  "%" SCNd32);
    READER_FMU_START_VALUES(uintegers32, "%" SCNu32);
    READER_FMU_START_VALUES(integers64,  "%" SCNd64);
    READER_FMU_START_VALUES(uintegers64, "%" SCNu64);
    READER_FMU_START_VALUES(booleans,    "%d");

#undef READER_FMU_START_VALUES

    status = read_conf_fmu_start_values_booleans1(fmu_io, file);
    if (status)
        return status;

    status = read_conf_fmu_start_values_strings(fmu_io, file);
    if (status)
        return status;

    return 0;
}
#undef READER_FMU_START_VALUE


static int read_conf_fmu_conversion(fmu_t *fmu, config_file_t* file) {
    unsigned long nb;

    CONFIG_GETLINE;
    if (sscanf(file->line, "%lu", &nb) < 1) {
        CONFIG_ERROR("Cannot read size of conversion table.");
        return -2;
    }

    fmu->conversions = convert_new(&fmu->container->logger, nb);
    if (nb && !fmu->conversions) {
        CONFIG_ERROR("Cannot allocate conversion table for %lu entries.", nb);
        return -3;
    }

    for(unsigned long i = 0; i < nb; i += 1) {
        int offset;
        fmu_vr_t from;
        fmu_vr_t to;

        CONFIG_GETLINE;
        if (sscanf(file->line, "%u %u %n", &from, &to, &offset) < 2) {
            CONFIG_ERROR("Cannot read conversion table %luth entry.", i);
            return -5;
        }
        fmu->conversions->entries[i].from = from & 0xFFFFFF;
        fmu->conversions->entries[i].to = to & 0xFFFFFF;

        fmu->conversions->entries[i].function = convert_function_get(file->line+offset);
        fmu->conversions->entries[i].to_real = convert_destination_real(file->line+offset);
        if (!fmu->conversions->entries[i].function) {
            CONFIG_ERROR("Cannot configure conversion %luth entry from '%s'", i, file->line+offset);
            return -6;
        }
        if (convert_check_range(fmu->container, file->line+offset, fmu->conversions->entries[i].from,
                                fmu->conversions->entries[i].to)) {
            CONFIG_ERROR("Conversion %luth entry '%s': local variable out of range.", i, file->line+offset);
            return -6;
        }
    }

    return 0;
}


/*
 * # Reset trigger of bb_velocity.fmu: <LOCAL_OFFSET>
 * -1
 */
static int read_conf_fmu_reset_trigger(fmu_t *fmu, config_file_t *file) {
    const container_t *container = fmu->container;

    CONFIG_GETLINE;
    if (sscanf(file->line, "%ld", &fmu->reset_trigger) < 1) {
        CONFIG_ERROR("Cannot read reset trigger.");
        return -1;
    }

    if (fmu->reset_trigger >= 0) {
        const unsigned long nb_local = (container->fmi_version == 2) ?
            container->booleans.nb_locals : container->booleans1.nb_locals;
        if ((unsigned long)fmu->reset_trigger >= nb_local) {
            CONFIG_ERROR("Reset trigger %ld is out of the local booleans storage.", fmu->reset_trigger);
            return -2;
        }
    }

    return 0;
}


static int read_conf_fmu_io(fmu_t* fmu, config_file_t* file) {

    if (read_conf_fmu_io_in(fmu->container, &fmu->fmu_io, file))
        return -1;

    if (read_conf_fmu_start_values(&fmu->fmu_io, file))
        return -2;

    if (read_conf_fmu_io_out(fmu->container, &fmu->fmu_io, file))
        return -3;

    if (read_conf_fmu_conversion(fmu, file))
        return -4;

    if (read_conf_fmu_reset_trigger(fmu, file))
        return -5;

    return 0;
}


static int clock_kind_from_name(const char *name, container_clock_kind_t *kind) {
    static const struct {
        const char              *name;
        container_clock_kind_t  kind;
    } kinds[] = {
        { "constant",   CONTAINER_CLOCK_CONSTANT },
        { "fixed",      CONTAINER_CLOCK_FIXED },
        { "tunable",    CONTAINER_CLOCK_TUNABLE },
        { "changing",   CONTAINER_CLOCK_CHANGING },
        { "countdown",  CONTAINER_CLOCK_COUNTDOWN }
    };

    for (size_t i = 0; i < sizeof(kinds) / sizeof(*kinds); i += 1) {
        if (strcmp(kinds[i].name, name) == 0) {
            *kind = kinds[i].kind;
            return 0;
        }
    }

    return -1;
}


static int read_conf_clocks(container_t *container, config_file_t *file) {
    CONFIG_GETLINE;
    if (sscanf(file->line, "%lu %lu", &container->clocks_list.nb_fmu, &container->clocks_list.nb_local_clocks) < 2) {
        CONFIG_ERROR("Cannot get size of clocks defintions table.");
        return -2;
    }
    if (container->clocks_list.nb_fmu) {
        CONFIG_ALLOC(container->clocks_list.clocks, container->clocks_list.nb_local_clocks);
        CONFIG_ALLOC(container->clocks_list.active, container->clocks.nb_locals);

        unsigned long pos = 0;
        for(unsigned long i = 0; i < container->clocks_list.nb_fmu; i += 1) {
            unsigned long fmu_id;
            unsigned long nb;
            int offset;

            CONFIG_GETLINE;
            if (config_line_to_host_decimal_point(file)) {
                CONFIG_ERROR("Cannot interpret %luth clock table entries.", i);
                return -5;
            }
            if (sscanf(file->line, "%lu %lu %n", &fmu_id, &nb, &offset) < 2) {
                CONFIG_ERROR("Cannot interpret %luth clock table entries.", i);
                return -5;
            }
            if (fmu_id >= (unsigned long)container->nb_fmu) {
                CONFIG_ERROR("Clock table: FMU index %lu is out of range.", fmu_id);
                return -5;
            }

            for(unsigned long j=0; j < nb; j += 1) {
                container_clock_t *clock;
                unsigned long local_clock_index;
                char kind[16];
                int read;

                if (pos >= container->clocks_list.nb_local_clocks) {
                    CONFIG_ERROR("Clock table: more than %lu clocks.", container->clocks_list.nb_local_clocks);
                    return -7;
                }
                clock = &container->clocks_list.clocks[pos];
                if (sscanf(file->line+offset, "%u %lu %15s %lf %lf %n",
                    &clock->fmu_vr,
                    &local_clock_index,
                    kind,
                    &clock->declared_interval,
                    &clock->declared_shift,
                    &read) < 5){
                    CONFIG_ERROR("Cannot interpret %luth clock table entries value #%lu", i, j);
                    return -7;
                }
                offset += read;
                local_clock_index &= 0xFFFFFF;
                if (local_clock_index >= container->clocks.nb_locals) {
                    CONFIG_ERROR("Clock table: clock %lu is out of range.", local_clock_index);
                    return -7;
                }
                if (clock_kind_from_name(kind, &clock->kind)) {
                    CONFIG_ERROR("Clock table: unknown clock variability '%s'.", kind);
                    return -7;
                }
                clock->local_vr = local_clock_index;
                clock->fmu_id = fmu_id;
                pos += 1;
            }
        }
    }
    
    return 0;
}


/*
 * The worker threads wait on threads_gate until every one of them is launched and the barriers are initialized
 * for them: when one cannot be launched, the gate is opened without barriers_ready and those already launched end.
 */
static int container_start_threads(container_t *container) {
    const logger_t *logger = &container->logger;
    if (!container->mt)
        return 0;

    if (thread_gate_init(&container->threads_gate)) {
        LOGGER_ERROR("Cannot initialize the start of the threads.");
        return -1;
    }
    container->threads_gate_ready = true;

    int status = 0;
    for (unsigned int i = 0; i < container->nb_cs; i += 1) {
        if (fmu_launch_thread(container->cs_fmu[i])) {
            LOGGER_ERROR("Cannot launch FMU '%s' thread.", container->cs_fmu[i]->name);
            status = -2;
            break;
        }
        container->nb_threads += 1;
    }

    if (!status) {
        LOGGER_DEBUG("Container barrier is configured with %u participants", container->nb_cs + 1);
        if (thread_barrier_init(&container->barrier_start, container->nb_cs + 1)) {
            LOGGER_ERROR("Cannot initialize thread barrier.");
            status = -1;
        } else if (thread_barrier_init(&container->barrier_end, container->nb_cs + 1)) {
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
        fmu_t *fmu = container->cs_fmu[i];
        LOGGER_DEBUG("Waiting for FMU '%s' thread to finish.", fmu->name);
        thread_join(fmu->thread);
        fmu->thread = NULL;
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


/* Value of a single hexadecimal digit, or -1 if it is not one. */
static int hex_digit(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}


/*
 * Convert an FMI resource location URI into a native filesystem directory.
 *
 * Per the FMI 2.0 standard, fmuResourceLocation is a URI following RFC 3986:
 * the "file://" scheme is stripped, the leading '/' before a Windows drive
 * letter is removed, and percent-encoded octets (e.g. "%20" -> ' ') are decoded.
 * The result is written into dest (of size bytes, always NUL-terminated).
 */
static void resource_location_to_path(const char *location, char *dest, size_t size) {
    const char *src;
    size_t i = 0;

    if (strncmp(location, "file://", 7) == 0)
        location += 7;

#ifdef _WIN32
    /* "file:///C:/..." -> drop the leading '/' before the drive letter. */
    if (location[0] == '/')
        location += 1;
#endif

    for (src = location; *src && i + 1 < size; ) {
        int hi, lo;
        if (src[0] == '%' && (hi = hex_digit(src[1])) >= 0 && (lo = hex_digit(src[2])) >= 0) {
            dest[i++] = (char)((hi << 4) | lo);
            src += 3;
        } else {
            dest[i++] = *src++;
        }
    }
    dest[i] = '\0';
}


int container_configure(container_t* container, const char* resource_location) {
    const logger_t *logger = &container->logger;
    config_file_t file;
    char dirname[CONFIG_FILE_SZ];

    LOGGER_WARNING("FMUContainer '" VERSION_TAG "'");

    /* The config parser registers ME FMUs into the solver as it reads them. */
    container->solver = solver_new(container);
    if (!container->solver) {
        LOGGER_ERROR("Cannot allocate ME solver.");
        return -1;
    }

    if (!resource_location) {
        LOGGER_ERROR("No resource location: the container needs its resources.");
        return -1;
    }
    resource_location_to_path(resource_location, dirname, sizeof(dirname));
    if (config_file_open(&file, logger, dirname, "container.txt")) {
        LOGGER_ERROR("Cannot open '%s/container.txt': %s.", dirname, strerror(errno));
        return -1;
    }

    if (read_version(&file)) {
        config_file_close(&file);
        return -2;
    }

    if (read_flags(container, &file)) {
        config_file_close(&file);
        return -2;
    }

    if (read_conf_time_step(container, &file)) {
        config_file_close(&file);
        return -3;
    }

    if (read_conf_fmu(container, dirname, &file)) {
        config_file_close(&file);
        return -4;
    }

    if (read_conf_init_order(container, &file)) {
        config_file_close(&file);
        LOGGER_ERROR("Cannot read the initialization order.");
        return -4;
    }

    if (read_conf_local(container, &file)) {
        config_file_close(&file);
        LOGGER_ERROR("Cannot allocate local variables.");
        return -5;
    }

    if (read_conf_io(container, &file)) {
        config_file_close(&file);
        LOGGER_ERROR("Cannot read translation table.");
        return -6;
    }

#define LOG_IO(variable, fmi_type, c_type) \
    if ((container-> variable .nb_locals > 0) || (container-> variable .nb_ports > 0)) \
        LOGGER_DEBUG("%-10s: %lu local variables and %lu ports", #variable, container-> variable .nb_locals, container-> variable .nb_ports);

    FOR_ALL_NUMERIC_TYPES(LOG_IO)
    LOG_IO(strings, String, char *)
    LOG_IO(binaries, Binary, fmu_binary_t)
    LOG_IO(clocks, Clock, bool)
#undef LOG_IO

    for (int i = 0; i < container->nb_fmu; i += 1) {
        if (read_conf_fmu_io(&container->fmu[i], &file)) {
            config_file_close(&file);
            LOGGER_ERROR("Cannot read I/O table for FMU#%d", i);
            return -7;
        }

#define LOG_IO(orientation, type) \
    if ((container->fmu[i].fmu_io. type . orientation .nb > 0) || (container->fmu[i].fmu_io.clocked_ ## type .nb_ ## orientation > 0)) \
        LOGGER_DEBUG("FMU#%2d: %-10s: [" #orientation "] %lu ports and %lu clocked", i, #type, container->fmu[i].fmu_io. type . orientation .nb, container->fmu[i].fmu_io.clocked_ ## type .nb_ ## orientation);

#define LOG_IO_CLASSIC(orientation, type) \
    if (container->fmu[i].fmu_io. type . orientation .nb > 0)\
        LOGGER_DEBUG("FMU#%2d: %-10s: [" #orientation "] %lu ports", i, #type, container->fmu[i].fmu_io. type . orientation .nb);
        
#define LOG_START(variable, fmi_type, c_type) \
    if (container->fmu[i].fmu_io.start_ ## variable .nb > 0) \
        LOGGER_DEBUG("FMU#%2d: %-10s: [start] %lu ", i, #variable, container->fmu[i].fmu_io.start_ ## variable .nb);

#define LOG_IO_IN(variable, fmi_type, c_type) LOG_IO(in, variable)
#define LOG_IO_OUT(variable, fmi_type, c_type) LOG_IO(out, variable)

    FOR_ALL_NUMERIC_TYPES(LOG_IO_IN)
    LOG_IO(in, strings);
    LOG_IO(in, binaries);
    LOG_IO_CLASSIC(in, clocks);

    FOR_ALL_NUMERIC_TYPES(LOG_START)
    LOG_START(strings, String, const char *)

    FOR_ALL_NUMERIC_TYPES(LOG_IO_OUT)
    LOG_IO(out, strings);
    LOG_IO(out, binaries);
    LOG_IO_CLASSIC(out, clocks);

#undef LOG_IO
#undef LOG_IO_CLASSIC
#undef LOG_IO_IN
#undef LOG_IO_OUT
#undef LOG_START
    }

    /* The cache of the values set by the importer, once the ports and the start values are read */
    container->cache = cache_new(container);
    if (!container->cache) {
        config_file_close(&file);
        return -12;
    }

    if (read_conf_clocks(container, &file)) {
        config_file_close(&file);
        LOGGER_ERROR("Cannot read the clocks of the importer.");
        return -11;
    }
    if (container->clocks_list.nb_fmu)
        LOGGER_DEBUG("Container will tick for clocks from %lu FMUs", container->clocks_list.nb_fmu);

    config_file_close(&file);

    LOGGER_DEBUG("Instanciate embedded FMUs...");
    for (int i = 0; i < container->nb_fmu; i += 1) {
        fmu_t *fmu = &container->fmu[i];
        const bool is_me = (fmu->kind == FMU_KIND_ME);

        /* Each embedded FMU gets its own instance name: two instances of one FMU must not share one. */
        const size_t len = strlen(container->instance_name) + 1 + strlen(fmu->name) + 1;
        fmu->instance_name = malloc(len);
        if (!fmu->instance_name) {
            LOGGER_ERROR("Cannot allocate the instance name of FMU '%s'", fmu->name);
            return -8;
        }
        snprintf(fmu->instance_name, len, "%s.%s", container->instance_name, fmu->name);
        LOGGER_DEBUG("FMU#%d: Instanciate '%s' as '%s' for %s", i, fmu->name, fmu->instance_name,
                     is_me ? "ModelExchange" : "CoSimulation");

        fmu_status_t status = is_me ? fmuInstantiateModelExchange(fmu, fmu->instance_name)
                                    : fmuInstantiateCoSimulation(fmu, fmu->instance_name);
        if (status != FMU_STATUS_OK) {
            LOGGER_ERROR("Cannot Instantiate FMU '%s'", fmu->name);
            return -8;
        }
    }

    container->integers32.locals[0] = 1;                /* Default: TS multiplier */
    container->integers32.locals[1] = 0;                /* Default: solver config (euler) */
    container->next_step = container->time_step; /* Default: no next event time */
    container->time = container->start_time;
    
    container->datalog = datalog_new(logger, dirname);

    /* Buffers of fmu_get_outputs() for the arrays of strings and of binaries */
    if (container->strings.nb_locals) {
        container->strings_tmp = malloc(container->strings.nb_locals * sizeof(*container->strings_tmp));
        if (!container->strings_tmp) {
             LOGGER_ERROR("Cannot allocate buffer for strings.");
             return -9;
        }
    } else
        container->strings_tmp = NULL;

    if (container->binaries.nb_locals) {
        container->binaries_tmp = malloc(container->binaries.nb_locals * sizeof(*container->binaries_tmp));
        container->binaries_size_tmp = malloc(container->binaries.nb_locals * sizeof(*container->binaries_size_tmp));
        if (!container->binaries_tmp || !container->binaries_size_tmp) {
            LOGGER_ERROR("Cannot allocate buffer for binaries.");
             return -9;
        }
    } else {
        container->binaries_tmp = NULL;
        container->binaries_size_tmp = NULL;
    }


    /* Build the CS working set (pointers into container->fmu[]). */
    container->nb_cs = 0;
    if (container->nb_fmu > 0) {
        container->cs_fmu = malloc((size_t)container->nb_fmu * sizeof(*container->cs_fmu));
        if (!container->cs_fmu) {
            LOGGER_ERROR("Cannot allocate CS working set.");
            return -9;
        }
        for (int i = 0; i < container->nb_fmu; i += 1) {
            if (container->fmu[i].kind != FMU_KIND_ME)
                container->cs_fmu[container->nb_cs++] = &container->fmu[i];
        }
    }

    if (container_start_threads(container)) {
        LOGGER_ERROR("Cannot start threads.");
        return -10;
    }

    LOGGER_DEBUG("Container is configured.");

    return 0;
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
        container->cache = NULL;

        /* allocated at the end of the configuration: freed by container_free() even if it fails before */
        container->binaries_tmp = NULL;
        container->binaries_size_tmp = NULL;
        container->strings_tmp = NULL;

        container->nb_cs = 0;
        container->cs_fmu = NULL;
        container->solver = NULL;

#define INIT(variable, fmi_type, c_type)        \
        container-> variable .nb_locals = 0;   \
        container-> variable .locals = NULL;            \
        container-> variable .nb_ports = 0;   \
        container-> variable .links = NULL;      \
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
        container->cancel = false;
        container->barriers_ready = false;
        container->threads_gate_ready = false;
        container->nb_threads = 0;
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
    for (unsigned long i = 0; i < container->binaries.nb_locals; i += 1)
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
