# Integration note: native (bin/zgo_native.dll and its Lua bootstrap)

Workstream "native", PLAN Phase F.

## 1. Summary

**What it is**

An optional engine add-on, `bin/zgo_native.dll`, plus its Lua bootstrap,
`zgo_native.script`.

- **Off by default.** It loads only while MCM → "Native extensions
  (experimental)" is ticked.
- **No per-user setup or bake.** The DLL finds every engine function and
  member it needs in the running game exe when it loads. Nothing is baked per
  mod list or per player, so the setup GUI has nothing to do for it. It ships
  as one file.

**DLL**

- mingw-w64 x86_64, plain C ABI (ABI 1).
- Static runtime: its imports are only `KERNEL32.dll` and `msvcrt.dll`.
- No threads of its own, no vendored code: the hook code is ours.

**Offset finder**

It works on any module base. It goes from the RTTI type descriptor to the
complete object locator to the vtable of `CKinematics` and
`CKinematicsAnimated`. Each target is taken by vtable slot, then verified by
byte patterns and IAT import names. Member offsets are read from accessor
functions. Anything unexpected is reported as "unsupported exe", and nothing
is enabled.

**First hook set (`CAP_BONES`)**

- **Hooks:** a post-process after `CalculateBones`, a capture in
  `LL_BoneID(LPCSTR)`, and model release in `Depart`.
- **Lua side:** Lua publishes op sets (bend = rotate, crush = scale,
  move = translate, per bone group) into DLL memory through a seqlock.
- **Hook side:** the hook applies them under the engine's own per-model lock.
  It is idempotent across the engine's early-outs, and it restores bones that
  leave the set.
- **Lua never runs inside a hook.**

**The first feature on it: "Broken limbs from explosions"**

- The host decides, from `zgo_blast`'s `blast_body` event.
- Every machine computes the same bends from a seed.
- A body is bent only after its ragdoll exists.
- The number of bent bodies is capped per machine.
- Kid mode removes the bends.

**Lua bootstrap**

