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
