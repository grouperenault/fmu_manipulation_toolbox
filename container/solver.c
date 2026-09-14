#include <stdbool.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>

#include "container.h"
#include "fmu.h"
#include "logger.h"
#include "solver.h"

/*
 * Forward-Euler integrator for Model Exchange FMUs.
 *
 * All ME FMUs are advanced in a single container-wide loop so their state
 * derivatives, state events and time events stay consistent across the
 * coupled set. State buffers (x, dx, x_save, z, z_prev) are flat and
 * concatenated over all ME FMUs; each solver->me[i] holds the offset of its
 * slice. Thin FMI-2/3 dispatchers (fmuSetTime, fmuGetContinuousStateDerivatives,
 * ...) live in fmu.c and are stateless.
 */

#define SOLVER_MAX_OUTER        1024
#define SOLVER_MAX_BISECT       20
#define SOLVER_MAX_EVENT_ITER   100


/*----------------------------------------------------------------------------
                       L I F E T I M E
----------------------------------------------------------------------------*/

solver_t *solver_new(container_t *container) {
    solver_t *s = calloc(1, sizeof(*s));
    if (!s) return NULL;

    s->container = container;
    s->max_outer = SOLVER_MAX_OUTER;
    s->max_bisect = SOLVER_MAX_BISECT;
    s->max_event_iter = SOLVER_MAX_EVENT_ITER;

    return s;
}


int solver_register_me(solver_t *solver, unsigned long fmu_idx, size_t nx, size_t nz) {
    void *p = realloc(solver->me, (solver->nb_me + 1) * sizeof(*solver->me));
    if (!p) {
        logger(LOGGER_ERROR, "solver_register_me: allocation failed.");
        return -1;
    }
    solver->me = p;

    solver_me_fmu_t *e = &solver->me[solver->nb_me];
    e->fmu     = NULL;                  /* resolved by solver_build() */
    e->fmu_idx = fmu_idx;
    e->nx      = nx;
    e->nz      = nz;
    e->x_off   = 0;
    e->z_off   = 0;
    solver->nb_me += 1;

    return 0;
}


int solver_build(solver_t *solver) {
    if (solver->nb_me == 0)
        return 0;

    size_t x_off = 0;
    size_t z_off = 0;
    for (size_t i = 0; i < solver->nb_me; i += 1) {
        solver_me_fmu_t *e = &solver->me[i];
        e->fmu   = &solver->container->fmu[e->fmu_idx];
        e->x_off = x_off;
        e->z_off = z_off;
        x_off += e->nx;
        z_off += e->nz;
    }
    solver->total_nx = x_off;
    solver->total_nz = z_off;

    if (solver->total_nx) {
        solver->x      = calloc(solver->total_nx, sizeof(*solver->x));
        solver->dx     = calloc(solver->total_nx, sizeof(*solver->dx));
        solver->x_save = calloc(solver->total_nx, sizeof(*solver->x_save));
        if (!solver->x || !solver->dx || !solver->x_save) goto fail;
    }
    if (solver->total_nz) {
        solver->z      = calloc(solver->total_nz, sizeof(*solver->z));
        solver->z_prev = calloc(solver->total_nz, sizeof(*solver->z_prev));
        if (!solver->z || !solver->z_prev) goto fail;
    }

    return 0;

fail:
    logger(LOGGER_ERROR, "solver_build: allocation failed.");
    return -1;
}


void solver_free(solver_t *solver) {
    if (!solver) return;
    free(solver->x);
    free(solver->dx);
    free(solver->x_save);
    free(solver->z);
    free(solver->z_prev);
    free(solver->me);
    free(solver);
}


/*----------------------------------------------------------------------------
                     C O U P L I N G   S W E E P
----------------------------------------------------------------------------*/

/* Refresh the ME<->ME coupling at the current operating point: one Gauss-Seidel
   sweep in registration order, so an output produced by me[i] reaches me[i+1]
   within the same sweep. Required before every evaluation of the right-hand
   side and of the event indicators (FMI-3.0 2.2.11), otherwise the coupled
   FMUs are evaluated with stale inputs. */
