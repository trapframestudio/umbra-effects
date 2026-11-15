# zgo_native.dll: the native add-on (experimental)

Optional engine add-on for Umbra Gore & Effects on the xrRazom game
executables. The Lua side, `gamedata/scripts/zgo_native.script`, loads it
through LuaJIT FFI only while MCM -> "Native extensions (experimental)" is on.
That switch is off by default. The DLL needs no per-user setup or bake: it
finds everything it needs in the running exe when it loads.

What it does today:

- **Offset finder (`CAP_FINDER`).** It recognises the exe and verifies every
  engine function it would touch. If anything is unexpected, it reports
  "unsupported exe" and nothing is ever enabled.
- **Bone hooks (`CAP_BONES`).** These post-process the skeleton after
  `CalculateBones`, so Lua can bend, crush or shift single bones. The first
  user is "broken limbs" on bodies near explosions. Lua never runs inside a
  hook. It publishes op sets into DLL memory, and the hook applies them on
  whatever thread the engine poses the body.

## Files

| Path | What |
|---|---|
| `include/zgo_native.h` | The plain C ABI (ABI 1). The Lua `ffi.cdef` must match it (`tests/zgo_test_native.lua` checks). |
| `src/zgo_pe.c/.h` | PE parsing of a mapped image: sections, imports by name. |
| `src/zgo_finder.c/.h` | The offset finder (RTTI -> COL -> vtable -> slot -> byte pattern) and its report. |
| `src/zgo_hook.c/.h` | Minimal x64 inline hooks: an 8-byte compare-and-swap patch, trampolines within 2 GB. |
| `src/zgo_bones.c/.h` | Bound objects, seqlock-published op sets, the post-process, matrix maths. |
| `src/zgo_dll.c` | Exports, detours, DllMain, log ring. |
| `tests/zgo_native_test.c`, `tests/run.sh` | Tests under Wine (below). |
| `Makefile` | Build, test and dependency check. |
| `build/` | Test exe and test logs. Not part of a release. |

No third-party code is vendored: the hook code is our own, so there is no
`third_party/` folder or licence to carry.

## Build

    dev/run.sh make -C native              # -> bin/zgo_native.dll
    dev/run.sh make -C native check-deps   # imports: KERNEL32.dll, msvcrt.dll only
    dev/run.sh make -C native test         # build + run the Wine tests

- **Toolchain.** mingw-w64 gcc (x86_64) from the zgo-dev container
  (`dev/distrobox.ini`).
- **Linking.** Static runtime (`-static -static-libgcc`): no libgcc_s,
  libstdc++ or winpthread DLLs. Stripped, with no timestamp, so builds are
  reproducible.
- **No threads of its own.** Every export runs on the caller's thread (the
  game's main thread, from Lua). The detours run on the engine's threads.

## Tests (`native/tests/run.sh`, Wine)

`run.sh` uses its own Wine prefix, `WINEPREFIX=$HOME/.cache/zgo-wine-native`,
never the game's. It reads the game exes from `../../anomaly/bin`, relative to
the mod folder. Set `ZGO_GAME_BIN` to use another folder. It writes logs to
`native/build/test-*.log`.

| Mode | What it checks |
|---|---|
| `math` | Bone matrix compose and invert against a double-precision reference (2000 random affine pairs). |
| `finder` | The finder on every `AnomalyDX*.exe`, in two ways: mapped by the Windows loader as an image resource, and manually mapped at another base. Both must agree. `VerifiedDX11.exe` (stock Anomaly 1.5.3) and `$ZGO_EXTRA_UNSUPPORTED`, if set, must be refused. |
| `mutate` | Twelve one-byte corruptions must each fail closed with a reason: prologues, member offsets, vtable slots, the type name, an extra vtable slot, and the import name. So must junk input and a short SizeOfImage. |
| `e2e` | The shipped DLL on the real engine code. The DX11AVX exe is mapped at its preferred base 0x140000000. Its KERNEL32 imports are resolved and every other import traps. The hooks go into the real `CalculateBones`, `LL_BoneID` and `Depart`. Fake kinematics objects (real vtables, a Bone_Calculate stub) then run through them. |

The `e2e` run covers:

- `zgo_init` fails closed on the test exe itself;
- capture through `LL_BoneID`, binding, bend, crush and move op sets;
- exact results after a recompute and after the engine's same-tick early-out (never applied twice);
- switching op sets; empty op sets restore every bone;
- bad input is refused;
- `Depart` marks the binding dead, and a pooled model gets a new handle;
- hooks out restore the exact original bytes;
- a stress run: 6 threads calling the real `CalculateBones` on 4 objects while the main thread installs and removes the hooks 600 times, binds 1200 times and commits 24000 op sets. Afterwards the bytes are identical and the results exact.

