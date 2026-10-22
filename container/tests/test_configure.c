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
    TEST_ASSERT_EQUAL_INT(1, container->nb_local_reals64);
    TEST_ASSERT_EQUAL_INT(2, container->nb_local_integers32);
    TEST_ASSERT_EQUAL_INT(1, container->nb_ports_reals64);
    TEST_ASSERT_EQUAL_INT(1, container->nb_ports_strings);
    TEST_ASSERT(container->strings[0] != NULL);
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
