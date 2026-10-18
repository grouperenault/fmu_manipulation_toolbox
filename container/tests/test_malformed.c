#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "container.h"
#include "test.h"

/*
 * Malformed container.txt: the configuration fails with an error, without crash nor out of bounds access (run them
 * under the sanitizers). Each case replaces one line of the valid fixture one_fmu.
 */

#define MALFORMED_DIR       TEST_FIXTURES_DIR "/malformed"
#define MAX_LINES           512

typedef struct {
    const char      *name;
    int             line;           /* 1-based line of the fixture one_fmu */
    const char      *expected;      /* its content, checked before the replacement */
    const char      *replacement;   /* may span several lines; NULL: the file is cut before this line */
    int             valid;          /* 1 if the configuration must succeed */
} malformed_case_t;

static const malformed_case_t cases[] = {
    { "control: valid input added",         52,  "0",          "1\n0 1 3",             1 },
    { "port out of range",                  18,  "0 1 1 -1 0", "5 1 1 -1 0",           0 },
    { "local variable out of range",        18,  "0 1 1 -1 0", "0 1 1 -1 1",           0 },
    { "FMU index out of range",             19,  "1 1 1 0 2",  "1 1 1 1 2",            0 },
    { "negative number of FMUs",            7,   "1 0",        "-1 0",                 0 },
    { "FMU input out of range",             52,  "0",          "1\n1 1 3",             0 },
    { "clocked input truncated",            54,  "0 0",        "1 1\n0 1 0 1",         0 },
    { "clocked input: clock out of range",  54,  "0 0",        "1 1\n0 1 0 1 3",       0 },
    { "start values: one count only",       110, "1 1",        "1",                    0 },
    { "start values: too many",             111, "2 1 0 2.5",  "2 2 0 2.5 3.5",        0 },
    { "conversion out of range",            195, "0",          "1\n0 0 F32_F64",       0 },
    { "conversion unknown",                 195, "0",          "1\n0 0 F64_XYZ",       0 },
    { "clocks: FMU index out of range",     199, "0 0",        "1 1\n3 1 0 0",         0 },
    { "file truncated",                     100, NULL,         NULL,                   0 },
};


static char *read_file(const char *path) {
    FILE *fp = fopen(path, "rb");
    if (!fp)
        return NULL;
    fseek(fp, 0, SEEK_END);
    const long size = ftell(fp);
    fseek(fp, 0, SEEK_SET);
    char *content = malloc((size_t)size + 1);
    if (content) {
        const size_t read = fread(content, 1, (size_t)size, fp);
        content[read] = '\0';
    }
    fclose(fp);
    return content;
}


/* Writes the fixture one_fmu with the case applied into MALFORMED_DIR. Returns 0, or -1 if the case does not apply. */
static int write_case(const char *original, const malformed_case_t *c) {
    char path[4096];
    snprintf(path, sizeof(path), "%s/container.txt", MALFORMED_DIR);
    FILE *fp = fopen(path, "wt");
    if (!fp)
        return -1;

    int status = -1;
    int number = 1;
    for (const char *line = original; *line; number += 1) {
        const char *end = strchr(line, '\n');
        const size_t len = end ? (size_t)(end - line) : strlen(line);
        if (number == c->line) {
            if (!c->expected)
                status = 0;                 /* cut the file here */
            else if (strlen(c->expected) == len && strncmp(line, c->expected, len) == 0) {
                fprintf(fp, "%s\n", c->replacement);
                status = 0;
            }
            if (!c->expected)
                break;
        } else
            fprintf(fp, "%.*s\n", (int)len, line);
        line = end ? end + 1 : line + len;
    }
    fclose(fp);

    return status;
}


static int configure_malformed(void) {
    container_t *container = container_new("malformed", "{uuid}", 2);
    if (!container)
        return -100;
    const int status = container_configure(container, "file://" MALFORMED_DIR);
    container_free(container);
    return status;
}


int test_malformed_container_txt(void) {
    char *original = read_file(TEST_FIXTURES_DIR "/one_fmu/container.txt");
    TEST_ASSERT(original != NULL);

    int failed = 0;
    for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); i += 1) {
        if (write_case(original, &cases[i])) {
            fprintf(stderr, "case '%s': line %d of one_fmu/container.txt is not '%s'\n", cases[i].name,
                    cases[i].line, cases[i].expected);
            failed += 1;
            continue;
        }
        const int status = configure_malformed();
        if ((status == 0) != cases[i].valid) {
            fprintf(stderr, "case '%s': configuration status %d\n", cases[i].name, status);
            failed += 1;
        }
    }
    free(original);
    TEST_ASSERT_EQUAL_INT(0, failed);

    return 0;
}


int test_malformed_datalog_txt(void) {
    char *original = read_file(TEST_FIXTURES_DIR "/one_fmu/container.txt");
    TEST_ASSERT(original != NULL);
    TEST_ASSERT(test_write_file(MALFORMED_DIR, "container.txt", original) == 0);
    free(original);
    /* datalog.txt cut after the file name: the datalog is dropped, the configuration goes on */
    TEST_ASSERT(test_write_file(MALFORMED_DIR, "datalog.txt",
                                "# Datalog filename\n" MALFORMED_DIR "/datalog.csv\n# real64: <VR> <NAME>\n") == 0);

    container_t *container = container_new("malformed", "{uuid}", 2);
    TEST_ASSERT(container != NULL);
    const int status = container_configure(container, "file://" MALFORMED_DIR);
    const int has_datalog = container->datalog != NULL;
    container_free(container);
    remove(MALFORMED_DIR "/datalog.txt");

    TEST_ASSERT_EQUAL_INT(0, status);
    TEST_ASSERT(!has_datalog);

    return 0;
}