Results on 2026-11-13 (xrRazom 1.4 exes, dated 2026-10-03):

    PASS math    2002 checks   worst error 7.7e-07
    PASS finder  8/8 supported, VerifiedDX11.exe and stock 1.5.3 DX11AVX refused (36 / 41 IKinematics slots)
    PASS mutate  18 checks
    PASS e2e     97 checks     stress: 4.86 M CalculateBones calls, 554 k recomputes, 600 hook toggles in 313 ms

The finder takes 0-17 ms per exe.

## How the finder works

Everything is found from the running module's own bytes. Nothing is
hard-coded per exe, and every step can refuse.

1. **Sections.** It parses the PE headers and sections of the main module.
   It refuses anything inconsistent.
2. **RTTI.** It looks for the type descriptors `.?AVCKinematics@@` and
   `.?AVCKinematicsAnimated@@`, which must be unique. It finds their complete
   object locators (`sig 1`, self-RVA, in `.rdata`) and their vtables (the
   slot before the vtable points at the COL). It uses the class hierarchy
   descriptor to find the `IKinematics` base at +232 (0xe8). It then requires:
   - the `IKinematics` vtable has exactly 46 slots;
   - the primary vtable has at least 27;
   - the slots both classes must share are identical (5, 26, 35);
   - `dcast_PKinematics` (primary slot 16) adds the same 0xe8.
3. **Targets.** It takes each hook target from its vtable slot and verifies
   it against a byte pattern. Only rip-relative displacements are wildcarded;
   their targets are checked instead:
   - `CalculateBones` (IK slot 35) must enter `EnterCriticalSection` on
     `[ik+0x10]`, store `UCalc_Time`, call `Update_Callback` and leave
     through `LeaveCriticalSection`. The import names are checked through
     the IAT.
   - `LL_BoneID(LPCSTR)` (IK slot 5).
   - `Depart` (primary slot 26) must take and release the global wallmark
     lock and clear the visibility mask.

   Every target must be 8-byte aligned, and its first instruction must be
   exactly 5 bytes and position independent.
4. **Members.** Member offsets are read out of the class's trivial accessors
   and checked against each other:
   - `LL_GetBoneInstance`: `bone_instances`, `CBoneInstance` size;
   - `LL_BoneCount`: the `bones` vector;
   - `LL_GetTransform_R`: `mRenderTransform`;
   - `Invalidate`: `UCalc_Time`;
   - `Callback`, `GetUpdateCallback` and `GetUpdateCallbackParam`.
5. **Result.** Any mismatch gives `UNSUPPORTED EXE: <why>`. `zgo_caps()`
   stays 0 and `zgo_enable` refuses.

### Offset table (xrRazom 1.4, verified by the finder on 2026-11-13)

RVAs from image base 0x140000000:

| Exe | md5 (first 12) | Timestamp | CalculateBones | LL_BoneID | Depart | IKinematics vtable | primary vtable | dwTimeGlobal |
|---|---|---|---|---|---|---|---|---|
| AnomalyDX11AVX | df0353e9d345 | 6ac1138f | 0x2ef2f0 | 0x2310c0 | 0x233b90 | 0x1297510 | 0x1297400 | 0x185b8e8 |
| AnomalyDX11    | c82225882069 | 6ac11345 | 0x2f7c00 | 0x2363e0 | 0x238ee0 | 0x12b39a0 | 0x12b3890 | 0x1875908 |
| AnomalyDX10AVX | 714a122fd0a9 | 6ac112ca | 0x2cfb90 | 0x22b440 | 0x22df10 | 0x123f548 | 0x123f838 | 0x17ff188 |
| AnomalyDX10    | c65e3e62b41e | 6ac11263 | 0x2d7fe0 | 0x230410 | 0x232f10 | 0x125ac20 | 0x125ab10 | 0x1818188 |
| AnomalyDX9AVX  | e4b0f24ac430 | 6ac111eb | 0x2afe80 | 0x224e10 | 0x2278e0 | 0x1200388 | 0x1200678 | 0x17ad578 |
| AnomalyDX9     | 78c486a216b2 | 6ac11175 | 0x2b7fd0 | 0x2298b0 | 0x22c3b0 | 0x121ba60 | 0x121b950 | 0x17c6598 |
| AnomalyDX8AVX  | df052629ad93 | 6ac110ff | 0x2aed80 | 0x223a00 | 0x2264d0 | 0x11d9028 | 0x11d9318 | 0x1781e98 |
| AnomalyDX8     | 4bf18719aa95 | 6ac11087 | 0x2b7460 | 0x2283c0 | 0x22aec0 | 0x11f3700 | 0x11f35f0 | 0x1799eb8 |

The member layout is the same in all eight.