fmu_status_t solver_propagate(solver_t *solver) {
    for (size_t i = 0; i < solver->nb_me; i += 1) {
        fmu_t *fmu = solver->me[i].fmu;

        if (fmu_set_inputs(fmu) != FMU_STATUS_OK) {
            logger(LOGGER_ERROR, "ME FMU '%s': cannot set inputs.", fmu->name);
            return FMU_STATUS_ERROR;
        }
        if (fmu_get_outputs(fmu) != FMU_STATUS_OK) {
            logger(LOGGER_ERROR, "ME FMU '%s': cannot get outputs.", fmu->name);
            return FMU_STATUS_ERROR;
        }
    }
    return FMU_STATUS_OK;
}


/*----------------------------------------------------------------------------
                   E V E N T   I T E R A T I O N
----------------------------------------------------------------------------*/

/* Collective event iteration (FMI-3.0 2.2.11): every ME FMU must already be in
   Event Mode. Each pass propagates the coupling, then closes the super-dense
   time instant on all FMUs, so a discrete change in one FMU is seen by the
   others at the same instant. */
static fmu_status_t solver_event_iteration(solver_t *solver) {
    for (int iter = 0; iter < solver->max_event_iter; iter += 1) {
        bool more_event = false;

        if (solver_propagate(solver) != FMU_STATUS_OK)
            return FMU_STATUS_ERROR;

        for (size_t i = 0; i < solver->nb_me; i += 1) {
            bool need_update = false;

            if (fmuUpdateDiscreteStates(solver->me[i].fmu, &need_update) != FMU_STATUS_OK)
                return FMU_STATUS_ERROR;

            more_event |= need_update;
        }

        if (!more_event)
            return FMU_STATUS_OK;
    }

    logger(LOGGER_ERROR, "Solver: event iteration did not converge after %d steps.",
           solver->max_event_iter);
    return FMU_STATUS_ERROR;
}


/* Back to Continuous Time Mode, refreshing the states and event indicators the
   event may have reset. */
fmu_status_t solver_leave_event_mode(solver_t *solver) {
    for (size_t i = 0; i < solver->nb_me; i += 1) {
        solver_me_fmu_t *e = &solver->me[i];

        if (fmuEnterContinuousTimeMode(e->fmu) != FMU_STATUS_OK) {
            logger(LOGGER_ERROR, "ME FMU '%s': cannot enter Continuous Time Mode.", e->fmu->name);
            return FMU_STATUS_ERROR;
        }
        if (fmuGetContinuousStates(e->fmu, &solver->x[e->x_off], e->nx) != FMU_STATUS_OK)
            return FMU_STATUS_ERROR;
        if (e->nz && fmuGetEventIndicators(e->fmu, &solver->z_prev[e->z_off], e->nz) != FMU_STATUS_OK)
            return FMU_STATUS_ERROR;
    }
    return FMU_STATUS_OK;
}


/*----------------------------------------------------------------------------
                S T A T E - E V E N T   D E T E C T I O N
----------------------------------------------------------------------------*/

/* Return true if any pair (a[i], b[i]) changes domain, as defined in FMI-3.0
   3.1.1: z > 0 <-> z <= 0. */
static bool solver_sign_changed(const double *a, const double *b, size_t n) {
    for (size_t i = 0; i < n; i += 1) {
        if ((a[i] > 0.0) != (b[i] > 0.0))
            return true;
    }
    return false;
}

/* Interpolate every ME FMU's state to t_start + h_mid on the flat buffer,
   push it to the FMUs and read back the event indicators for zero-crossing
   detection. */
