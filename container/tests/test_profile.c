#ifdef _WIN32
#	include <windows.h>
#else
#	include <time.h>
#endif

#include "profile.h"
#include "test.h"

/*
 * The clock of the profiling and of the warm-up of the multi-thread mode: monotonic, in ns.
 */

static void sleep_ms(unsigned int ms) {
#ifdef _WIN32
    Sleep(ms);
#else
    const struct timespec duration = { ms / 1000, (long)(ms % 1000) * 1000000L };
    nanosleep(&duration, NULL);
#endif
}


int test_profile_monotonic_clock(void) {
    profile_t profile = { 0, 0.0 };

    for (int i = 0; i < 1000; i += 1) {
        const double before = profile.total_elapsed;
        profile_tic(&profile);
        profile_toc(&profile, 1.0);
        TEST_ASSERT(profile.total_elapsed >= before);       /* never back */
        TEST_ASSERT(profile.total_elapsed < 1.0);           /* not a wrapped negative duration */
    }

    return 0;
}


int test_profile_toc(void) {
    profile_t *profile = profile_new(NULL);
    TEST_ASSERT(profile != NULL);

    profile_tic(profile);
    sleep_ms(20);
    const double ratio = profile_toc(profile, 1.0);     /* 1 s simulated in about 20 ms */
    const double elapsed = profile->total_elapsed;
    profile_free(profile);

    TEST_ASSERT(elapsed >= 0.019 && elapsed < 2.0);
    TEST_ASSERT(ratio > 0.5 && ratio <= 1.0 / 0.019);

    return 0;
}
