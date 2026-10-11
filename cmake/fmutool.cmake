# Common build settings of the native components (container, remoting).
# Include it right after project():
#     include(${CMAKE_CURRENT_SOURCE_DIR}/../cmake/fmutool.cmake)

set(FMUTOOL_CMAKE_DIR ${CMAKE_CURRENT_LIST_DIR})

option(FMUTOOL_WARNINGS_AS_ERRORS "Treat compiler warnings as errors"       OFF)
option(FMUTOOL_STRICT_CONVERSION  "Enable -Wconversion / -Wsign-conversion" OFF)

set(CMAKE_C_STANDARD 23)

# Default to Release if no build type is given (single-config generators only).
if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
    set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

# -----------------------------------------------------------------------------
# Platform: FMI binaries folder name, where the binaries are written.
# -----------------------------------------------------------------------------
if(CMAKE_SIZEOF_VOID_P EQUAL 8)
    set(_bits 64)
else()
    set(_bits 32)
endif()
if(WIN32)
    set(FMI_PLATFORM win${_bits})
elseif(APPLE)
    set(FMI_PLATFORM darwin64)
else()
    set(FMI_PLATFORM linux${_bits})
endif()

if(NOT WIN32)
    set(THREADS_PREFER_PTHREAD_FLAG ON)
    find_package(Threads REQUIRED)
endif()

set(FMUTOOL_RESOURCES_DIR "${FMUTOOL_CMAKE_DIR}/../fmu_manipulation_toolbox/resources/${FMI_PLATFORM}")
cmake_path(NORMAL_PATH FMUTOOL_RESOURCES_DIR)

# -----------------------------------------------------------------------------
# Compilation flags: warnings and release-time optimizations.
# -----------------------------------------------------------------------------
add_library(fmutool_flags INTERFACE)

if(MSVC)
    target_compile_options(fmutool_flags INTERFACE
        /W4
        /permissive-
        /wd4068    # unknown pragma (harmless across compilers)
        $<$<CONFIG:Release,RelWithDebInfo>:/fp:fast>
    )
    if(FMUTOOL_WARNINGS_AS_ERRORS)
        target_compile_options(fmutool_flags INTERFACE /WX)
    endif()
    if(FMUTOOL_STRICT_CONVERSION)
        target_compile_options(fmutool_flags INTERFACE /w14242 /w14254 /w14287)
    endif()
    # Silence CRT "deprecation" noise for strdup/snprintf/etc.
    target_compile_definitions(fmutool_flags INTERFACE
        _CRT_SECURE_NO_WARNINGS
        _CRT_NONSTDC_NO_DEPRECATE
    )
else()
    # GCC and Clang (incl. AppleClang)
    target_compile_options(fmutool_flags INTERFACE
        -Wall
        -Wextra
        -Wshadow
        -Wpointer-arith
        -Wstrict-prototypes
        -Wmissing-prototypes
        -Wnull-dereference
        -Wdouble-promotion
        -Wno-unknown-pragmas
        $<$<CONFIG:Release,RelWithDebInfo>:-O3>
        $<$<CONFIG:Release,RelWithDebInfo>:-fno-math-errno>
        $<$<CONFIG:Release,RelWithDebInfo>:-fno-trapping-math>
    )
    if(FMUTOOL_WARNINGS_AS_ERRORS)
        target_compile_options(fmutool_flags INTERFACE -Werror)
    endif()
    if(FMUTOOL_STRICT_CONVERSION)
        target_compile_options(fmutool_flags INTERFACE -Wconversion -Wsign-conversion)
    endif()
endif()

# -----------------------------------------------------------------------------
# version.h: regenerated at every build so that the git version is always
# current, not frozen at configure time.
# -----------------------------------------------------------------------------
add_custom_target(version_h ALL
    BYPRODUCTS ${CMAKE_CURRENT_BINARY_DIR}/version.h
    COMMAND ${CMAKE_COMMAND}
        -DSRC_DIR=${FMUTOOL_CMAKE_DIR}
        -DIN_FILE=${FMUTOOL_CMAKE_DIR}/version.h.in
        -DOUT_FILE=${CMAKE_CURRENT_BINARY_DIR}/version.h
        -P ${FMUTOOL_CMAKE_DIR}/gen_version.cmake
    COMMENT "Generating version.h from git"
    VERBATIM
)

include(CheckIPOSupported)
check_ipo_supported(RESULT FMUTOOL_IPO_SUPPORTED OUTPUT _ipo_output)

include(${FMUTOOL_CMAKE_DIR}/pgo.cmake)

# -----------------------------------------------------------------------------
# fmutool_native_target(<target>): applies the common settings to a binary.
# -----------------------------------------------------------------------------
function(fmutool_native_target target)
    target_link_libraries(${target} PRIVATE fmutool_flags)
    target_include_directories(${target} PRIVATE
        ${FMUTOOL_CMAKE_DIR}/../fmi
        ${CMAKE_CURRENT_BINARY_DIR}     # version.h, config.h
    )
    # The generator expression stops multi-config generators (Visual Studio)
    # from appending a per-configuration subdirectory.
    set_target_properties(${target} PROPERTIES
        PREFIX ""
        C_VISIBILITY_PRESET hidden
        RUNTIME_OUTPUT_DIRECTORY "$<1:${FMUTOOL_RESOURCES_DIR}>"
        LIBRARY_OUTPUT_DIRECTORY "$<1:${FMUTOOL_RESOURCES_DIR}>"
    )
    if(FMUTOOL_IPO_SUPPORTED)
        set_target_properties(${target} PROPERTIES
            INTERPROCEDURAL_OPTIMIZATION_RELEASE        ON
            INTERPROCEDURAL_OPTIMIZATION_RELWITHDEBINFO ON
        )
    endif()
    fmutool_pgo(${target})
    add_dependencies(${target} version_h)
endfunction()

# -----------------------------------------------------------------------------
# fmutool_summary(): prints the effective configuration.
# -----------------------------------------------------------------------------
function(fmutool_summary)
    message(STATUS "--- ${PROJECT_NAME} build summary")
    message(STATUS "  Platform    : ${FMI_PLATFORM} -> ${FMUTOOL_RESOURCES_DIR}")
    message(STATUS "  Compiler    : ${CMAKE_C_COMPILER_ID} ${CMAKE_C_COMPILER_VERSION}, C${CMAKE_C_STANDARD}")
    message(STATUS "  Build type  : ${CMAKE_BUILD_TYPE}${CMAKE_CONFIGURATION_TYPES}")
    message(STATUS "  IPO/LTO     : ${FMUTOOL_IPO_SUPPORTED}")
    message(STATUS "  Options     : FMUTOOL_WARNINGS_AS_ERRORS=${FMUTOOL_WARNINGS_AS_ERRORS}"
                   " FMUTOOL_STRICT_CONVERSION=${FMUTOOL_STRICT_CONVERSION} FMUTOOL_PGO=${FMUTOOL_PGO}")
endfunction()
