# Integration note: wounds (progressive wounds, the wound shader `zgo\dmg`)

## 1. Summary

**What it does.** Bodies now take damage where they are hit. Every hit lands on the nearest baked wound site and adds tissue damage there, scaled by calibre class and hit kind. The total sets the stage:

| Stage | Name | What happens |
|---|---|---|
| 1 | bruise | nothing drawn |
| 2 | open wound | tracked; the usual entry and exit marks |
| 3 | crater | larger wound mark, meat chunks thrown |
| 4 | down to the bone | larger marks, more chunks |
| 5 | destroyed | larger marks, more chunks; on a dead body's head or limb, the part comes off |

**Calibre caps.** Each kind of hit can take a wound only so far by itself; mixing hits raises the cap to the largest seen.

| Hit | Deepest stage |
|---|---|
| pistol | 3 |
| intermediate and full-power rifle | 4 |
| magnum, slug, anti-materiel, explosion | 5 |
| melee | 2 |
| explosion fragment | 3 |
| armour that stopped the round | 1 (bruise) |

**What drives it.**
- Explosions add fragment wounds plus a tear on the side that faced the blast (from the `blast_body` event).
- Exit wounds tear 1.25× more, on the far side.
- With no wound sites (no 1.7 bake, an index from before 1.7, "Use baked models" off), nothing changes; a test proves the output is identical.

**Co-op.** The host decides. One compact `Y` line per wounded body carries bind-space points, not site indices; seeded `Y` lines carry chunk bursts. Each machine maps the points onto its own sites and draws for itself.

**Kid mode.** Wounds are tracked and the lines still go out; no marks, chunks or craters are drawn.

**Experimental (off by default, local): Wound craters.** With a bake made with `bake.py --experimental-damage`, a wounded section's damage mesh D_s replaces its intact sub-mesh C_s on that NPC:
- `set_shader(C, "zgo\\off")`, then `set_shader(D, "zgo\\dmg", "<base>,zgo_dmg_<12 hex>[_<bump>]")`.
- The new shader `zgo\dmg` (`gamedata/shaders/r3/zgo_dmg*`) pushes the wound's vertices inward in the bind pose before the stock code skins them. The crater therefore follows animation, ragdolls, the previous-frame position (SSS motion vectors) and the shadow map, because the shadow vertex shader dents the same way.
- Depth is clamped to 85 % of the baked local thickness, and the floor is ragged.
- The pixel shader runs the stock G-buffer shader first. Then, only inside a wound, it repaints by depth (bloody rim, fat band, muscle, a dark cavity in thick parts, bone at the bottom of bone-deep wounds), adds wet gloss and uses the dented surface's own normal. Outside a wound the pixel is exactly the stock one.
- Per NPC and sub-mesh, up to 4 wounds travel as four 1×1 "number" textures in the vertex-shader slots (`zgo\wounds\n\000`..`fff`). The engine has 4 VS texture slots.
- It only runs when all of these hold: the renderer is r3/r4, the bake has damage meshes, the shader and textures are present, set_shader / reset_shader / get_shaders / get_default_shaders exist, and `zgo_bake.loaded_matches(obj)`. A failure turns it off with one log line.
- It is not verified in the game (needs probes 1–3); see section 7.

**Verified offline:**
- `tests/zgo_test_wounds.lua` (with `tests/mocks/wounds.lua`) passes with ZGO_BAKED=0 and 1, seeds 1 5 7 42 99. It covers:
  - every number texture decoded the way the vertex shader decodes it;
  - the blender mock binding the strings the runtime makes;
  - stage rules and site matching;
  - the game's own path (shots, kill, corpse hits, a grenade);
  - severing;
  - kid mode;
  - save/load and id reuse;
  - the experimental craters, including the fail-safes;
  - the baker's own fixture bake;
  - a co-op host and a client as separate processes.
- `dev/test-all.sh`: **150 runs, 0 failures**.
- `dev/shadercheck` on all `zgo_dmg*` stage files: **204 compiles PASS** under the game's d3dcompiler_47 6.3.9600, MS 10.0.26100, Wine and vkd3d, for every define set and the skinned variants 0–4. Linkage is OK for the flat, bump and shadow passes. The bump pass was checked with a temporary variant of the `.s`, since the stock `.s` dump only takes the flat path.
- `luajit dev/gen_mcm_text.lua --check`: up to date.
- `python3 tools/zgo_wounds/gen_textures.py --check`: all 4098 textures current.

