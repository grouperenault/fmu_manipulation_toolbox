#ifndef PATH_H
#define PATH_H

#include <stdbool.h>
#include <stddef.h>

/*
 * Paths of the file system and `file` URIs (IETF RFC 3986), as exchanged with the importer and the embedded FMUs:
 * the resource location of the container, the directories of the embedded FMUs, their resource locations.
 */

#ifdef _WIN32
#   define PATH_SEPARATOR       '\\'
#   define PATH_SEPARATOR_STR   "\\"
#else
#   define PATH_SEPARATOR       '/'
#   define PATH_SEPARATOR_STR   "/"
#endif

/* Native path of a `file` URI: the scheme is removed, as the leading '/' before a Windows drive letter, the
   percent-encoded octets are decoded, the separators are those of the platform. A text without scheme is taken as a
   path. Returns 0, or -1 if `dest` (of `size` bytes, always NUL-terminated) is too short. */
extern int path_from_uri(const char *uri, char *dest, size_t size);

/* `file` URI of an absolute native path (FMI 2.0 resource location): "file:///", separators '/', octets other than
   unreserved characters, '/' and ':' percent-encoded, no trailing '/' added. Returns 0, or -1 if `dest` is too short. */
extern int path_to_uri(const char *path, char *dest, size_t size);

/* Appends to the path in `buffer` the components given until NULL, each one after a separator of the platform unless
   the path already ends with a separator. Returns 0, or -1 if `buffer` (of `size` bytes) is too short. */
extern int path_join(char *buffer, size_t size, ...);

/* Whether `path` is an existing directory. */
extern bool path_is_directory(const char *path);

#endif
