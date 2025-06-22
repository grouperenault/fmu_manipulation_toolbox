#
# Nicolas.LAURENT@Renault.com
#
# To build for 64bits, use `cmake -A x64` and `cmake --config Release`
# To build for 32bits, use `cmake -A x86` and `cmake --config Release`
#

cmake_minimum_required(VERSION 3.20)
project(container C)
set (CMAKE_C_STANDARD 99)


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
message("FMI_PLATFORM: ${FMI_PLATFORM}")

####################
# Create CONTAINER #
####################
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

