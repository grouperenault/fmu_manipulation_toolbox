#ifdef WIN32
#	include <windows.h>
#else
#	include <unistd.h>
#endif
#include <stdlib.h>
#include <time.h>

#include "profile.h"

/*
 * profiling routines.
 */

profile_t *profile_new(void) {
    profile_t *profile = malloc(sizeof(*profile));
    
	profile->current_tic = 0;
	profile->total_elapsed = 0.0;

    return profile;
}

void profile_free(profile_t *profile) {
	if (profile) {
    	free(profile);
	}
    return;
}


void profile_tic(profile_t *profile) {
#ifdef WIN32
	profile->current_tic = GetTickCount();
#else
	struct timespec ts;
	clock_gettime(CLOCK_REALTIME, &ts);
	profile->current_tic = ts.tv_nsec / 1000000;
	profile->current_tic += ts.tv_sec * 1000;
#endif

	return;
}


double profile_toc(profile_t *profile, double current_time) {
	profile_tic_t now;
	
#ifdef WIN32
	now = GetTickCount();
#else
	struct timespec ts;
	clock_gettime(CLOCK_REALTIME, &ts);
	now = ts.tv_nsec / 1000000;
	now += ts.tv_sec * 1000;
#endif
	
    profile->total_elapsed += (now - profile->current_tic) / 1000.0; /* seconds */
	if (profile->total_elapsed > 1e-3)
		return current_time / profile->total_elapsed;
	else
		return current_time / 1e-3;
}

