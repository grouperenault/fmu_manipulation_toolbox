#include "thread.h"


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
