cmake_minimum_required(VERSION 3.21)

# 32-bit Linux build. Set before project() so that the compiler checks, and
# therefore FMI_PLATFORM, see a 32-bit target. (macOS: no 32-bit support,
# Windows: use the -A Win32 generator option instead.)
option(BUILD_32 "Build for a 32-bit Linux target" OFF)
if(BUILD_32)
    string(APPEND CMAKE_C_FLAGS " -m32")
endif()

project(remoting C)
include(${CMAKE_CURRENT_SOURCE_DIR}/../cmake/fmutool.cmake)

if(NOT WIN32)
    include(CheckFunctionExists)
    check_function_exists(semtimedop HAVE_SEMTIMEDOP)
endif()
configure_file(config.h.in ${CMAKE_CURRENT_BINARY_DIR}/config.h)

# -----------------------------------------------------------------------------
# server_sm: the executable that loads the original FMU.
# -----------------------------------------------------------------------------
add_executable(server_sm
    communication.c communication.h
    process.c       process.h
    server.c        server.h
)
if(UNIX)
    target_link_libraries(server_sm PRIVATE ${CMAKE_DL_LIBS})
endif()
if(UNIX AND NOT APPLE)
    target_link_libraries(server_sm PRIVATE rt Threads::Threads)
endif()
fmutool_native_target(server_sm)

# -----------------------------------------------------------------------------
# client_sm: the shared library embedded in the FMU, talking to server_sm.
# -----------------------------------------------------------------------------
add_library(client_sm SHARED
    client.c        client.h
    communication.c communication.h
    process.c       process.h
)
if(UNIX AND NOT APPLE)
    target_link_libraries(client_sm PRIVATE rt Threads::Threads)
endif()
fmutool_native_target(client_sm)

fmutool_summary()
