# Linux x86-64 entry and diagnostic bridges

`guest_start.S` provides an original, deliberately limited entry probe. It uses
Linux arch_prctl syscalls to capture host FS, select a supplied guest TCB, call
an entry on a separate aligned stack, then restore host FS/stack/registers on a
normal return. Startup and exit-callback pointers are passed in RDI and RSI.
No host libc call runs while guest FS is selected.

The API is declared in `guest_start.hpp`. Caller-supplied entry, TCB, stack and
output memory must remain valid. The stack's top 16 bytes are reserved by the
bridge; the entry is called with SysV stack alignment. This is not proof of the
complete Orbis process-entry stack contract. Arbitrary guest faults cannot
return safely through the normal-return path.

Optional diagnostic handlers enable a single-active-guest guard. An unknown
function thunk puts its import index in R10 and jumps to
`sky_guest_trap_bridge`. That bridge restores host FS and the original host
stack before calling the configured host handler. A signal handler installed
with SA_SIGINFO and SA_ONSTACK can use `sky_guest_fault_bridge`, which forwards
the original signal/info/ucontext to its host handler after the same restoration.
Both handlers must terminate; a returning handler exits with code 126, and failed
FS restoration exits with code 127. No unknown service is treated as successful.

These are stop-and-diagnose paths. Returning HLE calls, argument/XMM-state
marshalling, TLS module initialization, guest threads with diagnostic contexts,
guest exit handling, nonlocal returns and signal resumption remain unsupported.
Pure libc host bindings must not be called directly while guest FS is active.
The normal-return bridge is tested independently on several host threads; the
configured diagnostic path intentionally permits only one active guest thread.

Standalone synthetic tests, requiring no game or GPU:

```sh
cmake -S native/tests/guest_start -B .local/guest-start-build -G Ninja
cmake --build .local/guest-start-build
ctest --test-dir .local/guest-start-build --output-on-failure
```

Tests check guest FS:0, host FS restoration, startup pointers, guest register
clobbering, invalid-argument/kernel rejection, per-thread plain entries, an import
trap with exact index and a SIGSEGV diagnostic on an alternate signal stack.
Only original tiny assembly probe functions execute in these tests. Real-game
entry requires an explicit guarded integration decision by the main host.
