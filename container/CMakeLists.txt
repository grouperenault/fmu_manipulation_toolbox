cmake_minimum_required(VERSION 3.21)
project(container C)
set (CMAKE_C_STANDARD 23)


# -----------------------------------------------------------------------------
# Build options (cross-platform: Windows / Linux / macOS)
# -----------------------------------------------------------------------------
option(CONTAINER_WARNINGS_AS_ERRORS "Treat compiler warnings as errors"      OFF)
option(CONTAINER_STRICT_CONVERSION  "Enable -Wconversion / -Wsign-conversion" OFF)

# Default to Release if the user didn't pick a build type (single-config generators only)
if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
    set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
    message(STATUS "CMAKE_BUILD_TYPE not set — defaulting to '${CMAKE_BUILD_TYPE}'")
endif()
# Expose the allowed values to cmake-gui / ccmake / VS Code CMake Tools.
set_property(CACHE CMAKE_BUILD_TYPE PROPERTY STRINGS
    Debug Release RelWithDebInfo MinSizeRel)

# Interface target carrying warning flags — applied to every container target.
add_library(container_flags INTERFACE)

if(MSVC)
    target_compile_options(container_flags INTERFACE
        /W4
        /permissive-
        /wd4068    # unknown pragma (harmless across compilers)
    )
    if(CONTAINER_WARNINGS_AS_ERRORS)
        target_compile_options(container_flags INTERFACE /WX)
    endif()
    if(CONTAINER_STRICT_CONVERSION)
        target_compile_options(container_flags INTERFACE /w14242 /w14254 /w14287)
    endif()
    # Silence CRT "deprecation" noise for strdup/snprintf/etc.
    target_compile_definitions(container_flags INTERFACE
        _CRT_SECURE_NO_WARNINGS
        _CRT_NONSTDC_NO_DEPRECATE
    )
    target_compile_options(container_flags INTERFACE
        $<$<CONFIG:Release,RelWithDebInfo>:/fp:fast>
    )
else()
    # GCC and Clang (incl. AppleClang)
    target_compile_options(container_flags INTERFACE
        -Wall
        -Wextra
        -Wshadow
        -Wpointer-arith
        -Wstrict-prototypes
        -Wmissing-prototypes
        -Wnull-dereference
        -Wdouble-promotion
        -Wno-unknown-pragmas
    )
    if(CONTAINER_WARNINGS_AS_ERRORS)
        target_compile_options(container_flags INTERFACE -Werror)
    endif()
    if(CONTAINER_STRICT_CONVERSION)
        target_compile_options(container_flags INTERFACE -Wconversion -Wsign-conversion)
    endif()
    target_compile_options(container_flags INTERFACE
        $<$<CONFIG:Release,RelWithDebInfo>:-O3> 
        $<$<CONFIG:Release,RelWithDebInfo>:-fno-math-errno>
        $<$<CONFIG:Release,RelWithDebInfo>:-fno-trapping-math>
    )
endif()


# FMI Configuration
if (WIN32)
    if ("${CMAKE_SIZEOF_VOID_P}" STREQUAL "8")
        set(FMI_PLATFORM win64)
    else ()
        set(FMI_PLATFORM win32)
        endif ()
else ()
    set(THREADS_PREFER_PTHREAD_FLAG ON)
    find_package(Threads REQUIRED)
    
    if (APPLE)
        set(FMI_PLATFORM darwin64)
    else ()
        set(FMI_PLATFORM linux64)
    endif()
endif ()
message("--- FMI_PLATFORM: ${FMI_PLATFORM}")

# Version.h: regenerated at every build so the git
# version is always current, not frozen at CMake configure time.
set(VERSION_H ${CMAKE_CURRENT_BINARY_DIR}/version.h)
add_custom_target(version_h ALL
    BYPRODUCTS ${VERSION_H}
    COMMAND ${CMAKE_COMMAND}
        -DSRC_DIR=${CMAKE_SOURCE_DIR}
        -DIN_FILE=${CMAKE_SOURCE_DIR}/version.h.in
        -DOUT_FILE=${VERSION_H}
        -P ${CMAKE_SOURCE_DIR}/cmake/gen_version.cmake
    COMMENT "Generating version.h from git"
    VERBATIM
)


