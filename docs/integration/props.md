# Integration note: props (objects in the world: hits, leaks, lamps, breaking, fracture baker)

Workstream "props": PLAN Phase D item 4 and Phase E (E1 to E4, E3 started).

## 1. Summary

**What it does** (`gamedata/scripts/zgo_props*.script`)

- **Hit feedback.** Bullets on loose and destroyable objects throw material-matched bits: splinters and wood dust, sparks, glass, paper and cloth fluff, plastic and ceramic chips. They also play the game's own material sounds.
  - Materials come from the visual and section names (keywords), then from the physics bone material in `zgo_props_models.script` (578 base-game prop models with box, mass and material).
  - `zgo_impacts` (world) asks `zgo_props.handles_impact(rec)` and skips its own object dust when props draws.
- **Extra push.** The host adds an impulse on top of the engine's own bullet push: `J = (push + base) × 6 × energy × clamp(k_impulse, 0.5, 2)` N·s through `shell:apply_force` (F = J × 100, fixed step 0.01), plus a little torque. It is capped at 4 m/s per hit and 8 m/s per second per object. Explosions lift and spin loose objects (`blast_push`).
- **Leaks.** A hole in a barrel, canister or milk can below its seeded fill line leaks a stream and up to 4 growing puddles until it has run dry. Gas bottles and extinguishers hiss a 3.5 to 7 s jet instead.
  - Liquids are water, fuel, oil and chemicals, with ZGO puddle wallmarks (`mod_system_zgo_props.ltx`).
- **Lamps.** A hit on a hanging lamp throws glass and sparks. A lamp the hit put out showers shards. A lamp that survived may flicker (2 or 3 off/on pairs).
- **Native destroyables** (the game's own breakable crates, boards and jars): a burst of dust, splinters or glass sized to the object, plus a crack sound. This works through the vanilla binder's `death_callback` (wrapped once, guard `_G.zgo_props_binder_hooked`) and `set_callback(callback.death)` on unbound ones.
- **Breaking (E2).** Objects the game can't break wear down under fire, melee and explosions, then come apart:
  - Which objects: small crates, chairs, stools, bottles and jars; also barrels and cans once the player's fracture bake exists.
  - **Host:** releases the object (`alife_release`) and sends one `B` line (frame, seed, direction, impulse).
  - **Every machine:** rebuilds the same pieces as world attachments and runs a small fixed-step (60 Hz) simulation (gravity, wall and ground rays, resting faces, sleep). The pieces come to rest in the same places everywhere.
  - Piece sources, in order:
    1. `f`: the player's fracture bake;
    2. `k`: kit-bash from the game's own part models (box_wood_01 parts fitted to each crate's box, bottle_3l parts for bottles, stul_school_01_br, ...);
    3. `b`: a burst with no pieces, for small objects.
  - Objects that never break: story objects, objects with a binder or `db.storage` (logic, stashes, inventory boxes), explosives, and names containing door, gate, car, invbox, stash and similar.
- **E4: explosions break glass.** Bottles and jars near an explosion shatter. Lamps the blast puts out shower glass.
- **E1: native breaking (experimental).** The inert model-data templates `gamedata/configs/models/objects/zgo_props_crate_small.ltx` and `zgo_props_stool.ltx`.
  - The fracture baker's `--experimental-native` (off by default) writes copies of those crates and stools at their stock paths, with that model data plus a `[destroyed]` list of the baked pieces.
  - The game then breaks them itself. The runtime reads `native` from the bake index and leaves those models to the game.
