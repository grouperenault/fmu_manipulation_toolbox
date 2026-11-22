#include <locale.h>
#include <stdarg.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

#include "file.h"
#include "logger.h"

/*
 * Reading of the text files of the container (container.txt, datalog.txt): lines, comments, version header.
 */

/*
 * Read the next line, whatever its length: the buffer is doubled until it holds the whole line.
 * Return 0, -1 at the end of the file, -2 when the buffer cannot grow.
 */
static int read_line(file_t* file) {
    const logger_t *logger = file->logger;
    size_t len = 0;

    file->line[0] = '\0';
    while (fgets(file->line + len, (int)(file->line_size - len), file->fp)) {
        len += strlen(file->line + len);
        if (file->line[len - 1] == '\n')
            break;
        if (len + 1 < file->line_size)   /* last line, without '\n' */
            break;

        char *line = realloc(file->line, 2 * file->line_size);
        if (!line) {
            LOGGER_ERROR("Cannot allocate memory to read line #%u.", file->line_number + 1);
            return -2;
        }
        file->line = line;
        file->line_size *= 2;
    }

    if (len == 0)
        return -1;
    file->line_number += 1;

    /* CHOMP(): "\n" or "\r\n" (a file written on Windows, read on another platform) */
    if (file->line[len - 1] == '\n')
        file->line[--len] = '\0';
    if (len > 0 && file->line[len - 1] == '\r')
        file->line[len - 1] = '\0';

    return 0;
}


int file_get_line(file_t* file) {
    int status;

    do {
        status = read_line(file);
        if (status)
            return status;
    } while (file->line[0] == '#');

    return 0;
}


/*
 * Read the first line of the file, "# Version <N>", without skipping it as a comment.
 */
int file_version(file_t* file, int *version) {
    if (read_line(file))
        return -1;

    if (sscanf(file->line, "# Version %d", version) < 1)
        return -1;

    return 0;
}


int file_open(file_t* file, const logger_t *logger, const char *dirname, const char *filename) {
    char full_path[FILE_SZ];

    file->logger = logger;
    STRLCPY(full_path, dirname, sizeof(full_path));
    STRLCAT(full_path, "/", sizeof(full_path));
    STRLCAT(full_path, filename, sizeof(full_path));
    
    file->line = NULL;
    file->fp = fopen(full_path, "rt");
    if (! file->fp) {
        LOGGER_DEBUG("Cannot open configuration file '%s'.", full_path);
        return -1;
    }

    file->line_size = FILE_SZ;
    file->line = malloc(file->line_size);
    if (! file->line) {
        LOGGER_ERROR("Cannot allocate memory to read configuration file '%s'.", full_path);
        fclose(file->fp);
        file->fp = NULL;
        return -1;
    }

    LOGGER_DEBUG("Reading '%s'.", filename);

    file->line_number = 0;

    return 0;
}


void file_close(file_t* file) {
    if (file->fp)
        fclose(file->fp);
    free(file->line);
    file->line = NULL;

    return;
}

void file_error(file_t *file, unsigned int code_line_number, const char *message, ...) {
    const logger_t *logger = file->logger;
    char message_buffer[256];
    va_list ap;

    va_start(ap, message);
    vsnprintf(message_buffer, sizeof(message_buffer), message, ap);
    va_end(ap);

    LOGGER_ERROR("Configuration error (%u): line #%u: %s", code_line_number, file->line_number, message_buffer);
}


/*
 * The configuration files use a decimal dot, whereas scanf() uses the decimal point of the locale of the host, which an
 * FMU must not change (FMI 3.0, 2.2.1): the text is converted on its way to it.
 */

/* Before scanf() on a line of numbers. scanf() may not read a decimal point of several bytes (macOS): such a locale is
   refused, rather than misreading the values. */
int file_line_to_host_decimal_point(file_t *file) {
    const char *point = localeconv()->decimal_point;

    if (strlen(point) != 1) {
        file_error(file, __LINE__, "The decimal point '%s' of the locale of the importer is not supported.",
                          point);
        return -1;
    }

    for (char *c = file->line; *c; c += 1) {
        if (*c == '.')
            *c = *point;
    }

    return 0;
}
