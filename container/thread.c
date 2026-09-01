#include <stdlib.h>

#include "thread.h"

/*
 * portable (Windows/Linux/MacOS) thread / mutex routines
 */

thread_t thread_new(thread_function_t function, void *data) {
#ifdef WIN32
    HANDLE thread = CreateThread(NULL, 0, (LPTHREAD_START_ROUTINE)function, data, 0, NULL); /* Thread should be create _after_ mutexes */
    if (thread) {
        SetPriorityClass(GetCurrentProcess(), HIGH_PRIORITY_CLASS);
        SetThreadPriority(thread, THREAD_PRIORITY_HIGHEST);
        SetThreadPriority(thread, THREAD_PRIORITY_TIME_CRITICAL); /* Try RT ! */
    }
#else
    thread_t thread = malloc(sizeof(*thread));

    if (thread) {
        if (pthread_create(thread, NULL, (void *(*)(void*))function, data) != 0) {
            free(thread);
            thread = NULL;
        }
    }
#endif
    return thread;
}


void thread_join(thread_t thread) {
    if (thread) {
#ifdef WIN32
        WaitForSingleObject(thread, INFINITE);
        CloseHandle(thread);
#else

        pthread_join(*thread, NULL);
        free(thread);

#endif
    }
}


/*----------------------------------------------------------------------------
                       T H R E A D _ B A R R I E R
----------------------------------------------------------------------------*/

int thread_barrier_init(thread_barrier_t *barrier, unsigned int count) {
#ifdef WIN32
    return InitializeSynchronizationBarrier(barrier, (LONG)count, -1) ? 0 : -1;
#elif defined(__APPLE__)
    barrier->count = count;
    atomic_init(&barrier->arrived, 0u);
    barrier->sem = dispatch_semaphore_create(0);
    return barrier->sem ? 0 : -1;
#else
    return pthread_barrier_init(barrier, NULL, count) == 0 ? 0 : -1;
#endif
}


void thread_barrier_wait(thread_barrier_t *barrier) {
#ifdef WIN32
    /* NO_DELETE: barrier outlives every wait; skips the deletion refcount interlock. */
    EnterSynchronizationBarrier(barrier, SYNCHRONIZATION_BARRIER_FLAGS_NO_DELETE);
#elif defined(__APPLE__)
    const unsigned int n = atomic_fetch_add_explicit(&barrier->arrived, 1u,
                                                     memory_order_acq_rel) + 1u;
    if (n == barrier->count) {
        /* Last in: reset counter then release the cohort. */
        atomic_store_explicit(&barrier->arrived, 0u, memory_order_release);
        for (unsigned int i = 1; i < barrier->count; i += 1)
            dispatch_semaphore_signal(barrier->sem);
    } else {
        dispatch_semaphore_wait(barrier->sem, DISPATCH_TIME_FOREVER);
    }
#else
    pthread_barrier_wait(barrier);
#endif
}


void thread_barrier_destroy(thread_barrier_t *barrier) {
#ifdef WIN32
    DeleteSynchronizationBarrier(barrier);
#elif defined(__APPLE__)
    if (barrier->sem) {
        dispatch_release(barrier->sem);
        barrier->sem = NULL;
    }
#else
    pthread_barrier_destroy(barrier);
#endif
}