- **E3 started: the fracture baker** (`tools/zgo_fracture`). This is a player-side tool, like the body bake: Python 3 + numpy, about 5 s.
  - **Inputs:** the winning model of each target, from MO2 priority (via `zgo_baker.resolve`) and then the game's archives.
  - **Cutting:** barrels and bottles into Voronoi shells with a thin inner face; crates and stools into planks.
  - **Outputs:** one-bone rigid piece OGFs, `zgo_props_fracture_index.script` and the manifest `zgo_fracture_report.json`.
  - **Library API** for the setup GUI: `bake(options, progress, cancel)`, `remove(out)`, `default_options()`, `STAGES`, `FractureError` / `Cancelled`.
  - **Safety:** it refuses to overwrite files it didn't write, and nothing changes when the bake is cancelled.

**Kid mode:** nothing here is gore, so kid mode changes nothing on this page. No `kid_mode` hook is needed.

**Verified with tests**
- `tests/zgo_test_props.lua` with `tests/mocks/props.lua`. The SP sections cover:
  - HPB round trip, classification, kit-bash fit;
  - feedback, push and caps;
  - breaking and settling, leaks, lamps, native bursts, melee;
  - explosions and glass, baked fracture pieces;
  - options, kid mode and budgets, and "an NPC is not a prop".
- The test then runs itself as **host** and **client**: the client draws its own hit and sends K; the host applies K (including one with no ammo section, `-`); echoes are not drawn twice. The client replays the host's lines, and all broken pieces come to rest exactly where they rest on the host.
- Passes with `ZGO_BAKED=0` and `=1`, seeds 1 5 7 42 99 (10/10).
- `dev/test-all.sh`: **100 runs, 0 failures**.
- `python3 tools/zgo_fracture/selftest.py`: on synthetic meshes, shells and planks cover the surface exactly once (piece areas add up to the source area) and stay inside the source box, and a written piece reads back with `zgo_baker.ogf` as a one-bone `MT_SKELETON_RIGID` with the right mass and material. PASSED.
- Fracture bake against this machine's G.A.M.M.A. game files, into a scratch folder (never into the mod):
  - 15 models into 134 pieces, 2.5 MB, about 5 s. The barrels come from IXRTR, everything else from `meshes_dynamics.db0`.
  - Every piece reads back with `ogf.Model`, and the index loads in LuaJIT.
  - `--remove` removed exactly the files the report lists.
  - The overwrite refusal, cancel and missing-game errors were all exercised.
- `--experimental-native` copies read back with the new model data and the `[destroyed]` list.

**Not verified (needs the game):** everything in section 7. The main points:
- how strong `apply_force` is in practice;
- the attachment frame of the pieces;
- `alife_release` of props under xrRazom;
- the binder hook and `set_callback` on unbound destroyables;
- the experimental native copies.

## 2. Files

**Added** (paths from the mod root)

| File | What |
|---|---|
| `gamedata/scripts/zgo_props.script` | the runtime: classify, hits, push, damage, breaking, leaks, lamps, native bursts, co-op lines |
| `gamedata/scripts/zgo_props_data.script` | materials, liquids, part sets, rigs, native visuals, "never break" words |
| `gamedata/scripts/zgo_props_debris.script` | deterministic piece simulation (fixed step, seeded) and attachment posing |
| `gamedata/scripts/zgo_props_models.script` | generated: box, mass and material of 578 base-game prop models (`tools/zgo_fracture/assets/gen_props_models.py`) |
| `gamedata/scripts/zgo_settings_props.script` | MCM page "props" plus six Performance sliders |
| `gamedata/configs/mod_system_zgo_props.ltx` | puddle wallmark sections `zgo_props_puddle_<liquid>_<n>` |
| `gamedata/configs/models/objects/zgo_props_crate_small.ltx`, `zgo_props_stool.ltx` | inert model-data templates for the experimental native bake (no model includes them) |
| `gamedata/particles/zgo/props/*.pe` (23) | burst_wood, chips_light, chips_stone, dust_light, dust_metal, dust_stone, dust_stone_big, dust_wood, dust_wood_big, fluff, fluff_paper, glass, glass_burst, jet_gas, jet_powder, leak_chem, leak_fuel, leak_oil, leak_water, sparks, sparks_big, sparks_small, splinters. Shaders `particles\add` / `particles\blend`; textures ZGO already ships (crysis_3, fallout4, zgo\fx_streak) |
| `gamedata/textures/zgo/props/puddle_*.dds` (11) | puddle decals, DXT5 256 px with mips (generated) |
| `tools/zgo_fracture/fracture.py` | the fracture bake: library plus CLI |
| `tools/zgo_fracture/cut.py` | mesh cutting: Voronoi shells, planks, clipping, inner faces |
| `tools/zgo_fracture/selftest.py` | checks on synthetic meshes |
| `tools/zgo_fracture/README.md` | usage, outputs, library API |
| `tools/zgo_fracture/assets/gen_props_models.py`, `gen_props_fx.py`, `gen_props_textures.py` | developer generators for the shipped files above |
| `tests/zgo_test_props.lua`, `tests/mocks/props.lua` | tests (SP, host, client); the mock is active only with `PROPS_MOCKS = true` |
| `docs/integration/props.md` | this note |

