#include <stdio.h>
#include <string.h>

#include "test.h"

/*
 * Runner of the native tests: runs every test, or only the one named on the command line.
 */

static const struct {
    const char          *name;
    test_function_t     function;
} tests[] = {
    { "config_lines",       test_config_lines },
    { "config_long_line",   test_config_long_line },
    { "config_version",     test_config_version },
    { "config_crlf",        test_config_crlf },
    { "thread_barrier",                 test_thread_barrier },
    { "thread_barrier_consecutive",     test_thread_barrier_consecutive },
    { "configure_empty",                test_configure_empty },
    { "local_strings",                  test_local_strings },
    { "terminate_simulation",           test_terminate_simulation },
    { "path_from_uri",                  test_path_from_uri },
    { "path_to_uri",                    test_path_to_uri },
    { "path_join",                      test_path_join },
    { "path_is_directory",              test_path_is_directory },
    { "container_new_null",             test_container_new_null },
    { "configure_one_fmu",              test_configure_one_fmu },
    { "configure_one_fmu_mt",           test_configure_one_fmu_mt },
    { "configure_mt_instantiate_fails", test_configure_mt_instantiate_fails },
    { "logger_two_instances",           test_logger_two_instances },
    { "logger_fmi3_null_callback",      test_logger_fmi3_null_callback },
    { "instantiate_invalid_arguments",  test_instantiate_invalid_arguments },
    { "locale_decimal_comma",           test_locale_decimal_comma },
    { "locale_line_to_host_point",      test_locale_line_to_host_decimal_point },
    { "locale_long_decimal_point",      test_locale_long_decimal_point },
    { "malformed_container_txt",        test_malformed_container_txt },
    { "malformed_datalog_txt",          test_malformed_datalog_txt },
    { "start_value_refused",            test_start_value_refused },
    { "start_value_array",              test_start_value_array },
    { "datalog_rows",                   test_datalog_rows },
    { "datalog_decimal_comma",          test_datalog_decimal_comma },
    { "stub_xcp_fmi2",                  test_stub_xcp_fmi2 },
    { "stub_xcp_fmi3",                  test_stub_xcp_fmi3 },
    { "xcp_configuration_mode",         test_xcp_configuration_mode },
    { "xcp_without_configuration_mode", test_xcp_without_configuration_mode },
    { "xcp_fmi2_before_setup",          test_xcp_fmi2_before_setup_experiment },
    { "cache_read_after_write",         test_cache_read_after_write },
    { "cache_refused_value",            test_cache_refused_value },
    { "cache_order_of_the_calls",       test_cache_order_of_the_calls },
    { "cache_structural_warning",       test_cache_structural_warning },
};


int test_write_file(const char *dirname, const char *filename, const char *content) {
    char path[4096];

    snprintf(path, sizeof(path), "%s/%s", dirname, filename);
    FILE *fp = fopen(path, "wt");
    if (!fp) {
        fprintf(stderr, "Cannot write '%s'\n", path);
        return -1;
    }
    fputs(content, fp);
    fclose(fp);

    return 0;
}


int main(int argc, char **argv) {
    int failed = 0;
    int run = 0;

    setvbuf(stdout, NULL, _IONBF, 0);   /* nothing lost if a test hangs and is killed */

    for (size_t i = 0; i < sizeof(tests) / sizeof(tests[0]); i += 1) {
        if (argc > 1 && strcmp(argv[1], tests[i].name) != 0)
            continue;
        run += 1;
        const int status = tests[i].function();
        printf("%-32s %s\n", tests[i].name, status ? "FAILED" : "ok");
        failed += status ? 1 : 0;
    }

    if (run == 0) {
        fprintf(stderr, "No test named '%s'\n", argc > 1 ? argv[1] : "");
        return 2;
    }

    return failed ? 1 : 0;
}
