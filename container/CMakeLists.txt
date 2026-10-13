cmake_minimum_required(VERSION 3.21)
project(container C)
include(${CMAKE_CURRENT_SOURCE_DIR}/../cmake/fmutool.cmake)

# -----------------------------------------------------------------------------
# FMI sanity check: FMI 2.0 and 3.0 data types must share the same storage.
# -----------------------------------------------------------------------------
try_run(test_fmi test_fmi_compilation
    ${CMAKE_CURRENT_BINARY_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}/test_fmi.c
    CMAKE_FLAGS "-DINCLUDE_DIRECTORIES=${CMAKE_CURRENT_SOURCE_DIR}/../fmu_manipulation_toolbox/resources/fmi"
    COMPILE_OUTPUT_VARIABLE test_fmi_compilation_output
    RUN_OUTPUT_VARIABLE test_fmi_output
)
if(NOT test_fmi_compilation OR NOT test_fmi EQUAL 0)
    message(FATAL_ERROR "FMI sanity check failed:\n${test_fmi_compilation_output}${test_fmi_output}")
endif()

# -----------------------------------------------------------------------------
# container: the shared library embedded in the container FMUs.
# -----------------------------------------------------------------------------
add_library(container SHARED
    config.c    config.h
    container.c container.h
    convert.c   convert.h
    datalog.c   datalog.h
    fmi2.c
    fmi3.c
    fmu.c       fmu.h
    hash.c      hash.h
    library.c   library.h
    logger.c    logger.h
    profile.c   profile.h
    solver.c    solver.h
    thread.c    thread.h
)
if(WIN32)
    target_link_libraries(container PRIVATE Imagehlp.lib)
elseif(NOT APPLE)
    target_link_libraries(container PRIVATE Threads::Threads)
endif()
fmutool_native_target(container)

fmutool_summary()
