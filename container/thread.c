#include "thread.h"

/*
 * portable (Windows/Linux/MacOS) thread / mutex routines
 */

thread_t thread_new(thread_function_t function, void *data) {
#ifdef WIN32
    HANDLE thread = CreateThread(NULL, 0, (LPTHREAD_START_ROUTINE)function, data, 0, NULL); /* Thread should be create _after_ mutexes */
    SetPriorityClass(GetCurrentProcess(), HIGH_PRIORITY_CLASS);
    SetThreadPriority(thread, THREAD_PRIORITY_HIGHEST);
    SetThreadPriority(thread, THREAD_PRIORITY_TIME_CRITICAL); /* Try RT ! */
#else
    pthread_t thread;
    pthread_create(&thread, NULL, (void *(*)(void*))function, data);
#endif
    return thread;
}


void thread_join(thread_t thread) {
#ifdef WIN32
    WaitForSingleObject(thread, INFINITE);
    CloseHandle(thread);
#else
    pthread_join(thread, NULL);
#endif


    
#ifdef WIN32
    
#endif
}


mutex_t thread_mutex_new(void) {
#ifdef WIN32
    return CreateEventA(NULL, FALSE, FALSE, NULL);
#else
    pthread_mutex_t mutex;
    pthread_mutex_init(&mutex, NULL);
    pthread_mutex_lock(&mutex);
    return mutex;
#endif
}


void thread_mutex_free(mutex_t *mutex) {
#ifdef WIN32
    CloseHandle(*mutex);
#else
    pthread_mutex_destroy(mutex);
#endif

    return;
}


void thread_mutex_lock(mutex_t *mutex) {
#ifdef WIN32
    WaitForSingleObject(*mutex, INFINITE);
#else
    pthread_mutex_lock(mutex);
#endif

    return;
}


void thread_mutex_unlock(mutex_t *mutex) {
#ifdef WIN32
    SetEvent(*mutex);
#else
    pthread_mutex_unlock(mutex);
#endif

    return;
}


/*----------------------------------------------------------------------------
                       T H R E A D _ B A R R I E R
----------------------------------------------------------------------------*/

int thread_barrier_init(thread_barrier_t *barrier, unsigned int count) {
#ifdef WIN32
    return InitializeSynchronizationBarrier(barrier, (LONG)count, -1) ? 0 : -1;
#elif defined(__APPLE__)
    if (pthread_mutex_init(&barrier->mutex, NULL) != 0)
        return -1;
    if (pthread_cond_init(&barrier->cond, NULL) != 0) {
        pthread_mutex_destroy(&barrier->mutex);
        return -1;
    }
    barrier->count      = count;
    barrier->waiting    = 0;
    barrier->generation = 0;
    return 0;
#else
    return pthread_barrier_init(barrier, NULL, count) == 0 ? 0 : -1;
#endif
}


void thread_barrier_wait(thread_barrier_t *barrier) {
#ifdef WIN32
    EnterSynchronizationBarrier(barrier, 0);
#elif defined(__APPLE__)
    pthread_mutex_lock(&barrier->mutex);
    const unsigned int gen = barrier->generation;
    barrier->waiting += 1;
    if (barrier->waiting == barrier->count) {
        /* Last thread in: open the gate for the whole cohort. */
        barrier->generation += 1;
        barrier->waiting = 0;
        pthread_cond_broadcast(&barrier->cond);
    } else {
        /* Wait until this phase ends (generation advances). */
        while (gen == barrier->generation)
            pthread_cond_wait(&barrier->cond, &barrier->mutex);
    }
    pthread_mutex_unlock(&barrier->mutex);
#else
    pthread_barrier_wait(barrier);
#endif
}


void thread_barrier_destroy(thread_barrier_t *barrier) {
#ifdef WIN32
    DeleteSynchronizationBarrier(barrier);
#elif defined(__APPLE__)
    pthread_cond_destroy(&barrier->cond);
    pthread_mutex_destroy(&barrier->mutex);
#else
    pthread_barrier_destroy(barrier);
#endif
}
