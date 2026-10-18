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
 * C numeric locale of the current thread: the configuration files and the datalog use a decimal dot whatever the
 * locale of the host. enter / leave switch the current thread only; they may be called several times.
 */
int config_c_locale_init(config_c_locale_t *c_locale) {
#ifdef _WIN32
    c_locale->per_thread = 0;
    c_locale->previous = NULL;
    c_locale->locale = _create_locale(LC_NUMERIC, "C");
    return c_locale->locale ? 0 : -1;
#else
    c_locale->previous = (locale_t)0;
    locale_t base = duplocale(LC_GLOBAL_LOCALE);
    if (!base)
        return -1;
    c_locale->c_locale = newlocale(LC_NUMERIC_MASK, "C", base);
    if (!c_locale->c_locale) {
        freelocale(base);
        return -1;
    }
    return 0;
#endif
}


void config_c_locale_enter(config_c_locale_t *c_locale) {
#ifdef _WIN32
    c_locale->per_thread = _configthreadlocale(_ENABLE_PER_THREAD_LOCALE);
    const char *previous = setlocale(LC_NUMERIC, NULL);
    c_locale->previous = previous ? _strdup(previous) : NULL;
    setlocale(LC_NUMERIC, "C");
#else
    c_locale->previous = uselocale(c_locale->c_locale);
#endif
}


void config_c_locale_leave(config_c_locale_t *c_locale) {
#ifdef _WIN32
    if (c_locale->previous) {
        setlocale(LC_NUMERIC, c_locale->previous);
        free(c_locale->previous);
        c_locale->previous = NULL;
    }
    if (c_locale->per_thread != -1)
        _configthreadlocale(c_locale->per_thread);
#else
    if (c_locale->previous)
        uselocale(c_locale->previous);
    c_locale->previous = (locale_t)0;
#endif
}


void config_c_locale_free(config_c_locale_t *c_locale) {
#ifdef _WIN32
    free(c_locale->previous);
    c_locale->previous = NULL;
    _free_locale(c_locale->locale);
#else
    freelocale(c_locale->c_locale);
#endif
}
