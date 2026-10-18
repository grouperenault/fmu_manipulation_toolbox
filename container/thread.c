#include <stdlib.h>

#include "thread.h"

/*
 * portable (Windows/Linux/MacOS) thread / mutex routines
 */

thread_t thread_new(thread_function_t function, void *data) {
#ifdef _WIN32
    HANDLE thread = CreateThread(NULL, 0, (LPTHREAD_START_ROUTINE)function, data, 0, NULL); /* Thread should be create _after_ mutexes */
    if (thread)
        SetThreadPriority(thread, THREAD_PRIORITY_HIGHEST); /* the priority class of the host process is unchanged */
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
#ifdef _WIN32
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
#ifdef _WIN32
    return InitializeSynchronizationBarrier(barrier, (LONG)count, -1) ? 0 : -1;
#elif defined(__APPLE__)
    barrier->count = count;
    atomic_init(&barrier->arrived, 0u);
    atomic_init(&barrier->generation, 0u);
    barrier->sem[0] = dispatch_semaphore_create(0);
    barrier->sem[1] = dispatch_semaphore_create(0);
    if (!barrier->sem[0] || !barrier->sem[1]) {
        thread_barrier_destroy(barrier);
        return -1;
    }
    return 0;
#else
    return pthread_barrier_init(barrier, NULL, count) == 0 ? 0 : -1;
#endif
}


void thread_barrier_wait(thread_barrier_t *barrier) {
#ifdef _WIN32
    /* NO_DELETE: barrier outlives every wait; skips the deletion refcount interlock. */
    EnterSynchronizationBarrier(barrier, SYNCHRONIZATION_BARRIER_FLAGS_NO_DELETE);
#elif defined(__APPLE__)
    /* The phase cannot change before this thread arrives: read first, it is the phase of this wait. */
    const unsigned int generation = atomic_load_explicit(&barrier->generation, memory_order_acquire);
    dispatch_semaphore_t sem = barrier->sem[generation & 1u];
    const unsigned int n = atomic_fetch_add_explicit(&barrier->arrived, 1u,
                                                     memory_order_acq_rel) + 1u;
    if (n == barrier->count) {
        /* Last in: reset counter, start the next phase, then release the cohort. */
        atomic_store_explicit(&barrier->arrived, 0u, memory_order_relaxed);
        atomic_fetch_add_explicit(&barrier->generation, 1u, memory_order_release);
        for (unsigned int i = 1; i < barrier->count; i += 1)
            dispatch_semaphore_signal(sem);
    } else {
        dispatch_semaphore_wait(sem, DISPATCH_TIME_FOREVER);
    }
#else
    pthread_barrier_wait(barrier);
#endif
}


void thread_barrier_destroy(thread_barrier_t *barrier) {
#ifdef _WIN32
    DeleteSynchronizationBarrier(barrier);
#elif defined(__APPLE__)
    for (int i = 0; i < 2; i += 1) {
        if (barrier->sem[i]) {
            dispatch_release(barrier->sem[i]);
            barrier->sem[i] = NULL;
        }
    }
#else
    pthread_barrier_destroy(barrier);
#endif
}


/*----------------------------------------------------------------------------
                          T H R E A D _ G A T E
----------------------------------------------------------------------------*/

int thread_gate_init(thread_gate_t *gate) {
#ifdef _WIN32
    gate->event = CreateEvent(NULL, TRUE, FALSE, NULL);
    return gate->event ? 0 : -1;
#else
    gate->open = false;
    if (pthread_mutex_init(&gate->mutex, NULL) != 0)
        return -1;
    if (pthread_cond_init(&gate->cond, NULL) != 0) {
        pthread_mutex_destroy(&gate->mutex);
        return -1;
    }
    return 0;
#endif
}


void thread_gate_wait(thread_gate_t *gate) {
#ifdef _WIN32
    WaitForSingleObject(gate->event, INFINITE);
#else
    pthread_mutex_lock(&gate->mutex);
    while (!gate->open)
        pthread_cond_wait(&gate->cond, &gate->mutex);
    pthread_mutex_unlock(&gate->mutex);
#endif
}


void thread_gate_open(thread_gate_t *gate) {
#ifdef _WIN32
    SetEvent(gate->event);
#else
    pthread_mutex_lock(&gate->mutex);
    gate->open = true;
    pthread_cond_broadcast(&gate->cond);
    pthread_mutex_unlock(&gate->mutex);
#endif
}


void thread_gate_destroy(thread_gate_t *gate) {
#ifdef _WIN32
    CloseHandle(gate->event);
#else
    pthread_cond_destroy(&gate->cond);
    pthread_mutex_destroy(&gate->mutex);
#endif
}
