#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "config.h"
#include "test.h"

/*
 * Line reader of the configuration files (config.c).
 */

#define TEST_CONFIG_DIR TEST_BINARY_DIR


int test_config_lines(void) {
    config_file_t file;

    TEST_ASSERT(test_write_file(TEST_CONFIG_DIR, "lines.txt", "# comment\nfirst\n\n# other comment\nlast") == 0);
    TEST_ASSERT_EQUAL_INT(0, config_file_open(&file, NULL, TEST_CONFIG_DIR, "lines.txt"));

    TEST_ASSERT_EQUAL_INT(0, get_line(&file));
    TEST_ASSERT(strcmp(file.line, "first") == 0);
    TEST_ASSERT_EQUAL_INT(0, get_line(&file));
    TEST_ASSERT(strcmp(file.line, "") == 0);
    TEST_ASSERT_EQUAL_INT(0, get_line(&file));
    TEST_ASSERT(strcmp(file.line, "last") == 0);            /* last line without '\n' */
    TEST_ASSERT_EQUAL_INT(5, file.line_number);
    TEST_ASSERT_EQUAL_INT(-1, get_line(&file));             /* end of file */

    config_file_close(&file);

    return 0;
}


int test_config_long_line(void) {
    config_file_t file;
    const size_t len = 3 * CONFIG_FILE_SZ + 17;
    char *content = malloc(len + 3);

    TEST_ASSERT(content != NULL);
    memset(content, 'x', len);
    strcpy(content + len, "\ny");
    const int written = test_write_file(TEST_CONFIG_DIR, "long.txt", content);
    free(content);
    TEST_ASSERT(written == 0);

    TEST_ASSERT_EQUAL_INT(0, config_file_open(&file, NULL, TEST_CONFIG_DIR, "long.txt"));
    TEST_ASSERT_EQUAL_INT(0, get_line(&file));
    TEST_ASSERT_EQUAL_INT(len, strlen(file.line));
    TEST_ASSERT_EQUAL_INT(0, get_line(&file));
    TEST_ASSERT(strcmp(file.line, "y") == 0);
    config_file_close(&file);

    return 0;
}


int test_config_version(void) {
    config_file_t file;
    int version = 0;

    TEST_ASSERT(test_write_file(TEST_CONFIG_DIR, "version.txt", "# Version 42\n") == 0);
    TEST_ASSERT_EQUAL_INT(0, config_file_open(&file, NULL, TEST_CONFIG_DIR, "version.txt"));
    TEST_ASSERT_EQUAL_INT(0, config_file_version(&file, &version));
    TEST_ASSERT_EQUAL_INT(42, version);
    config_file_close(&file);

    TEST_ASSERT(test_write_file(TEST_CONFIG_DIR, "no_version.txt", "# Other header\n") == 0);
    TEST_ASSERT_EQUAL_INT(0, config_file_open(&file, NULL, TEST_CONFIG_DIR, "no_version.txt"));
    TEST_ASSERT_EQUAL_INT(-1, config_file_version(&file, &version));
    config_file_close(&file);

    return 0;
}


/* A file written on Windows (CRLF), whatever the platform that reads it. */
int test_config_crlf(void) {
    config_file_t file;
    char path[4096];

    snprintf(path, sizeof(path), "%s/crlf.txt", TEST_CONFIG_DIR);
    FILE *fp = fopen(path, "wb");   /* binary: the CRLF are written as is */
    TEST_ASSERT(fp != NULL);
    fputs("# comment\r\nstub\r\n\r\nlast\r\n", fp);
    fclose(fp);

    TEST_ASSERT_EQUAL_INT(0, config_file_open(&file, NULL, TEST_CONFIG_DIR, "crlf.txt"));
    TEST_ASSERT_EQUAL_INT(0, get_line(&file));
    TEST_ASSERT(strcmp(file.line, "stub") == 0);
    TEST_ASSERT_EQUAL_INT(0, get_line(&file));
    TEST_ASSERT(strcmp(file.line, "") == 0);
    TEST_ASSERT_EQUAL_INT(0, get_line(&file));
    TEST_ASSERT(strcmp(file.line, "last") == 0);
    config_file_close(&file);

    return 0;
}
