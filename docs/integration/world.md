# Integration note: world (bullet impacts on the world, explosion craters)

Workstream "world", PLAN Phase D items 1, 2, 3 and 5.

## 1. Summary

**What it does**

Bullets that hit level geometry now leave marks sized by calibre and throw dust, chips, splinters or sparks to match the surface:
- **Material families:** stone, brick, plaster, wood, metal, earth. Glass is left to the engine.
- **Material lookup:** one `ray_pick` along the bullet reads `get_result().material_name` and `get_normal()`. Materials added by other mods are matched by name; anything else takes nothing.

Repeated hits on one ~18 cm spot of a surface add up:
- **Masonry, plaster and wood:** chip → crack (wood splits) → gouge → a dark "breach".
- **Metal:** chip → dent → tear.
- **Earth:** only takes splashes.

**Objects** (crates, barrels, cars) get the particles only. If `zgo_props.handles_impact(rec)` says props owns the object, this layer draws nothing for it.

**Explosions** (the `zgo_util` "explosion" event) leave:
- a scorch mark and a dark pit, sized by `charge^(1/3)` (`zgo_blast.KINDS`, otherwise `blast/3` from the ini);
- fragment pocks, from seeded rays;
- a dust ring, a dust column, a dust flash, and smoke that hangs for Performance → Explosion smoke;
- **indoors** (a ceiling within 6 m, found with an upward ray), grit and dust falling from the ceiling, some of it delayed;
- **optionally** (experimental, off by default), a rubble or dirt rim mesh plus clods or concrete chunks. A small fixed-step simulation moves the clods, so they land in the same places on every co-op machine.
- **Rockets into walls** scorch the wall. **Air bursts** only make dust and smoke.

The engine's own `[explosion_marks]` is extended with DLTX: bigger, and with ZGO scorch textures added.

**Co-op:** the host decides everything and sends I and C lines. Clients forward their own impacts with J lines.

**Verified, with tests**
- `tests/zgo_test_world.lua`: single player, then it runs itself as a co-op host and as a co-op client. Every check is listed in section 7 of the test output.
- `dev/test-all.sh`: **80 runs, 0 failures** (both bake modes, seeds 1 5 7 42 99).
- Both shaders compile with the native Microsoft `d3dcompiler_47` 10.0.26100.1 under Wine:
  - against the base shaders with SSS 23 on top, and against the base shaders alone;
  - with the engine's macros (`dev/shadercheck/sc_engine.defines(BASE)`), entry `main`, `vs_5_0` / `ps_5_0`, flags 8;
  - result **OK** in all cases.
- The generated OGFs match the game's own rigid debris model chunk for chunk. They were checked by reading them back with `tools/zgo_baker/ogf.py`.

**Not verified (needs the game)**
- How the marks, effects and meshes look in game.
- The DLTX override of `[explosion_marks]`.
- `ray_pick:get_result().material_name` and `get_normal()` on the xrRazom build. All of these names are in the exe strings; the code falls back to `zgo_util.surface_at` and treats the surface as stone.
- Script particles' `stop_deffered`.
- The deep-mark shader route, which needs the dispatcher in request R3.
- The new meshes as level attachments. This is why the rubble option is experimental.

## 2. Files

All the files below are new. No existing file was edited except the two generated MCM string tables.

**Scripts** (`gamedata/scripts/`)

| File | What it holds |
|---|---|
| `zgo_impacts.script` | Bullet impacts, the damage grid, marks and their budget, I and J lines, the frame update, level-change reset |
| `zgo_impacts_crater.script` | Craters, the C line, rim and clod pieces with their simulation |
| `zgo_impacts_fx.script` | Particle holder (keeps references until an effect finishes, `stop_deffered` for smoke) and the per-second budget |
| `zgo_impacts_data.script` | Material → family, per-family thresholds and sizes, section / effect / mesh names |
| `zgo_settings_world.script` | "World impacts" MCM page and seven Performance sliders |

