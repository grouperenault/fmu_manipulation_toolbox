#ifndef THREAD_H
#   define THREAD_H

#	ifdef __cplusplus
extern "C" {
#	endif

#   ifdef WIN32
#       include <windows.h>
#   else
#       include <pthread.h>
#   endif

#   ifdef __APPLE__
#       include <dispatch/dispatch.h>
#       include <stdatomic.h>
#   endif

#   ifdef WIN32
typedef HANDLE                      thread_t;
typedef HANDLE                      mutex_t;
/* SYNCHRONIZATION_BARRIER requires Windows 8 / Server 2012 or later; Windows 7 is not supported. */
typedef SYNCHRONIZATION_BARRIER     thread_barrier_t;
#   elif defined(__APPLE__)
typedef pthread_t       *thread_t;
/* Darwin lacks pthread_barrier_t: rebuilt on top of dispatch_semaphore. */
typedef struct {
    unsigned int            count;      /* total participants (immutable after init) */
    _Atomic unsigned int    arrived;    /* incremented on entry, reset by last-in */
    dispatch_semaphore_t    sem;        /* non-last threads park here */
} thread_barrier_t;
#   else
typedef pthread_t       *thread_t;
typedef pthread_barrier_t thread_barrier_t;
#   endif

typedef void *(*thread_function_t)(void *);

/*----------------------------------------------------------------------------
                            P R O T O T Y P E S
----------------------------------------------------------------------------*/

extern thread_t thread_new(thread_function_t function, void *data);
extern void thread_join(thread_t thread);

/*
 * Portable N-way barrier. All `count` threads calling thread_barrier_wait()
 * block until the count is reached, then all are released together. The
 * barrier is automatically reusable (subsequent phases start fresh).
 *
 * Provides memory synchronization: writes before a wait are visible to other
 * threads after their matching wait.
 */
extern int  thread_barrier_init(thread_barrier_t *barrier, unsigned int count);
extern void thread_barrier_wait(thread_barrier_t *barrier);
extern void thread_barrier_destroy(thread_barrier_t *barrier);

#	ifdef __cplusplus
}
#	endif
#endif
