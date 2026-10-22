#include <stdbool.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>

#include "container.h"
#include "fmu.h"
#include "logger.h"
#include "solver.h"

/*
 * Fixed-step integrator for Model Exchange FMUs (forward Euler or RK4).
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
static fmu_status_t solver_integrate_euler(solver_t *solver, double t, double h);
static fmu_status_t solver_integrate_rk4(solver_t *solver, double t, double h);

solver_t *solver_new(container_t *container) {
    const logger_t *logger = &container->logger;
    LOGGER_ERROR("Solver configure....");
    solver_t *solver = calloc(1, sizeof(*solver));
    if (!solver) {
        LOGGER_ERROR("solver allocation failed.");
        return NULL;
    }
    solver->container = container;
    solver->max_outer = SOLVER_MAX_OUTER;
    solver->max_bisect = SOLVER_MAX_BISECT;
    solver->max_event_iter = SOLVER_MAX_EVENT_ITER;
    solver->integrator = solver_integrate_euler;

    return solver;
}


int solver_register_me(solver_t *solver, unsigned long fmu_idx, size_t nx, size_t nz) {
    const logger_t *logger = &solver->container->logger;
    void *p = realloc(solver->me, (solver->nb_me + 1) * sizeof(*solver->me));
    if (!p) {
        LOGGER_ERROR("solver_register_me: allocation failed.");
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
    e->coupled_reals64.nb = 0;
    e->coupled_reals64.translations = NULL;
    e->coupled_reals32.nb = 0;
    e->coupled_reals32.translations = NULL;
    e->feeds_me = false;
    solver->nb_me += 1;

    return 0;
}


/* Flat buffers, allocated by solver_configure(). */
static void solver_free_buffers(solver_t *solver) {
    free(solver->x);
    free(solver->dx);
    free(solver->x_save);
    free(solver->z);
    free(solver->z_prev);
    free(solver->k2);
    free(solver->k3);
    free(solver->k4);
    free(solver->x_tmp);
    solver->x = solver->dx = solver->x_save = solver->z = solver->z_prev = NULL;
    solver->k2 = solver->k3 = solver->k4 = solver->x_tmp = NULL;

    for (size_t i = 0; i < solver->nb_me; i += 1) {
        free(solver->me[i].coupled_reals64.translations);
        free(solver->me[i].coupled_reals32.translations);
        solver->me[i].coupled_reals64.translations = solver->me[i].coupled_reals32.translations = NULL;
        solver->me[i].coupled_reals64.nb = solver->me[i].coupled_reals32.nb = 0;
        solver->me[i].feeds_me = false;
    }
    solver->has_coupling = false;
}


/*----------------------------------------------------------------------------
                       M E   ->   M E   C O U P L I N G S
----------------------------------------------------------------------------*/

/* Mark the local slots [offset, offset + dimension) in `slots`. */
static void solver_mark(bool *slots, unsigned long offset, unsigned long dimension) {
    for (unsigned long k = 0; k < dimension; k += 1)
        slots[offset + k] = true;
}


/* Whether one of the local slots [offset, offset + dimension) is marked in `slots`. */
static bool solver_marked(const bool *slots, unsigned long offset, unsigned long dimension) {
    for (unsigned long k = 0; k < dimension; k += 1) {
        if (slots[offset + k])
            return true;
    }
    return false;
}


/* Mark the real local slots written by an ME FMU: its continuous outputs, and the real destinations of its
   conversions (run with its outputs). */
static void solver_mark_outputs(const container_t *container, const fmu_t *fmu, bool *slots64, bool *slots32) {
    for (unsigned long i = 0; i < fmu->fmu_io.reals64.out.nb; i += 1)
        solver_mark(slots64, fmu->fmu_io.reals64.out.translations[i].vr, fmu->fmu_io.reals64.out.translations[i].dimension);
    for (unsigned long i = 0; i < fmu->fmu_io.reals32.out.nb; i += 1)
        solver_mark(slots32, fmu->fmu_io.reals32.out.translations[i].vr, fmu->fmu_io.reals32.out.translations[i].dimension);
    if (!fmu->conversions)
        return;
    for (unsigned long i = 0; i < fmu->conversions->nb; i += 1) {
        const convert_table_entry_t *entry = &fmu->conversions->entries[i];
        if (entry->to_real == 64)
            solver_mark(slots64, container->port_reals64[entry->to].links[0].fmu_vr,
                        container->port_reals64[entry->to].dimension);
        else if (entry->to_real == 32)
            solver_mark(slots32, container->port_reals32[entry->to].links[0].fmu_vr,
                        container->port_reals32[entry->to].dimension);
    }
}