**Configs**
- `gamedata/configs/mod_system_zgo_impacts.ltx`: 118 `zgo_world_*` wallmark sections, plus `![explosion_marks]`.

**Generated MCM text** (by `luajit dev/gen_mcm_text.lua`; `--check` is clean)
- `gamedata/configs/text/eng/ui_st_zgo_mcm.xml`
- `gamedata/configs/text/rus/ui_st_zgo_mcm.xml`

**Textures:** `gamedata/textures/zgo/impacts/*.dds` (62) and `gamedata/textures/zgo/impacts/deep/*.dds` (56), 13 MB in all.
- All are uncompressed B8G8R8A8 with mips.
- They are modulate-2x art: 128 grey leaves the wall unchanged. The border is exactly 128, and mips of 4 px and smaller are flat 128.
- `deep/` textures carry height in alpha.

**Particles:** `gamedata/particles/zgo/world/*.pe` (32 effects, text format). They use only textures ZGO already ships.

**Meshes:** `gamedata/meshes/zgo/world/*.ogf`. All are MT_SKELETON_RIGID with one bone "link" and shader `models\model`:
- `crater_rim_{earth,stone}_{1,2}`, textured `grnd\grnd_zemlya` and `crete\crete_beton_lom`;
- `clod_earth_{1..3}` and `chunk_stone_{1..3}`.

**Shaders:** `gamedata/shaders/r3/zgo_wm_deep.vs` and `zgo_wm_deep.ps` (experimental, only reached through R3).

**Tests:** `tests/zgo_test_world.lua` and `tests/mocks/world.lua`.

