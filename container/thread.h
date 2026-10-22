#ifndef THREAD_H
#   define THREAD_H

#	ifdef __cplusplus
extern "C" {
#	endif

#   include <stdbool.h>

#   ifdef _WIN32
#       include <windows.h>
#   else
#       include <pthread.h>
#   endif

#   ifdef __APPLE__
#       include <dispatch/dispatch.h>
#       include <stdatomic.h>
#   endif

#   ifdef _WIN32
typedef HANDLE                      thread_t;
typedef HANDLE                      mutex_t;
/* SYNCHRONIZATION_BARRIER requires Windows 8 / Server 2012 or later; Windows 7 is not supported. */
typedef SYNCHRONIZATION_BARRIER     thread_barrier_t;
#   elif defined(__APPLE__)
typedef pthread_t       *thread_t;
/* Darwin lacks pthread_barrier_t: rebuilt on top of dispatch_semaphore. The threads of one phase (generation)
   park on the semaphore of its parity: a thread that enters the next phase before the others left this one cannot
   take their wake-up. */
typedef struct {
    unsigned int            count;      /* total participants (immutable after init) */
    _Atomic unsigned int    arrived;    /* incremented on entry, reset by last-in */
    _Atomic unsigned int    generation; /* incremented by last-in, when it releases the phase */
    dispatch_semaphore_t    sem[2];     /* non-last threads park on sem[generation & 1] */
} thread_barrier_t;
#   else
typedef pthread_t       *thread_t;
typedef pthread_barrier_t thread_barrier_t;
#   endif

/* Gate: the threads that wait on it block until it is opened, once for all. */
#   ifdef _WIN32
typedef struct {
    HANDLE                  event;      /* manual-reset event */
} thread_gate_t;
#   else
typedef struct {
    pthread_mutex_t         mutex;
    pthread_cond_t          cond;
    bool                    open;
} thread_gate_t;
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
 * barrier is automatically reusable, also by consecutive waits on the same
 * barrier (subsequent phases start fresh).
 *
 * Provides memory synchronization: writes before a wait are visible to other
 * threads after their matching wait.
 */
extern int  thread_barrier_init(thread_barrier_t *barrier, unsigned int count);
extern void thread_barrier_wait(thread_barrier_t *barrier);
extern void thread_barrier_destroy(thread_barrier_t *barrier);

/* Gate, initially closed. thread_gate_wait() returns once thread_gate_open() was called. */
extern int  thread_gate_init(thread_gate_t *gate);
extern void thread_gate_wait(thread_gate_t *gate);
extern void thread_gate_open(thread_gate_t *gate);
extern void thread_gate_destroy(thread_gate_t *gate);

#	ifdef __cplusplus
}
#	endif
#endif
