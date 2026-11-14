#include <string.h>

#include "fmi2Functions.h"

#include "container.h"
#include "test.h"

/*
 * Worker threads of the multi-thread mode: started at the end of the warm-up (MT_WARMUP internal steps) for the heavy
 * FMUs only, stopped by container_free(), also when the configuration fails.
 */

static int configure_fixture(const char *name, int *status) {
    char location[4096];
    container_t *container = container_new(name, "{uuid}", 2);

    TEST_ASSERT(container != NULL);
    snprintf(location, sizeof(location), "file://%s/%s", TEST_FIXTURES_DIR, name);
    *status = container_configure(container, location);
    container_free(container);  /* must not hang nor crash */

    return 0;
}


int test_configure_one_fmu(void) {
    int status;

    TEST_ASSERT_EQUAL_INT(0, configure_fixture("one_fmu", &status));
    TEST_ASSERT_EQUAL_INT(0, status);

    return 0;
}


int test_configure_one_fmu_mt(void) {
    int status;

    TEST_ASSERT_EQUAL_INT(0, configure_fixture("one_fmu_mt", &status));
    TEST_ASSERT_EQUAL_INT(0, status);

    return 0;
}


int test_configure_mt_instantiate_fails(void) {
    int status;

    TEST_ASSERT_EQUAL_INT(0, configure_fixture("mt_instantiate_fails", &status));
    TEST_ASSERT(status != 0);

    return 0;
}


/* Silent logger: the fixtures of the multi-thread mode log their mode as warnings. */
static void quiet_logger(fmi2ComponentEnvironment environment, fmi2String instanceName, fmi2Status status,
                         fmi2String category, fmi2String message, ...) {
    (void)environment; (void)instanceName; (void)status; (void)category; (void)message;
}


/* Instantiates the fixture `name` (two stub FMUs, see two_fmus_fixture of CMakeLists.txt) and runs `steps` internal
   steps (the internal step of the fixture is 0.1 s, one per fmi2DoStep). */
static fmi2Component simulate(const char *name, int steps, fmi2CallbackFunctions *functions) {
    char location[4096];

    snprintf(location, sizeof(location), "file://%s/%s", TEST_FIXTURES_DIR, name);
    memset(functions, 0, sizeof(*functions));
    functions->logger = quiet_logger;
    fmi2Component c = fmi2Instantiate(name, fmi2CoSimulation, "{uuid}", location, functions, fmi2False, fmi2False);
    if (!c)
        return NULL;
    if (fmi2SetupExperiment(c, fmi2False, 0.0, 0.0, fmi2False, 100.0) != fmi2OK ||
        fmi2EnterInitializationMode(c) != fmi2OK || fmi2ExitInitializationMode(c) != fmi2OK) {
        fmi2FreeInstance(c);
        return NULL;
    }
    for (int i = 0; i < steps; i += 1) {
        if (fmi2DoStep(c, 0.1 * i, 0.1, fmi2True) != fmi2OK) {
            fmi2FreeInstance(c);
            return NULL;
        }
    }
    return c;
}


static unsigned int expected_workers(unsigned int nb_heavy) {
    const unsigned int nb_cores = thread_nb_cores();
    return nb_heavy < nb_cores - 1 ? nb_heavy : nb_cores - 1;
}


int test_mt_warmup_then_hybrid(void) {
    fmi2CallbackFunctions functions;

    fmi2Component c = simulate("mt_hybrid", MT_WARMUP - 1, &functions);
    TEST_ASSERT(c != NULL);
    const container_t *container = (const container_t *)c;
    TEST_ASSERT_EQUAL_INT(0, container->nb_threads);            /* still in the warm-up */
    TEST_ASSERT_EQUAL_INT(1, container->mt_warmup);

    TEST_ASSERT_EQUAL_INT(fmi2OK, fmi2DoStep(c, 0.1 * (MT_WARMUP - 1), 0.1, fmi2True));
    TEST_ASSERT_EQUAL_INT(0, container->mt_warmup);
    TEST_ASSERT_EQUAL_INT(expected_workers(1), container->nb_threads);
    if (container->nb_threads) {
        TEST_ASSERT_EQUAL_INT(1, container->nb_light);
        TEST_ASSERT(container->light_fmu[0] == &container->fmu[0]);     /* the light stub on the main thread */
        TEST_ASSERT_EQUAL_INT(1, container->workers[0].nb_fmu);
        TEST_ASSERT(container->workers[0].fmu[0] == &container->fmu[1]);   /* the slow one on the worker */
    }

    for (int i = MT_WARMUP; i < MT_WARMUP + 5; i += 1)
        TEST_ASSERT_EQUAL_INT(fmi2OK, fmi2DoStep(c, 0.1 * i, 0.1, fmi2True));
    fmi2Real value = 0.0;
    const fmi2ValueReference vr = 1;                            /* port linked to the start value 2.5 of FMU#0 */
    TEST_ASSERT_EQUAL_INT(fmi2OK, fmi2GetReal(c, &vr, 1, &value));
    TEST_ASSERT(value == 2.5);
    fmi2FreeInstance(c);                                        /* must not hang nor crash */

    return 0;
}


int test_mt_all_heavy(void) {
    fmi2CallbackFunctions functions;

    fmi2Component c = simulate("mt_all_heavy", MT_WARMUP + 5, &functions);
    TEST_ASSERT(c != NULL);
    const container_t *container = (const container_t *)c;
    TEST_ASSERT_EQUAL_INT(expected_workers(2), container->nb_threads);
    if (container->nb_threads) {
        unsigned int nb_fmu = 0;
        for (unsigned int i = 0; i < container->nb_workers; i += 1)
            nb_fmu += container->workers[i].nb_fmu;
        TEST_ASSERT_EQUAL_INT(2, nb_fmu);
        TEST_ASSERT_EQUAL_INT(0, container->nb_light);
        TEST_ASSERT(container->workers[0].fmu[0] == &container->fmu[1]);   /* the longest first */
    }
    fmi2FreeInstance(c);

    return 0;
}


int test_mt_no_heavy(void) {
    fmi2CallbackFunctions functions;

    fmi2Component c = simulate("mt_no_heavy", MT_WARMUP + 5, &functions);
    TEST_ASSERT(c != NULL);
    const container_t *container = (const container_t *)c;
    TEST_ASSERT_EQUAL_INT(0, container->nb_threads);            /* the mono-thread parallel mode goes on */
    TEST_ASSERT_EQUAL_INT(2, container->nb_light);
    fmi2FreeInstance(c);

    return 0;
}
