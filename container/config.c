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

/* Before scanf() on a line of numbers. scanf() may not read a decimal point of several bytes (macOS): such a locale is
   refused, rather than misreading the values. */
int config_line_to_host_decimal_point(config_file_t *config_file) {
    const char *point = localeconv()->decimal_point;

    if (strlen(point) != 1) {
        config_file_error(config_file, __LINE__, "The decimal point '%s' of the locale of the importer is not supported.",
                          point);
        return -1;
    }

    for (char *c = config_file->line; *c; c += 1) {
        if (*c == '.')
            *c = *point;
    }

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
