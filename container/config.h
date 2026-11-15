#ifndef CONFIG_H
#define CONFIG_H

#	ifdef __cplusplus
extern "C" {
#	endif

/*----------------------------------------------------------------------------
                            P R O T O T Y P E S
----------------------------------------------------------------------------*/

struct container_s;
/* Reads resources/container.txt (and datalog.txt) of the container, instantiates its FMUs. 0 on success. */
extern int config_container(struct container_s *container, const char *resource_location);

#	ifdef __cplusplus
}
#	endif
#endif
