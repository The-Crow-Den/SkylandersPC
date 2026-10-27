# Original native pack host

This C++20 host loads and runs the framework's privately prepared `SKYPS401`
image packs. It is independent of shadPS4 and does not invoke the AppImage.
`--inspect`/`--load` only validate and map a pack and never call the guest
entry. `--run PACK IMPORT_TYPES [BOOT_PLAN [GAME_ROOT]]` (alias `--trace-start`)
executes the guest through `GuestRuntime`; `tools/run_session.py` uses it.

```sh
cmake -S native -B .local/native-build -G Ninja -DCMAKE_BUILD_TYPE=Debug
cmake --build .local/native-build
ctest --test-dir .local/native-build --output-on-failure
.local/native-build/skylanders-native-host --inspect /path/to/private/image.pack
.local/native-build/skylanders-native-host --load /path/to/private/image.pack
```

Plain `PACK` is equivalent to `--inspect`. Inspection does not reserve a guest
address space or apply relocations. `--load` requires Linux
`MAP_FIXED_NOREPLACE`, maps the declared page-aligned guest base, zero-fills the
arena, copies file-backed segment bytes, and applies relocations. An occupied
range is an error: MAP_FIXED is never used to overwrite existing mappings.
Current mapping has a zero base slide. The arena is unmapped when the host exits.

Every unresolved import remains explicit and its relocation slot retains the
original bytes. No successful dummy return or zero address is installed. If any
import relocation remains pending, executable permissions are withheld. A zero
exit code means structural inspection/loading succeeded, never that a game booted.

## Pack contract

All integers are little-endian. Payload offsets are absolute file offsets.

| Record | Layout |
| --- | --- |
| Header | `8s6Q`: magic `SKYPS401`, entry VA, image base, image size, segment count, relocation count, import count |
| Segment | `5Q`: guest VA, memory size, file size, ELF PF flags, payload offset |
| Relocation | `QQQq`: target VA, type, symbol/import value, signed addend |
| Import | 128-byte UTF-8 string, NUL terminated and zero padded |

Tables follow the header in segment/relocation/import order. Nonempty segment
payloads follow the tables. Segments must fit the image and may not overlap in
memory; payload ranges and eight-byte relocation targets may not overlap either.
The entry must be within an executable segment. Maximum file and image size is
512 MiB; count/range/overflow checks run before mapping.

Supported relocation types are x86-64 ABS64 (1), GLOB_DAT (6), JUMP_SLOT (7) and
RELATIVE (8). Bit 63 marks an imported relocation; its symbol value is then an
import-record index. Defined symbols are guest VAs. RELATIVE requires symbol zero
and computes base slide plus addend. ABS64 adds its signed addend to its defined
or resolved symbol. GLOB_DAT/JUMP_SLOT require zero addend. Imported RELATIVE and
other relocation types are refused. Local DTPMOD64 (16) stores a TLS module ID 1..16 with zero addend; other TLS
relocations are refused.

Import names use canonical `NID#actualLibraryName#actualModuleName` identities.
`hle/pure_libc.cpp` binds only its explicitly implemented exact identities; it is
not an allocator, OS, threading, TLS or exception runtime. The host reports
resolved/pending import records and relocation-site counts separately.

## Runtime layout

| Piece | Files | Role |
| --- | --- | --- |
| Loader | `main.cpp` | Pack validation, fixed no-replace mapping, relocations, permissions |
| Runtime | `guest_runtime.*` | Import thunks, service dispatch, fault reporting, module init and entry |
| Bridge | `guest_start.*`, `bridge_features.cpp` | Guest/host FS (TLS) switching, calls, callbacks, thread exit |
| Threads | `thread_context.*`, `hle/kernel_thread.*` | Guest stacks, TCB/DTV, per-thread TLS blocks |
| Services | `hle/*` | Exact-NID HLE services; unknown imports terminate with a report |
| Graphics/audio | `gpu_backend.*` | Optional pinned bbport component (`SKY_BBPORT_GPU`) |
| Game hooks | `game_hooks.*`, `trap_team_hooks.*` | Exact-build (executable SHA-256) game-specific probes |

Game-specific host code must go through `GameHooks`. A hook activates only when
the game root's `eboot.bin` matches a registered executable hash; shared code
never checks a title ID before reading fixed guest addresses.

Threads: finished detached guest threads release their stack and TLS; joinable
threads release on join. Guest-visible stacks and TLS are mapped below 2 GiB
(`MAP_32BIT`) as during bring-up; whether any title requires this is unverified.

File I/O: `hle/kernel_file.cpp` guards its descriptor tables with a lock but
performs blocking reads/writes outside it, so one stalled read does not block
other threads' file calls.

The bring-up history (first structural load, first entry attempt, startup
stops) is kept in `docs/NATIVE_BRINGUP_20261021.md` and
`docs/CUSTOM_BOOT_PROGRESS_20261021.md`.
