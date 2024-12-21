#ifndef PROFILE_H
#   define PROFILE_H


/*-----------------------------------------------------------------------------
                              P R O F I L E _ T
-----------------------------------------------------------------------------*/

typedef unsigned int profile_tic_t;

typedef struct {
    profile_tic_t   current_tic;            /* ms */
    double          total_elapsed;          /* s */
} profile_t;


/*----------------------------------------------------------------------------
                            P R O T O T Y P E S
----------------------------------------------------------------------------*/

extern profile_t *profile_new(void);
extern void profile_free(profile_t *profile);
extern void profile_tic(profile_t *profile);
extern double profile_toc(profile_t *profile, double current_time);

#endif