**Written only on the player's machine** (by `tools/zgo_fracture/fracture.py`, all listed in `zgo_fracture_report.json`, never shipped):
- `gamedata/meshes/zgo/props/fracture/*.ogf`;
- `gamedata/scripts/zgo_props_fracture_index.script`;
- with `--experimental-native` only: `gamedata/meshes/dynamics/box/box_1{a,b,c}.ogf`, `dynamics/box/box_wood_02.ogf`, `dynamics/stul/taburet_{wood_01,village}.ogf`.

**Changed (generated, shared):** `gamedata/configs/text/eng/ui_st_zgo_mcm.xml` and `rus/ui_st_zgo_mcm.xml`, by `luajit dev/gen_mcm_text.lua` (`--check` passes).

## 3. Requests to the integrator

**R1. `dev/package.py`: leave out the fracture bake.** Replace `REPORT` and `generated()` with:

```python
REPORTS = ('zgo_bake_report.json', 'zgo_fracture_report.json')
FRACTURE = ('gamedata/meshes/zgo/props/fracture/', 'gamedata/scripts/zgo_props_fracture_index.script')


def generated():
    out = set(REPORTS)
    for rep in REPORTS:
        try:
            with open(os.path.join(ROOT, rep)) as f:
                out |= {p.replace('\\', '/') for p in json.load(f).get('files', [])}
        except (OSError, ValueError):
            pass
    return out
```

Then in `main()` change the skip test to:

```python
if rel in gen or rel.startswith(FRACTURE) or fn.startswith('.') or fn.endswith(('.pyc', '.part')):
```

`FRACTURE` also keeps a developer's own fracture bake out of the zip if its report was lost. `tools/zgo_fracture/**` itself ships, like `tools/zgo_baker`.

**R2. Setup GUI (`setup` workstream): add a "Breakable objects" step** after the body bake.
- `sys.path.insert(0, <mod>/tools/zgo_fracture); import fracture`.
- Bake with `fracture.bake(fracture.default_options(), progress, cancel)`. Pass the same MO2 folder, profile and game folder the user picked for the body bake (`Options(mo2=, profile=, anomaly=, out=<mod root>)`).
- Remove with `fracture.remove(<mod root>)`.
- `progress(stage, done, total, message)`, with `stage` in `fracture.STAGES = ('prepare', 'resolve', 'cut', 'install', 'done')`.
- `cancel()` returning True raises `fracture.Cancelled` before anything is written. Other failures raise `fracture.FractureError`, whose message is meant for the player.
- It returns the report dict. `report['results']` has one entry per model, with a `status` of `ok` or the reason it was skipped.
- One experimental checkbox, off by default: "Let the game break crates and stools itself (experimental)" → `opts.experimental_native = True`.
- It takes about 5 s and needs only numpy (already a body-bake dependency).

