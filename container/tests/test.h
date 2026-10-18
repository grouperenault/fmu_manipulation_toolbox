#ifndef TEST_H
#   define TEST_H

#include <stdio.h>

/*
 * Minimal test harness of the native runtime: a test is a function that returns 0 on success. The assertions log
 * the failing expression and make the test return 1.
 */

#define TEST_ASSERT(expression)                                                                     \
    do {                                                                                            \
        if (!(expression)) {                                                                        \
            fprintf(stderr, "%s:%d: assertion failed: %s\n", __FILE__, __LINE__, #expression);      \
            return 1;                                                                               \
        }                                                                                           \
    } while (0)

#define TEST_ASSERT_EQUAL_INT(expected, actual)                                                     \
    do {                                                                                            \
        const long long _expected = (long long)(expected);                                          \
        const long long _actual = (long long)(actual);                                              \
        if (_expected != _actual) {                                                                 \
            fprintf(stderr, "%s:%d: %s: expected %lld, got %lld\n", __FILE__, __LINE__, #actual,    \
                    _expected, _actual);                                                            \
            return 1;                                                                               \
        }                                                                                           \
    } while (0)

typedef int (*test_function_t)(void);

/* Directory of the test fixtures (container/tests/data), set by CMake. */
#ifndef TEST_DATA_DIR
#   error "TEST_DATA_DIR must be defined"
#endif
/* Directory of the fixtures built with the stub FMU (tests/stub_fmu.c), set by CMake. */
#ifndef TEST_FIXTURES_DIR
#   error "TEST_FIXTURES_DIR must be defined"
#endif

/* Tests of each module, registered in test_main.c */
extern int test_config_lines(void);
extern int test_config_long_line(void);
extern int test_config_version(void);
extern int test_config_crlf(void);
extern int test_thread_barrier(void);
extern int test_thread_barrier_consecutive(void);
extern int test_configure_empty(void);
extern int test_container_new_null(void);
extern int test_configure_one_fmu(void);
extern int test_configure_one_fmu_mt(void);
extern int test_configure_mt_instantiate_fails(void);
extern int test_logger_two_instances(void);
extern int test_logger_fmi3_null_callback(void);
extern int test_instantiate_invalid_arguments(void);
extern int test_locale_decimal_comma(void);
extern int test_malformed_container_txt(void);
extern int test_malformed_datalog_txt(void);
extern int test_start_value_refused(void);
extern int test_start_value_array(void);
extern int test_datalog_rows(void);

/* Helper: writes content into a temporary file of the test directory. Returns 0 on success. */
extern int test_write_file(const char *dirname, const char *filename, const char *content);

#endif