/* The inputs of `list` whose local slots are marked in `produced` (they go to `coupled`); their slots are marked
   in `consumed`. */
static int solver_select_inputs(const fmu_translation_list_t *list, const bool *produced, bool *consumed,
                                fmu_translation_list_t *coupled) {
    coupled->nb = 0;
    coupled->translations = NULL;
    if (list->nb == 0)
        return 0;
    coupled->translations = malloc(list->nb * sizeof(*coupled->translations));
    if (!coupled->translations)
        return -1;
    for (unsigned long i = 0; i < list->nb; i += 1) {
        const fmu_translation_t *t = &list->translations[i];
        if (solver_marked(produced, t->vr, t->dimension)) {
            coupled->translations[coupled->nb] = *t;
            coupled->nb += 1;
            solver_mark(consumed, t->vr, t->dimension);
        }
    }
    return 0;
}


/* Find the ME -> ME couplings: only them are refreshed by the coupling sweep during the integration. The other
   continuous inputs of the ME FMUs (fed by Co-Simulation FMUs or by the importer) are constant during the step: they
   are set once before the integration. */
static int solver_find_couplings(solver_t *solver) {
    const container_t *container = solver->container;
    const logger_t *logger = &container->logger;
    const unsigned long nb64 = container->nb_local_reals64, nb32 = container->nb_local_reals32;
    bool *produced64 = calloc(nb64 + 1, sizeof(bool)), *produced32 = calloc(nb32 + 1, sizeof(bool));
    bool *consumed64 = calloc(nb64 + 1, sizeof(bool)), *consumed32 = calloc(nb32 + 1, sizeof(bool));
    bool *outputs64 = calloc(nb64 + 1, sizeof(bool)), *outputs32 = calloc(nb32 + 1, sizeof(bool));
    int status = -1;

    if (!produced64 || !produced32 || !consumed64 || !consumed32 || !outputs64 || !outputs32)
        goto end;

    for (size_t i = 0; i < solver->nb_me; i += 1)
        solver_mark_outputs(container, solver->me[i].fmu, produced64, produced32);

    for (size_t i = 0; i < solver->nb_me; i += 1) {
        solver_me_fmu_t *e = &solver->me[i];
        if (solver_select_inputs(&e->fmu->fmu_io.reals64.in, produced64, consumed64, &e->coupled_reals64) ||
            solver_select_inputs(&e->fmu->fmu_io.reals32.in, produced32, consumed32, &e->coupled_reals32))
            goto end;
        if (e->coupled_reals64.nb || e->coupled_reals32.nb)
            solver->has_coupling = true;
    }

    for (size_t i = 0; i < solver->nb_me; i += 1) {
        solver_me_fmu_t *e = &solver->me[i];
        memset(outputs64, 0, (nb64 + 1) * sizeof(bool));
        memset(outputs32, 0, (nb32 + 1) * sizeof(bool));
        solver_mark_outputs(container, e->fmu, outputs64, outputs32);
        for (unsigned long k = 0; k < nb64 && !e->feeds_me; k += 1)
            e->feeds_me = outputs64[k] && consumed64[k];
        for (unsigned long k = 0; k < nb32 && !e->feeds_me; k += 1)
            e->feeds_me = outputs32[k] && consumed32[k];
        LOGGER_DEBUG("Solver: ME FMU '%s': %lu coupled continuous input(s), %s an ME FMU.", e->fmu->name,
                     e->coupled_reals64.nb + e->coupled_reals32.nb, e->feeds_me ? "feeds" : "does not feed");
    }
    status = 0;

end:
    if (status)
        LOGGER_ERROR("Solver: cannot allocate the ME couplings.");
    free(produced64);
    free(produced32);
    free(consumed64);
    free(consumed32);
    free(outputs64);
    free(outputs32);
    return status;
}


