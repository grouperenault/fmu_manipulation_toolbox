#ifndef CONFIG_H
#define CONFIG_H

#	ifdef __cplusplus
extern "C" {
#	endif

#include <stdio.h>


#ifdef WIN32
#   define STRLCPY(dst, src, len)   strcpy_s(dst, len, src)
#   define STRLCAT(dst, src, len)   strcat_s(dst, len, src)
#else
#   define STRLCPY(dst, src, len)   strlcpy(dst, src, len)
#   define STRLCAT(dst, src, len)   strlcat(dst, src, len)
#endif

/*----------------------------------------------------------------------------
                        C O N F I G _ F I L E _ T
----------------------------------------------------------------------------*/
#define CONFIG_FILE_SZ			4096
typedef struct {
	FILE						*fp;
	char						line[CONFIG_FILE_SZ];
} config_file_t;


/*----------------------------------------------------------------------------
                            P R O T O T Y P E S
----------------------------------------------------------------------------*/

int get_line(config_file_t* config_file);
extern int config_file_open(config_file_t* config_file, const char *dirname, const char *filename);
extern void config_file_close(config_file_t* config_file);

#	ifdef __cplusplus
}
#	endif
#endif