# FMI Sanity check
try_run(test_fmi test_fmi_compilation ${CMAKE_CURRENT_BINARY_DIR}/ ${CMAKE_CURRENT_SOURCE_DIR}/test_fmi.c
    CMAKE_FLAGS "-DINCLUDE_DIRECTORIES=${CMAKE_CURRENT_SOURCE_DIR}/../fmi"
    COMPILE_OUTPUT_VARIABLE test_fmi_compilation_output
    RUN_OUTPUT_VARIABLE test_fmi_output)
if("${test_fmi_compilation}" AND ("${test_fmi}" EQUAL 0))
    message(${test_fmi_output})
    message("--- FMI support seems to be OK.")
ELSE()
    # Error on failure and print error message:
    MESSAGE(FATAL_ERROR "Failed check: ${test_fmi_compilation_output}")
ENDIF()


# Create CONTAINER  Shared library
add_library(container SHARED
        config.c    config.h
		container.c	container.h
        convert.c   convert.h
        datalog.c   datalog.h
        fmi2.c
        fmi3.c
		fmu.c		fmu.h
		hash.c      hash.h
		library.c	library.h
		logger.c    logger.h
		profile.c   profile.h
		thread.c    thread.h)
target_include_directories(container PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/../fmi
    ${CMAKE_CURRENT_BINARY_DIR}
)
if (UNIX AND NOT APPLE)
        target_link_libraries(container PRIVATE Threads::Threads)
endif()
if (WIN32)
    target_link_libraries(container PRIVATE Imagehlp.lib)
endif()
set_target_properties(container PROPERTIES
                      PREFIX ""
                      C_VISIBILITY_PRESET hidden
                      VISIBILITY_INLINES_HIDDEN ON
					  RUNTIME_OUTPUT_DIRECTORY_RELEASE "${CMAKE_CURRENT_SOURCE_DIR}/../fmu_manipulation_toolbox/resources/${FMI_PLATFORM}"
					  LIBRARY_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/../fmu_manipulation_toolbox/resources/${FMI_PLATFORM}")

# Apply common warning flags and release-time optimizations
target_link_libraries(container PRIVATE container_flags)

# Enable Link-Time Optimization (IPO) in Release/RelWithDebInfo when supported.
include(CheckIPOSupported)
check_ipo_supported(RESULT _ipo_supported OUTPUT _ipo_output)
if(_ipo_supported)
    set_property(TARGET container PROPERTY
                 INTERPROCEDURAL_OPTIMIZATION_RELEASE TRUE)
    set_property(TARGET container PROPERTY
                 INTERPROCEDURAL_OPTIMIZATION_RELWITHDEBINFO TRUE)
    message(STATUS "IPO/LTO enabled for container (Release/RelWithDebInfo)")
else()
    message(STATUS "IPO/LTO not supported: ${_ipo_output}")
endif()

# -----------------------------------------------------------------------------
# Print the effective compilation flags applied to `container`.
# Generator expressions (e.g. $<$<CONFIG:Release>:...>) are shown unresolved
# at configure time; for the fully-resolved per-config list, look at
# build/CMakeFiles/container.dir/flags.make after generation.
# -----------------------------------------------------------------------------
get_target_property(_container_flags container_flags INTERFACE_COMPILE_OPTIONS)
get_target_property(_container_defs  container_flags INTERFACE_COMPILE_DEFINITIONS)
if(_container_flags)
    string(REPLACE ";" " " _container_flags "${_container_flags}")
else()
    set(_container_flags "")
endif()
if(_container_defs)
    string(REPLACE ";" " " _container_defs "${_container_defs}")
else()
    set(_container_defs "")
endif()
message(STATUS "--- container build summary ---")
message(STATUS "  Build type       : ${CMAKE_BUILD_TYPE}")
message(STATUS "  C compiler       : ${CMAKE_C_COMPILER_ID} ${CMAKE_C_COMPILER_VERSION}")
message(STATUS "  C standard       : C${CMAKE_C_STANDARD}")
message(STATUS "  Compile options  : ${_container_flags}")
if(_container_defs)
    message(STATUS "  Compile defines  : ${_container_defs}")
endif()
message(STATUS "  CFLAGS (global)  : ${CMAKE_C_FLAGS} ${CMAKE_C_FLAGS_${CMAKE_BUILD_TYPE}}")
message(STATUS "-------------------------------")

# Ensure version.h is regenerated before container is compiled, so the current
# git commit id is picked up within the same build.
add_dependencies(container version_h)