**Asset generators** (not shipped)
- Location: `~/.cache/zgo-world/gen/` — `gen_textures.py`, `gen_ltx.py`, `gen_particles.py`, `gen_meshes.py`, `run_all.sh`.
- How to run: `dev/run.sh bash ~/.cache/zgo-world/gen/run_all.sh "$PWD"` (numpy; `gen_meshes.py` imports `tools/zgo_baker/ogf.py` and `xdb.py`, reading the game's `meshes_dynamics.db0` for the template winding).
- They are also kept in the session scratchpad. See R4.

**Downloads and packages**
- Engine sources from `https://raw.githubusercontent.com/themrdemonized/xray-monolith/b86d733f4a/src/...` into `~/.cache/zgo-src/`:
  - `xrGame/Level_Bullet_Manager.cpp`, `Level_bullet_manager_firetrace.cpp`, `script_wallmarks_manager.cpp`, `raypick.h`, `raypick.cpp`, `wallmark_manager.cpp`, `level_script.cpp`, `script_attachment_manager.{h,cpp}`, `script_attachment_script.cpp`, `script_particles.cpp`;
  - `Layers/xrRender/ParticleEffectDef.{h,cpp}`, `ParticleEffectActions.cpp`, `ResourceManager_Scripting.cpp`;
  - `xrParticles/particle_core.cpp`;
  - the GitHub tree listing.
- **No packages installed.**
- Wine prefix `~/.cache/zgo-wine-world` (created with `wineboot`). It is used only to run the existing `~/.cache/zgo_shadercheck/bin/zgo_d3dc.exe` with the existing `~/.cache/zgo_shadercheck/compilers/ms-10.0.26100.1/d3dcompiler_47.dll`.

## 3. Requests to the integrator

**R1. `zgo_main.script`, `on_bullet`:** pass the engine's material and distance on the "bullet" event. That saves one ray per impact and gets the exact triangle's material. Add `material = bullet.material, distance = bullet.distance,` to the table:
```lua
U.defer(U.emit_event, "bullet", { pos = U.v3(p.x, p.y, p.z), dir = U.v3(d.x, d.y, d.z), speed = bullet.speed,
    ammo = bullet.section, element = bullet.element, target_id = bullet.target_id, shooter = bullet.parent_id,
    weapon_id = bullet.weapon_id, material = bullet.material, distance = bullet.distance })
```
`zgo_impacts` already uses `rec.material` when present. It still probes for the normal.

**R2. `zgo_blast.script`:** two small changes.
1. Export the charge scale: rename `local function kind_of(r)` to `function kind_of(r)`. The local callers stay as they are.
2. Add the section to the "explosion" event: in `on_frag_init`, change the emit to `{ eid = eid, center = U.vcopy(r.center), thrower = parent, sec = r.sec }`.

`zgo_impacts_crater.charge_of` currently repeats the `KINDS` / `blast/3` rule and reads the section from `level.object_by_id(eid)`. With R2 it can use `rec.sec` when the grenade object is already gone.

**R3. Deep-mark dispatcher:** ship `gamedata/shaders/r3/effects_wallmark.s` (only for the experimental "Deep impact marks" option). Nothing in the modlist overrides this file; it lives only in `shaders.db0`. The else-branch below is byte-identical to the stock file. Content:
```lua
function normal(shader, t_base, t_second, t_detail)
  -- Zone Gore Overhaul: textures under zgo\impacts\deep\ (MCM World impacts ->
  -- Deep impact marks) go to its parallax decal shader; everything else is stock.
  if t_base and string.find(string.lower(t_base), "zgo\\impacts\\deep\\", 1, true) then
    shader:begin("zgo_wm_deep","zgo_wm_deep")
      : blend   (true,blend.destcolor,blend.srccolor)
      : zb      (true,false)
    shader:dx10texture ("s_base", t_base)
    shader:dx10sampler ("smp_base")
    shader:dx10color_write_enable( true, true, true, false)
    return
  end
  shader:begin("effects_wallmark","stub_default_ma")
		: blend		(true,blend.destcolor,blend.srccolor)
		: zb 		(true,false)
	shader:dx10texture	("s_base", t_base)
	shader:dx10sampler	("smp_rtlinear")
	shader:dx10color_write_enable( true, true, true, false)
end
```
- The shader Lua state opens `base`, `table`, `string`, `math` and `jit` (`ResourceManager_Scripting.cpp:344`), so `string.find` is available.
- Without this file the option is harmless: the `*_d` sections use the same colours, and the stock shader never writes alpha.
- If the shadercheck workstream finishes `dev/shadercheck`, please add `r3/zgo_wm_deep.vs` and `r3/zgo_wm_deep.ps` to its set.

**R4. Asset generators:** move them from `~/.cache/zgo-world/gen/` to `tools/zgo_world_assets/`, so the art can be regenerated. Change `run_all.sh`'s default `GAME_DB` to come from the environment only.

**R5. Ownership path:** WORKSTREAMS lists `gamedata/configs/materials/*zgo*`, but the engine reads material pairs from `$game_data$\materials\material_pairs.ltx`, i.e. `gamedata/materials/`. Its DLTX files are `gamedata/materials/mod_material_pairs_<name>.ltx`, with `@[mtlA@mtlB]` to change keys of an existing pair; the exe has the `[material_pairs.ltx]` DLTX log strings.

I decided not to ship a pair extension, because the script layer covers everything:
- G.A.M.M.A.'s pairs come from several mods: Teamson & Oleh's Bullet and Grenade Impact Sounds (#295) restates every `X@objects\bullet` pair, plus Oleh's Misc Sound (#44), Bolt Impact (#294), Dark Signal footsteps (#70) and Items Model Drop (#284). Touching pairs risks their sounds and particles.
- Changes to pairs can't be switched off from MCM.

Please fix the path in WORKSTREAMS for whoever needs it later.

**R6. PROTO:** no bump is needed. I, C and J are new kinds, and an older peer ignores kinds it has no handler for (`handlers[t[1]]` is nil). Bump it only if the release bumps it anyway.

**R7. `test-all.sh`:** nothing needed. `zgo_test_world.lua` is picked up automatically, ends with `ALL WORLD TESTS PASSED`, and runs its own host and client roles as subprocesses.

**Harness note:** `tests/mocks/world.lua` records `zgo_world_*` marks in `WORLD_PLACED` and `zgo\world\` effects in `WORLD_FX` instead of `PLACED` / `FX`.
- Reason: other suites assert that kid mode leaves no decals and no gory effects, and world impacts are not gore. This keeps their counts as they were.
- The harness's own checks still run on these marks and effects: the section exists, the size is in range, the trace hits.
- The mock also adds `get_result()` / `get_normal()` to `ray_pick`, plus an optional ceiling (`WORLD_CEILING`).

## 4. Settings added

**Page "world"** ("World impacts", `after = "explosions"`, coop host):

| Key | Default | Co-op | Notes |
|---|---|---|---|
| `world/enable` | true | host | bullet impacts on level geometry and objects |
| `world/escalation` | true | host | damage builds up per spot |
| `world/mark_size` | 1.0 | host | track 0.5–2, step 0.05 |
| `world/objects` | true | host | particles off crates, barrels, cars |
| `world/npc_impacts` | true | host | NPC rounds near a player count too |
| `world/craters` | true | host | |
| `world/crater_debris` | **false** | host | **experimental**: rim and clod meshes |
| `world/particles` | true | **local** | |
| `world/deep_marks` | **false** | **local** | **experimental**: needs R3 |

**Performance page** (perf = potato, low, medium, high, ultra; the default is High):

| Key | perf | Range / step |
|---|---|---|
| `world_marks` (marks per second) | 6, 10, 16, 24, 40 | 2–60, step 1 |
| `world_mark_lifetime` (s) | 60, 120, 240, 480, 900 | 30–1800, step 30 |
| `world_fx` (effects per second) | 6, 10, 18, 28, 48 | 2–80, step 1 |
| `world_range` (m) | 30, 45, 60, 80, 120 | 15–200, step 5 |
| `world_cells` (damage spots remembered) | 64, 128, 256, 512, 1024 | 32–2048, step 32 |
| `world_debris` (pieces at once) | 0, 4, 8, 14, 24 | 0–64, step 1 |
| `world_smoke` (s) | 0, 6, 10, 15, 25 | 0–60, step 1 |

Every option has English and Russian names and descriptions.

**Kid mode:** not consulted anywhere. Impacts and craters are not gore.

## 5. Co-op

**`I|x|y|z|nx|ny|nz|fam|cls|mk|var|size|rot|fx|tok`** (host → clients): one decided impact.

| Field | Meaning |
|---|---|
| x y z, n | quantised with `U.q3`: point and outward normal |
| fam | `zgo_impacts_data.FAMILIES` index (1 stone … 7 glass) |
| cls | calibre class 1–5 |
| mk | index into the family's marks: 0 none, 1 chip or splash, 2–4 stages |
| var | texture variant |
| size | mark half-size |
| rot | rotation in degrees |
| fx | 0 none, 1 dust, 2 heavy, 3 stage burst, 4 breach |
| tok | the J token it answers, or 0 |

- One line per impact (dust for everyone) plus one per stage reached.
- Clients draw the marks within their own mark budget and lifetime.
- A client skips particles for a line that carries one of its own tokens.

**`C|x|y|z|nx|ny|nz|fam|charge|ceil|seed|flags`** (host → clients): one crater.
- Point and normal of the surface under the blast (or the blast centre).
- `fam` is 0 for none.
- `charge` is TNT relative to a hand grenade.
- `ceil` is the ceiling height above the point (0 means none).
- `seed` drives all randomness.
- `flags`: 1 ground, 2 wall, 4 debris (the host's `crater_debris`), 8 ceiling grit.

Every machine, the host included, draws from the line with `U.rng(seed)`. Tests confirm identical marks and identical clod rest positions on host and client.

**`J|x|y|z|nx|ny|nz|fam|cls|e|tok|obj`** (client → host): the client's own round hit something.
- It is sent only for the client's own rounds, because the host never sees them.
- At most 30 per second.
- The client plays its dust immediately.
- The host resolves the impact through the same grid and answers with I lines carrying `tok`.

**Who does what**
- **The host decides:** chips and their chance, damage stages, sizes, rotations, craters, the debris flag. It never acts on a peer's own bullets.
- **Clients ignore all other bullets;** the host's lines cover them.
- **Range:** the host checks every player (the actor and the `XrrPlayers` peer proxies). A client checks its own draw range.
- **Rubbish lines** (short, NaN, huge, zero normal, unknown family) are dropped. Tests cover this.

## 6. README text

Insert under WHAT IT DOES, after the explosions part:

```
  World impacts
    Rounds that hit walls, floors, trees and objects leave marks sized by
    calibre on top of the game's own bullet holes: a pistol round chips,
    a rifle round gouges, buckshot peppers. Dust, chips, splinters and
    sparks match the surface (concrete, brick, plaster, wood, metal,
    earth). Keep firing at one spot and the damage builds up: chips turn
    into cracks, then a deep gouge, and sustained fire knocks a dark breach
    into masonry and wood (metal dents and tears). Marks only: walls don't
    open and bullets don't pass through.
    Explosions leave a scorched crater sized by the charge (grenade, VOG,
    mine, RPG, IED), pock marks from fragments on the walls and floor
    around it, a ring of dust rolling out along the ground and smoke that
    hangs for a while; indoors, grit and dust rain from the ceiling.
    Optional (experimental): clods of earth and chunks of concrete thrown
    out of the crater, and a rim of thrown-up dirt or rubble.
    MCM -> World impacts; how many marks, effects and pieces, their
    lifetime and range are on the Performance page. Not gore: kid mode
    leaves all of it alone.
```

Add to LIMITS:

```
  * World impact marks are decals: walls never open, and marks are not
    kept in saves. The game's own marks around explosions
    ([explosion_marks]) are made a little larger and get scorch textures
    from this mod; they don't follow the MCM options.
  * Deep impact marks (experimental) need the effects_wallmark.s file
    shipped with this mod; another mod that replaces that file turns them
    back into ordinary marks.
```

CHANGES bullet:

```
  1.7.0  World impacts: calibre-sized bullet marks with dust, chips and
         sparks per material, damage that builds up per spot (chip ->
         crack -> gouge -> breach), explosion craters with fragment pocks,
         dust ring, hanging smoke and ceiling grit indoors; optional
         rubble and clods (experimental) and parallax "deep" marks
         (experimental). Host-decided in co-op.
```

## 7. In-game checks

1. **Load and log.** Load a save, wait 10 s and open the log. There must be no `world impact error`, `world crater error` or missing-texture or missing-particle lines.
2. **Marks on concrete.** Shoot a concrete wall at 5–10 m.
   - Small light chips with a dark centre should appear next to the game's holes, with grey dust puffing off the wall towards you.
   - With a pistol the chips are smaller. Marks must not show a visible square or a tinted border; if they do, report it with a screenshot.
3. **Build-up.** Empty a magazine into one spot (hold still).
   - The stages should appear in order at the same spot: crack lines, then a larger gouge, then a dark breach with a burst of chips.
   - Repeat on a brick wall (reddish dust), plaster (white dust), a wooden fence (splinters, a long split) and sheet metal (sparks, dent, then a torn hole).
4. **Earth.** Shoot the ground: dirt splashes, no build-up.
5. **Objects.** Shoot a wooden crate and a metal barrel: splinters and sparks, and no new marks from this mod.
6. **Craters.** Throw an F1 grenade onto open ground.
   - A dark pit and a scorch (about 1.5 m across) should appear, with pocks on nearby walls, a ring of dust rolling outwards and smoke hanging about 15 s (High preset).
   - Fire an RPG at the ground: the crater should be larger.
   - Throw a grenade into a room: grit should fall from the ceiling for a second or two.
7. **Engine explosion marks.** Around every explosion the game's own grenade marks should now also include the ZGO scorch textures, slightly larger. If explosion marks vanish entirely, the DLTX `![explosion_marks]` failed: report the log.
8. **Experimental: Crater rubble and clods.** Tick it and throw a grenade on open ground.
   - A low ring of dirt should sit around the pit, and 4–6 clods should fly out and come to rest on the ground. They must not float or sink deep.
   - On concrete you should see grey chunks and a rubble rim.
   - If the game crashes with a model or visual error, untick it and send the log.
9. **Experimental: Deep impact marks.** Requires R3. Tick it, then shoot a concrete wall until a gouge appears.
   - Gouges and breaches should look recessed when you move sideways (parallax), and fade out smoothly near the end of their lifetime.
   - Flat grey squares mean the shader route failed; a crash at the first mark means a shader compile failure. Report the log either way.
10. **Co-op** (host and one client).
    - The client shoots a wall: it sees dust at once, and the same marks appear on both screens.
    - An NPC fires at a wall near the client: both see marks.
    - The host throws a grenade: both see the same crater. With rubble on, the clods land in the same places.
11. **Performance.** Set the Performance preset to Potato and hold automatic fire on a wall for 20 s. Frame time should not climb; marks are capped at 6 per second.

## 8. Risks and open questions

**Engine behaviour not yet seen in game**
- **Material and normal lookup.** `rq_result.material_name` and `ray_pick:get_normal()` exist in the exe strings, but I haven't seen them in game.
- **Material names vary by level.** If `material_name` comes back empty on some levels, everything falls back to a "stone" family guess, which is not right everywhere.
- **Floating marks.** `wallmarks_manager():place` raycasts with rqtBoth and gives up if an object is in the way, so marks never float. On thin geometry, a mark can still land on the far side of a wall; this is the same as the blood decals.
- **Stage-mark lifetime.** A stage mark replaces an older mark using the same shader within 2 cm (an engine rule), so stacking is limited. The previous stage stays visible underneath until it fades, which is intended. Stage marks live `world_mark_lifetime` from the moment they are placed.

**Experimental pieces**
- **Rubble meshes.** These are new, generated models (verified structurally against the game's own rigid debris). They are behind the experimental option because a bad model is a crash, not a fallback.
- **Clod simulation.** It casts one ray per step for each flying clod: at most ~24 clods for about 1–2 s on Ultra.
- **Deep-mark shader.** It compiles cleanly, but the parallax depth (0.07 UV) and the cotangent frame are unverified visually. TAA jitter comes from SSS's engine constant `ssfx_jitter`; it is declared locally when SSS's header isn't present (it is zero without TAA).

**Particles.** These are newly written effects in the documented text format, with every action's parameter count checked against `ParticleEffectActions.cpp`. Their look (sizes, colours, speeds) needs an in-game pass. `crater_smoke` emits until the script calls `stop_deffered`; if that call fails on this build, the 120 s time limit ends it.

**`[explosion_marks]` override**
- It applies to every explosive with `wallmark_section = explosion_marks`, which is all of them in G.A.M.M.A. (GBOOBS ammo, EFT grenades).
- It is static, so MCM can't switch it off.
- The keys are moderate: dist 0.8, size 0.75, max_count 7.

**Texture size.** 13 MB of uncompressed textures. If that is too much for the release, the chips and pocks (64 px) could be dropped to 32 px, or `deep/` could be left out when R3 isn't shipped.

**Overlap with props.** `zgo_props` dust takes precedence on objects it classifies (`handles_impact`). If props is switched off in MCM, this layer draws its generic object particles instead.
