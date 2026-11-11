#include <stdarg.h>
#include <string.h>
#include <sys/stat.h>

#include "path.h"


/* Value of a single hexadecimal digit, or -1 if it is not one. */
static int hex_digit(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}


static bool is_separator(char c) {
    return (c == '/') || (c == '\\');
}


/*
 * Per the FMI 2.0 standard, fmuResourceLocation is a URI following RFC 3986: "file:///C:/temp/MyFMU/resources" or
 * "file:/C:/temp/MyFMU/resources" (with or without the authority component).
 */
int path_from_uri(const char *uri, char *dest, size_t size) {
    const char *src = uri;
    size_t i = 0;

    if (size == 0)
        return -1;

    if (strncmp(src, "file:", 5) == 0) {
        src += 5;
        if (strncmp(src, "//", 2) == 0)
            src += 2;               /* empty authority: "file:///path" */
    }

#ifdef _WIN32
    /* "/C:/..." -> drop the leading '/' before the drive letter. */
    if ((src[0] == '/') && src[1] && (src[2] == ':'))
        src += 1;
#endif

    while (*src) {
        int hi, lo;
        char c;
        if ((src[0] == '%') && ((hi = hex_digit(src[1])) >= 0) && ((lo = hex_digit(src[2])) >= 0)) {
            c = (char)((hi << 4) | lo);
            src += 3;
        } else {
            c = *src++;
        }
        if (is_separator(c))
            c = PATH_SEPARATOR;
        if (i + 1 >= size) {
            dest[i] = '\0';
            return -1;
        }
        dest[i++] = c;
    }
    dest[i] = '\0';

    return 0;
}


/* Unreserved characters of RFC 3986, and the separators of the path that stay as they are. */
static bool is_kept_in_uri(char c) {
    return ((c >= 'A') && (c <= 'Z')) || ((c >= 'a') && (c <= 'z')) || ((c >= '0') && (c <= '9')) ||
           (c == '-') || (c == '.') || (c == '_') || (c == '~') || (c == '/') || (c == ':');
}


int path_to_uri(const char *path, char *dest, size_t size) {
    static const char hex[] = "0123456789ABCDEF";
    size_t i = 0;

#define PUT(c)  do { if (i + 1 >= size) { if (size) dest[i] = '\0'; return -1; } dest[i++] = (c); } while (0)

    for (const char *p = "file://"; *p; p += 1)
        PUT(*p);
    if (!is_separator(path[0]))
        PUT('/');                   /* "C:\..." -> "file:///C:/..." */

    for (const char *src = path; *src; src += 1) {
        char c = *src;
        if (is_separator(c))
            c = '/';
        if (is_kept_in_uri(c)) {
            PUT(c);
        } else {
            const unsigned char octet = (unsigned char)c;
            PUT('%');
            PUT(hex[octet >> 4]);
            PUT(hex[octet & 0x0F]);
        }
    }
#undef PUT
    dest[i] = '\0';

    return 0;
}


int path_join(char *buffer, size_t size, ...) {
    va_list params;
    const char *component;
    size_t length = strlen(buffer);
    int status = 0;

    va_start(params, size);
    while ((component = va_arg(params, const char *))) {
        while (is_separator(component[0]) && (length > 0))
            component += 1;         /* no doubled separator */
        if ((length > 0) && !is_separator(buffer[length - 1])) {
            if (length + 1 >= size) {
                status = -1;
                break;
            }
            buffer[length++] = PATH_SEPARATOR;
        }
        const size_t component_length = strlen(component);
        if (length + component_length >= size) {
            status = -1;
            break;
        }
        memcpy(buffer + length, component, component_length);
        length += component_length;
    }
    va_end(params);
    buffer[length] = '\0';

    return status;
}


bool path_is_directory(const char *path) {
#ifdef _WIN32
    struct _stat info;
    return (_stat(path, &info) == 0) && (info.st_mode & _S_IFDIR);
#else
    struct stat info;
    return (stat(path, &info) == 0) && S_ISDIR(info.st_mode);
#endif
}