static fmu_status_t solver_push_and_read_indicators(solver_t *solver,
                                                    double t_start, double h,
                                                    bool *any_crossed) {
    /* Flat interpolation: x[k] = x_save[k] + h * dx[k]. */
    const double *xs = solver->x_save;
    const double *dx = solver->dx;
    double *x = solver->x;
    for (size_t k = 0; k < solver->total_nx; k += 1)
        x[k] = xs[k] + h * dx[k];

    for (size_t i = 0; i < solver->nb_me; i += 1) {
        solver_me_fmu_t *e = &solver->me[i];
        if (fmuSetTime(e->fmu, t_start + h) != FMU_STATUS_OK) return FMU_STATUS_ERROR;
        if (fmuSetContinuousStates(e->fmu, &x[e->x_off], e->nx) != FMU_STATUS_OK) return FMU_STATUS_ERROR;
    }

    if (solver_propagate(solver) != FMU_STATUS_OK)
        return FMU_STATUS_ERROR;

    if (any_crossed) *any_crossed = false;
    for (size_t i = 0; i < solver->nb_me; i += 1) {
        solver_me_fmu_t *e = &solver->me[i];
        if (e->nz == 0) continue;
        if (fmuGetEventIndicators(e->fmu, &solver->z[e->z_off], e->nz) != FMU_STATUS_OK)
            return FMU_STATUS_ERROR;
        if (any_crossed && !*any_crossed &&
            solver_sign_changed(&solver->z_prev[e->z_off], &solver->z[e->z_off], e->nz))
            *any_crossed = true;
    }
    return FMU_STATUS_OK;
}


/* Bisect [0, h_step] to the earliest sub-step where at least one FMU shows a
   zero-crossing. All ME FMUs are advanced to the same h_mid so couplings stay
   consistent along the search. */
static fmu_status_t solver_locate_state_event(solver_t *solver,
                                              double t_start, double h_step,
                                              double *h_out) {
    const double tol = solver->container->tolerance;
    double h_lo = 0.0;
    double h_hi = h_step;

    for (int iter = 0; iter < solver->max_bisect && (h_hi - h_lo) > tol; iter += 1) {
        const double h_mid = 0.5 * (h_lo + h_hi);
        bool crossed = false;
        if (solver_push_and_read_indicators(solver, t_start, h_mid, &crossed) != FMU_STATUS_OK)
            return FMU_STATUS_ERROR;
        if (crossed) h_hi = h_mid;
        else         h_lo = h_mid;
    }

    if (solver_push_and_read_indicators(solver, t_start, h_hi, NULL) != FMU_STATUS_OK)
        return FMU_STATUS_ERROR;

    *h_out = h_hi;
    return FMU_STATUS_OK;
}


/*----------------------------------------------------------------------------
                      C O L L E C T I V E   S T E P
----------------------------------------------------------------------------*/

