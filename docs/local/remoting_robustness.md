# Robustness of the native code of the remoting

**Created**: 18 October 2026 — **Status**: draft, decisions to take — **Branch**: to be decided (from `integration`)
— **Roadmap**: not listed

## Context

A review of the native code of the remoting (`remoting/*.c`, 18 October 2026) found the following weaknesses. The
Python side (`fmu_manipulation_toolbox/remoting.py`) only generates Windows configurations (win32 ↔ win64), but the
CI also builds the remoting for Linux 32 / 64 bits.

### A. FMI semantics

1. **Values set during the Initialization Mode are not forwarded before `fmi2ExitInitializationMode`.** The client
   only marks them as `changed`; `RPC_fmi2ExitInitializationMode` (`remoting/server.c:521`) does not call
   `update_values_from_client()`: they are applied at the first `fmi2DoStep`.
2. **Outputs are stale after `fmi2ExitInitializationMode` and `fmi2Reset`.** The buffers are refreshed only after
   `fmi2EnterInitializationMode` (`initialize()`) and after `fmi2DoStep`.
3. **`fmi2Warning` is handled as an error.** `do_step()`, `initialize()` and `update_values_from_client()` stop at
   `status != fmi2OK`: on a warning of `fmi2SetReal` or `fmi2DoStep`, the outputs are not read back.
4. **The resource location is altered.** `fmi2Instantiate` (`remoting/client.c:425-428`) strips `file://` and the
   leading `/`, and the server forwards this plain path to the FMU instead of the URI. `%20` and other escapes are not
   decoded when the client opens `remoting_table.txt`. On POSIX the path becomes relative.
5. `loggingOn` and `visible` are not forwarded (the server always passes `fmi2False`), `fmuType` is not checked
   (Model Exchange accepted), `fmi2SetDebugLogging` is a no-op.

### B. Collisions between instances

6. **IPC key** (`client_new_key()`, `client.c:314`): CRC32 of the resource location + PID + `time()` (1 s
   resolution). Two instances of the same FMU instantiated within the same second in one process get the same key.
   On Windows, `CreateSemaphoreA` / `CreateFileMappingA` then silently open the existing objects
   (`ERROR_ALREADY_EXISTS` is not checked): both instances share the semaphores and the shared memory.

### C. Server command line (Windows)

7. `process_spawn()` (`remoting/process.c`) joins the arguments with spaces **without quoting**: a path with a space
   (`C:\Program Files\...`, user profile, temporary directory of the importer) breaks the launch of the server.
8. `strncat(dst, src, sizeof(dst) - strlen(dst))` overflows by one byte (`process.c`, `client_module_path()`): the
   bound must be `sizeof - strlen - 1`.

### D. Lifecycle and cleanup

9. **Orphan server.** When `client_new()` fails after the spawn (server not responding) or when
   `RPC_fmi2Instantiate` fails (`client.c:448`), the client frees everything without `RPC_fmi2FreeInstance` nor
   terminating the server: the server lives as long as the host. On POSIX the semaphores are also removed
   (`IPC_RMID`): `semtimedop` returns -1, which is "true" for the watchdog loop: busy loop at 100 % CPU.
10. **Leaks and invalid handles in `client_new()`**: `malloc` not checked; on a failure of `communication_new()`, `fp`
    is not closed and `instance_name` / `client` leak; on a failure of `spawn_server()`, no `client_free()` (shared
    memory and semaphores leak); the error paths before the spawn call `client_free()` with an uninitialized
    `server_handle` (`CloseHandle(garbage)`).
11. `communication_new_client()`: when the creation of the first semaphore fails, `server_ready` is uninitialized and
    freed by `communication_free()`.
12. `server_new()` does not check `communication_new() == NULL` before `communication_data_initialize()`.
13. `process_spawn()` on POSIX returns -1 on a `fork()` failure: `!client->server_handle` does not detect it.

### E. Bounds and formats

