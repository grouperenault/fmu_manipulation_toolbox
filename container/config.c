#include <stdarg.h>
#include <string.h>
#include <stdio.h>

#include "config.h"
#include "logger.h"

/*
 * Routine to "parse" config files
 */

int get_line(config_file_t* config_file) {
    do {
        if (!fgets(config_file->line, CONFIG_FILE_SZ, config_file->fp)) {
            config_file->line[0] = '\0';
            return -1;
        }
        config_file->line_number += 1;
    } while (config_file->line[0] == '#');

    /* CHOMP() */
    if (config_file->line[strlen(config_file->line) - 1] == '\n')
        config_file->line[strlen(config_file->line) - 1] = '\0'; 
    
    return 0;
}


int config_file_open(config_file_t* config_file, const char *dirname, const char *filename) {
    char full_path[CONFIG_FILE_SZ];

    STRLCPY(full_path, dirname, sizeof(full_path));
    STRLCAT(full_path, "/", sizeof(full_path));
    STRLCAT(full_path, filename, sizeof(full_path));
    
    config_file->fp = fopen(full_path, "rt");
    if (! config_file->fp)
        return -1;
    
    logger(LOGGER_DEBUG, "Reading '%s'...", filename);

    config_file->line_number = 0;

    return 0;
}


void config_file_close(config_file_t* config_file) {
    if (config_file->fp)
        fclose(config_file->fp);

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
