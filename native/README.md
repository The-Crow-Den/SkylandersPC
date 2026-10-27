# Original native pack host

This C++20 host loads the framework's privately prepared `SKYPS401` image packs.
It is independent of shadPS4 and does not invoke the AppImage. It validates pack
structure, optionally maps guest memory, applies supported internal relocations
and binds a small exact-scope libc service set. Inspect/load modes never call the
guest entry. The separate `--trace-start PACK IMPORT_TYPES` diagnostic attempts
startup and stops at the first imported call or fault; it is not a full runtime.

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
other relocation types are refused. TLS relocations are not supported.

Import names use canonical `NID#actualLibraryName#actualModuleName` identities.
`hle/pure_libc.cpp` binds only its explicitly implemented exact identities; it is
not an allocator, OS, threading, TLS or exception runtime. The host reports
resolved/pending import records and relocation-site counts separately.

## Current real-data structural evidence

The first private Trap Team pack inspected and loaded at guest base `0x400000`:
two segments spanning 22,585,344 bytes; 114,973 internal relocations applied;
640 import records; six pure libc bindings resolved six sites; 634 import records
and 1,446 sites remained unresolved. The entry was not called and no guest
executable permissions were enabled. Private results are under
`out/native-trap-team-initial/`; game bytes and packs remain ignored.

CTest runs synthetic pack validation/loading cases and the pure-libc ABI tests.
The synthetic executable entry is an INT3 trap so accidental execution would
fail the test. This infrastructure milestone does not establish boot,
gameplay, renderer support or correctness of unimplemented PS4 services.

## Diagnostic startup checkpoint

The linked eboot/libc/Fios image under `out/native-linked-initial` was attempted
once with `--trace-start`, under a five-second external timeout. It executed
startup instructions and stopped with exit70 on the unresolved libkernel data
import `__stack_chk_guard` (NID f7uOxY9mM1U), in linked libc at PC27070048.
Private evidence: `out/native-linked-initial/entry-trace.log`.

Function imports are redirected to named stopping thunks, including otherwise
implemented libc functions, because a returning host-call bridge is not ready.
Unimplemented data imports point at inaccessible guard pages. Fault/import bridges restore
host FS and stack before reporting and terminating. The diagnostic TCB is a
minimal zeroed observation context, not complete PS4 TLS initialization. Linked
module initializers have not been run. No rendered custom-host boot is claimed.

The linked pack adds bounded local DTPMOD64 relocation support: type16 stores
the assigned TLS module ID1..16 with zero addend; imported/other TLS forms remain
unsupported. Module placement, TLS templates and exact binding evidence are
recorded in the private linked-pack metadata.

The next startup attempt passed the libc stack-canary read after adding an
exact-scope, object-only `__stack_chk_guard` binding. The diagnostic process
generates its guard with Linux `getrandom` before guest entry and exposes a
read-only page for its lifetime. Randomness/protection failures abort setup.
This provider currently belongs to diagnostic execution; normal loader binding
counts are unchanged. Synthetic execution tests cover a successful read followed
by a named function trap, wrong scope/type rejection and write protection.

Private evidence: `out/native-linked-initial/entry-trace-canary.log`. Startup now
stops at `F8bUHwAG284#libkernel#libkernel`, identified by the supplied reference
import table as `scePthreadMutexattrInit`. The next prerequisite is a tested
returning host-call bridge that restores host FS around services and guest FS
before resuming, followed by real mutex-attribute semantics. Returning dummy
success from the stopping thunk would not provide those semantics. This remains
startup execution evidence, with no custom rendering or visible boot yet.
