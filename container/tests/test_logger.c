#include <stdarg.h>
#include <string.h>

#include "fmi2Functions.h"
#include "fmi3Functions.h"

#include "container.h"
#include "test.h"

/*
 * Logger of each instance of the container: the messages of an instance reach its own callback, with its own
 * environment and instance name, whatever the other instances do.
 */

typedef struct {
    int             nb_messages;
    int             nb_debug;
    char            instance_name[64];
} logger_environment_t;


static void test_logger_fmi2(fmi2ComponentEnvironment environment, fmi2String instanceName, fmi2Status status,
                             fmi2String category, fmi2String message, ...) {
    logger_environment_t *env = environment;
    (void)category; (void)message;

    env->nb_messages += 1;
    if (status == fmi2OK)
        env->nb_debug += 1;
    strncpy(env->instance_name, instanceName, sizeof(env->instance_name) - 1);
}


static fmi2Component instantiate_fmi2(const char *name, logger_environment_t *env, fmi2CallbackFunctions *functions,
                                      fmi2Boolean logging_on) {
    char location[4096];

    snprintf(location, sizeof(location), "file://%s/one_fmu", TEST_FIXTURES_DIR);
    memset(functions, 0, sizeof(*functions));
    functions->logger = test_logger_fmi2;
    functions->componentEnvironment = env;

    return fmi2Instantiate(name, fmi2CoSimulation, "{uuid}", location, functions, fmi2False, logging_on);
}


int test_logger_two_instances(void) {
    logger_environment_t env1 = { 0 }, env2 = { 0 };
    fmi2CallbackFunctions functions1, functions2;

    fmi2Component c1 = instantiate_fmi2("first", &env1, &functions1, fmi2True);
    TEST_ASSERT(c1 != NULL);
    fmi2Component c2 = instantiate_fmi2("second", &env2, &functions2, fmi2False);
    TEST_ASSERT(c2 != NULL);

    TEST_ASSERT(env1.nb_debug > 0);         /* debug messages of the first instance... */
    TEST_ASSERT_EQUAL_INT(0, env2.nb_debug);  /* ...but not of the second one */
    TEST_ASSERT(strcmp(env1.instance_name, "first") == 0);

    fmi2FreeInstance(c1);                   /* the second instance keeps its own logger */
    const int nb1 = env1.nb_messages;
    const int nb2 = env2.nb_messages;
    TEST_ASSERT(fmi2ExitInitializationMode(c2) == fmi2Error);   /* wrong state: logs an error */
    TEST_ASSERT_EQUAL_INT(nb1, env1.nb_messages);
    TEST_ASSERT_EQUAL_INT(nb2 + 1, env2.nb_messages);
    TEST_ASSERT(strcmp(env2.instance_name, "second") == 0);

    TEST_ASSERT(fmi2SetDebugLogging(c2, fmi2True, 0, NULL) == fmi2OK);    /* this instance only */
    fmi2FreeInstance(c2);
    TEST_ASSERT(env2.nb_debug > 0);
    TEST_ASSERT_EQUAL_INT(nb1, env1.nb_messages);

    return 0;
}


int test_logger_fmi3_null_callback(void) {
    char location[4096];

    snprintf(location, sizeof(location), "%s/one_fmu", TEST_FIXTURES_DIR);
    fmi3Instance instance = fmi3InstantiateCoSimulation("null_logger", "{uuid}", location, fmi3False, fmi3True,
                                                        fmi3False, fmi3False, NULL, 0, NULL, NULL, NULL);
    TEST_ASSERT(instance != NULL);
    TEST_ASSERT(fmi3ExitInitializationMode(instance) == fmi3Error);    /* wrong state: logs an error */
    fmi3FreeInstance(instance);

    return 0;
}


int test_instantiate_invalid_arguments(void) {
    logger_environment_t env = { 0 };
    fmi2CallbackFunctions functions;
    char location[4096];

    snprintf(location, sizeof(location), "file://%s/one_fmu", TEST_FIXTURES_DIR);
    memset(&functions, 0, sizeof(functions));
    functions.logger = test_logger_fmi2;
    functions.componentEnvironment = &env;

    TEST_ASSERT(fmi2Instantiate("name", fmi2CoSimulation, "{uuid}", location, NULL, fmi2False, fmi2False) == NULL);
    TEST_ASSERT(fmi2Instantiate("name", fmi2CoSimulation, NULL, location, &functions, fmi2False, fmi2False) == NULL);
    TEST_ASSERT(fmi3InstantiateCoSimulation("name", "{uuid}", NULL, fmi3False, fmi3False, fmi3False, fmi3False,
                                            NULL, 0, NULL, NULL, NULL) == NULL);

    return 0;
}