## 2. Files

Added (all mine):

| File | What |
|---|---|
| `gamedata/scripts/zgo_wounds.script` | the runtime: events, stages, marks, chunks, severing, co-op `Y`, save/load, the experimental crater switch |
| `gamedata/scripts/zgo_settings_wounds.script` | page `wounds` (after Dismemberment), 3 Performance sliders |
| `gamedata/shaders/r3/zgo_dmg.s` | the shader `zgo\dmg`: parses the second texture name; bump / flat pass, `l_point` shadow |
| `gamedata/shaders/r3/zgo_dmg.h` | shared HLSL: number decode with check byte, dent, tissue triplanar, layer painting |
| `gamedata/shaders/r3/zgo_dmg_bump.vs`, `zgo_dmg_flat.vs`, `zgo_dmg_shadow.vs` | the stock `deffer_model_bump/flat.vs` and `shadow_direct_model.vs` (whichever mod's copy wins), wrapped per skinning variant |
| `gamedata/shaders/r3/zgo_dmg_bump.ps`, `zgo_dmg_flat.ps` | the stock `deffer_base_bump/flat.ps` wrapped; wound painting after it |
| `gamedata/textures/zgo/wounds/n/000.dds` … `fff.dds` | 4096 number textures, 1×1 A8R8G8B8, one mip, 132 bytes each |
| `gamedata/textures/zgo/wounds/tissue.dds` | 256², mips: R muscle fibre, G fat lobules, B bone pores, A clot |
| `gamedata/textures/zgo/wounds/stump.dds` | 256², mips: a cut face (clot, muscle, fat ring, skin) over the caps' UV square 0.15–0.85 (request R4) |
| `tools/zgo_wounds/gen_textures.py` | deterministic numpy generator for all of the above (`--check`, `--out`); see R7 |
| `tests/zgo_test_wounds.lua`, `tests/mocks/wounds.lua` | the suite and its mocks; the mock is active only with `WOUNDS_MOCKS` set |
| `docs/integration/wounds.md` | this note |

Changed by a generator, as the task says: `gamedata/configs/text/eng/ui_st_zgo_mcm.xml` and `rus/ui_st_zgo_mcm.xml`, rewritten by `luajit dev/gen_mcm_text.lua`. Re-run it after merging every workstream's settings.

Nothing else was touched.

**Downloads and packages.**
- Six engine source files were read for slot counts, the texture-name parser and the skinning paths: `R_Backend.h`, `SkeletonX.cpp`, `FSkinned.cpp`, `FBasicVisual.cpp`, `dx10Texture.cpp` and `rm.cpp`.
  - Source: raw.githubusercontent.com, xray-monolith at commit b86d733f4a.
  - Saved to `~/.cache/zgo_wounds_src/` (outside the mod).
  - Nothing user-identifying was sent.
- No packages were installed: numpy was already present.
- No Wine prefix of my own was needed; shadercheck used its own compilers.
- `dev/setup.sh` was not run, and the game and MO2 were not launched.

## 3. Requests to the integrator

**R1. Kid mode hook (optional, recommended).**
- Where: `zgo_settings.update()`.
- Change: next to the other `kid_mode` calls, add `pcall(zgo_wounds.kid_mode, kid)`.
- Why it is optional: zgo_wounds also polls `zgo_util.gore()` every frame, so it already works. The hook makes the craters go in the same frame as everything else.

**R2. Sync documentation and PROTO.**
- In the header of `zgo_sync.script`, change "Y zgo_wounds (wound stages)" to:
  `Y|w|<id>|<game sec>|<sec,bx,by,bz,stage,level,bone;...>` (or `-`) and `Y|g|<id>|px|py|pz|dx|dy|dz|count|seed` (zgo_wounds).
- PROTO is unchanged, as instructed.
- Peers running 1.6 have no `Y` handler and drop the lines. The lines reference no asset a peer could lack: chunks are the same gib models as `G` lines, and craters are local and capability-checked.
- So `Y` alone does not force a PROTO bump. Bump it if another 1.7 workstream needs one.

**R3. cuts / zgo_dismember: a severing entry point for wounds.**
- Wanted: `zgo_dismember.sever_wound(obj, root, ev)`, which applies the Dismemberment rules and the cut style (bones, off shader, in-model caps), then cuts.
  - `ev = { id, bone = root, prof, dir, pos, dead = true, was_dead, center, allow_dismember = true }`.
- zgo_wounds already calls it when it exists.
- Until then, zgo_wounds runs its own guarded fallback. It checks `dismember/enable`, `corpses`, `mutants`, `head`/`limbs`, `bone_gone` and `can_show_cut`, then calls `zgo_dismember.sever(obj, root, ev, head, false)`.
- Keep `sever`, `bone_gone`, `can_show_cut` and `uses_shader` public and keep their signatures. zgo_wounds uses `uses_shader` + `bone_gone` to leave a cut section's C_s alone.

**R4. cuts / zgo_debris: the bake's own chunks.**
- Wanted: `zgo_debris.spawn_chunks(obj, section, site_index, pos, dir, count, seed)`, which throws the site's own baked chunk (`zgo_bake.chunks`, bone `site_i`) and falls back to `spawn_gibs`.
- zgo_wounds would switch to it when present.
- Today it uses `spawn_gibs(pos, dir, count, ignore, seed)`; please keep that signature stable.

**R5. baker.**
- (a) Optional: point the stump-cap flesh texture at `zgo\wounds\stump`. The cap's UV square is 0.15–0.85, centred.
- (b) In the D_s u code, add how far out in its patch each vertex lies: `code = site + 32·rq`, with rq 1 (centre) … 7 (rim) and 0 for "not given".
  - The shader already decodes `site = code & 31` and makes a bowl from rq, so the change is forward compatible and needs no shader change.
  - Please update `docs/formats/damage.md` to match.

**R6. README.** Apply the text in section 6. It replaces the LIMITS bullet "No wound craters or chunks taken out of bodies yet…".

**R7. Ownership of `tools/zgo_wounds/`.**
- The generator is a new folder under a name only this workstream uses. It is not in my listed paths.
- Please confirm, or move it, e.g. into `tools/zgo_baker/` or `dev/`.
- The textures are committed output; players never run it.

**R8. Setup GUI (the user's request).**
- Nothing in this workstream is per-modlist. The number, tissue and stump textures are static shipped assets.
- The only per-player data is the bake, which the setup GUI already drives. The wound sites come with every default bake.
- The craters additionally need the `--experimental-damage` bake. The setup GUI should offer it as an experimental tick box, off by default, with the warning "much larger models".

**R9. Probe (optional).**
- Probe 3 checks digit textures. A wound variant would close the in-game gap: a known number string on one body, then a read back that the crater appears.
- Owner: the probe workstream (`zgo_probe` 'dmg_shader' could take `zgo\dmg` with `zgo_dmg_021000000000`).

No harness or `test-all.sh` changes are needed. The suite is picked up automatically and runs its own co-op roles.

## 4. Settings added

Page `wounds` ("Wounds" / "Раны", after Dismemberment, `coop = "host"`):

| id | type | default | coop | what |
|---|---|---|---|---|
| `enable` | check | on | host | progressive wounds at all |
| `growth` | track 0.25–3 | 1 | host | how fast wounds deepen (damage multiplier) |
| `marks` | check | on | host | larger wound marks at stage 3+ |
| `chunks` | check | on | host | meat chunks from stage 3+ (also needs Dismemberment → Gibs) |
| `sever` | check | on | host | stage 5 on a dead body's head / limb takes it off (Dismemberment rules) |
| `dents` | check | **off** | **local** | Wound craters in the body **(experimental, your own)** |

Page `performance` (local):

| id | range | potato / low / medium / high / ultra | what |
|---|---|---|---|
| `wound_npcs` | 0–32 | 2 / 4 / 6 / **10** / 16 | bodies near you drawing craters |
| `wound_sites` | 1–24 | 4 / 6 / 8 / **12** / 16 | wounds kept per body (the lightest goes) |
| `wound_rate` | 1–10 /s | 1 / 2 / 3 / **4** / 6 | how often craters are re-chosen and host wounds applied |

Every option has an English and a Russian explanation. Defaults are the High preset.

## 5. Co-op

- **Authority.** Only the host (or single player) handles `hit` and `blast_body`, decides stages, throws chunks, places marks (`zgo_decals.place_body` sends its own `S` lines) and severs (`zgo_dismember` sends `D`).
- **`Y|w|<id>|<game section>|<entries>`.**
  - Sent when a body's stages or depths change, at most once per update tick.
  - Rebroadcast every 20 s, 8 bodies per round, for late joiners.
  - When a living body heals (15 min unhit), `-` is sent and the client forgets the body.
  - Each entry is `section,bx,by,bz,stage,level,bone`: a bind-space point in mm, the stage, the depth in 2 mm steps and the bone flag. There are at most 16 entries, deepest first, and stages below 2 are not sent.
  - The client maps each point to its own nearest site of that section and drops anything more than 8 cm off. A partner whose model comes from another bake therefore never gets wounds on the wrong spot.
  - A line for a body that is not online yet waits until it is.
- **`Y|g|<id>|pos|dir|count|seed`.** The client replays the chunk burst with the host's seed. Seeds stay below 1e9, so `zgo_sync` sends them as integers.
- **Craters are local.** Each machine draws them under its own `dents` option, renderer and budget.
- **Kid mode.** A kid-mode host still sends every line. A kid-mode client keeps the state and draws nothing gory; turning kid mode off brings the craters back.
- **Malformed lines** are dropped. A `w` line whose entries do not parse never clears a body's wounds.
- **Tests.** The host and client run as separate processes and exchange lines through a wire file. They check:
  - the same wounds on both machines;
  - craters drawn on the client;
  - chunks replayed with the host's count;
  - rubbish ignored;
  - kid mode on either side;
  - a late body;
  - forgetting;
  - another bake.

## 6. README text

Add under WHAT IT DOES, after "Bodies and bleeding":

```
  Progressive wounds (baked models, see BAKED MODELS)
    Damage builds up where a body is hit. Every hit lands on the nearest
    wound spot the baker marked on the model and adds to it by calibre:
    bruise, open wound, crater, down to the bone, destroyed. A pistol opens
    and craters wounds but never reaches the bone by itself, rifles do,
    slugs, magnums, anti-materiel rounds and explosions go all the way;
    fragments and the blast tear the side that faced the explosion. From a
    crater on, chunks of meat fly out of the wound and a larger torn mark
    goes on the body; a destroyed head or limb on a dead body comes off
    (Dismemberment settings apply; the living never lose parts).
    Experimental, off by default (MCM -> Wounds -> Wound craters): with
    models baked with --experimental-damage, wounds become real craters in
    the body that move with it and its shadow: a bloody rim, fat and muscle
    on the walls, bone at the bottom of the deepest. DirectX 10/11 only.
```

Under SETTINGS, add:

```
  Wounds          progressive wounds on/off, how fast they deepen, marks,
                  chunks, destroyed parts coming off; wound craters
                  (experimental, each player's own)
  Performance     + bodies with wound craters, wounds kept per body,
                  wound updates per second
```

In LIMITS, replace the bullet "No wound craters or chunks taken out of bodies yet: …" with:

```
  * Wound craters are experimental (off by default): they need models
    baked with --experimental-damage (much larger), the DirectX 10/11
    renderer, and up to four craters per body part are drawn. Without them
    wounds still deepen, throw chunks and tear limbs off bodies, shown with
    wound marks. Wounds need the wound sites of a 1.7 bake; without baked
    models bodies get the usual entry and exit marks only.
```

## 7. In-game checks

All with baked models from bake.py 1.7 (default bake), DX11, a quiet spot, and an NPC or a fresh body near you.

1. **Stages and chunks (default settings).**
   - Shoot one spot on a standing NPC's chest with a 5.45 rifle, 3–5 times.
   - Expected:
     - after the third round, a few meat chunks fly from the wound and a larger torn mark appears;
     - another burst comes at about the fifth round;
     - the log line `[ZGO] wounds:` only appears if Diagnostics status is called.
   - Not expected: errors in the log, or chunks from a pistol before the fourth round.
2. **A limb comes off.**
   - Kill an NPC. Fire a 12-gauge slug (zhekan) 3–4 times into one forearm or calf of the body.
   - Expected: the part comes off (cap, flying piece, as Dismemberment normally does it).
   - Repeat on a living NPC: nothing comes off.
3. **Kid mode.**
   - Tick kid mode and repeat 1.
   - Expected: no marks, chunks or cut parts. Untick it: nothing reappears from the shots made while it was on, except the wounds, which keep counting.
4. **Co-op (xrRazom).**
   - The host shoots one NPC's chest 4 times with a 7.62x54R.
   - Expected: the client sees the chunk bursts at the same moments and the same torn marks. The client's own shots do nothing until the host processes them.
5. **Save and load.**
   - Wound a body to stage 4 (step 1), save, load, and shoot the same spot once.
   - Expected: chunks fly at once; the wound continued, it did not restart.
6. **Wound craters (experimental).**
   - Bake with `--experimental-damage` and install. In MCM → Diagnostics, run probes 1, 2 and 3; all must PASS. Save.
   - Tick Wounds → Wound craters. Shoot one spot on a body 4–5 times with a rifle.
   - Expected:
     - a crater opens there, with a dark red rim, yellowish fat and dark red muscle on the walls, and bone-coloured at the bottom after the 5th round;
     - the rest of the body looks exactly as before, including the bump detail;
     - its shadow has the dent;
     - it moves correctly while the body is a ragdoll.
   - Walk away (more than about 80 m) and back: the crater is still there. Kid mode on: craters vanish at once. Off: they return.
   - Bad signs, which you should report with the log:
     - the game closes;
     - pink or untextured bodies;
     - a whole body part vanishes or flickers;
     - a seam between the crater part and the rest;
     - shadows without the dent;
     - the log line `wound craters (experimental): off: …` names why it turned itself off.
7. **No damage bake with the option on.**
   - Expected: one log line, `wound craters (experimental): off: the baked models have no damage meshes`, and nothing else changes.

## 8. Risks and open questions

1. **The crater shader is unverified in the game.** Shadercheck proves it compiles and links under the game's compiler, but not:
   - that the engine binds 1×1 textures to VS slots as expected (probe 3 checks this for digits);
   - that `zgo\off` + `zgo\dmg` swaps look seamless (probe 2);
   - how it renders on every renderer path: SSS, Atmospherics, MSAA.

   That is why it is experimental, off, and fail-safe.
2. **Seams between D_s and C_s.** D_s is the whole section (subdivided near sites), so swapping C for D shows D everywhere in that section. Outside the patches D must look exactly like C; the baker keeps open borders unsplit, so it should. An in-game look is needed (check 6).
3. **Normals inside a crater.**
   - The bind normal does not change with the dent. The pixel shader therefore uses the derivative normal of the dented surface, which is faceted on 1.5 cm triangles; it is acceptable at wound scale.
   - Lighting outside wounds uses the stock normal (unchanged).
   - A smoother crater needs the radial code (R5b) or per-vertex normals from the baker.
4. **4096 loose number files** (16 MB on disk at 4 KB per block, about 300 KB zipped).
   - MO2 handles them; the engine loads only the ones used, each once.
   - If file count matters for packaging, halve the depth precision (4 mm steps, 1024 files) or move to native shader constants (the zgo_native route) later.
5. **Four craters per section per body.** The deepest four are drawn. A torso shot many times shows the four deepest as craters and the rest as marks only.
6. **Shader object churn.** Every distinct wound string creates its own engine Shader for that NPC's D_s. Changes are rate-limited (at most once per tick per body), and old ones are released when replaced. Memory is small; it is not measured in game.
7. **Site matching without an exact impact point.**
   - When the engine has no impact point (rare: a co-op peer's round arriving late), the hit position is the bone origin. zgo_wounds then picks the site on the side the round came from.
   - If nothing lies within 1.3 × reach + 3 cm, no wound is made. That is deliberate: no wound on the wrong spot.
8. **Corpse hits by NPCs** do not reach zgo_wounds: zgo_main only reports a player's corpse hits. Living NPC-vs-NPC hits do count. Severing needs `allow_dismember` (player hits and explosions), matching Dismemberment.
9. **Balancing.** The thresholds are reasoned estimates, not measured in play: stages at 0.4 / 1.8 / 3.6 / 6.5, class weights 0.8–1.5, exit 1.25×. "How fast wounds deepen" scales everything.
10. **Interplay with cuts' in-model caps and off-shader cuts.**
    - A cut section's D_s is switched off. Its C_s is left to zgo_dismember when it draws the cut through the off shader (`uses_shader`); otherwise C is reset, and the hidden bones keep it hidden.
    - Covered by tests with the cuts mock, but needs a look in game with `dismember/offshader_cuts` on.
11. **Open question: craters on the living.** With dents on, living NPCs also show craters (the dent follows animation). Should it be dead-only? A one-line change if wanted.