| From `IKinematics*` | Offset |
|---|---|
| Base subobject | primary + 0xe8 |
| `UCalc_Mutex` (pointer to a CRITICAL_SECTION) | 0x10 |
| `bone_instances` | 0xc8 |
| `bones` (vector of `CBoneData*`) | 0xd0 |
| `bone_map_N` | 0xe0 |
| `UCalc_Time` | 0xf4 |
| `Update_Callback` | 0x118 |
| `Update_Callback_Param` | 0x120 |

`CBoneInstance` is 0x168 bytes: `mTransform` +0x0, `mRenderTransform` +0x80.

IKinematics vtable slots in this build: 5 `LL_BoneID(LPCSTR)`,
9 `LL_GetBoneInstance`, 12 `LL_BoneCount`, 22 `LL_GetTransform_R`,
35 `CalculateBones`, 36 `Invalidate`, 37 `Callback`, 41/42 the callback
getters. That makes 46 slots: public b86d733f4a has 40 and public dev-mt has
47 (no `CopyBonesFrom` here).

## Hooks and safety

- **Patching.** Each target's first 5 bytes become a `jmp` to a relay in a
  trampoline page within +-2 GB. The patch is written as one 8-byte
  compare-and-swap of bytes 0..7 (bytes 5..7 unchanged), so a thread running
  through it sees the old instruction or the jmp, never half. The CAS refuses
  if the bytes changed since they were verified (another hook). Removal swaps
  the original bytes back the same way. `DllMain(PROCESS_DETACH)` restores
  them at exit.
- **No unloading under a running thread.** Trampolines are never freed. The
  DLL pins itself (`GetModuleHandleEx PIN`) when it first installs a hook, so
  closing the Lua state can never unload code a thread is still in.
- **Locking.** The post-process runs after the original `CalculateBones`,
  under the engine's own per-model `UCalc_Mutex`, plus a per-slot try-lock.
  Op sets are published with a seqlock: the hook sees the old set or the new
  one, never a mix.
- **Idempotent.** For every bone it touched, the hook remembers the matrices
  the engine produced and the ones it wrote. If a call finds its own output
  still there (no recompute), it starts from the engine's matrices, so an
  early-out never bends twice. Bones that leave the op set get the engine's
  matrices back.
- **Model pool.** The engine pools models. `Depart` (on every release) marks
  bindings dead before the model can serve another object.
- **Hot path.** Unbound models cost one atomic load plus a 64-bit bloom test
  per `CalculateBones`. `LL_BoneID` costs a 1-byte compare.
- **Capture.** `obj:get_bone_id("\1zgo:<token>")` is intercepted by the
  `LL_BoneID` detour, which stores the object's `IKinematics*` and returns
  BI_NONE. Any other name passes through untouched.

## After an xrRazom update: re-verify

1. Run the tests on the new exes:
   `dev/run.sh make -C native test ZGO_GAME_BIN=/path/to/anomaly/bin`, or
   `ZGO_GAME_BIN=... native/tests/run.sh`.
2. All `finder` lines say SUPPORTED, and `e2e` passes: nothing to do. The
   finder adapts to moved code.
3. Any `UNSUPPORTED EXE: <why>`: the add-on stays off in game by itself, and
   players lose nothing but the native features. The reason names the step
   that failed:
   - a vtable now has another slot count;
   - a prologue differs;
   - a member offset moved.
   Disassemble the named function (vtable slot from the report) and compare
   it with the pattern in `src/zgo_finder.c`. Update the pattern or slot
   index, and add the new layout as an alternative; never loosen a check.
   Then run `make test` again and update the offset table above.
4. Any change to `include/zgo_native.h`: bump `ZGO_NATIVE_ABI` and `ABI` in
   `zgo_native.script` together. `tests/zgo_test_native.lua` fails until the
   two declaration lists match.

## Risks

- **Engine code changes with every xrRazom release.** Handled by
  fail-closed verification. The cost is the features until someone
  re-verifies.
- **Another tool patching the same functions** (a future ReShade addon,
  another mod's DLL). The CAS refuses to install over changed bytes. If
  someone hooks over ours, removal leaves theirs in place (it passes through
  ours).
- **FFI removed from the game's Lua** (monolith PR #249 proposes it). The
  script then falls back cleanly: everything native reports missing.
- **Under MO2/usvfs, the DLL is loaded through the VFS.** It is loaded from
  the exe's folder, and `LoadLibrary` goes through usvfs. Not yet seen in
  game: see the in-game checks in `docs/integration/native.md`.
- **Visual-only changes to bones.** `bone_position` also reads the bent
  matrices, so decals follow the bent limb. Ragdoll physics reads its own
  bodies, not these matrices, so collision is unchanged. That this holds in
  every engine path is checked in game, not proven.
