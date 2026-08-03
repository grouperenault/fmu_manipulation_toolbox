# Regenerates version.h from version.h.in with the current git description.
# Run at build time (cmake -P) so the version always reflects the current commit.
find_package(Git QUIET)
if(NOT Git_FOUND)
    set(GIT_TAG "LOCAL Version")
else()
    execute_process(
        COMMAND ${GIT_EXECUTABLE} describe --tags --always
        WORKING_DIRECTORY ${SRC_DIR}
        OUTPUT_VARIABLE GIT_TAG
        OUTPUT_STRIP_TRAILING_WHITESPACE
        RESULT_VARIABLE GIT_RESULT
    )
    if(NOT GIT_RESULT EQUAL 0)
        set(GIT_TAG "LOCAL Version")
    endif()
endif()
message("--- Version: ${GIT_TAG}")
configure_file(${IN_FILE} ${OUT_FILE} @ONLY)
