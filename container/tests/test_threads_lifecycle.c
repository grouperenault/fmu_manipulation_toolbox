#include "container.h"
#include "test.h"

/*
 * Worker threads of the multi-thread mode: started by the configuration, stopped by container_free(), also when
 * the configuration fails.
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
