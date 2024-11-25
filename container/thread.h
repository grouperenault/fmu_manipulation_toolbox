#ifndef THREAD_H
#   define THREAD_H

#   ifdef WIN32
#       include <windows.h>
#   else
#       include <pthread.h>
#   endif

#   ifdef WIN32
typedef HANDLE          thread_t;
typedef HANDLE          mutex_t;
#   else
typedef pthread_t       thread_t;
typedef pthread_mutex_t mutex_t;
#   endif

typedef void *(*thread_function_t)(void *);

/*----------------------------------------------------------------------------
                            P R O T O T Y P E S
----------------------------------------------------------------------------*/

extern thread_t thread_new(thread_function_t function, void *data);
extern mutex_t thread_mutex_new(void);
void thread_mutex_free(mutex_t *mutex);
extern void thread_mutex_lock(mutex_t *mutex);
extern void thread_mutex_unlock(mutex_t *mutex);

#endif
