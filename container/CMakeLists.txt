# Container runtime, built by the root project (CMakeLists.txt at the root of
# the repository), which includes the common settings and CTest.
project(container C)

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
    cache.c     cache.h
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
if(BUILD_TESTING)
    add_executable(container_tests
        ${CONTAINER_SOURCES}
        tests/test.h
        tests/test_main.c
        tests/test_config.c
        tests/test_configure.c
        tests/test_logger.c
        tests/test_locale.c
        tests/test_malformed.c
        tests/test_datalog.c
        tests/test_thread.c
        tests/test_threads_lifecycle.c
        tests/test_stub_xcp.c
        tests/test_xcp_container.c
    )
    target_link_libraries(container_tests PRIVATE fmutool_flags)
    target_include_directories(container_tests PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}
        ${FMUTOOL_CMAKE_DIR}/../fmu_manipulation_toolbox/resources/fmi
        ${FMUTOOL_GENERATED_DIR}        # version.h
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

    # FMUs of FMI-LS-XCP of the tests (descriptors in tests/data/ls-xcp of the repository), one per FMI version.
    foreach(_version 2 3)
        set(_target stub_xcp_fmi${_version})
        add_library(${_target} MODULE tests/stub_xcp_fmi${_version}.c tests/stub_xcp.h)
        target_link_libraries(${_target} PRIVATE fmutool_flags)
        target_include_directories(${_target} PRIVATE ${FMUTOOL_CMAKE_DIR}/../fmu_manipulation_toolbox/resources/fmi)
        set_target_properties(${_target} PROPERTIES PREFIX "" SUFFIX "${_stub_suffix}" OUTPUT_NAME stub_xcp
                              C_VISIBILITY_PRESET hidden
                              LIBRARY_OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/${_target}")
        add_dependencies(container_tests ${_target})
        target_compile_definitions(container_tests PRIVATE
            STUB_XCP_FMI${_version}_LIBRARY="$<TARGET_FILE:${_target}>")
    endforeach()
    file(MAKE_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/stub_xcp")     # journal of the stubs

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
    container_fixture(one_fmu_terminate     "{stub-terminate}"          0)
    container_fixture(malformed             "{stub}"                    0)  # container.txt rewritten by the tests
    container_fixture(one_fmu_strings       "{stub}"                    0)  # container.txt replaced below
    set(GUID "{stub}")
    set(MT 0)
    configure_file(tests/data/one_fmu/strings.txt.in "${TEST_FIXTURES_DIR}/one_fmu_strings/container.txt" @ONLY)

    # Fixtures of FMI-LS-XCP: tests/data/xcp/container_fmi<2|3>.txt with the stub FMU of the same FMI version, in the
    # binaries directory of its FMI version (FMU2_BINDIR / FMU3_BINDIR of fmu.h).
    if(WIN32)
        set(_fmi3_platform "$<IF:$<EQUAL:${CMAKE_SIZEOF_VOID_P},8>,x86_64-windows,x86-windows>")
    elseif(APPLE)
        if(CMAKE_SYSTEM_PROCESSOR MATCHES "arm64|aarch64")
            set(_fmi3_platform "aarch64-darwin")
        else()
            set(_fmi3_platform "x86_64-darwin")
        endif()
    else()
        set(_fmi3_platform "x86_64-linux")
    endif()
    foreach(_version 2 3)
        if(_version EQUAL 2)
            set(_platform "${FMI_PLATFORM}")
        else()
            set(_platform "${_fmi3_platform}")
        endif()
        set(_dir "${TEST_FIXTURES_DIR}/xcp_fmi${_version}")
        configure_file(tests/data/xcp/container_fmi${_version}.txt "${_dir}/container.txt" COPYONLY)
        add_custom_command(TARGET stub_xcp_fmi${_version} POST_BUILD
            COMMAND ${CMAKE_COMMAND} -E make_directory "${_dir}/00/binaries/${_platform}" "${_dir}/00/resources"
            COMMAND ${CMAKE_COMMAND} -E copy $<TARGET_FILE:stub_xcp_fmi${_version}>
                    "${_dir}/00/binaries/${_platform}/stub_xcp${_stub_suffix}"
        )
    endforeach()
endif()

fmutool_summary()