- LuaJIT 2.0.4 FFI `cdef`, then `ffi.load` under pcall. It tries next to the
  exe (where MO2 maps the mod's `bin/`), then the normal DLL search, then
  `$fs_root$\bin`.
- ABI check, capability mask, and `has(cap)` for the whole session.
- `probe()` for the probe workstream.
- Co-op capability exchange as sync kind N (section 5).
- `deform()` / `undeform()` for other modules.

**Verified (tests)**

- **`native/tests/run.sh`** (Wine, own prefix `~/.cache/zgo-wine-native`):
  - **math:** 2002 checks.
  - **finder:**
    - all 8 xrRazom 1.4 exes SUPPORTED, in 0–17 ms;
    - the Windows-loader mapping and a manual mapping at another base agree;
    - `VerifiedDX11.exe` (stock 1.5.3) and a stock 1.5.3 DX11AVX are refused.
  - **mutate:** 18 checks. Every one-byte corruption of a prologue, member
    offset, vtable slot, type name or import name fails closed, with a reason.
  - **e2e:** 97 checks, using the shipped DLL against the real engine code.
    - The DX11AVX exe is mapped at 0x140000000. The hooks go into its real
      `CalculateBones`, `LL_BoneID` and `Depart`.
    - The checks: capture, bind, the bend/crush/move maths (exact to 1e-4),
      early-out idempotency, switching op sets, `Depart` and pool reuse, and
      the exact original bytes after removal.
    - A stress run: 6 engine threads with 4.86 M `CalculateBones` calls while
      the hooks are toggled 600 times and 24000 op sets are committed.
  - The full table is in `native/README.md`.
- **`tests/zgo_test_native.lua`:**
  - the real-FFI fallback on Linux, which fails cleanly and logs once;
  - the `ffi.cdef` against `native/include/zgo_native.h` (all 20 functions,
    the struct, the ABI, the capability bits);
  - the unsupported-exe, wrong-ABI and failing-hook paths;
  - every settings gate;
  - the co-op exchange as host (one player, two players, a missing answer,
    another ABI, no player list, periodic re-announce without a gap, host
    switched off) and as client;
  - broken bodies: records, waiting for the ragdoll, subtrees, determinism
    across body pose and heading, limits, kid mode, `Depart`, session loss,
    switches, level change, save/load, release, client replay;
  - `deform()` / `undeform()`, `probe()`, the status button.

  It passes with `ZGO_BAKED=0` and `=1`.
- **`dev/test-all.sh`:** see the run at the end of this note.

**Not verified (needs the game)**

- That `ffi.load` finds the DLL through MO2's usvfs, under Proton.
- That the hooks stay stable in real play on the multithreaded engine.
- That `obj:get_bone_id(...)` reaches the hooked `LL_BoneID(LPCSTR)` in game.
  It does in the exe's code; the e2e test drives it through the vtable.
- How the bends look on real ragdolls.
- That physics never reads the bent matrices back.

All of these are in section 7.

## 2. Files

**Added**

| File | What |
|---|---|
| `native/include/zgo_native.h` | The C ABI (ABI 1) |
| `native/src/zgo_pe.c`, `zgo_pe.h` | PE parsing on a mapped image |
| `native/src/zgo_finder.c`, `zgo_finder.h` | The offset finder and its report |
| `native/src/zgo_hook.c`, `zgo_hook.h` | x64 inline hooks (8-byte CAS patch, near trampolines) |
| `native/src/zgo_bones.c`, `zgo_bones.h` | Bindings, op sets (seqlock), the post-process, matrix maths |
| `native/src/zgo_dll.c` | Exports, detours, DllMain, log ring |
| `native/Makefile` | `make`, `make test`, `make check-deps`, `make clean` |
| `native/tests/zgo_native_test.c`, `native/tests/run.sh` | Wine tests: math, finder, mutate, e2e |
| `native/README.md` | Build, how the finder works, offset table, re-verification after an xrRazom update, risks |
| `bin/zgo_native.dll` | Build output (68 KB) |
| `gamedata/scripts/zgo_native.script` | Lua bootstrap, co-op exchange, broken bodies, `deform()`, `probe()` |
| `gamedata/scripts/zgo_settings_native.script` | MCM page "Native extensions (experimental)" and one Performance slider |
| `tests/zgo_test_native.lua` | Lua suite (picked up by `dev/test-all.sh`) |
| `tests/mocks/native.lua` | A Lua stand-in for the DLL. Inert in other suites: it only wraps `get_bone_id` for names starting with `\1`, and only while a test sets `NATIVE_MOCK_LIB` |

`native/build/` holds the test exe and logs. It is not needed by players.

**Changed**

- `gamedata/configs/text/eng/ui_st_zgo_mcm.xml` and
  `gamedata/configs/text/rus/ui_st_zgo_mcm.xml`: regenerated with
  `luajit dev/gen_mcm_text.lua`.

**Packages and downloads**

- **Packages:** none installed. mingw-w64 GCC 16 and Wine 11 come with the
  zgo-dev container.
- **Downloads:** reference sources only, not shipped, fetched read-only from
  raw.githubusercontent.com into `~/.cache/zgo-native-src/`:
  `themrdemonized/xray-monolith` at `b86d733f4a`, files `SkeletonRigid.cpp`,
  `SkeletonCustom.*`, `SkeletonAnimated.cpp`, `Kinematics*.h`, `_matrix.h`,
  `bone.h`, `FBasicVisual.h`, `FHierrarhyVisual.*`, `RenderVisual.h`,
  `ModelPool.cpp`, `script_game_object*.cpp`, `GameObject.cpp`.
- **Earlier phase:** the disassembly during discovery used capstone/pefile
  from that phase's scratch `pylib`, and the stock 1.5.3 exe in the negative
  test came from it too. That exe is optional, through
  `ZGO_EXTRA_UNSUPPORTED`.

## 3. Requests to the integrator

**R1. Kid mode at once.** In `gamedata/scripts/zgo_settings.script`,
`update()`, after `pcall(zgo_decals.kid_mode, kid)`, add:

    pcall(zgo_native.kid_mode, kid)

`zgo_native` also polls `zgo_util.gore()` every 500 ms. Without this line
kid mode still straightens the bodies, just up to half a second later.

**R2. Release zip.** In `dev/package.py`, change

    SKIP_DIRS = {'dev', 'tests', 'docs', '.git', '__pycache__'}

to

    SKIP_DIRS = {'dev', 'tests', 'docs', '.git', '__pycache__', 'native'}

- Players need only `bin/zgo_native.dll`, which is outside `native/`.
- No other folder in the mod is named `native`.
- To ship the sources for transparency, about 120 KB, skip only the build
  folder instead: add `if rel_dir.startswith('native/build'): continue`.

**R3. PROTO.** N lines are new (section 5). Bump `zgo_sync.PROTO` once,
together with the other workstreams' kinds. The header comment already lists
`N / up N`.

The exchange does not depend on the bump. A peer that doesn't answer N lines
simply leaves the session without native features.

**R4. Settings test (optional).** In `tests/zgo_test_settings.lua`, add
`"zgo_native"` to the file list of the "every setting the scripts read
exists" loop (line 86). `tests/zgo_test_native.lua` already checks this for
its own script.

**R5. README.txt.** Add the text in section 6:

- the feature block under WHAT IT DOES;
- the page line under SETTINGS;
- the LIMITS bullet;
- the CHANGES bullet.

**R6. dev/README.md (optional).** One line under the tests:

    dev/run.sh make -C native test   # the native add-on under Wine (needs the game exes; native/README.md)

**R7. probe workstream (for its owner, no integrator edit).**
`zgo_probe` test 4 calls `zgo_native.probe()` with no arguments. That never
loads the DLL while "Native extensions" is off, so with the defaults it
reports `loaded=false, state=not loaded (Native extensions are off)`.
`zgo_native.probe({ load = true })` loads it for the report. That runs the
finder only and never installs a hook.

**R8. xrRazom 1.5 wording (with R5).** When adding the R5 LIMITS bullet to
README.txt, use the updated text in section 6 ("all eight of xrRazom 1.4 and
of xrRazom 1.5"). No other change for 1.5 is needed in shared files: the
C ABI (1), the capability bits and the Lua side are unchanged.

## 4. Settings added

Page `native`, "Native extensions (experimental)": `coop = "local"`, placed
last.

| Key | Type | Default | Co-op | Shown | What |
|---|---|---|---|---|---|
| `native/enable` | check | **false** | local | always | Master switch: load the DLL and run the finder. Experimental. |
| `native/bones` | check | **false** | local | with `native/enable` | The bone hooks (CalculateBones, LL_BoneID, Depart). Experimental. Off takes them out at once. |
| `native/deform_corpses` | check | true | host | with `native/bones` | Broken limbs from explosions. Does nothing unless the hooks are on everywhere. |
| `native/deform_strength` | track 0.25–2, step 0.25 | 1.0 | host | with `native/bones` | How many limbs break and how far. |
| `native/status` | button | – | – | with `native/enable` | "Write a status report to the log" (`zgo_native.log_report`). |
| `performance/native_bodies` | track 0–32, step 1 | perf {4, 8, 12, 16, 24} | local | Performance page | Bodies with broken limbs at once (newest first). |

- Every option has English and Russian names and explanations.
- The page note explains the co-op rule and the status button.
- The MCM xml was regenerated.

## 5. Co-op

**Sync kind N, both directions.** Fields are `|`-separated; integers are sent
as integers.

| Line | Direction | Meaning |
|---|---|---|
| `N\|H\|abi\|wire\|caps\|round` | host → clients | Announce. The host's ABI (1), line format (`WIRE` 1), its capabilities, and a round number. |
| `N\|C\|abi\|wire\|caps\|round` | client → host (`send_up`) | Answer with this machine's capabilities. Also sent unasked when they change. |
| `N\|S\|round\|caps` | host → clients | The session's capabilities: the AND over the host and every player. |
| `N\|B\|id\|seed\|power` | host → clients | A body with broken limbs. `id` is the host object id, `seed` an integer below 1e9, `power` like `0.950`. |
| `N\|F\|id` | host → clients | That body was released: forget it. |

Capabilities are bits: 1 = finder (exe recognised), 2 = bone hooks installed.

**The rule: a feature runs only when every machine has it.**

- **Single player:** this machine's capabilities.
- **Host:**
  - The host announces when its capabilities change, when the player set
    changes (netids from `XrrPlayers():GetPeerNetidAt(i)`, 1-based, or else
    `XrrPeerCount`), and every 30 s.
  - The session is 0 until every current player has answered a round since
    the player set last changed.
  - A different ABI or wire version counts as 0, with one log line.
  - Periodic re-announces don't reset the session, so there is no flicker.
  - A host with native off sends nothing, or one `N|S|…|0` if it had said
    otherwise.
- **Client:** `has(cap)` = the host's `S` AND this machine's own
  capabilities.
  - A client with native off still answers (caps 0) and loads nothing.

**Who decides what**

| What | Who |
|---|---|
| Whether a body gets broken limbs, its seed and its power (blast severity × the host's `deform_strength`) | The host |
| The bends themselves | Each machine, from the seed. Bends are in each bone's own frame, so they match regardless of pose and heading (tested). |
| How many bent bodies it draws (`performance/native_bodies`) | Each machine |
| Kid mode | Each machine |

- **Joining players:** a player answering for the first time after a
  player-set change gets every record re-sent.
- **Save:** records live in the host's save (`m_data.zgo_native`, at most 64
  bodies).
- **Not synced:** the bends are visual only. Nothing physical is synced or
  needs to be.

## 6. README text

**WHAT IT DOES** (new block):

```
  Native extensions (experimental, off by default)
    An optional engine add-on (bin\zgo_native.dll) for the xrRazom game
    executables, for what scripts can't do. It only switches on when it
    recognises the exact exe: it looks up every engine function it needs and
    compares its code byte by byte; on any other exe it stays off and says
    why in the log. Nothing to set up or bake: it finds what it needs when
    the game starts.
    First feature: broken limbs. Bodies close to an explosion get arms and
    legs bent at broken angles, and with a heavy charge a crushed chest or a
    dislocated shoulder. Only bodies, only once they have gone limp, the
    same on every co-op machine. Needs MCM -> Native extensions -> both
    switches on (on every player's computer in co-op).
```

**SETTINGS** (page list, new line):

```
    Native extensions  (experimental) loading the engine add-on, its bone
                    hooks, broken limbs from explosions and their strength,
                    a status report for the log
```

**LIMITS** (new bullet):

```
  * Native extensions are experimental and off by default. They only work
    on the xrRazom executables they recognise (all eight of xrRazom 1.4);
    after an xrRazom update they may switch themselves off until the mod is
    updated. Broken limbs are a visual change of the body's bones: the
    ragdoll's physics and collision stay as they were. In co-op a native
    feature only runs when every player has it switched on and working.
```

**CHANGES** (bullet for 1.7.0):

```
         Native extensions (experimental, off by default): an optional
         engine add-on that verifies the game executable before it does
         anything; first feature: broken limbs and crushed chests on bodies
         near explosions (same on every co-op machine; kid mode removes them).
```

## 7. In-game checks

Turn on MCM → General → "Debug log" for these. All `[ZGO] native:` lines go to
`appdata/logs/xray_<user>.log`.

1. **Load.** Tick "Native extensions", leave "Bone hooks" off, and load a
   save.
   - Expected in the log: `native: zgo_native 1.0.0 (abi 1, …) loaded from
     …\bin\zgo_native.dll; supported exe (timestamp 6ac1138f): …; verified:
     finder+bones`.
   - If it says `not loaded`, the reason follows. Report it: FFI missing,
     usvfs not mapping `bin\`, or a load error.
2. **Status button.** Press "Write a status report to the log".
   - Expected: `state = ready`, `caps = finder+bones`, `hooks = none`.
   - Expected: the finder report lines (`hook CalculateBones … verified`,
     `result: SUPPORTED`).
3. **Bone hooks.** Tick "Bone hooks…" and close MCM.
   - Expected: `native: hooks in: bones`.
   - Play 10–15 minutes with fights and many NPCs on screen. There must be no
     crash and no visible FPS change.
   - Press the status button again. `capture_test = ok (LL_BoneID hook saw
     the actor)` and a growing `calc_calls` confirm both hooks run.
4. **Broken limbs.** Kill a group of NPCs with a grenade, or throw one at
   bodies.
   - Expected: a second after they go limp, arms and legs bend at broken
     angles. A close charge may also give a flattened chest or a shoulder out
     of place.
   - The bends must stay attached and follow the body as it rolls or is
     dragged. There must be no stretching to the world origin and no jitter.
   - Debug log: `native: body <id>: <n> groups`.
5. **Blood follows.** Shoot a bent limb. The wound decals and blood must sit
   on the bent limb.
6. **Ragdoll stays sane.** Push and drag a bent body around and drop it from
   a height. The physics must behave as before: no explosion, no spinning, no
   jitter.
7. **Switches.**
   - Kid mode on: the bent bodies straighten within half a second. Off: they
     bend again.
   - "Bone hooks" off: the bodies straighten at once, and the log says
     `hooks in: none`.
   - "Native extensions" off: the same.
   - Performance → "Bodies with broken limbs at once" = 1: only the newest
     stays bent.
8. **Save and reload.** Save near bent bodies and reload: they are bent
   again, the same way.
9. **Leave and return.** Go far enough that the bodies go offline, then
   return; they are bent again. Change level and come back. Quit to the main
   menu, load another save, then exit the game. There must be no crash at
   any step; the DLL restores the engine's bytes at exit.
10. **Co-op.**
    - Host and client both tick both switches. Host log:
      `co-op session capabilities: finder+bones`. Client log: `… (from the
      host): finder+bones`.
    - Blow up bodies: both players see the same limbs bent the same way.
    - Then the client unticks "Bone hooks". The host logs `… capabilities:
      finder` and the bodies straighten on both machines.
    - A client joining later sees the bodies already bent.
11. **Other executables (optional).** Start once with another renderer, for
    example DX10 or DX9. Step 1 must again say "supported exe".

## 8. Risks and open questions

**Engine code in memory**

- **The hook runs inside the engine on its worker threads.** A bug there is a
  crash, not a Lua error. Mitigations:
  - the e2e stress test on the real engine code;
  - fail-closed verification;
  - off by default and labelled experimental.
- **Physics reading bent matrices back.** If any engine path reads
  `mTransform` back into the ragdoll after it exists, the bend could feed into
  physics and cause jitter. Examples: re-enabling sleeping elements,
  activating a carried or dragged body, re-creating a shell. We bend only
  after the shell exists, and ragdoll callbacks write bones from physics, not
  the other way round. In-game checks 4 and 6 cover this.
- **Visibility box.** It is computed inside `CalculateBones` before our
  post-process, so a strongly bent limb may be culled a little early at the
  screen edge. Minor and cosmetic.
- **Model pool.** `CModelPool::DeleteInternal` always calls `Depart()` before
  pooling or freeing, which is what invalidates bindings. That holds for
  `CKinematics` and `CKinematicsAnimated`; the finder requires their `Depart`
  to be the same function. A future class with its own `Depart` override
  would escape this. The finder would still pass if the two known classes are
  unchanged, so recheck when xrRazom adds skeleton classes.

**Updates and loading**

- **Every xrRazom update can move or change the code.** The add-on then
  switches itself off and logs `unsupported exe: <step>`.
  `native/README.md` → "After an xrRazom update" lists the re-verification
  steps. It takes minutes when only addresses moved, and the finder handles
  that by itself.
- **FFI could go away.** Monolith PR #249 proposes removing it from the
  game's Lua. The script then falls back cleanly.
- **Loading through MO2.** usvfs and Proton loading is untested in game
  (check 1).

**Gameplay and data**

- **Bends are visual, but `bone_position` reads them.** Other ZGO features
  that take bone positions from a bent body (blood, cuts) follow the bent
  limb. That is intended, but dismemberment on a bent limb is untested in
  game.
- **One op set per body.** `deform()` (for other modules) and broken limbs
  can't share a body; the second one is refused with a reason.
- **Save size.** Records are at most 64 entries of three numbers.

**Open questions**

- Whether the setup GUI should show a "Native extensions" hint. It needs no
  setup, so probably only a mention.
- Whether to ship the C sources in the release zip (R2).

**Last `dev/test-all.sh` run:** see the final report of this workstream.
