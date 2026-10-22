# -----------------------------------------------------------------------------
# Profile-Guided Optimization (PGO)
#
# Workflow:
#   1. Configure with -DFMUTOOL_PGO=GENERATE and build. The binaries are
#      instrumented (~2-3x slower) and write raw profile data at runtime to
#      <build dir>/pgo-data/.
#   2. Use the instrumented binaries in a representative FMU simulation (long
#      enough to cover the hot paths).
#   3. For Clang only, merge the raw profiles:
#        llvm-profdata merge -output=pgo-data/default.profdata pgo-data/*.profraw
#      GCC produces .gcda files consumed as-is.
#   4. Reconfigure with -DFMUTOOL_PGO=USE and rebuild.
#
# Notes:
#   - Requires a matching source tree between GENERATE and USE builds.
#   - Instrumentation runtime is linked automatically (Clang: libclang_rt.profile,
#     GCC: libgcov). MSVC PGO requires the MSVC toolset (not clang-cl).
# -----------------------------------------------------------------------------
set(FMUTOOL_PGO "OFF" CACHE STRING "PGO mode: OFF, GENERATE, or USE")
set_property(CACHE FMUTOOL_PGO PROPERTY STRINGS "OFF" "GENERATE" "USE")

set(FMUTOOL_PGO_DIR "${CMAKE_BINARY_DIR}/pgo-data")
if(NOT FMUTOOL_PGO STREQUAL "OFF")
    file(MAKE_DIRECTORY "${FMUTOOL_PGO_DIR}")
endif()

# fmutool_pgo(<target>): applies FMUTOOL_PGO to the target.
function(fmutool_pgo target)
    if(FMUTOOL_PGO STREQUAL "GENERATE")
        if(MSVC)
            # /GENPROFILE requires /LTCG (enabled by IPO).
            target_link_options(${target} PRIVATE /GENPROFILE)
        else()
            target_compile_options(${target} PRIVATE -fprofile-generate=${FMUTOOL_PGO_DIR})
            target_link_options(${target}    PRIVATE -fprofile-generate=${FMUTOOL_PGO_DIR})
        endif()
    elseif(FMUTOOL_PGO STREQUAL "USE")
        if(MSVC)
            # /USEPROFILE requires /LTCG (enabled by IPO).
            target_link_options(${target} PRIVATE /USEPROFILE)
        elseif(CMAKE_C_COMPILER_ID MATCHES "Clang")
            # Clang expects a merged .profdata file.
            target_compile_options(${target} PRIVATE -fprofile-use=${FMUTOOL_PGO_DIR}/default.profdata)
            target_link_options(${target}    PRIVATE -fprofile-use=${FMUTOOL_PGO_DIR}/default.profdata)
        else()
            # GCC consumes .gcda files directly from the directory.
            target_compile_options(${target} PRIVATE -fprofile-use=${FMUTOOL_PGO_DIR} -fprofile-correction)
            target_link_options(${target}    PRIVATE -fprofile-use=${FMUTOOL_PGO_DIR})
        endif()
    endif()
endfunction()
