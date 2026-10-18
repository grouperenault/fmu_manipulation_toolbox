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
set(CONTAINER_SOURCES
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

# container_link_platform(<target>): system libraries of the runtime.
function(container_link_platform target)
    if(WIN32)
        target_link_libraries(${target} PRIVATE Imagehlp.lib)
    elseif(NOT APPLE)
        target_link_libraries(${target} PRIVATE Threads::Threads)
    endif()
endfunction()

add_library(container SHARED ${CONTAINER_SOURCES})
container_link_platform(container)
fmutool_native_target(container)

# -----------------------------------------------------------------------------
# Native tests: the sources of the runtime compiled again with the tests, so
# that the internal functions can be called (the shared library exports only
# the FMI API). Run with: ctest --test-dir <build dir> -C <config>
# -----------------------------------------------------------------------------
include(CTest)
if(BUILD_TESTING)
    add_executable(container_tests
        ${CONTAINER_SOURCES}
        tests/test.h
        tests/test_main.c
        tests/test_config.c
        tests/test_configure.c
        tests/test_logger.c
        tests/test_locale.c
        tests/test_thread.c
        tests/test_threads_lifecycle.c
    )
    target_link_libraries(container_tests PRIVATE fmutool_flags)
    target_include_directories(container_tests PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}
        ${FMUTOOL_CMAKE_DIR}/../fmu_manipulation_toolbox/resources/fmi
        ${CMAKE_CURRENT_BINARY_DIR}     # version.h
    )
    target_compile_definitions(container_tests PRIVATE
        TEST_DATA_DIR="${CMAKE_CURRENT_SOURCE_DIR}/tests/data"
        TEST_BINARY_DIR="${CMAKE_CURRENT_BINARY_DIR}"
    )
    container_link_platform(container_tests)
    add_dependencies(container_tests version_h)
    add_test(NAME container_tests COMMAND container_tests)

    # FMI 2.0 FMU of the tests, embedded in the fixtures made of tests/data/one_fmu/container.txt.in.
    add_library(stub_fmu MODULE tests/stub_fmu.c)
    target_link_libraries(stub_fmu PRIVATE fmutool_flags)
    target_include_directories(stub_fmu PRIVATE ${FMUTOOL_CMAKE_DIR}/../fmu_manipulation_toolbox/resources/fmi)
    if(WIN32)
        set(_stub_suffix ".dll")
    elseif(APPLE)
        set(_stub_suffix ".dylib")
    else()
        set(_stub_suffix ".so")
    endif()
    set_target_properties(stub_fmu PROPERTIES PREFIX "" SUFFIX "${_stub_suffix}" C_VISIBILITY_PRESET hidden)
    add_dependencies(container_tests stub_fmu)

    set(TEST_FIXTURES_DIR "${CMAKE_CURRENT_BINARY_DIR}/fixtures")
    target_compile_definitions(container_tests PRIVATE TEST_FIXTURES_DIR="${TEST_FIXTURES_DIR}")

    # container_fixture(<name> <guid> <mt>): container.txt with the stub FMU, given its GUID (which selects its
    # behaviour, see tests/stub_fmu.c) and the multi-thread flag.
    function(container_fixture name guid mt)
        set(GUID "${guid}")
        set(MT "${mt}")
        set(_dir "${TEST_FIXTURES_DIR}/${name}")
        configure_file(tests/data/one_fmu/container.txt.in "${_dir}/container.txt" @ONLY)
        add_custom_command(TARGET stub_fmu POST_BUILD
            COMMAND ${CMAKE_COMMAND} -E make_directory "${_dir}/00/binaries/${FMI_PLATFORM}"
            COMMAND ${CMAKE_COMMAND} -E copy $<TARGET_FILE:stub_fmu> "${_dir}/00/binaries/${FMI_PLATFORM}/stub${_stub_suffix}"
        )
    endfunction()
    container_fixture(one_fmu               "{stub}"                    0)
    container_fixture(one_fmu_datalog       "{stub}"                    0)
    set(DATALOG_FILE "${TEST_FIXTURES_DIR}/one_fmu_datalog/datalog.csv")
    configure_file(tests/data/one_fmu/datalog.txt.in "${TEST_FIXTURES_DIR}/one_fmu_datalog/datalog.txt" @ONLY)
    container_fixture(one_fmu_mt            "{stub}"                    1)
    container_fixture(mt_instantiate_fails  "{stub-fail-instantiate}"   1)
endif()

fmutool_summary()