14. `get_pos()` (`client.c:519`) with `nb == 0` reads `vr_table[-1]` and may return index 0 of an empty array.
15. `strncpy()` into `shm->instance_name` / `shm->token` (128 bytes) and `resource_directory` does not guarantee the
    final `'\0'`: the `strdup()` of the server may overrun.
16. `LOG_ERROR(..., "vr=%lu", vr[i])`: `fmi2ValueReference` is `unsigned int` (`%u`).

### F. Logging

17. Every message of the server is forwarded as `fmi2Warning`: the status and the category given by the FMU are lost.
18. The client calls the logger with `category = NULL`.
19. Inconsistent categories in `server.c`: `"[SERVER]"`, `"SERVER"`, `"SERVER]"`.
20. Messages beyond 4 KB (`COMMUNICATION_MESSAGE_SIZE`) are silently truncated.

### G. Detection of the death of the peer

21. Windows: the client and the server poll every 3 s (`COMMUNICATION_TIMEOUT_DEFAULT`).
    `WaitForMultipleObjects({semaphore, process handle})` would detect the death at once.

### H. Protocol of the shared memory

22. No magic nor version in `communication_shm_t`: a mismatch between client and server is not detected.
23. No `static_assert` on the layout shared by a 32-bit and a 64-bit process.
24. The `int` arrays that follow the `bool` arrays are not aligned (tolerated on x86, undefined behaviour).

### I. POSIX only

25. `mmap()` returns `MAP_FAILED`, not `NULL`: its failure is not detected. The `shm_open()` descriptor is never
    closed; `ftruncate()` not checked; `shm_join()` result not checked.
26. `process_is_alive()` uses `kill(pid, 0)`, which succeeds on a zombie: a crashed server is never detected, the
    client waits forever. `process_waitfor()` uses `WNOHANG` right after `FreeInstance`: zombie left.
27. The child calls `exit(-1)` when `execv()` fails (runs the `atexit` handlers and flushes the stdio buffers of the
    host): `_exit(127)` expected. All the descriptors of the host are inherited.
28. Without `semtimedop` (macOS), the client DLL installs a `SIGALRM` handler and uses `ITIMER_REAL`: process-wide,
    overrides the ones of the host, not thread-safe.
29. `ftok()` + files in `/tmp` + `IPC_EXCL`: `ftok()` collisions and leftovers of crashes make the instantiation
    fail. `IPC_PRIVATE` semaphores whose ids are stored in the shared memory would remove the files and `ftok()`.
30. `communication_sem_free()` tests `if (sem)`: SysV id 0 is valid (leak), -1 passes the test.
31. `#define _GNU_SOURCE` comes after `<stdlib.h>` in `communication.c`: no effect (`semtimedop` may be undeclared;
    to be checked against the CI build logs).
32. The client and the server both call `shm_unlink()` / `IPC_RMID`: the resources should belong to the client only.

### J. Consistency with `modelDescription.xml`

33. `remoting.py` keeps the capability flags of the original FMU: an FMU that declares `canGetAndSetFMUstate`,
    `canSerializeFMUstate`, `providesDirectionalDerivative`, a `<ModelExchange>` element or String variables
    advertises functions that the client answers with `fmi2Error`. String variables are only logged as "not supported".

### K. Quality

34. The reals / integers / booleans blocks are duplicated in `client.c`, `server.c` and `communication.c`;
    `communication_timedwaitfor_client()` / `_server()` are copies; `get_pos()` could use `bsearch()`.
35. No native test of the remoting; the integration test (`tests/integration/test_remoting.py`) needs a 32-bit
    Windows FMU and runs only on Windows.

## Decisions to take

None of the following is decided yet. Each must be answered before the implementation starts.

1. **Scope**: all the points above, or a subset (e.g. A–G + J first, H / I / K later)?
2. **Branch**: name of the branch (from `integration`), e.g. `remoting-robustness`. Worktree or main checkout?
3. **POSIX support** (points 25–32): fix it fully, keep it compiling only, or drop it (the user documentation
   mentions Linux, the Python side does not generate it)?
