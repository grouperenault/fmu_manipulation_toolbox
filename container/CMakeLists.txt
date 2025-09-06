cmake_minimum_required(VERSION 3.20)
project(container C)
set (CMAKE_C_STANDARD 99)


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
		container.c	container.h
        convert.c convert.h
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
        target_link_libraries(container Threads::Threads)
endif()
if (WIN32)
    target_link_libraries(container Imagehlp.lib)
endif()
set_target_properties(container PROPERTIES
					  RUNTIME_OUTPUT_DIRECTORY_RELEASE "${CMAKE_CURRENT_SOURCE_DIR}/../fmu_manipulation_toolbox/resources/${FMI_PLATFORM}"
					  LIBRARY_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/../fmu_manipulation_toolbox/resources/${FMI_PLATFORM}")
					  
#target_compile_options(container PRIVATE /W4 /WX)

