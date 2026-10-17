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
            logger(LOGGER_ERROR, "Cannot allocate memory to read line #%u.", config_file->line_number + 1);
            return -2;
        }
        config_file->line = line;
        config_file->line_size *= 2;
    }

    if (len == 0)
        return -1;
    config_file->line_number += 1;

    /* CHOMP() */
    if (config_file->line[len - 1] == '\n')
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


int config_file_open(config_file_t* config_file, const char *dirname, const char *filename) {
    char full_path[CONFIG_FILE_SZ];

    STRLCPY(full_path, dirname, sizeof(full_path));
    STRLCAT(full_path, "/", sizeof(full_path));
    STRLCAT(full_path, filename, sizeof(full_path));
    
    config_file->line = NULL;
    config_file->fp = fopen(full_path, "rt");
    if (! config_file->fp) {
        logger(LOGGER_DEBUG, "Cannot open configuration file '%s'.", full_path);
        return -1;
    }

    config_file->line_size = CONFIG_FILE_SZ;
    config_file->line = malloc(config_file->line_size);
    if (! config_file->line) {
        logger(LOGGER_ERROR, "Cannot allocate memory to read configuration file '%s'.", full_path);
        fclose(config_file->fp);
        config_file->fp = NULL;
        return -1;
    }

    logger(LOGGER_DEBUG, "Reading '%s'...", filename);

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
    char message_buffer[256];
    va_list ap;

    va_start(ap, message);
    vsnprintf(message_buffer, sizeof(message_buffer), message, ap);
    va_end(ap);

    logger(LOGGER_ERROR, "Configuration error(%u): line #%u: %s", code_line_number, config_file->line_number, message_buffer);
}