4. **Timed wait on macOS** (point 28), if POSIX is kept: polling with `IPC_NOWAIT` + `nanosleep()`, pipes /
   `poll()` between client and server (also detect the death of the peer by EOF), or no macOS support?
5. **Native tests** (point 35): a CTest target with a stub FMI 2.0 FMU (reuse of `container/tests/stub_fmu.c`) run
   through a same-bitness "front-end" configuration, so that the remoting is tested on every CI platform? Which
   scenarios (two instances in one process, path with a space, server crash, warning statuses...)?
6. **Failure after the spawn** (point 9): send `RPC_fmi2FreeInstance` then wait with a timeout, or terminate the
   server at once (`TerminateProcess` / `kill(SIGKILL)`)?
7. **IPC key** (point 6): which source of uniqueness — per-process counter, address of the `client_t`, random bytes
   (`BCryptGenRandom` / `getrandom`)? Fail or retry with a new key on `ERROR_ALREADY_EXISTS` / `EEXIST`?
8. **Resource location** (point 4): pass the original URI to the FMU and decode it (percent-decoding, `file:///C:/`
   vs `file:///home`) only to open `remoting_table.txt` — confirm.
9. **`fmi2SetDebugLogging` and `loggingOn`** (point 5): new RPC `RPC_fmi2SetDebugLogging` with the categories
   copied into the shared memory, or only the flag `loggingOn` forwarded at instantiation?
10. **Log protocol** (points 17–20): a list of entries (status, category, text) in the shared memory, or a single
    buffer with a status / category prefix per line? Behaviour on overflow (truncation notice, flush in several
    RPCs)?
11. **Protocol header** (point 22): magic + version checked by the server at the first RPC; on a mismatch, the
    instantiation fails with an explicit message — confirm.
12. **`modelDescription.xml`** (point 33): rewrite the capability flags / remove `<ModelExchange>` when the remoting
    is added, or refuse the operation (with an explicit error) when the FMU declares something unsupported?
    String variables: refuse, or keep them unreachable with a warning?
13. **Refactoring** (point 34): in this plan, or separately?
14. **Order of the steps**: tests first (as for `native_robustness`), then the fixes?

## Steps (proposal, to be adjusted to the decisions)

### Step 1 – Native test target (point 35, decision 5)

- `remoting/CMakeLists.txt`: `include(CTest)`; under `BUILD_TESTING`, a stub FMI 2.0 FMU (shared library, same
  bitness) and a test executable that loads `client_sm` as an importer would and drives `server_sm`.
- First scenarios: instantiate / step / free; two instances of the same FMU in one process.
- `.github/workflows`: run `ctest` after the native build of the remoting.

Commit message: `Add a CTest target for the native remoting`

### Step 2 – Unique IPC key (point 6, decision 7)

- `client_new_key()`: add the chosen source of uniqueness; the key keeps fitting in `COMMUNICATION_KEY_LEN`.
- `communication_sem_create()` / `communication_shm_create()` on Windows: fail (or retry) on
  `ERROR_ALREADY_EXISTS`.
- Test: two instances of the same FMU instantiated in the same second.

Commit message: `Give each remoting instance a unique IPC key`

### Step 3 – Server command line and bounds (points 7, 8, 14, 15, 16)

