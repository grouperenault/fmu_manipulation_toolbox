/*
 * 2022-2024 Nicolas.LAURENT@Renault.com
 * 
 * DLL/SO loading functions.
 */

#ifndef LIBRARY_H
#define LIBRARY_H

#	ifdef __cplusplus
extern "C" {
#	endif

#ifdef WIN32
#	include <Windows.h>
#endif

/*----------------------------------------------------------------------------
                              L I B R A R Y _ T
----------------------------------------------------------------------------*/

#ifdef WIN32
typedef HINSTANCE library_t;
#else
typedef void* library_t;
#endif


/*----------------------------------------------------------------------------
                             P R O T O T Y P E S
----------------------------------------------------------------------------*/

extern void* library_symbol(library_t library, const char *symbol_name);
extern library_t library_load(struct container_s *container, const char* library_filename);
extern void library_unload(library_t library);

#	ifdef __cplusplus
}
#	endif

#endif