fmu_status_t solver_do_step(solver_t *solver, double t0, double h_total) {
    if (solver->nb_me == 0) return FMU_STATUS_OK;

    const double tol = solver->container->tolerance;
    const double h_max = solver->container->time_step;
    double t = t0;
    const double t_end = t0 + h_total;

    for (int outer = 0; outer < solver->max_outer; outer += 1) {
        if (t + tol >= t_end) {
            /* Leave the coupling consistent with the final (t, x). */
            return solver_propagate(solver);
        }

        /* Substep bounded by the earliest scheduled time event across all ME FMUs. */
        double h_step = t_end - t;
        bool is_time_event = false;
        for (size_t i = 0; i < solver->nb_me; i += 1) {
            solver_me_fmu_t *e = &solver->me[i];
            if (!e->fmu->have_next_event_time) continue;
            if (e->fmu->next_event_time >= t_end + tol) continue;

            const double dt_to_event = e->fmu->next_event_time - t;
            if (dt_to_event <= tol) {
                h_step = 0.0;
                is_time_event = true;
                break;
            }
            if (dt_to_event < h_step) {
                h_step = dt_to_event;
                is_time_event = true;
            }
        }

        /* Euler accuracy: never integrate more than one base time step at once,
           whatever the communication step size. */
        if ((h_max > 0.0) && (h_step > h_max)) {
            h_step = h_max;
            is_time_event = false;
        }

        bool state_event = false;

        if (h_step > 0.0) {
            /* At (t, x): dispatch derivatives per FMU into their slice. */
            for (size_t i = 0; i < solver->nb_me; i += 1) {
                solver_me_fmu_t *e = &solver->me[i];
                if (fmuSetTime(e->fmu, t) != FMU_STATUS_OK) return FMU_STATUS_ERROR;
                if (fmuSetContinuousStates(e->fmu, &solver->x[e->x_off], e->nx) != FMU_STATUS_OK) return FMU_STATUS_ERROR;
            }
            if (solver_propagate(solver) != FMU_STATUS_OK)
                return FMU_STATUS_ERROR;
            for (size_t i = 0; i < solver->nb_me; i += 1) {
                solver_me_fmu_t *e = &solver->me[i];
                if (fmuGetContinuousStateDerivatives(e->fmu, &solver->dx[e->x_off], e->nx) != FMU_STATUS_OK) return FMU_STATUS_ERROR;
            }

            /* Snapshot and forward-Euler advance on the flat buffers. */
            if (solver->total_nx)
                memcpy(solver->x_save, solver->x, solver->total_nx * sizeof(*solver->x));
            {
                double *x = solver->x;
                const double *dx = solver->dx;
                for (size_t k = 0; k < solver->total_nx; k += 1)
                    x[k] += h_step * dx[k];
            }

            /* Push new (t, x) and read event indicators. */
            const double t_new_tentative = t + h_step;
            for (size_t i = 0; i < solver->nb_me; i += 1) {
                solver_me_fmu_t *e = &solver->me[i];
                if (fmuSetTime(e->fmu, t_new_tentative) != FMU_STATUS_OK) return FMU_STATUS_ERROR;
                if (fmuSetContinuousStates(e->fmu, &solver->x[e->x_off], e->nx) != FMU_STATUS_OK) return FMU_STATUS_ERROR;
            }
            if (solver_propagate(solver) != FMU_STATUS_OK)
                return FMU_STATUS_ERROR;
            for (size_t i = 0; i < solver->nb_me; i += 1) {
                solver_me_fmu_t *e = &solver->me[i];
                if (e->nz == 0) continue;
                if (fmuGetEventIndicators(e->fmu, &solver->z[e->z_off], e->nz) != FMU_STATUS_OK)
                    return FMU_STATUS_ERROR;
                if (solver_sign_changed(&solver->z_prev[e->z_off], &solver->z[e->z_off], e->nz))
                    state_event = true;
            }

            if (state_event) {
                double h_event = h_step;
                if (solver_locate_state_event(solver, t, h_step, &h_event) != FMU_STATUS_OK)
                    return FMU_STATUS_ERROR;
                h_step = h_event;
            }

            /* CompletedIntegratorStep on all ME FMUs. */
            for (size_t i = 0; i < solver->nb_me; i += 1) {
                solver_me_fmu_t *e = &solver->me[i];
                bool completed_event = false;
                if (fmuCompletedIntegratorStep(e->fmu, &completed_event) != FMU_STATUS_OK) return FMU_STATUS_ERROR;
                if (completed_event) state_event = true;
            }

            t += h_step;
        }

        if (is_time_event || state_event) {
            for (size_t i = 0; i < solver->nb_me; i += 1) {
                if (fmuEnterEventMode(solver->me[i].fmu) != FMU_STATUS_OK)
                    return FMU_STATUS_ERROR;
            }

            if (solver_event_iteration(solver) != FMU_STATUS_OK)
                return FMU_STATUS_ERROR;

            if (solver_leave_event_mode(solver) != FMU_STATUS_OK)
                return FMU_STATUS_ERROR;

            /* Let the container replay the event over the whole set, so the CS
               FMUs see the discrete changes of the ME FMUs. */
            solver->container->need_event_update = true;
        } else if (solver->total_nz) {
            memcpy(solver->z_prev, solver->z, solver->total_nz * sizeof(*solver->z));
        }
    }

    logger(LOGGER_ERROR, "Solver: doStep did not converge (t=%g, t_end=%g).", t, t_end);
    return FMU_STATUS_ERROR;
}
