#include "thread.h"
#include "test.h"

/*
 * Barrier of the worker threads (thread.c), used as by the container: a start barrier and an end barrier that
 * alternate.
 */

#define TEST_NB_THREADS     4
#define TEST_NB_PHASES      2000

static struct {
    thread_barrier_t        start;
    thread_barrier_t        end;
    unsigned int            counter[TEST_NB_THREADS];   /* one per worker: no atomic needed */
} barrier_test;


static void *barrier_worker(void *data) {
    unsigned int *counter = data;

    for (int phase = 0; phase < TEST_NB_PHASES; phase += 1) {
        thread_barrier_wait(&barrier_test.start);
        *counter += 1;
        thread_barrier_wait(&barrier_test.end);
    }

    return NULL;
}


int test_thread_barrier(void) {
    thread_t threads[TEST_NB_THREADS];

    TEST_ASSERT_EQUAL_INT(0, thread_barrier_init(&barrier_test.start, TEST_NB_THREADS + 1));
    TEST_ASSERT_EQUAL_INT(0, thread_barrier_init(&barrier_test.end, TEST_NB_THREADS + 1));
    for (int i = 0; i < TEST_NB_THREADS; i += 1) {
        barrier_test.counter[i] = 0;
        threads[i] = thread_new(barrier_worker, &barrier_test.counter[i]);
        TEST_ASSERT(threads[i] != NULL);
    }

    int status = 0;
    for (int phase = 0; phase < TEST_NB_PHASES; phase += 1) {
        thread_barrier_wait(&barrier_test.start);
        thread_barrier_wait(&barrier_test.end);
        /* every worker went through this phase, none started the next one */
        for (int i = 0; i < TEST_NB_THREADS; i += 1)
            if (barrier_test.counter[i] != (unsigned int)(phase + 1))
                status = 1;
    }

    for (int i = 0; i < TEST_NB_THREADS; i += 1)
        thread_join(threads[i]);
    thread_barrier_destroy(&barrier_test.start);
    thread_barrier_destroy(&barrier_test.end);

    TEST_ASSERT_EQUAL_INT(0, status);

    return 0;
}