**R3. `zgo_sync.script`: bump `PROTO` (2 → 3) for 1.7.** The props workstream adds the kinds `B`, `X` and up `K` (section 5) and new particle and texture assets. If the 1.7 version / bake handshake from the PLAN is added, include `zgo_props_fracture_index.bake` (string, absent = no fracture bake). A mismatch is cosmetic only: the client falls back to kit-bash pieces. So log it, don't refuse.

**R4. `tests/zgo_harness.lua` line 70: read every ZGO wallmark ltx.** Replace

```lua
for _, fname in ipairs({ "mod_system_zgo.ltx", "mod_system_zgo_engine_marks.ltx" }) do
```

with a list of `gamedata/configs/mod_system_zgo*.ltx`, for example

```lua
local fnames = {}
local p = io.popen('ls "' .. GAMEDATA .. '/configs" 2>/dev/null')   -- use the harness's own gamedata path variable
for l in p:lines() do if l:match("^mod_system_zgo.*%.ltx$") then fnames[#fnames + 1] = l end end
p:close()
table.sort(fnames)
for _, fname in ipairs(fnames) do
```

Until then, `tests/mocks/props.lua` adds `mod_system_zgo_props.ltx` itself.

**R5. `dev/gen_mcm_text.lua` and `tests/zgo_test_settings.lua`: fail on a broken settings page.**
- **Problem:** `zgo_settings` looks feature pages up through a pcall, so a `zgo_settings_<ws>.script` with a syntax error is silently left out. The generator then writes the strings without that page, `--check` passes and the settings test passes.
- **How I found it:** it happened briefly in this workstream, and I fixed it within a minute. Please check that the final generated xml contains "Objects break apart"; if another workstream regenerated during that minute, re-run the generator.
- **Suggested fix:** in `gen_mcm_text.lua`, after loading, glob `gamedata/scripts/zgo_settings_*.script` and `assert(loadfile(path))` each one. Do the same in the settings test.

**R6. kidfx: leave `gamedata/particles/zgo/props/*.pe` as they are.** They are environmental effects (dust, splinters, sparks, glass, liquids) with stock `particles\add` / `particles\blend` shaders. Kid mode doesn't change props. They are played by `zgo_props` itself (`particles_object`), not through `zgo_fx`, so `zgo_fx.is_gore` never sees them.

**R7. README.md:** add the PROPS text from section 6 (its "Objects (props)" section). The "Objects break apart" option text points to "README, PROPS".

**R8. Not needed:**
- **kid_mode wiring:** nothing here is gory.
- **test-all.sh:** it globs `zgo_test_*.lua`.
- **dev/distrobox.ini:** no new packages for players or tests. The developer asset generators use PIL and ImageMagick, already on the host.

## 4. Settings added

All in `zgo_settings_props.script`. Page `props` (after `explosions`), co-op `host` unless marked `local`. English and Russian names and descriptions are present.

| Key | Type | Default | Notes |
|---|---|---|---|
| `props/enable` | check | on | master switch |
| `props/feedback` | check | on | local: hit effects on objects |
| `props/push` | track 0 to 3, step 0.1 | 1.0 | extra bullet push (0 = engine only) |
| `props/blast_push` | track 0 to 3, step 0.1 | 1.0 | explosions lift and spin objects |
| `props/leaks` | check | on | leaking containers |
| `props/native_bursts` | check | on | local: bursts on the game's own breakables |
| `props/lamps` | check | on | lamps shatter and flicker |
| `props/breaking` | check | on | objects break apart |
| `props/toughness` | track 0.25 to 4, step 0.25 | 1.0 | hit-points multiplier |
| `props/melee_breaks` | check | on | melee counts toward breaking |
| `props/blast_glass` | check | on | explosions break glass |
| `props/sounds` | check | on | local: breaking sounds |

Performance page; `perf` = potato, low, medium, high, ultra, and the default is high:

