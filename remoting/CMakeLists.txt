#    ___                                               __   __              
#  .'  _|.--------.--.--.  .----.-----.--------.-----.|  |_|__|.-----.-----.
#  |   _||        |  |  |  |   _|  -__|        |  _  ||   _|  ||     |  _  |
#  |__|  |__|__|__|_____|  |__| |_____|__|__|__|_____||____|__||__|__|___  |
#  Copyright 2023 Renault SAS                                        |_____|
#  The remoting code is written by Nicolas.LAURENT@Renault.com. 
#  This code is released under the 2-Clause BSD license.
#

cmake_minimum_required(VERSION 3.18)
project (remoting)
set(VERSION "1.0")

set (CMAKE_C_STANDARD 99)
option(BUILD_32 "Build for 32bits target" OFF)
option(BUILD_TESTER "Build tester executbale" OFF)

if (WIN32)
    if ("${CMAKE_SIZEOF_VOID_P}" STREQUAL "8")
        set(FMI_PLATFORM win64)
    else ()
        set(FMI_PLATFORM win32)
	endif ()
else ()
    set(THREADS_PREFER_PTHREAD_FLAG ON)
    find_package(Threads REQUIRED)
    
    include(CheckFunctionExists)
    check_function_exists(semtimedop HAVE_SEMTIMEDOP)

    if (APPLE)
        set(FMI_PLATFORM darwin64)
        # Compilation in 32 bits mode is no longer supported in MacOS 
    else ()
        if (BUILD_32)
           set(FMI_PLATFORM linux32)
           set(BITNESS "-m32")
        else ()
           set(FMI_PLATFORM linux64)
        endif ()
    endif()

endif ()

configure_file(${CMAKE_CURRENT_SOURCE_DIR}/config.h.in
    ${CMAKE_CURRENT_BINARY_DIR}/config.h)

message("FMI_PLATFORM: ${FMI_PLATFORM}")

if (MSVC)
  add_compile_definitions(_CRT_SECURE_NO_WARNINGS)
endif ()

#
# shared memory server
#
add_executable(server_sm
    communication.c communication.h
    process.c process.h 
    remote.c remote.h
    server.c server.h
    ${CMAKE_CURRENT_BINARY_DIR}/config.h
)

set_target_properties(server_sm PROPERTIES COMPILE_OPTIONS "${BITNESS}" LINK_FLAGS "${BITNESS}")
target_include_directories(server_sm PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/../fmi
    ${CMAKE_CURRENT_BINARY_DIR})

if (UNIX)
    target_link_libraries(server_sm ${CMAKE_DL_LIBS})
    if (NOT APPLE)
        target_link_libraries(server_sm rt Threads::Threads)
    endif()
endif ()

set_target_properties(server_sm PROPERTIES
					  RUNTIME_OUTPUT_DIRECTORY_RELEASE "${CMAKE_CURRENT_SOURCE_DIR}/../fmu_manipulation_toolbox/resources/${FMI_PLATFORM}"
					  RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/../fmu_manipulation_toolbox/resources/${FMI_PLATFORM}")


#
# shared memory client_sm #
#
add_library(client_sm SHARED
	client.c client.h
    communication.c communication.h
    process.c process.h 
    remote.c remote.h
    ${CMAKE_CURRENT_BINARY_DIR}/config.h
)

set_target_properties(client_sm PROPERTIES PREFIX "" COMPILE_OPTIONS "${BITNESS}" LINK_FLAGS "${BITNESS}")

target_include_directories(client_sm PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/../fmi
    ${CMAKE_CURRENT_BINARY_DIR})

if (UNIX AND NOT APPLE)
        target_link_libraries(client_sm rt Threads::Threads)
endif()

set_target_properties(client_sm PROPERTIES
					  RUNTIME_OUTPUT_DIRECTORY_RELEASE "${CMAKE_CURRENT_SOURCE_DIR}/../fmu_manipulation_toolbox/resources/${FMI_PLATFORM}"
					  LIBRARY_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/../fmu_manipulation_toolbox/resources/${FMI_PLATFORM}")

#
# test_sizeof
#
if (BUILD_TESTER)
    add_executable(test_sizeof
        ${CMAKE_CURRENT_SOURCE_DIR}/test_sizeof.c
        remote.h
    )

    add_custom_command(OUTPUT test_sizeof.c
        COMMAND python ${CMAKE_CURRENT_SOURCE_DIR}/gen_sizeof.py
        DEPENDS gen_sizeof.py
    )


    add_executable(test_server
        ${CMAKE_CURRENT_SOURCE_DIR}/test_server.c
    )
    #target_link_libraries(test_server client_sm)
    target_include_directories(test_server PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/../fmi
    )

    target_include_directories(test_sizeof PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/../fmi
    )

endif ()
