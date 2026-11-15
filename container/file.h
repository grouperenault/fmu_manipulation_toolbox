#ifndef FILE_H
#define FILE_H

#	ifdef __cplusplus
extern "C" {
#	endif

#include <stdio.h>


#ifdef _WIN32
#   define STRLCPY(dst, src, len)   strcpy_s(dst, len, src)
#   define STRLCAT(dst, src, len)   strcat_s(dst, len, src)
#else
#   define STRLCPY(dst, src, len)   strncpy(dst, src, len-1);             dst[len-1] = '\0'
#   define STRLCAT(dst, src, len)   strncat(dst, src, len-strlen(dst)-1); dst[len-1] = '\0'
#endif

#ifdef _WIN32
#   define __attribute__(x)
#endif


/*----------------------------------------------------------------------------
                             F I L E _ T
----------------------------------------------------------------------------*/
#define FILE_SZ			4096	/* size of the path buffers, initial size of the line buffer */
struct logger_s;

typedef struct {
	const struct logger_s		*logger;	/* logger of the container that reads the file */
	FILE						*fp;
	char						*line;		/* current line, grown to hold a line of any length */
	size_t						line_size;
    unsigned int                line_number;
} file_t;


/*----------------------------------------------------------------------------
                            P R O T O T Y P E S
----------------------------------------------------------------------------*/

int file_get_line(file_t* file);
extern int file_version(file_t* file, int *version);
extern int file_open(file_t* file, const struct logger_s *logger, const char *dirname,
                            const char *filename);
extern void file_close(file_t* file);
extern int file_line_to_host_decimal_point(file_t *file);
extern void file_error(file_t *file, unsigned int code_line_number, const char *message, ...) __attribute__((__format__(__printf__, 3, 4)));

#	ifdef __cplusplus
}
#	endif
#endif
