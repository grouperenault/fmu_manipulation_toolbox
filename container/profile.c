#ifdef _WIN32
#	include <windows.h>
#else
#	include <unistd.h>
#endif
#include <stdlib.h>
#include <time.h>

#include "logger.h"
#include "profile.h"

/*
 * profiling routines.
 */

profile_t *profile_new(const logger_t *logger) {
    profile_t *profile = malloc(sizeof(*profile));

    if (profile) {
        profile->current_tic = 0;
        profile->total_elapsed = 0.0;
    } else {
        LOGGER_ERROR("Cannot allocate profiling structure.");
    }

    return profile;
}

void profile_free(profile_t *profile) {
	if (profile) {
    	free(profile);
	}
    return;
}


/* A monotonic clock in ns, immune to the changes of the wall clock: QueryPerformanceCounter (counter and frequency
   divided apart, counter * 1e9 would overflow after a few days at 10 MHz), CLOCK_MONOTONIC. */
void profile_tic(profile_t *profile) {
#ifdef _WIN32
	LARGE_INTEGER counter, frequency;
	QueryPerformanceFrequency(&frequency);
	QueryPerformanceCounter(&counter);
	const uint64_t ticks = (uint64_t)counter.QuadPart, hz = (uint64_t)frequency.QuadPart;
	profile->current_tic = (ticks / hz) * 1000000000u + (ticks % hz) * 1000000000u / hz;
#else
	struct timespec ts;
	clock_gettime(CLOCK_MONOTONIC, &ts);
	profile->current_tic = (profile_tic_t)ts.tv_sec * 1000000000u + (profile_tic_t)ts.tv_nsec;
#endif

	return;
}


double profile_toc(profile_t *profile, double current_time) {
	profile_tic_t now;

#ifdef _WIN32
	LARGE_INTEGER counter, frequency;
	QueryPerformanceFrequency(&frequency);
	QueryPerformanceCounter(&counter);
	const uint64_t ticks = (uint64_t)counter.QuadPart, hz = (uint64_t)frequency.QuadPart;
	now = (ticks / hz) * 1000000000u + (ticks % hz) * 1000000000u / hz;
#else
	struct timespec ts;
	clock_gettime(CLOCK_MONOTONIC, &ts);
	now = (profile_tic_t)ts.tv_sec * 1000000000u + (profile_tic_t)ts.tv_nsec;
#endif

    profile->total_elapsed += (double)(now - profile->current_tic) / 1e9; /* seconds */
	if (profile->total_elapsed > 1e-3)
		return current_time / profile->total_elapsed;
	else
		return current_time / 1e-3;
}
