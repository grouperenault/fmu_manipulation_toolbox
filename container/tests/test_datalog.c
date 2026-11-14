#include <locale.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "fmi2Functions.h"

#include "container.h"
#include "datalog.h"
#include "fmu.h"
#include "test.h"

/*
 * Rows of the datalog: every significant digit of the reals, CSV fields quoted when needed.
 */

#define DATALOG_DIR     TEST_FIXTURES_DIR "/malformed"

static const char *datalog_txt =
    "# Datalog filename\n" DATALOG_DIR "/datalog.csv\n"
    "# real64: <VR> <NAME>\n2\n2 a[1,2]\n2 say \"hi\"\n"
    "0\n0\n0\n0\n0\n0\n0\n0\n0\n0\n0\n0\n0\n0\n";   /* the 14 other types */


static char *read_file(const char *path) {
    FILE *fp = fopen(path, "rt");   /* text: the CRLF of a Windows checkout are read as LF */
    if (!fp)
        return NULL;
    char *content = calloc(1, 65536);
    if (content && fread(content, 1, 65535, fp) == 0)
        content[0] = '\0';
    fclose(fp);
    return content;
}


int test_datalog_rows(void) {
    char *original = read_file(TEST_FIXTURES_DIR "/one_fmu/container.txt");
    TEST_ASSERT(original != NULL);
    const int written = test_write_file(DATALOG_DIR, "container.txt", original) ||
                        test_write_file(DATALOG_DIR, "datalog.txt", datalog_txt);
    free(original);
    TEST_ASSERT_EQUAL_INT(0, written);

    container_t *container = container_new("datalog", "{uuid}", 2);
    TEST_ASSERT(container != NULL);
    TEST_ASSERT_EQUAL_INT(0, container_configure(container, "file://" DATALOG_DIR));
    TEST_ASSERT(container->datalog != NULL);

    const fmu_vr_t vr = 0;          /* container VR 2 is the real 0 of the FMU */
    const double third = 1.0 / 3.0;
    TEST_ASSERT_EQUAL_INT(FMU_STATUS_OK, fmuSetReal64(&container->fmu[0], &vr, 1, &third, 1));
    container->time = 0.1;
    datalog_log(container);
    container_free(container);
    remove(DATALOG_DIR "/datalog.txt");

    char *csv = read_file(DATALOG_DIR "/datalog.csv");
    TEST_ASSERT(csv != NULL);
    char *row = strchr(csv, '\n');
    const int has_row = row != NULL;
    if (row)
        *row++ = '\0';
    const int header_ok = strcmp(csv, "time,\"a[1,2]\",\"say \"\"hi\"\"\"") == 0;
    char *end = NULL;
    const double time = has_row ? strtod(row, &end) : 0.0;
    const double value = (end && *end == ',') ? strtod(end + 1, NULL) : 0.0;
    free(csv);

    TEST_ASSERT(header_ok);
    TEST_ASSERT(has_row);
    TEST_ASSERT(time == 0.1);       /* read back bit for bit */
    TEST_ASSERT(value == third);

    return 0;
}


