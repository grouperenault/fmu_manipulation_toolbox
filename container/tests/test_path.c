#include <string.h>

#include "path.h"
#include "test.h"

/*
 * Paths of the file system and `file` URIs (path.c).
 */

#ifdef _WIN32
#   define NATIVE(posix, windows)  windows
#else
#   define NATIVE(posix, windows)  posix
#endif


int test_path_from_uri(void) {
    char path[64];

    TEST_ASSERT_EQUAL_INT(0, path_from_uri(NATIVE("file:///var/a%20b/res", "file:///C:/a%20b/res"), path, sizeof(path)));
    TEST_ASSERT(strcmp(path, NATIVE("/var/a b/res", "C:\\a b\\res")) == 0);
    TEST_ASSERT_EQUAL_INT(0, path_from_uri(NATIVE("file:/var/x", "file:/C:/x"), path, sizeof(path)));     /* no authority */
    TEST_ASSERT(strcmp(path, NATIVE("/var/x", "C:\\x")) == 0);
    TEST_ASSERT_EQUAL_INT(0, path_from_uri(NATIVE("/var/x", "C:/x"), path, sizeof(path)));               /* a path */
    TEST_ASSERT(strcmp(path, NATIVE("/var/x", "C:\\x")) == 0);
    TEST_ASSERT_EQUAL_INT(-1, path_from_uri("file:///a/much/longer/path/than/the/buffer", path, 8));
    TEST_ASSERT(strlen(path) < 8);

    return 0;
}


int test_path_to_uri(void) {
    char uri[64];

    TEST_ASSERT_EQUAL_INT(0, path_to_uri(NATIVE("/var/a b/r%s", "C:\\a b\\r%s"), uri, sizeof(uri)));
    TEST_ASSERT(strcmp(uri, NATIVE("file:///var/a%20b/r%25s", "file:///C:/a%20b/r%25s")) == 0);
    TEST_ASSERT_EQUAL_INT(-1, path_to_uri("/a/much/longer/path/than/the/buffer", uri, 12));
    TEST_ASSERT(strlen(uri) < 12);

    /* A round trip gives the path again */
    char path[64];
    TEST_ASSERT_EQUAL_INT(0, path_to_uri(NATIVE("/tmp/x~y_z-1.2", "D:\\x~y_z-1.2"), uri, sizeof(uri)));
    TEST_ASSERT_EQUAL_INT(0, path_from_uri(uri, path, sizeof(path)));
    TEST_ASSERT(strcmp(path, NATIVE("/tmp/x~y_z-1.2", "D:\\x~y_z-1.2")) == 0);

    return 0;
}


int test_path_join(void) {
    char path[16];

    path[0] = '\0';
    TEST_ASSERT_EQUAL_INT(0, path_join(path, sizeof(path), "a", "b", NULL));
    TEST_ASSERT(strcmp(path, "a" PATH_SEPARATOR_STR "b") == 0);

    strcpy(path, "a/");                                                     /* no doubled separator */
    TEST_ASSERT_EQUAL_INT(0, path_join(path, sizeof(path), "/00", NULL));
    TEST_ASSERT(strcmp(path, "a/00") == 0);

    strcpy(path, "a");                                                      /* a trailing separator */
    TEST_ASSERT_EQUAL_INT(0, path_join(path, sizeof(path), "", NULL));
    TEST_ASSERT(strcmp(path, "a" PATH_SEPARATOR_STR) == 0);

    strcpy(path, "abcdef");
    TEST_ASSERT_EQUAL_INT(-1, path_join(path, sizeof(path), "ghijklmnop", NULL));
    TEST_ASSERT(strlen(path) < sizeof(path));

    return 0;
}


int test_path_is_directory(void) {
    TEST_ASSERT(path_is_directory(TEST_DATA_DIR));
    TEST_ASSERT(!path_is_directory(TEST_DATA_DIR "/not-a-directory"));
    TEST_ASSERT(!path_is_directory(TEST_DATA_DIR "/one_fmu/container.txt.in"));

    return 0;
}
