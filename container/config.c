#include <locale.h>
#include <stdarg.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

#include "config.h"
#include "logger.h"

/*
 * Routine to "parse" config files
 */

/*
 * Read the next line, whatever its length: the buffer is doubled until it holds the whole line.
 * Return 0, -1 at the end of the file, -2 when the buffer cannot grow.
 */
static int read_line(config_file_t* config_file) {
    const logger_t *logger = config_file->logger;
    size_t len = 0;

    config_file->line[0] = '\0';
    while (fgets(config_file->line + len, (int)(config_file->line_size - len), config_file->fp)) {
        len += strlen(config_file->line + len);
        if (config_file->line[len - 1] == '\n')
            break;
        if (len + 1 < config_file->line_size)   /* last line, without '\n' */
            break;

        char *line = realloc(config_file->line, 2 * config_file->line_size);
        if (!line) {
            LOGGER_ERROR("Cannot allocate memory to read line #%u.", config_file->line_number + 1);
            return -2;
        }
        config_file->line = line;
        config_file->line_size *= 2;
    }

    if (len == 0)
        return -1;
    config_file->line_number += 1;

    /* CHOMP(): "\n" or "\r\n" (a file written on Windows, read on another platform) */
    if (config_file->line[len - 1] == '\n')
        config_file->line[--len] = '\0';
    if (len > 0 && config_file->line[len - 1] == '\r')
        config_file->line[len - 1] = '\0';

    return 0;
}


int get_line(config_file_t* config_file) {
    int status;

    do {
        status = read_line(config_file);
        if (status)
            return status;
    } while (config_file->line[0] == '#');

    return 0;
}


/*
 * Read the first line of the file, "# Version <N>", without skipping it as a comment.
 */
int config_file_version(config_file_t* config_file, int *version) {
    if (read_line(config_file))
        return -1;

    if (sscanf(config_file->line, "# Version %d", version) < 1)
        return -1;

    return 0;
}


int config_file_open(config_file_t* config_file, const logger_t *logger, const char *dirname, const char *filename) {
    char full_path[CONFIG_FILE_SZ];

    config_file->logger = logger;
    STRLCPY(full_path, dirname, sizeof(full_path));
    STRLCAT(full_path, "/", sizeof(full_path));
    STRLCAT(full_path, filename, sizeof(full_path));
    
    config_file->line = NULL;
    config_file->fp = fopen(full_path, "rt");
    if (! config_file->fp) {
        LOGGER_DEBUG("Cannot open configuration file '%s'.", full_path);
        return -1;
    }

    config_file->line_size = CONFIG_FILE_SZ;
    config_file->line = malloc(config_file->line_size);
    if (! config_file->line) {
        LOGGER_ERROR("Cannot allocate memory to read configuration file '%s'.", full_path);
        fclose(config_file->fp);
        config_file->fp = NULL;
        return -1;
    }

    LOGGER_DEBUG("Reading '%s'...", filename);

    config_file->line_number = 0;

    return 0;
}


void config_file_close(config_file_t* config_file) {
    if (config_file->fp)
        fclose(config_file->fp);
    free(config_file->line);
    config_file->line = NULL;

    return;
}

void config_file_error(config_file_t *config_file, unsigned int code_line_number, const char *message, ...) {
    const logger_t *logger = config_file->logger;
    char message_buffer[256];
    va_list ap;

    va_start(ap, message);
    vsnprintf(message_buffer, sizeof(message_buffer), message, ap);
    va_end(ap);

    LOGGER_ERROR("Configuration error(%u): line #%u: %s", code_line_number, config_file->line_number, message_buffer);
}


/*
 * The configuration files and the datalog use a decimal dot, whereas scanf() and printf() use the decimal point of the
 * locale of the host, which an FMU must not change (FMI 3.0, 2.2.1): the text is converted on its way to or from them.
 */

/* Before scanf() on a line of numbers. Without a decimal point, a number reads the same in every locale, and has the
   same value: "2.5" becomes "25e-1". scanf() may not read a decimal point of several bytes (macOS). */
int config_line_without_decimal_point(config_file_t *config_file) {
    enum { MAX_EXPONENT_SZ = 24 };  /* "e" and a long */
    const char *from = config_file->line;
    size_t nb_dots = 0;
    size_t length = 0;

    for (; from[length]; length += 1)
        nb_dots += (from[length] == '.');
    if (nb_dots == 0)
        return 0;

    const size_t size = length + nb_dots * MAX_EXPONENT_SZ + 1;
    char *text = malloc(size);
    if (!text)
        return -1;

    char *to = text;
    while (*from) {
        const size_t token = strcspn(from, " \t");
        const char *dot = memchr(from, '.', token);

        if (dot) {
            const size_t before = (size_t)(dot - from);
            const char *digits = dot + 1;
            const size_t nb_digits = strspn(digits, "0123456789");
            const char *exponent = digits + nb_digits;
            const long value = (*exponent == 'e' || *exponent == 'E') ? strtol(exponent + 1, NULL, 10) : 0;

            memcpy(to, from, before);
            to += before;
            memcpy(to, digits, nb_digits);
            to += nb_digits;
            to += snprintf(to, MAX_EXPONENT_SZ, "e%ld", value - (long)nb_digits);
        } else {
            memcpy(to, from, token);
            to += token;
        }
        from += token;

        const size_t separators = strspn(from, " \t");
        memcpy(to, from, separators);
        to += separators;
        from += separators;
    }
    *to = '\0';

    free(config_file->line);
    config_file->line = text;
    config_file->line_size = size;

    return 0;
}


/* Formats a real with a decimal dot. */
void config_real_to_text(char *text, size_t size, const char *format, double value) {
    const char *point = localeconv()->decimal_point;

    snprintf(text, size, format, value);
    if (strcmp(point, ".") != 0) {
        char *found = strstr(text, point);
        if (found) {
            const size_t point_size = strlen(point);
            *found = '.';
            memmove(found + 1, found + point_size, strlen(found + point_size) + 1);
        }
    }
}