/* With a decimal comma, the columns are separated by a semicolon: a name is quoted if it contains a semicolon. */
int test_datalog_decimal_comma(void) {
    static const char *names =
        "# Datalog filename\n" DATALOG_DIR "/datalog.csv\n"
        "# real64: <VR> <NAME>\n2\n2 a[1,2]\n2 b;c\n"
        "0\n0\n0\n0\n0\n0\n0\n0\n0\n0\n0\n0\n0\n0\n";   /* the 14 other types */
    char *original = read_file(TEST_FIXTURES_DIR "/one_fmu/container.txt");
    TEST_ASSERT(original != NULL);
    const int written = test_write_file(DATALOG_DIR, "container.txt", original) ||
                        test_write_file(DATALOG_DIR, "datalog.txt", names);
    free(original);
    TEST_ASSERT_EQUAL_INT(0, written);

    if (!setlocale(LC_ALL, "fr_FR.UTF-8") && !setlocale(LC_ALL, "fr_FR.utf8") && !setlocale(LC_ALL, "de_DE.UTF-8") &&
        !setlocale(LC_ALL, "de_DE.utf8") && !setlocale(LC_ALL, "French_France.1252")) {
        printf("No locale with a decimal comma on this system: test skipped.\n");
        remove(DATALOG_DIR "/datalog.txt");
        return 0;
    }

    container_t *container = container_new("datalog", "{uuid}", 2);
    const int configured = container ? container_configure(container, "file://" DATALOG_DIR) : 1;
    if (container) {
        if (configured == 0) {
            container->time = 0.25;
            datalog_log(container);
        }
        container_free(container);
    }
    setlocale(LC_ALL, "C");
    remove(DATALOG_DIR "/datalog.txt");
    TEST_ASSERT_EQUAL_INT(0, configured);

    char *csv = read_file(DATALOG_DIR "/datalog.csv");
    TEST_ASSERT(csv != NULL);
    const int header_ok = strncmp(csv, "time;a[1,2];\"b;c\"\n", strlen("time;a[1,2];\"b;c\"\n")) == 0;
    const char *row = strchr(csv, '\n');
    const int row_ok = row && strncmp(row + 1, "0,25;", 5) == 0;
    free(csv);

    TEST_ASSERT(header_ok);
    TEST_ASSERT(row_ok);

    return 0;
}


static void quiet_logger(fmi2ComponentEnvironment environment, fmi2String instanceName, fmi2Status status,
                         fmi2String category, fmi2String message, ...) {
    (void)environment; (void)instanceName; (void)status; (void)category; (void)message;
}


static int count_lines(const char *path) {
    char *text = read_file(path);
    int lines = 0;
    if (text) {
        for (const char *c = text; *c; c += 1)
            lines += (*c == '\n');
        free(text);
    }
    return lines;
}


/* The rows are in the file once the container returns from fmi2DoStep, before the end of the simulation. */
int test_datalog_flushed_at_each_step(void) {
    char *original = read_file(TEST_FIXTURES_DIR "/one_fmu/container.txt");
    TEST_ASSERT(original != NULL);
    const int written = test_write_file(DATALOG_DIR, "container.txt", original) ||
                        test_write_file(DATALOG_DIR, "datalog.txt", datalog_txt);
    free(original);
    TEST_ASSERT_EQUAL_INT(0, written);

    fmi2CallbackFunctions functions;
    memset(&functions, 0, sizeof(functions));
    functions.logger = quiet_logger;
    fmi2Component c = fmi2Instantiate("datalog", fmi2CoSimulation, "{uuid}", "file://" DATALOG_DIR, &functions,
                                      fmi2False, fmi2False);
    TEST_ASSERT(c != NULL);
    TEST_ASSERT_EQUAL_INT(fmi2OK, fmi2SetupExperiment(c, fmi2False, 0.0, 0.0, fmi2False, 1.0));
    TEST_ASSERT_EQUAL_INT(fmi2OK, fmi2EnterInitializationMode(c));
    TEST_ASSERT_EQUAL_INT(fmi2OK, fmi2ExitInitializationMode(c));

    TEST_ASSERT_EQUAL_INT(fmi2OK, fmi2DoStep(c, 0.0, 0.1, fmi2True));
    const int after_one = count_lines(DATALOG_DIR "/datalog.csv");
    TEST_ASSERT_EQUAL_INT(fmi2OK, fmi2DoStep(c, 0.1, 0.1, fmi2True));
    const int after_two = count_lines(DATALOG_DIR "/datalog.csv");
    fmi2FreeInstance(c);
    remove(DATALOG_DIR "/datalog.txt");

    TEST_ASSERT(after_one >= 2);                /* the header and the rows of the first step, before the free */
    TEST_ASSERT(after_two > after_one);

    return 0;
}
