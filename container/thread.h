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

#   ifdef WIN32
typedef HANDLE                      thread_t;
typedef HANDLE                      mutex_t;
typedef SYNCHRONIZATION_BARRIER     thread_barrier_t;
#   elif defined(__APPLE__)
typedef pthread_t       *thread_t;
/* Darwin lacks pthread_barrier_t: hand-rolled below. */
typedef struct {
    pthread_mutex_t     mutex;
    pthread_cond_t      cond;
    unsigned int        count;      /* total participants */
    unsigned int        waiting;    /* threads currently waiting */
    unsigned long       generation; /* distinguishes successive barrier phases */
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
