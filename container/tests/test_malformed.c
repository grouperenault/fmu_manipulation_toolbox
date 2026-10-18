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
    int             nb_lines;       /* lines replaced from `line` */
} malformed_case_t;

static const malformed_case_t cases[] = {
    { "control: valid input added",         52,  "0",          "1\n0 1 3",             1, 1 },
    { "port out of range",                  18,  "0 1 1 -1 0", "5 1 1 -1 0",           0, 1 },
    { "local variable out of range",        18,  "0 1 1 -1 0", "0 1 1 -1 1",           0, 1 },
    { "FMU index out of range",             19,  "1 1 1 0 2",  "1 1 1 1 2",            0, 1 },
    { "negative number of FMUs",            7,   "1 0",        "-1 0",                 0, 1 },
    { "FMU input out of range",             52,  "0",          "1\n1 1 3",             0, 1 },
    { "clocked input truncated",            54,  "0 0",        "1 1\n0 1 0 1",         0, 1 },
    { "clocked input: clock out of range",  54,  "0 0",        "1 1\n0 1 0 1 3",       0, 1 },
    { "start values: one count only",       110, "1 1",        "1",                    0, 1 },
    { "start values: too many",             111, "2 1 0 2.5",  "2 2 0 2.5 3.5",        0, 1 },
    { "conversion out of range",            195, "0",          "1\n0 0 F32_F64",       0, 1 },
    { "conversion unknown",                 195, "0",          "1\n0 0 F64_XYZ",       0, 1 },
    { "clocks: FMU index out of range",     199, "0 0",        "1 1\n3 1 0 0",         0, 1 },
    { "file truncated",                     100, NULL,         NULL,                   0, 1 },
};


static char *read_file(const char *path) {
    FILE *fp = fopen(path, "rt");   /* text: the CRLF of a Windows checkout are read as LF */
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
    const int last = c->line + c->nb_lines - 1;
    for (const char *line = original; *line; number += 1) {
        const char *end = strchr(line, '\n');
        const size_t len = end ? (size_t)(end - line) : strlen(line);
        if (number > c->line && number <= last) {
            /* replaced with the line c->line */
        } else if (number == c->line) {
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


/* Status of container_setup_experiment(), which sets the start values, with the start value line `line`. */
static int setup_with_start_value(const char *original, const char *line, fmu_status_t *status) {
    const malformed_case_t c = { "start value", 111, "2 1 0 2.5", line, 1, 1 };

    TEST_ASSERT_EQUAL_INT(0, write_case(original, &c));
    container_t *container = container_new("start", "{uuid}", 2);
    TEST_ASSERT(container != NULL);
    TEST_ASSERT_EQUAL_INT(0, container_configure(container, "file://" MALFORMED_DIR));
    *status = container_setup_experiment(container, false, 0.0, 0.0, false, 0.0);
    container_free(container);

    return 0;
}


int test_start_value_refused(void) {
    char *original = read_file(TEST_FIXTURES_DIR "/one_fmu/container.txt");
    fmu_status_t accepted = FMU_STATUS_ERROR, refused = FMU_STATUS_OK;    /* both wrong until set */

    TEST_ASSERT(original != NULL);
    const int status = setup_with_start_value(original, "2 1 0 2.5", &accepted) ||
                       setup_with_start_value(original, "20 1 0 2.5", &refused);    /* the stub FMU has VR 0-15 */
    free(original);
    TEST_ASSERT_EQUAL_INT(0, status);
    TEST_ASSERT_EQUAL_INT(FMU_STATUS_OK, accepted);
    TEST_ASSERT_EQUAL_INT(FMU_STATUS_ERROR, refused);

    return 0;
}


int test_start_value_array(void) {
    char *original = read_file(TEST_FIXTURES_DIR "/one_fmu/container.txt");
    const malformed_case_t c = { "array start value", 110, "1 1", "1 3\n2 3 0 1.5 2.5 3.5", 1, 2 };

    TEST_ASSERT(original != NULL);
    const int written = write_case(original, &c);
    free(original);
    TEST_ASSERT_EQUAL_INT(0, written);

    container_t *container = container_new("array", "{uuid}", 2);
    TEST_ASSERT(container != NULL);
    TEST_ASSERT_EQUAL_INT(0, container_configure(container, "file://" MALFORMED_DIR));
    const fmu_start_reals64_t *start = &container->fmu[0].fmu_io.start_reals64;
    const int nb = (int)start->nb;
    const unsigned int dimension = nb ? start->start_values[0].dimension : 0;
    const double last = nb ? start->start_values[0].value[2] : 0.0;
    container_free(container);

    TEST_ASSERT_EQUAL_INT(1, nb);
    TEST_ASSERT_EQUAL_INT(3, dimension);    /* given as the number of values to fmuSetReal64() */
    TEST_ASSERT(last == 3.5);

    return 0;
}
