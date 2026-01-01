#include <string.h>

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
    } while (config_file->line[0] == '#');

    /* CHOMP() */
    if (config_file->line[strlen(config_file->line) - 1] == '\n')
        config_file->line[strlen(config_file->line) - 1] = '\0'; 
    
    return 0;
}


int config_file_open(config_file_t* config_file, const char *dirname, const char *filename) {
    char full_path[CONFIG_FILE_SZ];

    strncpy(full_path, dirname, sizeof(full_path) - 1);
    full_path[sizeof(full_path) - 1] = '\0';
    strncat(full_path, "/", sizeof(full_path) - strlen(full_path) - 1);
    full_path[sizeof(full_path) - 1] = '\0';
    strncat(full_path, filename, sizeof(full_path) - strlen(full_path) - 1);
    full_path[sizeof(full_path) - 1] = '\0';

    
    config_file->fp = fopen(full_path, "rt");
    if (! config_file->fp)
        return -1;
    
    logger(LOGGER_DEBUG, "Reading '%s'...", filename);

    return 0;
}


void config_file_close(config_file_t* config_file) {
    if (config_file->fp)
        fclose(config_file->fp);

    return;
}
