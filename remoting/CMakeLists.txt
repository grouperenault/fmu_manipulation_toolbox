# Remoting client and server, built by the root project (CMakeLists.txt at the
# root of the repository), which includes the common settings and handles the
# 32-bit builds (BUILD_32).
project(remoting C)

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
