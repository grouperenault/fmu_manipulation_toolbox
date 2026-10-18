#ifndef CONFIG_H
#define CONFIG_H

#	ifdef __cplusplus
extern "C" {
#	endif

#include <stdio.h>
#include <locale.h>
#ifdef __APPLE__
#   include <xlocale.h>
#endif


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
                        C O N F I G _ F I L E _ T
----------------------------------------------------------------------------*/
#define CONFIG_FILE_SZ			4096	/* size of the path buffers, initial size of the line buffer */
struct logger_s;

typedef struct {
	const struct logger_s		*logger;	/* logger of the container that reads the file */
	FILE						*fp;
	char						*line;		/* current line, grown to hold a line of any length */
	size_t						line_size;
    unsigned int                line_number;
} config_file_t;


/*----------------------------------------------------------------------------
                      C O N F I G _ C _ L O C A L E _ T
----------------------------------------------------------------------------*/

/* C numeric locale (decimal dot) for the current thread only: the locale of the host is never changed. */
typedef struct {
#ifdef _WIN32
    _locale_t                   locale;     /* C numeric locale, for the _l functions (_fprintf_l...) */
    int                         per_thread; /* setting of _configthreadlocale() before enter */
    char                        *previous;  /* LC_NUMERIC of the thread before enter */
#else
    locale_t                    c_locale;   /* copy of the global locale with the C numeric category */
    locale_t                    previous;   /* locale of the thread before enter */
#endif
} config_c_locale_t;


/*----------------------------------------------------------------------------
                            P R O T O T Y P E S
----------------------------------------------------------------------------*/

int get_line(config_file_t* config_file);
extern int config_file_version(config_file_t* config_file, int *version);
extern int config_file_open(config_file_t* config_file, const struct logger_s *logger, const char *dirname,
                            const char *filename);
extern void config_file_close(config_file_t* config_file);
extern int config_c_locale_init(config_c_locale_t *c_locale);
extern void config_c_locale_enter(config_c_locale_t *c_locale);
extern void config_c_locale_leave(config_c_locale_t *c_locale);
extern void config_c_locale_free(config_c_locale_t *c_locale);
extern void config_file_error(config_file_t *config_file, unsigned int code_line_number, const char *message, ...) __attribute__((__format__(__printf__, 3, 4)));

#	ifdef __cplusplus
}
#	endif
#endif
