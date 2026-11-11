#include <stdarg.h>
#include <string.h>

#include "fmi2Functions.h"

#include "container.h"
#include "test.h"

/*
 * Configuration of a container from its container.txt (container_configure).
 */

int test_configure_empty(void) {
    container_t *container = container_new("empty", "{uuid}", 2);

    TEST_ASSERT(container != NULL);
    TEST_ASSERT_EQUAL_INT(0, container_configure(container, "file://" TEST_DATA_DIR "/empty"));
    TEST_ASSERT_EQUAL_INT(0, container->nb_fmu);
    TEST_ASSERT_EQUAL_INT(1, container->reals64.nb_locals);
    TEST_ASSERT_EQUAL_INT(2, container->integers32.nb_locals);
    TEST_ASSERT_EQUAL_INT(1, container->reals64.nb_ports);
    TEST_ASSERT_EQUAL_INT(1, container->strings.nb_ports);
    TEST_ASSERT(container->strings.locals[0].data != NULL);      /* a string is never NULL */
    container_free(container);

    return 0;
}


int test_container_new_null(void) {
    TEST_ASSERT(container_new(NULL, "{uuid}", 2) == NULL);
    TEST_ASSERT(container_new("name", NULL, 2) == NULL);

    container_t *container = container_new("name", "{uuid}", 2);
    TEST_ASSERT(container != NULL);
    TEST_ASSERT(container->logger.callback.logger_fmi2 == NULL);   /* every member starts at zero */
    TEST_ASSERT(container_configure(container, NULL) != 0);        /* no resources */
    container_free(container);

    return 0;
}


static void test_print_logger(fmi2ComponentEnvironment environment, fmi2String instanceName, fmi2Status status,
                              fmi2String category, fmi2String message, ...) {
    va_list args;
    (void)environment; (void)instanceName; (void)category;
    if (status != fmi2OK) {
        va_start(args, message);
        vfprintf(stderr, message, args);
        va_end(args);
        fputc('\n', stderr);
    }
}


/* A string output of an FMU reaches the input it is linked to, through a local string (copied without allocation
   once it has the capacity). */
int test_local_strings(void) {
    char location[4096];
    fmi2CallbackFunctions functions;

    snprintf(location, sizeof(location), "file://%s/one_fmu_strings", TEST_FIXTURES_DIR);
    memset(&functions, 0, sizeof(functions));
    functions.logger = test_print_logger;
    fmi2Component container = fmi2Instantiate("strings", fmi2CoSimulation, "{uuid}", location, &functions,
                                              fmi2False, fmi2False);
    TEST_ASSERT(container != NULL);
    TEST_ASSERT_EQUAL_INT(fmi2OK, fmi2SetupExperiment(container, fmi2False, 0.0, 0.0, fmi2False, 1.0));
    TEST_ASSERT_EQUAL_INT(fmi2OK, fmi2EnterInitializationMode(container));
    TEST_ASSERT_EQUAL_INT(fmi2OK, fmi2ExitInitializationMode(container));

    const fmi2ValueReference in = 201326592, out = 201326593;
    const char *values[] = {"short", "a much longer string than the first one", "tiny"};
    double time = 0.0;
    for (size_t i = 0; i < sizeof(values) / sizeof(values[0]); i += 1) {
        fmi2String read = NULL;
        TEST_ASSERT_EQUAL_INT(fmi2OK, fmi2SetString(container, &in, 1, &values[i]));
        TEST_ASSERT_EQUAL_INT(fmi2OK, fmi2DoStep(container, time, 0.1, fmi2True));     /* output -> local */
        time += 0.1;
        TEST_ASSERT_EQUAL_INT(fmi2OK, fmi2DoStep(container, time, 0.1, fmi2True));     /* local -> input */
        time += 0.1;
        TEST_ASSERT_EQUAL_INT(fmi2OK, fmi2GetString(container, &out, 1, &read));
        TEST_ASSERT(read != NULL && strcmp(read, values[i]) == 0);
    }
    fmi2FreeInstance(container);

    return 0;
}


/* An FMU that asks to terminate the simulation (FMI-2.0: fmi2Discard, then fmi2Terminated) ends the simulation of the
   container: fmi2DoStep returns fmi2Discard, fmi2Terminated and fmi2LastSuccessfulTime tell it, no further step. */
int test_terminate_simulation(void) {
    char location[4096];
    fmi2CallbackFunctions functions;

    snprintf(location, sizeof(location), "file://%s/one_fmu_terminate", TEST_FIXTURES_DIR);
    memset(&functions, 0, sizeof(functions));
    functions.logger = test_print_logger;
    fmi2Component container = fmi2Instantiate("terminate", fmi2CoSimulation, "{uuid}", location, &functions,
                                              fmi2False, fmi2False);
    TEST_ASSERT(container != NULL);
    TEST_ASSERT_EQUAL_INT(fmi2OK, fmi2SetupExperiment(container, fmi2False, 0.0, 0.0, fmi2False, 1.0));
    TEST_ASSERT_EQUAL_INT(fmi2OK, fmi2EnterInitializationMode(container));
    TEST_ASSERT_EQUAL_INT(fmi2OK, fmi2ExitInitializationMode(container));

    fmi2Boolean terminated = fmi2True;
    TEST_ASSERT_EQUAL_INT(fmi2OK, fmi2DoStep(container, 0.0, 0.1, fmi2True));
    TEST_ASSERT_EQUAL_INT(fmi2OK, fmi2DoStep(container, 0.1, 0.1, fmi2True));
    TEST_ASSERT_EQUAL_INT(fmi2OK, fmi2GetBooleanStatus(container, fmi2Terminated, &terminated));
    TEST_ASSERT(terminated == fmi2False);

    /* The stub asks to terminate in the step from 0.2 to 0.3 */
    fmi2Real last_time = -1.0;
    TEST_ASSERT_EQUAL_INT(fmi2Discard, fmi2DoStep(container, 0.2, 0.1, fmi2True));
    TEST_ASSERT_EQUAL_INT(fmi2OK, fmi2GetBooleanStatus(container, fmi2Terminated, &terminated));
    TEST_ASSERT(terminated == fmi2True);
    TEST_ASSERT_EQUAL_INT(fmi2OK, fmi2GetRealStatus(container, fmi2LastSuccessfulTime, &last_time));
    TEST_ASSERT(last_time > 0.29 && last_time < 0.31);

    TEST_ASSERT_EQUAL_INT(fmi2Error, fmi2DoStep(container, 0.3, 0.1, fmi2True));    /* no further step */
    fmi2FreeInstance(container);

    return 0;
}