int solver_configure(solver_t *solver) {
    const logger_t *logger = &solver->container->logger;
    if (solver->nb_me == 0)
        return 0;

    /* Called again by each ExitInitializationMode after a reset of the container. */
    solver_free_buffers(solver);

    const int solver_integrator = solver->container->integers32[1];
    
    switch(solver_integrator) {
        case 0: /* Euler */
            LOGGER_WARNING("Solver configured to use Euler integrator.");
            solver->integrator = solver_integrate_euler;
            break;
        case 1: /* RK4 */
            LOGGER_WARNING("Solver configured to use RK4 integrator.");
            solver->integrator = solver_integrate_rk4;
            break;
        default:
            LOGGER_ERROR("Solver configured to use default Euler integrator. (%d)", solver_integrator);
            solver->integrator = solver_integrate_euler;
            break;
    }

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


        solver->k2    = calloc(solver->total_nx, sizeof(*solver->k2));
        solver->k3    = calloc(solver->total_nx, sizeof(*solver->k3));
        solver->k4    = calloc(solver->total_nx, sizeof(*solver->k4));
        solver->x_tmp = calloc(solver->total_nx, sizeof(*solver->x_tmp));
        if (!solver->k2 || !solver->k3 || !solver->k4 || !solver->x_tmp) goto fail;
    }
    if (solver->total_nz) {
        solver->z      = calloc(solver->total_nz, sizeof(*solver->z));
        solver->z_prev = calloc(solver->total_nz, sizeof(*solver->z_prev));
        if (!solver->z || !solver->z_prev) goto fail;
    }

    if (solver_find_couplings(solver))
        return -1;

    return 0;

fail:
    LOGGER_ERROR("solver_build: allocation failed.");
    return -1;
}


