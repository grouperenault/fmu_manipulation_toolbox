#ifndef PROFILE_H
#   define PROFILE_H

#	ifdef __cplusplus
extern "C" {
#	endif

#   include <stdint.h>

/*-----------------------------------------------------------------------------
                          P R O F I L E _ T I C _T
-----------------------------------------------------------------------------*/

typedef uint64_t profile_tic_t;             /* ns of a monotonic clock */


/*-----------------------------------------------------------------------------
                              P R O F I L E _ T
-----------------------------------------------------------------------------*/

typedef struct {
    profile_tic_t   current_tic;            /* ns */
    double          total_elapsed;          /* s */
} profile_t;


/*----------------------------------------------------------------------------
                            P R O T O T Y P E S
----------------------------------------------------------------------------*/

struct logger_s;
extern profile_tic_t profile_now(void);
extern profile_t *profile_new(const struct logger_s *logger);
extern void profile_free(profile_t *profile);
extern void profile_tic(profile_t *profile);
extern double profile_toc(profile_t *profile, double current_time);

#	ifdef __cplusplus
}
#	endif
#endif