| Key | Range, step | perf |
|---|---|---|
| `performance/props_fx` (effects per second) | 4 to 80, 2 | 6, 10, 16, 24, 40 |
| `performance/props_pieces` (pieces at once; 0 = burst only) | 0 to 96, 4 | 8, 16, 28, 40, 64 |
| `performance/props_pieces_life` (s) | 10 to 600, 10 | 20, 40, 60, 90, 180 |
| `performance/props_leaks` (at once) | 0 to 16, 1 | 1, 2, 4, 6, 10 |
| `performance/props_range` (m) | 10 to 150, 5 | 20, 30, 45, 60, 90 |
| `performance/props_marks_life` (puddles, s) | 60 to 3600, 60 | 120, 240, 480, 900, 1800 |

**Experimental flag:** the baker's `--experimental-native` (setup GUI checkbox, off by default). There is no in-game experimental option.

**Defaults:**
- Objects the game already breaks keep breaking exactly as before; ZGO only adds bursts.
- "Objects break apart" is on: breaking stock crates, chairs and bottles is the feature.
- It uses only well-known script APIs: `apply_force`, `alife_release`, level attachments as used by `zgo_debris`, and particles.
- The one route that changes engine behaviour (model data on stock models) is behind the experimental bake flag.

## 5. Co-op

**What the host and clients do**
- **The host decides:** push, damage, breaking (it releases the object), leaks, lamp outcome and blast effects.
- **Every machine draws:** hit effects, pieces, leaks, puddles, lamp shards and flicker.
- **Clients:**
  - draw their own hit at once and forward it up as `K` with a token;
  - never push or break anything, and ignore the host's echo carrying their token;
  - ignore all lines when ZGO is disabled.
- **The host** ignores a peer's bullet seen locally (the peer forwards it). It applies `K` with the engine's share of the push added, unless it saw the round itself.
- **Replication:** physics motion of pushed objects replicates through xrRazom; releases replicate through ALife.

**Lines.** Positions and directions are quantized with `zgo_util.q3` / `qv`. Seeds are 1 to 2147483646.

```
B|id|visual|src|px|py|pz|h|p|b|dx|dy|dz|imp|seed|mtl
    an object broke. src f/k/b (the client uses the same source when it has
    it, else falls back k -> b); frame = position + heading/pitch/bank of the
    object; d = break direction; imp = 0..12; mtl = material code
X|h|mtl|px|py|pz|nx|ny|nz|e|seed|tok
    a hit effect (energy e); tok = the forwarding client's token or 0
X|l|id|sec|lx|ly|lz|liquid|ms|seed
    a leak: hole in object space, liquid code, duration in ms
X|f|id|seed          a lamp flickers (pattern from the seed)
X|s|px|py|pz|seed    lamp shards
X|d|mtl|px|py|pz|size|seed
    a burst (native destroyable death, blast glass, burst-only breaks)
up K|id|sec|ammo|speed|px|py|pz|dx|dy|dz|tok
    a client's round on an object (ammo "-" when unknown)
```

**Determinism.** The pieces follow from (visual, src, frame, seed, d, imp) and a fixed-step simulation, with no `math.random` and no frame-time dependence. The host and client tests compare rest poses (15 pieces, 0 differences).

**Fracture bakes on different machines.** A machine without the host's source falls back to kit-bash pieces. This is cosmetic only, since the object is already released on the server.

## 6. README text

Insert under WHAT IT DOES, after World impacts:

