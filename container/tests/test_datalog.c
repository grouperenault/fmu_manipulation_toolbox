#include <stdio.h>
#include <stdlib.h>
#include <string.h>

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
    char *end;
    const double time = has_row ? strtod(row, &end) : 0.0;
    const double value = (has_row && *end == ',') ? strtod(end + 1, NULL) : 0.0;
    free(csv);

    TEST_ASSERT(header_ok);
    TEST_ASSERT(has_row);
    TEST_ASSERT(time == 0.1);       /* read back bit for bit */
    TEST_ASSERT(value == third);

    return 0;
}