void solver_free(solver_t *solver) {
    if (!solver) return;
    solver_free_buffers(solver);
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
   FMUs are evaluated with stale inputs. Only the couplings found by
   solver_find_couplings() are refreshed: the other continuous inputs are
   constant during the step, and nothing is done without coupling.

   Continuous Time Mode only: exchange the continuous (real) couplings, never the
   discrete ones. Per FMI-2.0 2.1.3, discrete variables may only be set/get in
   Event or Initialization Mode; touching a discrete boolean/integer input here
   (e.g. a bounce "reset" flag) corrupts the target FMU's edge detection. The
   discrete couplings are exchanged by solver_event_iteration() in Event Mode. */
static fmu_status_t solver_propagate(solver_t *solver) {
    if (!solver->has_coupling)
        return FMU_STATUS_OK;

    const container_t *container = solver->container;
    const logger_t *logger = &container->logger;
    for (size_t i = 0; i < solver->nb_me; i += 1) {
        const solver_me_fmu_t *e = &solver->me[i];

        for (unsigned long k = 0; k < e->coupled_reals64.nb; k += 1) {
            const fmu_translation_t *t = &e->coupled_reals64.translations[k];
            if (fmuSetReal64(e->fmu, &t->fmu_vr, 1, &container->reals64[t->vr], t->dimension) != FMU_STATUS_OK) {
                LOGGER_ERROR("ME FMU '%s': cannot set inputs.", e->fmu->name);
                return FMU_STATUS_ERROR;
            }
        }
        for (unsigned long k = 0; k < e->coupled_reals32.nb; k += 1) {
            const fmu_translation_t *t = &e->coupled_reals32.translations[k];
            if (fmuSetReal32(e->fmu, &t->fmu_vr, 1, &container->reals32[t->vr], t->dimension) != FMU_STATUS_OK) {
                LOGGER_ERROR("ME FMU '%s': cannot set inputs.", e->fmu->name);
                return FMU_STATUS_ERROR;
            }
        }
        if (e->feeds_me && fmu_get_continuous_outputs(e->fmu) != FMU_STATUS_OK) {
            LOGGER_ERROR("ME FMU '%s': cannot get outputs.", e->fmu->name);
            return FMU_STATUS_ERROR;
        }
    }
    return FMU_STATUS_OK;
}


/*----------------------------------------------------------------------------
                   E V E N T   I T E R A T I O N
----------------------------------------------------------------------------*/

/* Collective event iteration (FMI-3.0 2.2.11): every ME FMU must already be in
   Event Mode. Gauss-Seidel sweep in registration order (Set inputs ->
   fmi*UpdateDiscreteStates -> Get outputs per FMU), so a discrete output
   produced by me[i] reaches me[i+1] within the same pass and the outputs read
   back reflect the freshly updated discrete state. */
static fmu_status_t solver_event_iteration(solver_t *solver) {
    const logger_t *logger = &solver->container->logger;
    for (int iter = 0; iter < solver->max_event_iter; iter += 1) {
        bool more_event = false;

        for (size_t i = 0; i < solver->nb_me; i += 1) {
            fmu_t *fmu = solver->me[i].fmu;
            bool need_update = false;

            if (fmu_set_inputs(fmu) != FMU_STATUS_OK) {
                LOGGER_ERROR("ME FMU '%s': cannot set inputs.", fmu->name);
                return FMU_STATUS_ERROR;
            }

            if (fmuUpdateDiscreteStates(fmu, &need_update) != FMU_STATUS_OK)
                return FMU_STATUS_ERROR;

            more_event |= need_update;

            if (fmu_get_outputs(fmu) != FMU_STATUS_OK) {
                LOGGER_ERROR("ME FMU '%s': cannot get outputs.", fmu->name);
                return FMU_STATUS_ERROR;
            }
        }

        if (!more_event)
            return FMU_STATUS_OK;
    }

    LOGGER_ERROR("Solver: event iteration did not converge after %d steps.",
                 solver->max_event_iter);
    return FMU_STATUS_ERROR;
}


/* Back to Continuous Time Mode for one ME FMU, refreshing its slices of the
   states and event indicators the event may have reset. */
static fmu_status_t solver_leave_event_mode_entry(solver_t *solver, const solver_me_fmu_t *e) {
    const logger_t *logger = &solver->container->logger;
    if (fmuEnterContinuousTimeMode(e->fmu) != FMU_STATUS_OK) {
        LOGGER_ERROR("ME FMU '%s': cannot enter Continuous Time Mode.", e->fmu->name);
        return FMU_STATUS_ERROR;
    }
    if (fmuGetContinuousStates(e->fmu, &solver->x[e->x_off], e->nx) != FMU_STATUS_OK)
        return FMU_STATUS_ERROR;
    if (e->nz && fmuGetEventIndicators(e->fmu, &solver->z_prev[e->z_off], e->nz) != FMU_STATUS_OK)
        return FMU_STATUS_ERROR;
    return FMU_STATUS_OK;
}


/* Back to Continuous Time Mode, refreshing the states and event indicators the
   event may have reset. */
fmu_status_t solver_leave_event_mode(solver_t *solver) {
    for (size_t i = 0; i < solver->nb_me; i += 1) {
        if (solver_leave_event_mode_entry(solver, &solver->me[i]) != FMU_STATUS_OK)
            return FMU_STATUS_ERROR;
    }
    return FMU_STATUS_OK;
}


fmu_status_t solver_leave_event_mode_fmu(solver_t *solver, unsigned long fmu_idx) {
    const logger_t *logger = &solver->container->logger;
    for (size_t i = 0; i < solver->nb_me; i += 1) {
        if (solver->me[i].fmu_idx == fmu_idx)
            return solver_leave_event_mode_entry(solver, &solver->me[i]);
    }
    LOGGER_ERROR("Solver: FMU #%lu is not a Model-Exchange FMU.", fmu_idx);
    return FMU_STATUS_ERROR;
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
                         I N T E G R A T O R S
----------------------------------------------------------------------------*/

/* Evaluate the coupled right-hand side f(t, x): push (t, x) to every ME FMU,
   refresh the couplings, then read the state derivatives into dxdt. */
static fmu_status_t solver_eval_f(solver_t *solver, double t,
                                  const double *x, double *dxdt) {
    for (size_t i = 0; i < solver->nb_me; i += 1) {
        solver_me_fmu_t *e = &solver->me[i];
        if (fmuSetTime(e->fmu, t) != FMU_STATUS_OK) return FMU_STATUS_ERROR;
        if (fmuSetContinuousStates(e->fmu, &x[e->x_off], e->nx) != FMU_STATUS_OK) return FMU_STATUS_ERROR;
    }
    if (solver_propagate(solver) != FMU_STATUS_OK)
        return FMU_STATUS_ERROR;
    for (size_t i = 0; i < solver->nb_me; i += 1) {
        solver_me_fmu_t *e = &solver->me[i];
        if (fmuGetContinuousStateDerivatives(e->fmu, &dxdt[e->x_off], e->nx) != FMU_STATUS_OK) return FMU_STATUS_ERROR;
    }
    return FMU_STATUS_OK;
}


/* Advance x_save -> x over [t, t+h] with the selected fixed-step integrator.
   On entry solver->dx must hold k1 = f(t, x_save); it is left untouched so the
   caller can reuse it as the linear slope for event localization. */
static fmu_status_t solver_integrate_euler(solver_t *solver, double t, double h) {
    const size_t n = solver->total_nx;
    const double *xs = solver->x_save;
    const double *k1 = solver->dx;
    double *x = solver->x;

    (void)t;
    (void)h;

    for (size_t i = 0; i < n; i += 1)
        x[i] = xs[i] + h * k1[i];

    return FMU_STATUS_OK;
}


static fmu_status_t solver_integrate_rk4(solver_t *solver, double t, double h) {
    const size_t n = solver->total_nx;
    const double *xs = solver->x_save;
    const double *k1 = solver->dx;
    double *x = solver->x;
    double *k2 = solver->k2, *k3 = solver->k3, *k4 = solver->k4, *xt = solver->x_tmp;

    for (size_t i = 0; i < n; i += 1)
        xt[i] = xs[i] + 0.5 * h * k1[i];
    
    if (solver_eval_f(solver, t + 0.5 * h, xt, k2) != FMU_STATUS_OK)
        return FMU_STATUS_ERROR;

    for (size_t i = 0; i < n; i += 1)
        xt[i] = xs[i] + 0.5 * h * k2[i];
    if (solver_eval_f(solver, t + 0.5 * h, xt, k3) != FMU_STATUS_OK)
        return FMU_STATUS_ERROR;

    for (size_t i = 0; i < n; i += 1)
        xt[i] = xs[i] + h * k3[i];
    if (solver_eval_f(solver, t + h, xt, k4) != FMU_STATUS_OK)
        return FMU_STATUS_ERROR;

    const double h6 = h / 6.0;
    for (size_t i = 0; i < n; i += 1)
        x[i] = xs[i] + h6 * (k1[i] + 2.0 * k2[i] + 2.0 * k3[i] + k4[i]);

    return FMU_STATUS_OK;
}


/*----------------------------------------------------------------------------
                      C O L L E C T I V E   S T E P
----------------------------------------------------------------------------*/

fmu_status_t solver_do_step(solver_t *solver, double t0, double h_total) {
    const logger_t *logger = &solver->container->logger;
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
            /* Snapshot the state at the start of the step. */
            if (solver->total_nx)
                memcpy(solver->x_save, solver->x, solver->total_nx * sizeof(*solver->x));

            /* k1 = f(t, x_save): start-of-step slope, also reused as the linear
               interpolation slope for event localization. */
            if (solver_eval_f(solver, t, solver->x_save, solver->dx) != FMU_STATUS_OK)
                return FMU_STATUS_ERROR;

            /* Advance x_save -> x over h_step with the selected integrator. */
            if (solver->integrator(solver, t, h_step) != FMU_STATUS_OK)
                return FMU_STATUS_ERROR;

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

    LOGGER_ERROR("Solver: doStep did not converge (t=%g, t_end=%g).", t, t_end);
    return FMU_STATUS_ERROR;
}