```
  Objects (PROPS)
    Bullets throw splinters, dust, sparks, glass or fluff off crates,
    barrels, bottles, lamps and furniture, and shove loose objects harder
    (heavier rounds more, heavy objects less); explosions lift and spin
    them. A hole in a barrel, canister or milk can below its fill line
    leaks water, fuel, oil or chemicals into a growing puddle until it runs
    dry; gas bottles hiss out a jet. Shot lamps shower glass, or flicker if
    they survive. Crates, boards and jars the game can already break now
    burst with dust and splinters.
    Small crates, chairs, stools, bottles and jars that the game can't
    break wear down under fire, knife hits and explosions and come apart
    into pieces (the game's own crate and bottle parts). Barrels and milk
    cans break too once the setup tool's "Breakable objects" step has cut
    pieces from the models your mod list uses (about 5 seconds; re-run it
    after changing mods that replace prop models). Explosions shatter glass
    nearby. Quest items, stashes, doors, explosive barrels and anything
    with its own script never break.
    MCM -> Objects; how many effects, pieces and leaks, their lifetime and
    range are on the Performance page. Not gore: kid mode leaves all of it
    alone.
```

Add to LIMITS:

```
  * Broken objects are gone for good (also after loading a save); their
    pieces, leaks and puddles are not saved.
  * Pieces of broken objects are visual only: they don't block bullets,
    can't be picked up and don't push other objects.
  * Window panes are part of the level and never break.
  * The "Breakable objects" pieces are made from your own game files and
    are not in the download. In co-op, a player without them sees the
    game's own parts instead.
  * Experimental: "Let the game break crates and stools itself" (setup
    tool) replaces those crate and stool models with copies that the game
    breaks on its own. Untested in co-op; leave it off there.
```

CHANGES bullet:

```
  1.7.0  Objects: material hit effects, harder pushes and blast throws,
         leaking barrels and canisters with puddles, shattering and
         flickering lamps, bursts on the game's breakables; small crates,
         chairs, stools, bottles and jars break apart under fire, knife
         and explosions, barrels and cans too after the setup tool's
         "Breakable objects" step. Host-decided in co-op, the pieces land
         in the same places for everyone.
```

## 7. In-game checks

Use single player first (with MCM -> ZGO -> Debug log on if available), then co-op with one client.

1. **Push strength.** In Cordon, at the village, shoot a loose chair or bucket with a pistol, then an AK, then a shotgun.
   - Expected: it moves more than in vanilla, but no object jumps more than about a metre from one round.
   - With "Extra push" at 0 it should look vanilla. If the push is far too strong or too weak, report it (the `apply_force` scale was derived from source).
2. **Pieces are placed and oriented right.** Shoot a small wooden crate (`box_1a` style, not a stash) until it breaks.
   - Expected: the planks appear exactly where the crate was, the same way round. Rotate other crates and repeat.
   - If the pieces appear mirrored, rotated 90° or offset, the attachment frame or the HPB convention is wrong.
3. **Pieces fall and rest.** The pieces fly away from the shot, bounce, settle on the floor (not inside it or floating) and vanish after "Pieces: time on the ground".
4. **Bottles and jars.** Shoot a vodka bottle on a table: glass pieces and a shatter sound. Throw a grenade near some bottles: bottles within a few metres shatter.
5. **Leaks.** Shoot a closed barrel low down, then high up.
   - Low: a stream from the hole and growing puddles under it, which stop after a while.
   - High (above the fill line): no leak.
   - A gas bottle gives a short hissing jet. The puddles should look like liquid, not like squares.
6. **Lamps.**
   - Shoot a hanging lamp: glass and sparks. If it went out: a shower of shards. If it stayed on: sometimes a short flicker that ends with the lamp on.
   - A grenade under a lamp that puts it out also showers glass.
7. **The game's own breakables.** Knife or shoot a breakable crate (vanilla `physic_destroyable_object`, e.g. in Agroprom).
   - Expected: it breaks as in vanilla, plus a dust and splinter burst and a crack.
   - Check the log for errors around the vanilla binder (`bind_physic_object`).
