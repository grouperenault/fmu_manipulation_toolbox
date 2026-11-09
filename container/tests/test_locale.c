#include <locale.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "container.h"
#include "datalog.h"
#include "test.h"

/*
 * The configuration is read with a decimal dot whatever the locale of the host, which is left unchanged. The datalog
 * follows this locale: a decimal comma, and a semicolon between its columns.
 */

/* Sets a locale with a decimal comma. Returns its name, or NULL if the system has none. */
static const char *set_decimal_comma_locale(void) {
    static const char *candidates[] = { "fr_FR.UTF-8", "fr_FR.utf8", "de_DE.UTF-8", "de_DE.utf8", "French_France.1252",
                                        "fr-FR", NULL };

    for (int i = 0; candidates[i]; i += 1) {
        if (setlocale(LC_ALL, candidates[i]) && strcmp(localeconv()->decimal_point, ",") == 0)
            return candidates[i];
    }
    setlocale(LC_ALL, "C");
    return NULL;
}


static int check_c_locale(container_t *container, const char *host_locale) {
    char location[4096];
    char line[256];

    snprintf(location, sizeof(location), "file://%s/one_fmu_datalog", TEST_FIXTURES_DIR);
    TEST_ASSERT_EQUAL_INT(0, container_configure(container, location));

    /* the locale of the host is unchanged */
    TEST_ASSERT(strcmp(setlocale(LC_NUMERIC, NULL), host_locale) == 0);
    TEST_ASSERT(strcmp(localeconv()->decimal_point, ",") == 0);

    /* time step "0.1" and start value "2.5" read with a decimal dot */
    TEST_ASSERT(container->time_step == 0.1);
    TEST_ASSERT(container->fmu[0].fmu_io.start_reals64.nb == 1);
    TEST_ASSERT(*container->fmu[0].fmu_io.start_reals64.start_values[0].value == 2.5);

    /* datalog row with the decimal point of the host: the columns are separated by a semicolon */
    container->time = 0.25;
    datalog_log(container);
    TEST_ASSERT(strcmp(localeconv()->decimal_point, ",") == 0);
    container_free(container);

    FILE *fp = fopen(TEST_FIXTURES_DIR "/one_fmu_datalog/datalog.csv", "rt");
    TEST_ASSERT(fp != NULL);
    const int read_header = fgets(line, sizeof(line), fp) != NULL;
    const int read_row = read_header && fgets(line, sizeof(line), fp) != NULL;
    fclose(fp);
    TEST_ASSERT(read_row);
    TEST_ASSERT(strncmp(line, "0,25;", 5) == 0);
    TEST_ASSERT(strchr(line, '.') == NULL);

    return 0;
}


int test_locale_decimal_comma(void) {
    const char *name = set_decimal_comma_locale();
    if (!name) {
        printf("No locale with a decimal comma on this system: test skipped.\n");
        return 0;
    }
    char host_locale[256];
    snprintf(host_locale, sizeof(host_locale), "%s", setlocale(LC_NUMERIC, NULL));

    container_t *container = container_new("locale", "{uuid}", 2);
    const int status = container ? check_c_locale(container, host_locale) : 1;
    setlocale(LC_ALL, "C");

    return status;
}


/* The dots of a line are replaced, with the same values, to the last bit, and the other tokens stay as they are. */
int test_locale_line_to_host_decimal_point(void) {
    const char *name = set_decimal_comma_locale();
    if (!name) {
        printf("No locale with a decimal comma on this system: test skipped.\n");
        return 0;
    }

    config_file_t file;
    char line[] = "12 3 countdown 2.5 0.1\t0.10000000000000001 -1.5e-3 6.02E+23";
    double value[5];

    memset(&file, 0, sizeof(file));
    file.line = line;
    file.line_size = sizeof(line);
    TEST_ASSERT_EQUAL_INT(0, config_line_to_host_decimal_point(&file));
    TEST_ASSERT(strcmp(line, "12 3 countdown 2,5 0,1\t0,10000000000000001 -1,5e-3 6,02E+23") == 0);
    TEST_ASSERT_EQUAL_INT(5, sscanf(line + strlen("12 3 countdown "), "%lf %lf %lf %lf %lf", &value[0], &value[1],
                                    &value[2], &value[3], &value[4]));
    setlocale(LC_ALL, "C");

    TEST_ASSERT(value[0] == 2.5);
    TEST_ASSERT(value[1] == 0.1);
    TEST_ASSERT(value[2] == 0.10000000000000001);
    TEST_ASSERT(value[3] == -1.5e-3);
    TEST_ASSERT(value[4] == 6.02e23);

    return 0;
}


/* A decimal point of several bytes: scanf() may not read it, so the configuration is refused. */
int test_locale_long_decimal_point(void) {
    if (!setlocale(LC_ALL, "fa_IR.UTF-8") || strlen(localeconv()->decimal_point) < 2) {
        setlocale(LC_ALL, "C");
        printf("No locale with a decimal point of several bytes on this system: test skipped.\n");
        return 0;
    }

    char location[4096];
    char line[] = "2.5";
    config_file_t file;

    /* refused by the conversion itself, the line left as it is: a start value would be misread without any error */
    memset(&file, 0, sizeof(file));
    file.line = line;
    file.line_size = sizeof(line);
    const int converted = config_line_to_host_decimal_point(&file);

    snprintf(location, sizeof(location), "file://%s/one_fmu_datalog", TEST_FIXTURES_DIR);
    container_t *container = container_new("locale", "{uuid}", 2);
    const int configured = container ? container_configure(container, location) : 0;
    if (container)
        container_free(container);

    setlocale(LC_ALL, "C");

    TEST_ASSERT(converted != 0);
    TEST_ASSERT(strcmp(line, "2.5") == 0);
    TEST_ASSERT(configured != 0);

    return 0;
}
