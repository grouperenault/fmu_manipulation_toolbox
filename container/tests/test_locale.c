#include <locale.h>
#include <stdio.h>
#include <string.h>

#include "container.h"
#include "datalog.h"
#include "test.h"

/*
 * The configuration is read, and the datalog written, with a decimal dot whatever the locale of the host, which is
 * left unchanged.
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

    /* start value "2.5" read with a decimal dot */
    TEST_ASSERT(container->fmu[0].fmu_io.start_reals64.nb == 1);
    TEST_ASSERT(*container->fmu[0].fmu_io.start_reals64.start_values[0].value == 2.5);

    /* datalog row with a decimal dot: one comma, between the time and the value */
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
    int nb_commas = 0;
    for (const char *c = line; *c; c += 1)
        nb_commas += (*c == ',');
    TEST_ASSERT_EQUAL_INT(1, nb_commas);
    TEST_ASSERT(strchr(line, '.') != NULL);

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
