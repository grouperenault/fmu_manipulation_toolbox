cmake_minimum_required(VERSION 3.21)
project(container C)
set (CMAKE_C_STANDARD 23)


# -----------------------------------------------------------------------------
# Build options (cross-platform: Windows / Linux / macOS)
# -----------------------------------------------------------------------------
option(CONTAINER_WARNINGS_AS_ERRORS "Treat compiler warnings as errors"      OFF)
option(CONTAINER_STRICT_CONVERSION  "Enable -Wconversion / -Wsign-conversion" OFF)
option(CONTAINER_ENABLE_SANITIZERS  "Enable AddressSanitizer (+UBSan on GCC/Clang)" OFF)

# Default to Release if the user didn't pick a build type (single-config generators only)
if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
    set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

# Interface target carrying warning flags — applied to every container target.
add_library(container_warnings INTERFACE)

if(MSVC)
    target_compile_options(container_warnings INTERFACE
        /W4
        /permissive-
        /wd4068    # unknown pragma (harmless across compilers)
    )
    if(CONTAINER_WARNINGS_AS_ERRORS)
        target_compile_options(container_warnings INTERFACE /WX)
    endif()
    if(CONTAINER_STRICT_CONVERSION)
        target_compile_options(container_warnings INTERFACE /w14242 /w14254 /w14287)
    endif()
    # Silence CRT "deprecation" noise for strdup/snprintf/etc.
    target_compile_definitions(container_warnings INTERFACE
        _CRT_SECURE_NO_WARNINGS
        _CRT_NONSTDC_NO_DEPRECATE
    )
else()
    # GCC and Clang (incl. AppleClang)
    target_compile_options(container_warnings INTERFACE
        -Wall
        -Wextra
        -Wpedantic
        -Wshadow
        -Wpointer-arith
        -Wstrict-prototypes
        -Wmissing-prototypes
        -Wnull-dereference
        -Wdouble-promotion
        -Wformat=2
        -Wno-unknown-pragmas
    )
    if(CONTAINER_WARNINGS_AS_ERRORS)
        target_compile_options(container_warnings INTERFACE -Werror)
    endif()
    if(CONTAINER_STRICT_CONVERSION)
        target_compile_options(container_warnings INTERFACE -Wconversion -Wsign-conversion)
    endif()
endif()

# Sanitizers (interface target; opt-in via CONTAINER_ENABLE_SANITIZERS)
add_library(container_sanitizers INTERFACE)
if(CONTAINER_ENABLE_SANITIZERS)
    if(MSVC)
        # MSVC: ASan only (UBSan not supported). Requires VS 2019 16.9+.
        target_compile_options(container_sanitizers INTERFACE /fsanitize=address)
        # MSVC ASan is incompatible with /RTC* and /INCREMENTAL
        target_compile_options(container_sanitizers INTERFACE /Oy- /Zi)
        message(STATUS "Sanitizers: AddressSanitizer (MSVC)")
    else()
        set(_san_flags -fsanitize=address -fsanitize=undefined -fno-omit-frame-pointer)
        target_compile_options(container_sanitizers INTERFACE ${_san_flags})
        target_link_options   (container_sanitizers INTERFACE ${_san_flags})
        message(STATUS "Sanitizers: AddressSanitizer + UndefinedBehaviorSanitizer")
    endif()
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


# Version.h creation
find_package(Git QUIET)
if(NOT Git_FOUND)
    message(WARNING "Git not found")
    set(GIT_TAG, "LOCAL Version")
else()
    execute_process(
        COMMAND ${GIT_EXECUTABLE} describe --tags --always
        WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
        OUTPUT_VARIABLE GIT_TAG
        OUTPUT_STRIP_TRAILING_WHITESPACE
        RESULT_VARIABLE GIT_RESULT
    )
endif()
message("--- Version: ${GIT_TAG}")
configure_file(
    ${CMAKE_SOURCE_DIR}/version.h.in
    ${CMAKE_CURRENT_BINARY_DIR}/version.h
)

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
set_target_properties(container PROPERTIES PREFIX "")
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
					  RUNTIME_OUTPUT_DIRECTORY_RELEASE "${CMAKE_CURRENT_SOURCE_DIR}/../fmu_manipulation_toolbox/resources/${FMI_PLATFORM}"
					  LIBRARY_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/../fmu_manipulation_toolbox/resources/${FMI_PLATFORM}")

# Apply common warning flags and (optional) sanitizers
target_link_libraries(container PRIVATE container_warnings container_sanitizers)

