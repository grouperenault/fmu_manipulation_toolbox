#ifndef SOLVER_H
#define SOLVER_H

#ifdef __cplusplus
extern "C" {
#endif

#include <stdbool.h>
#include <stddef.h>

#include "fmu.h"

typedef fmu_status_t (*solver_integrator_t)(struct solver_s *solver,
     double t, double h);

/*----------------------------------------------------------------------------
                   S O L V E R _ M E _ F M U _ T
----------------------------------------------------------------------------*/

typedef struct solver_me_fmu_s {
    fmu_t       *fmu;                   /* resolved by solver_build() */
    unsigned long fmu_idx;              /* index in container->fmu[] */
    size_t       nx;                    /* nb continuous states */
    size_t       nz;                    /* nb event indicators */
    size_t       x_off;                 /* offset into x/dx/x_save (total_nx) */
    size_t       z_off;                 /* offset into z/z_prev    (total_nz) */
} solver_me_fmu_t;


/*----------------------------------------------------------------------------
                         S O L V E R _ T
----------------------------------------------------------------------------*/

typedef struct solver_s {
    struct container_s  *container;

    size_t              nb_me;
    solver_me_fmu_t     *me;

    /* Flat buffers, concatenated over all ME FMUs. */
    size_t              total_nx;
    size_t              total_nz;
    double              *x;             /* total_nx */
    double              *dx;            /* total_nx (start-of-step slope k1) */
    double              *x_save;        /* total_nx */
    double              *z;             /* total_nz */
    double              *z_prev;        /* total_nz */

    /* RK4 scratch buffers (allocated only when method == SOLVER_METHOD_RK4). */
    double              *k2;            /* total_nx */
    double              *k3;            /* total_nx */
    double              *k4;            /* total_nx */
    double              *x_tmp;         /* total_nx */

    /* Integrator selection and iteration limits (defaults set by solver_new()). */
    solver_integrator_t integrator;
    int                 max_outer;
    int                 max_bisect;
    int                 max_event_iter;
} solver_t;


/*----------------------------------------------------------------------------
                        P R O T O T Y P E S
----------------------------------------------------------------------------*/

extern solver_t *solver_new(struct container_s *container);
extern void solver_free(solver_t *solver);

/* Declare one ME FMU. Called by the config parser for each ME entry. */
extern int solver_register_me(solver_t *solver, unsigned long fmu_idx,
                              size_t nx, size_t nz);

/* Resolve FMU pointers, compute slice offsets and allocate the flat buffers.
   Must be called once every ME FMU has been registered. */
extern int solver_build(solver_t *solver);

/* Move every ME FMU from Event Mode to Continuous Time Mode, refreshing the
   states and event indicators the event may have changed. */
extern fmu_status_t solver_leave_event_mode(solver_t *solver);

/* Collective fixed-step integration (Euler or RK4) of all ME FMUs over
   [t0, t0+h_total]. */
extern fmu_status_t solver_do_step(solver_t *solver, double t0, double h_total);

#ifdef __cplusplus
}
#endif

#endif /* SOLVER_H */