- `process_spawn()` (Windows): quote each argument (escaping of `"` and trailing `\` as `CommandLineToArgvW`
  expects).
- `strncat()` bounds fixed; `strncpy()` into the shared memory replaced by a bounded copy that always ends with `'\0'`
  (`snprintf`), with an error when the value is truncated.
- `get_pos()`: `-1` when `nb == 0` (or replaced by `bsearch()`).
- `%u` for the value references.
- Test: FMU stored in a directory whose path contains a space.

Commit message: `Quote the command line of the remoting server and fix string bounds`

### Step 4 – Lifecycle and cleanup (points 9–13, decision 6)

- `client_new()`: `calloc()`, `server_handle` initialized to an invalid value, one cleanup path that closes `fp`,
  frees `instance_name`, the communication and the client.
- Failure after the spawn: stop the server as decided, then wait for it.
- `communication_new()`: every handle initialized to its invalid value before any creation.
- `server_new()`: check `communication_new()`; `process_spawn()` failure detected on POSIX.
- Tests: server binary missing; instantiation refused by the stub FMU — no orphan process, no leaked object.

Commit message: `Clean up the remoting client and server on every failure path`

### Step 5 – FMI semantics (points 1–5, decisions 8, 9)

- Server: pending values applied before every RPC that needs them (Enter / Exit Initialization Mode, `DoStep`,
  `Terminate`), buffers refreshed after Enter / Exit Initialization Mode, `DoStep` and `Reset`.
- `fmi2Warning` (and `fmi2Discard` for `DoStep`) no longer stop the exchange; the worst status is returned.
- Resource location: as decided (decision 8).
- `fmuType`: `NULL` returned for Model Exchange; `loggingOn` / `fmi2SetDebugLogging` as decided (decision 9).
- Tests with the stub FMU: value set between Enter and Exit is seen by `ExitInitializationMode`; output computed at
  Exit is read back; a warning of `DoStep` still updates the outputs.

Commit message: `Forward the values and statuses of the initialization through the remoting`

### Step 6 – Logging (points 17–20, decision 10)

- Shared memory log protocol as decided; status and category of the FMU kept; client category set (e.g.
  `"remoting"`); server categories made consistent; overflow reported.
- Test: messages of each status emitted by the stub FMU are received with the same status.

Commit message: `Keep the status and category of the messages of the remoted FMU`

### Step 7 – Death of the peer on Windows (point 21)

- `communication_timedwaitfor_server()` / `_client()` take the process handle of the peer and use
  `WaitForMultipleObjects()`; the polling loops of `make_rpc()` and of the main loop of the server are simplified.
- Test: the stub FMU crashes in `DoStep`: the client returns `fmi2Fatal` without waiting for the timeout.

Commit message: `Detect the death of the remoting peer without polling on Windows`

### Step 8 – Protocol of the shared memory (points 22–24, decision 11)

- `communication_shm_t`: magic + protocol version, checked at `RPC_fmi2Instantiate`.
- Each array of the data area aligned on 8 bytes; `communication_shm_size()` and `communication_data_initialize()`
  updated together.
- `static_assert` on the offsets of `communication_shm_t`.

Commit message: `Version and align the shared memory of the remoting`

### Step 9 – POSIX (points 25–32, decisions 3, 4)

- Depending on decision 3: `MAP_FAILED`, descriptor closed, `ftruncate()` / `shm_join()` checked; `waitpid()` for the
  liveness and the end of the server; `_exit(127)` and `O_CLOEXEC` / `posix_spawn()`; no `SIGALRM` (decision 4);
  `IPC_PRIVATE` semaphores whose ids are stored in the shared memory; resources owned by the client;
  `_GNU_SOURCE` defined before any system header (or through CMake).
- Tests: the CTest target of step 1 on Linux (and macOS if kept).

Commit message: `Fix the POSIX implementation of the remoting`

### Step 10 – Consistency with `modelDescription.xml` (point 33, decision 12)

- `remoting.py`: as decided (capability flags rewritten / `<ModelExchange>` removed, or explicit refusal).
- Python test on an FMU that declares the unsupported capabilities.

Commit message: `Keep the model description consistent with the capabilities of the remoting`

### Step 11 – Refactoring (point 34, decision 13)

- One generic helper per operation for the three types (macro or table of descriptors); one timed wait function
  with the semaphore as a parameter; `bsearch()`.
- No change of behaviour; the tests of the previous steps pass unchanged.

Commit message: `Factorize the per-type code of the remoting`

### Step 12 – User documentation

- `docs/user-guide/fmutool/remoting.md`: supported platforms (decision 3), limitations (Strings, FMU state,
  directional derivatives, Model Exchange) and how the model description is adapted (decision 12), behaviour on a
  crash of the server, logging of the remoted FMU.
- `docs/API/remoting.md` if the Python API changes; changelog entry.

Commit message: `Document the robustness changes of the remoting`
