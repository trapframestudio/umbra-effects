# Integration note: probe (Phase 0, engine smoke tests)

Workstream "probe", PLAN Phase 0. Nine in-game probes on a new MCM page, Diagnostics. The later phases rely on these engine paths, and each probe checks one of them on the player's machine.

## 1. Summary

**What it does**

The Diagnostics page appears only while General → Debug log is ticked. It has:
- one button per probe;
- "Run all safe probes" (9, 4, 8, 6, then a summary line);
- two buttons for the probes judged by eye: "The last probe looked right" and "The last probe looked wrong".

A button queues the probe, and the probe starts when the menu closes. While it runs, it:
- logs `[ZGO probe] <n> <name>: PASS|FAIL|MANUAL <details>` (MANUAL means: judge it by eye);
- shows the same line on screen (`actor_menu.set_msg`), plus a PDA news message saying what to look at;
- appends everything to `appdata\zgo_probe_report.txt`. The file is opened with `getFS():update_path("$app_data_root$", …)` and starts with a header giving the ZGO version, SP or co-op role, level, kid mode, baked-model count, and shader bus version;
- restores everything it changed, through an undo list. The list also runs if the probe errors, a level change starts, or a save starts while a probe holds a change.

| # | Probe | Kind | What it checks |
|---|---|---|---|
| 1 | Off shader `zgo\off` | experimental | Defines `l_special` only. Through `set_shader`, it hides one sub-mesh of the nearest living NPC and the nearest body (the highest one, usually the head), and their shadows, for the hold time. The shader text reads back. Kid mode: the whole body instead. |
| 2 | Pass-through shader `zgo\probe_dmg` | experimental | Wraps the stock `deffer_model_bump/flat.vs` and `shadow_direct_model.vs`. It is put on bodies chosen so their sub-meshes cover all four skinning formats, 1W–4W, which it reads from the OGF files. Held 2× the hold time. They must look identical. |
| 3 | Digit textures `zgo\probe_digits` | experimental | Per-NPC numbers through ten 1×1 textures (`zgo\probe\d00..d15`): four in vertex-shader slots, six in pixel-shader slots, read with `Load`. Each body gets a 10-digit code in its second texture string. The torso turns red, green or blue when every digit arrived and the checksums hold. Magenta means the pixel-shader slots failed. A vanished torso with its shadow left means the vertex-shader slots failed. |
| 4 | FFI | safe | `require("ffi")`, `ffi.os`, `jit.version`, and `GetModuleHandleA(nil)` = 0x140000000. Also asks `zgo_native.probe()` when that module is there. |
| 5 | Save and reload with cut bodies | safe, two steps | Records cut bodies near you into the next save (`m_data.zgo_probe`). After loading that save, it waits 8 s. Then it checks every recorded body: still online, same section, the same cut roots in ZGO's state, those bones still hidden, moved less than 0.5 m. |
| 6 | Co-op view hash over sync kind Z | safe | The host asks every client to hash its view of the same bodies: cut roots and `bone_visible`, `set_shader` overrides, alive/dead. It compares the hashes per body and per player and sends each client the verdict. Debris and decal counts go along for information. |
| 7 | `set_visual_name` on a one-bone prop | experimental, SP only | Swaps a small loose object's model (one bone, OGF type 3/10) for another small one-bone model, for the hold time, then swaps it back. A save made meanwhile is put right on load. |
| 8 | Kid-mode lane `zgo_view` | safe | Flips kid mode for `zgo_settings.update` only. Every module's `kid_mode` handler is held, so debris and cuts are untouched. Expects lane x 0 → 1 → 0, read with `shader_bus.get` and `get_pending`. On failure it writes the lane with its own token to tell "the bus is broken" from "ZGO's write is broken". |
| 9 | Baked models in use | safe | For NPCs near you, compares the number of sub-meshes the game loaded against the bake (`zgo_bake.parts` / `info`) and against the OGF on disk. Verdicts: baked model in use; stale (the game loaded the model before the bake: restart); overridden (another mod's model wins: reorder or bake again). |

**Verified (tests, shader compiles)**
- `tests/zgo_test_probe.lua` runs all nine probes in single player. It then reruns itself as a co-op host and as a co-op client:
  - **Host round:** match, mismatch, and a silent client.
  - **Client:** answering, an empty question, the verdict, and asking the host to run.
  - **Other cases:** rubbish lines, debug off on the host, the four safe probes in order with their summary, the report file, and the marks.
  - **After every probe:** no shader override is left, `zgo_settings.gore` and every `kid_mode` handler are put back, no swapped model or probe state is left, and the kid-mode lane is off.
- **Model reading:** OGF parsing through `getFS():r_open` is tested on built OGFs. These cover:
  - type 3, 4 and 10 models;
  - children with 1W, 2W, 3W and 4W vertex formats;
  - bounding boxes, textures, shaders and one-bone props.
- **The three `.s` files** are run in a sandbox with the engine's `adopt_compiler` surface. The tests also check:
  - that the wrapper `.vs` files define `main` for every `SKIN_*`;
  - that the 16 DDS files hold the right bytes;
  - the digit-code round trip.
- **Results:** `ZGO_BAKED=0` and `ZGO_BAKED=1` pass, in SP, host and client. `dev/test-all.sh`: **120 runs, 0 failures**.
- **shadercheck** (`dev/run.sh … shadercheck.py`, Wine prefix `~/.cache/zgo-wine-probe`): every probe stage file passes **292 of 292** compiles:
  - compilers: Microsoft 6.3.9600.16384 (the one this game's prefix loads), Microsoft 10.0.26100.1, Wine's builtin, and vkd3d;
  - define sets: user, default, low, hbao_msaa, ultra, msaa_atoc10, plus the 5 skinned VS variants;
  - linkage checked for every pass of `zgo_off.s`, `zgo_probe_dmg.s` (flat + shadow) and `zgo_probe_digits.s`.
- **Engine names:** every engine name the probes call is in `AnomalyDX11AVX.exe`'s strings, among them:
  - `set_shader`, `reset_shader`, `get_shaders`, `get_default_shaders`, `set_visual_name`, `get_visual_name`;
  - `bone_visible`, `list_bones`, `get_physics_shell`, `iterate_nearest`, `r_open`, `r_close`, `r_elapsed`, `r_stringZ`, `r_float`;
  - `give_game_news`, `character_name`, `owner_of`, `describe`, `get_pending`, `stats`, `try_register`.
- **Requests R1–R3** (below) were applied to a scratch copy of the mod. There, probe 8 turns from FAIL to PASS, the settings suite passes, and the kidfx lane check passes.

**Not verified (needs the game):** everything the probes exist to find out:
- whether `set_shader`/`reset_shader` work on NPC sub-meshes in this build, and what `get_shaders` returns;
- whether a Lua `.s` file with only `l_special` hides a part and its shadow;
- the pass-through and digit shaders on screen;
- FFI inside the game;
- cuts across a real save;
- the co-op hash between real machines;
- `set_visual_name` on a live physics object;
- the lane write.

**Known result today:** probe 8 **FAILS** until request R1 lands. The installed `lua_help_ex.script` (shader_bus version 2) says `set` takes the token `register` returned, but `zgo_settings.lane_set` passes the lane name. So kid mode cannot hide blood that is already on screen through the shaders. The probe names this cause.

## 2. Files

All the files below are new.

| File | What it holds |
|---|---|
| `gamedata/scripts/zgo_probe.script` | The runner (queue, coroutine probes, undo list, report file, HUD and news), the nine probes, the OGF reader, the Z line handlers, the save/load hooks |
| `gamedata/scripts/zgo_settings_probe.script` | The Diagnostics page: 2 options, 12 buttons, English and Russian |
| `gamedata/shaders/r3/zgo_off.s` | `l_special` only: nothing is drawn, and no shadow either (E0–E3 null, so `r_dsgraph_insert_dynamic` skips the part) |
| `gamedata/shaders/r3/zgo_probe_dmg.s` | `normal` (bump or flat pass, chosen by the second texture) and `l_point` (shadow) |
| `gamedata/shaders/r3/zgo_probe_dmg_bump.vs`, `zgo_probe_dmg_flat.vs`, `zgo_probe_dmg_shadow.vs` | Wrappers: `#define main zgo_stock_main` + `#include` of the stock file, then one `main` per `SKIN_*` |
| `gamedata/shaders/r3/zgo_probe_digits.s`, `.vs`, `.ps` | Parse `zgo_dg_<10 hex>`, bind the digit textures; the VS checksum collapses the part on a mismatch, the PS paints the colour or magenta |
| `gamedata/textures/zgo/probe/d00.dds` … `d15.dds` | 1×1 A8R8G8B8, one mip, grey = digit × 17 (132 bytes each) |
| `tests/zgo_test_probe.lua` | The suite (SP, then host and client as subprocesses) |
| `tests/mocks/probe.lua` | Active only when `PROBE_MOCKS` is set: OGF builder and reader, `getFS` reading, the shader API on NPCs, one-bone props |
| `docs/integration/probe.md` | This note |

**Changed:** only the generated `gamedata/configs/text/{eng,rus}/ui_st_zgo_mcm.xml`, via `luajit dev/gen_mcm_text.lua`.

**Downloads:** none. **Container packages:** none added. **Game install, MO2, profiles, other mods:** only read. The digit textures were written by a script; no external tools were used.

## 3. Requests to the integrator

**R1 + R2 + R3 must land together.** R1 alone breaks the settings and kidfx suites, whose bus mocks still use the lane name. R2 or R3 alone breaks them the other way round. All three were tried together on a scratch copy: settings passes, the kidfx lane checks pass, and probe 8 reads 0, 1, 0.

**R1. `gamedata/scripts/zgo_settings.script`: write the kid-mode lane with its token.** `shader_bus.set` takes the number that `register`/`try_register` returned (`anomaly/gamedata/scripts/lua_help_ex.script`, shader_bus version 2: `bool set(number token, …)`). WORKSTREAMS.md "Facts worth knowing" still says `set(id, …)`; please correct it there too. If the kidfx work has already made `lane_set` write `w`, keep that and swap only the first argument.

```diff
@@ -499,7 +499,7 @@
 -- the shader bus lane the blood shaders read: x = 1 hides gore
 local LANE = "zgo_view"
-local lane_ok
+local lane_ok, lane_token
@@ -520,6 +520,10 @@
 	local reg = b.try_register or b.register
 	local ok, err = false, "no register function"
 	if reg then ok, err = pcall(reg, LANE, "Umbra Gore & Effects", "x = 1: kid mode, the blood shaders draw nothing") end
+	-- register/try_register return the write token (nil: another owner holds the id)
+	if ok then
+		if err ~= nil and err ~= false then lane_token = err else ok, err = false, "the id belongs to " .. tostring(b.owner_of and select(2, pcall(b.owner_of, LANE))) end
+	end
 	local p = present()
 	lane_ok = ok and p ~= false
@@ -529,8 +533,8 @@
 local function lane_set(kid)
 	local b = bus()
 	if not (b and b.set and lane_ready(b)) then return false end
-	local ok, err = pcall(b.set, LANE, kid and 1 or 0, 0, 0, 0)
-	if not ok then zgo_util.log("shader bus %s: set failed: %s", LANE, tostring(err)) return false end
+	local ok, err = pcall(b.set, lane_token, kid and 1 or 0, 0, 0, 0)
+	if not ok or err == false then zgo_util.log("shader bus %s: set failed: %s", LANE, tostring(err)) return false end
 	return true
 end
```

**R2. `tests/zgo_test_settings.lua`: a bus mock with token semantics.** It keeps `BUS.lanes[id] = {x, y, z, w}` and `BUS.sets`, so the existing asserts stay as they are. Replace lines 9–14:

```lua
-- shader bus as the exe has it: register a lane, then set (x, y, z, w)
-- (lua_help_ex.script, shader_bus version 2: register returns the write token)
BUS = { lanes = {}, owners = {}, tokens = {}, sets = {} }
shader_bus = {
	try_register = function(id, owner, desc)
		assert(type(id) == "string" and type(owner) == "string" and type(desc) == "string")
		if BUS.owners[id] and BUS.owners[id] ~= owner then return nil end
		BUS.owners[id] = owner
		BUS.lanes[id] = BUS.lanes[id] or { 0, 0, 0, 0 }
		BUS.tokens[#BUS.tokens + 1] = id
		return #BUS.tokens
	end,
	has = function(id) return BUS.lanes[id] ~= nil end,
	owner_of = function(id) return BUS.owners[id] end,
	set = function(token, x, y, z, w)
		local id = assert(type(token) == "number" and BUS.tokens[token], "shader_bus.set takes the token register returned, not " .. tostring(token))
		BUS.lanes[id] = { x, y, z, w } BUS.sets[#BUS.sets + 1] = x
		return true
	end,
}
```

**R3. `tests/zgo_test_kidfx.lua` (kidfx's file): the same mock.** Use R2's block, except that line's `BUS.sets[#BUS.sets + 1] = x` becomes `BUS.sets[#BUS.sets + 1] = { x, y, z, w }`, as kidfx records the whole value. Without it, "kid mode on: lane x = 1" fails once R1 is in.

**R4. `zgo_settings.update`: also call `zgo_native.kid_mode`.** `zgo_native.script:1010` defines it, but `update()` doesn't call it. Skip this if the native note already asks for it. Probe 8 holds it either way: it holds every `zgo_*` module's `kid_mode` while it flips the lane.

**R5. `zgo_decals.stats()`: add `placed`,** the number of ZGO decals currently on surfaces and bodies. Probe 6 reports the host's and each client's count beside the hash. Today it shows "n/a". This is informational only and does not affect the verdict.

**R6 (optional). `zgo_bake`: give probe 9 an exact count.** Either add `expected_children(obj)` or a `kids = <sub-mesh count>` field per model in `zgo_bake_index`. Today the probe uses a lower bound: the sections plus the body, and the highest child id in `zgo_bake.parts`. A stale model that happens to have at least as many sub-meshes as the bake is then not caught. Probe 9 already reads either form.

**R7. PROTO:** kind Z, both directions (section 5). Bump it once with the other kinds.

**R8. README:** add the section 6 text under SETTINGS (or as its own block before LIMITS), plus the CHANGES bullet.

No harness change is needed. The probe mocks are inert unless `PROBE_MOCKS` is set, and `dev/test-all.sh` already picks up `zgo_test_probe.lua`.

## 4. Settings added (page `diagnostics`)

The whole page has `coop = "local"` (per machine) and `show_if = "general/debug"`.

| Key | Type | Default | Notes |
|---|---|---|---|
| `diagnostics/hold` | track 2–30 s, step 1 | 6 | How long probes 1, 2 (×2), 3, 7 and 8 keep their change on screen |
| `diagnostics/experimental` | check | **off** | "(experimental)": shows probes 1, 2, 3 and 7. Calling them while it is off is refused with a message. |
| `diagnostics/run_all` | button | | Probes 9, 4, 8, 6, then a summary line |
| `diagnostics/off_shader` | button | | Probe 1 (experimental) |
| `diagnostics/dmg_shader` | button | | Probe 2 (experimental, "save first") |
| `diagnostics/digits` | button | | Probe 3 (experimental, "save first") |
| `diagnostics/ffi` | button | | Probe 4 |
| `diagnostics/save_reload` | button | | Probe 5, step 1 (step 2 runs by itself after loading) |
| `diagnostics/coop` | button | | Probe 6 |
| `diagnostics/props` | button | | Probe 7 (experimental, SP only) |
| `diagnostics/kid_lane` | button | | Probe 8 |
| `diagnostics/baked` | button | | Probe 9 |
| `diagnostics/mark_ok`, `diagnostics/mark_bad` | buttons | | Add a `USER` line about the last probe to the report |

Every item has an English and a Russian name and explanation (cp1251-safe), and the string tables are regenerated. Nothing is read outside this page, and no console commands are used.

## 5. Co-op

Sync kind **Z** goes both ways. Empty fields are sent as `-` (`zgo_sync.split` drops empty ones).

**Host → clients** (`zgo_sync.emit`)
- `Z|q|<nonce>|<id,id,...>` (`-` when there are no ids): the host's question: "hash your view of these bodies". `<nonce>` is `n<hex time><hex counter>`. The ids are the dead bodies within 40 m of the host, at most 24, sorted.
- `Z|r|<nonce>|<player>|<word>|<detail>`: the verdict for one player.
  - `<word>` is `match` or `mismatch`; `<detail>` lists differing ids, bodies not online there, debris, decals and sync counters, with `|` and newlines replaced.
  - A refused run is `Z|r|-|all|not run|the host has Debug log off`.

**Client → host** (`zgo_sync.send_up`)
- `Z|a|<nonce>|<n>|<total>|<per>|<debris>|<decals>|<recv>`: the answer.
  - `<n>`: bodies found.
  - `<total>`: 8 hex digits, a hash over every body's signature.
  - `<per>`: 4 hex digits per asked id, in order, where `----` means not online here (`-` when no ids were asked).
  - `<debris>`: `zgo_debris.count()`; `<decals>`: `zgo_decals.stats().placed`, or `-`.
  - `<recv>`: the sync lines this client received.
- `Z|run`: a client pressed the button. The host runs the probe if its Debug log is on; otherwise it answers `not run`.

**The hash.** Per body it covers: section, alive or dead, every cut root in ZGO's severed state with `bone_visible` (`+`/`-`/`?`), and every `set_shader` override (`child=shader`).

**Who decides what.** The host decides nothing in the world. The probe only compares. Clients answer, log and show the verdict, and draw nothing. The host's PASS needs every connected peer (`XrrPeerCount`) to answer within 5 s and match.

**Per-machine probes.**
- Probes 1, 2, 3 and 8 change only this machine's rendering (render-side overrides and the local shader bus).
- Probe 5 is refused on clients (they don't save).
- Probe 7 is refused in co-op: a model swap would go through the server to everyone.
- Probes 4 and 9 are read only.

## 6. README text

For the SETTINGS part:

```
  Diagnostics (shown while General -> Debug log is ticked): smoke tests
  for the engine features later versions of this mod build on. Each
  button runs one probe when you close the menu; it writes PASS, FAIL or
  MANUAL (judge it by eye) to the log and to appdata\zgo_probe_report.txt,
  says on screen what to look for, and puts back everything it changed.
  After a probe you judge by eye, press "looked right" or "looked wrong";
  send the report file with a bug report.
    Run all safe probes   baked models in use, FFI, the kid mode shader
                          lane, co-op comparison (changes nothing; blood
                          hides for a few seconds)
    5 Save and reload     press, save, load that save, wait 8 seconds:
                          bodies with parts cut off must come back the same
    6 Co-op               the host compares what every player sees of the
                          bodies nearby (a client's button asks the host)
    Experimental probes (tick "Allow the experimental probes", Accept,
    reopen; save first: if a shader fails to compile the game closes):
    1 Off shader, 2 Pass-through shader, 3 Digit textures (ZGO shaders
    on NPCs for a few seconds), 7 Props (single player: a loose object's
    model is swapped and back).
```

For LIMITS:

```
  * The Diagnostics probes need something near you (NPCs, bodies, cut
    bodies, a small loose object); they say so when there is none. The
    probes you judge by eye can only tell you what to look for.
```

CHANGES bullet:

```
  1.7.0  Diagnostics page (with Debug log on): nine engine probes for
         bug reports, written to appdata\zgo_probe_report.txt.
```

## 7. In-game checks

This is a script for the user. Allow about 20 minutes. Probes 2 and 3 can close the game if a shader does not compile, so **save before them**.

**Setup**
1. Start the game with ZGO enabled and load a save at a base with several stalkers. Cordon's village or the Rookie Village works well.
2. Open MCM → Umbra Gore & Effects → General, tick **Debug log**, press **Accept** and close the menu. Reopen MCM: a **Diagnostics** page is now there.
3. Expected file: `appdata\zgo_probe_report.txt` in the Anomaly folder. Under Mod Organizer it may land in MO2's `overwrite\appdata\` instead; the summary line of "Run all" prints the full path. Every probe also writes `[ZGO probe]` lines to `appdata\logs\xray_<user>.log`.

**Safe probes**
4. Diagnostics → **Run all safe probes**, then close the menu. Over about 15 s you will see four on-screen lines and a summary such as `run all safe probes: 1 PASS, 1 FAIL, 2 MANUAL (report: …)`.
   - **9 baked models:**
     - MANUAL "no baked models are installed" if you haven't baked.
     - After a bake, standing near stalkers: PASS "baked model in use".
     - FAIL "(stale)": restart the game.
     - FAIL "(overridden)": move ZGO lower in MO2's left pane (it must win), or bake again.
   - **4 FFI:** on Windows or Proton, PASS with `image base 0x140000000`. A FAIL here means the native add-on cannot work on this machine.
   - **8 kid mode lane:** blood on walls and bodies should vanish for the hold time and come back.
     - **Expected today: FAIL**, naming "zgo_settings must pass its token to shader_bus.set" (request R1). The same FAIL also shows `written directly with the lane's token it reads 1 then 0`, which proves the bus itself works.
     - After R1: PASS. Then press "looked right" or "looked wrong" according to whether the blood really vanished and came back.
     - Skipped (it reports the lane value) while kid mode is on.
   - **6 co-op:** in single player, MANUAL with this machine's view hash.

**Probe 5, save and reload**
5. Kill two or three stalkers with a shotgun or grenade so that limbs come off, and stand within 40 m of them.
6. Press **5. Save and reload: start** and close the menu. The screen says "N cut bodies near you will be checked".
7. Save to any slot, load that save, and wait about 10 s without moving away.
   - Expected: PASS "N of N recorded bodies came back as saved".
   - Also look: stumps still capped, no pinched joints, no body jumped or fell when the save loaded.
   - A FAIL names the body and what changed, for example "bip01_r_forearm is on screen again" or "moved 2.3 m since the save".

**Probe 6, co-op** (needs a second machine)
8. Host and client both run ZGO, and the host has Debug log on. Stand together near a few cut-up bodies. On the host, press **6. Co-op: compare machines**.
   - Expected: PASS "1 of 1 player(s) answered … player N: match".
   - The client's log and report get "the host compared player N: match".
   - A mismatch lists the body ids that differ.
   - Also press the button on the client: it asks the host, and both get the verdict.

**Experimental probes**
9. Tick **Allow the experimental probes (experimental)**, press Accept, and reopen MCM. Buttons 1, 2, 3 and 7 now show. **Save the game now.**
10. **1. Off shader:** stand 3–10 m from a living NPC and a dead body, and press. For the hold time (6 s by default):
    - Each one's head (or its highest part) must vanish completely, its shadow too, with no stretched skin at the neck. Then it comes back.
    - The screen line names the NPC and the part.
    - Then press "looked right" or "looked wrong".
    - FAIL "set_shader refused" or "reads back the old shader" means the engine path does not work.
11. **2. Pass-through shader:** stand among several different NPCs or mutants (a base with a dog nearby is ideal). The news message lists the chosen bodies and the formats covered (1W 2W 3W 4W). For 12 s:
    - They must look exactly as before: same colours and bumps, shadows, no flicker, no smearing when you or they move.
    - Bodies "without a bump map" look a little flatter. That is expected.
    - If the game closes, send `appdata\logs` and the report. That means a shader compile failure.
    - Mark the result.
12. **3. Digit textures:** stand near two or three NPCs. Their torsos turn plain **red, green and blue**, in the order the news message names them.
    - Magenta means the pixel-shader texture slots failed.
    - A missing torso whose shadow is still there means the vertex-shader slots failed.
    - Mark the result.
13. **7. Props** (single player): stand next to a bottle, can or small box lying loose, and press. For the hold time it turns into another small object (a paper box, canister, vodka bottle, mug or tin).
    - Walk into it or shoot it: the new model must move and fall with the physics.
    - Then it turns back.
    - Mark the result.
    - Optional: save during the hold and load that save. The original model must be back.
14. Untick the experimental option again if you like.

**Kid mode** (the rule check)
15. Tick General → Kid mode, Accept, and run **1. Off shader** again. The whole NPC and body vanish briefly, not just a part, and nothing gory appears. **Run all** reports probe 8 as "kid mode is on and the lane reads x = 1" (PASS once R1 is in).
16. Optionally run probe 5 again with kid mode on. It must still PASS, and it says the hidden parts were not checked on screen.

**Send back** `zgo_probe_report.txt`.

## 8. Risks and open questions

**Rendering and shaders**
- **A shader that fails to compile closes the game** (probes 2 and 3). This is why they sit behind the experimental option with "save first".
  - shadercheck passes them on four compilers and six define sets.
  - The bump branch of `zgo_probe_dmg.s` had its VS compiled but no linkage check: shadercheck's blender mock passes `null` as the second texture. Its VS output is the stock `v2p_bumped`, unchanged, so the link equals the stock pair.
- **`set_shader` / `reset_shader` / `get_shaders` on NPC sub-meshes are untested in this build** (`docs/discovery/npc.md`).
  - The probes map `get_shaders` entries to child ids by position.
  - If the build numbers them differently, probes 1–3 report it as "reads back the old shader" or as a count mismatch, not as a crash.
  - In the monolith source, the texture-swap path also sets the visual's skinning flag. That is harmless on skinned NPC models, which are all that probes 1–3 touch.
- **`zgo_off.s` defines only `l_special`.** The engine's `_lua_HasShader` accepts that. `_lua_Create` then leaves E0–E3 empty, and `r_dsgraph_insert_dynamic` returns on a null element. If this build differs, the part shows normally and the probe's "judge by eye" catches it.

**Reading files and saves**
- **`getFS():r_open` / `r_close`:**
  - If `r_close` isn't bound, every model read leaks one reader. Reads are cached per model per session, so it is at most one per distinct model.
  - If `r_open` itself is missing, probes 2 and 9 fall back to what the game reports and say "OGF not readable".
- **Saves during a hold.** `on_before_save_input` is registered under pcall. If this build lacks it, a save made during probes 1–3 still saves nothing wrong: shader overrides are render state and not saved. The prop swap of probe 7 is undone on load from the save record.

**Probe-specific**
- **Probe 8:**
  - It replaces `zgo_settings.gore` and holds every `kid_mode` handler during the flip. A future module that hides gore through something other than a `kid_mode` handler would flash for the hold time.
  - Any `zgo_*` global table with a `kid_mode` function is found automatically.
- **Probe 9** is a lower bound until R6 lands (see R6).
- **Probe 6:**
  - The hash includes `set_shader` overrides. Running probes 1–3 on one machine while probe 6 compares gives a mismatch, by design.
  - Bodies outside a client's online radius show as "not online there", not as a mismatch.

**Environment**
- **The test LuaJIT is 2.1; the game's is 2.0.4.** The scripts use no 5.2-only syntax (checked), and FFI is only used behind pcall.
- **Report location under MO2:** the report goes through `$app_data_root$`. Under MO2's virtual file system a newly created file may land in `overwrite\appdata` instead. The summary line prints the path the game used.