8. **Melee on unbound breakables.** Knife a small crate the game can't break: it breaks after about 3 hits.
9. **Never breaks.** Stashes, quest items, doors, explosive barrels, inventory boxes and the trader's crates never break or vanish.
10. **Save/load.** Break a crate, save, load: it stays gone, with no errors.
11. **Co-op (host + one client).** Repeat 1 to 6 with the client shooting:
    - the client sees its own hit effect at once;
    - the host sees the push and the break;
    - both see the pieces land in the same places;
    - the broken object disappears on the client too (ALife release replicated);
    - leaks and lamp flickers show on both.
12. **Fracture bake** (once the setup step exists, or by running `python3 tools/zgo_fracture/fracture.py` and re-loading).
    - Shoot a barrel until it breaks: metal shells with an inner face, no gaps or missing faces, the barrel's own texture.
    - Then run `fracture.py --remove`: barrels no longer break.
13. **Experimental native** (`fracture.py --experimental-native`, SP only).
    - A crate the level spawned as `physic_destroyable_object` breaks by itself into the baked planks; loose crates that use the same model behave as before.
    - Then `--remove` and check that the crates are back to normal.

## 8. Risks and open questions

**Engine behaviour that is unverified** (the code fails safe with pcall)
- How strong `apply_force` is in practice, and the `apply_torque` signature on an element.
- The bone / xform frame of the piece attachments.
- `set_callback(callback.death / callback.hit)` on unbound destroyables.
- Binder wrapping when another mod also replaces `generic_physics_binder.death_callback`. The wrap is done once and calls the previous function.

**Co-op**
- `alife_release` of a physic object on the xrRazom host is assumed to replicate to clients. If it doesn't, clients keep a ghost of the object (cosmetic) until they reload.
- Native destroyables (DESTR_HIT / DESTR_DEST) are handled engine-side by xrRazom. ZGO only adds client-side bursts, through the binder's death callback on each machine.

**Experimental native copies**
- They are written at stock model paths. They only work while ZGO is above other mods that ship those crate and stool models, and they change model data for every object using those models. Only `physic_destroyable_object` reads `[destroyed]`; how a plain `physic_object` treats the extra sections (`[collide]`, `[disable]`) is unverified. This is why they are off by default.
- The baker's `native_copy` uses `ogf.write_chunks` and `model.tail` from `zgo_baker.ogf`. If baker2 changes those names, the experimental path breaks; the default bake does not use them.

**Shipped derived metadata**
- `zgo_props_models.script` ships numbers derived from base-game models: a bounding box, the summed bone mass and a material class per model. It contains no geometry or textures.
- Is shipping that acceptable? If not, the setup GUI can run `tools/zgo_fracture/assets/gen_props_models.py --anomaly <game>` instead, and the runtime then falls back to name keywords.

**Coverage left for later phases**
- Chairs (`stul_wood_01`), lab boxes (`box_lab_01/03`) and bigger furniture have no fracture targets yet (chairs use kit-bash rigs).
- Glass panes in levels are level geometry and can't break.

**Performance**
- A scan every 2 s of objects within 35 m (`level.iterate_nearest`) for lamps and destroyables.
- The piece simulation runs per flying piece, and resting pieces sleep. Both are capped by the Performance sliders.

**Downloads and packages**
- Downloaded (read only, into `~/.cache/zgo-props-src`, from `https://raw.githubusercontent.com/themrdemonized/xray-monolith/b86d733f4a/src/...`): `PhysicsCommon.h`, `PHElementInline.h`, `PHWorld.cpp`, `Physics.cpp`, `script_attachment_script.cpp`, `script_attachment_manager.cpp`, `script_attachment_manager.h`, `_matrix.h`.
- No packages installed and no Wine used.
- Tools used: python3 with numpy and PIL, ImageMagick (`magick`), luajit.

**Test infrastructure**
- `tests/mocks/props.lua` used to override `level.iterate_nearest`, `clsid`, `alife_object` and `sound_object` for every suite. That broke the new probe and native suites in `test-all`.
- It is now gated on `PROPS_MOCKS = true`, like the probe mock, and test-all is clean.
