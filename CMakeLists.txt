# Root project: builds the native components (container, remoting) in one build
# tree. The platforms are described by CMakePresets.json, used by the CI:
#     cmake --list-presets
#     cmake --workflow --preset <platform>
cmake_minimum_required(VERSION 3.25)

# 32-bit Linux build. Set before project() so that the compiler checks, and
# therefore FMI_PLATFORM, see a 32-bit target. (macOS: no 32-bit support,
# Windows: use the -A Win32 generator option instead.)
option(BUILD_32 "Build for a 32-bit Linux target" OFF)
if(BUILD_32)
    string(APPEND CMAKE_C_FLAGS " -m32")
endif()

project(fmutool_native C)
include(${CMAKE_CURRENT_SOURCE_DIR}/cmake/fmutool.cmake)
include(CTest)

option(FMUTOOL_BUILD_CONTAINER "Build the container runtime" ON)
option(FMUTOOL_BUILD_REMOTING  "Build the remoting client and server" ON)

if(FMUTOOL_BUILD_CONTAINER)
    add_subdirectory(container)
endif()
if(FMUTOOL_BUILD_REMOTING)
    add_subdirectory(remoting)
endif()
