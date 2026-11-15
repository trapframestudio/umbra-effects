# ZGO plan after discovery (2026-11-13, updated at 1.6.0)

Built on the four discovery reports in `docs/discovery/`:
- `npc.md`: deforming and destroying NPC models;
- `objects.md`: breaking props;
- `level.md`: damage to level geometry;
- `native.md`: native add-on code.

Tags used below:
- [V]: verified in the code or the exe.
- [T]: needs an in-game test.
- S / M / L: days / 1–2 weeks / weeks.

## Ground rules

- **Compatibility is the hard line:** everything must work in single-player G.A.M.M.A. and in xrRazom co-op + G.A.M.M.A. The exe is never swapped. We extend rather than edit: script callbacks, data files, our own shaders and shader extensions, a native DLL that ZGO loads itself, and xrRazom's public APIs (sync events, `xrr_mcm_authority`). Extending xrRazom itself is allowed when needed, through additions rather than edits.
- **Settings:** anything a player might want to tweak gets an MCM option with an explanation (English and Russian), grouped on the page for its concern. Every option lives in `zgo_settings.script`; `dev/gen_mcm_text.lua` writes the string tables, and the tests fail on a missing text. No console commands inside the game. Command-line tools outside it (dev tooling, the baker) are fine.
- **Performance:** build the full feature, then scale it with a Performance-page slider that has a value for each preset (potato, low, medium, high, ultra).
- **Kid mode:** every gory feature checks `zgo_util.gore()` before drawing and still sends its co-op line. Environmental effects stay.
- **Host authority:** the host decides. Clients replay compact sync lines with seeds. Bump `PROTO` whenever a line changes.
- **Graceful fallback:** every feature switches off on its own when something is missing (baked models, shader support, native DLL, a co-op peer without it). The fallback is today's behaviour.
- **Testing:** every change gets harness tests (both bake modes, several seeds) before it ships. Anything the harness can't model goes on the in-game checklist.

## Status

| Area | State |
|---|---|
| Blood, wounds as decals, spurts, trails, pools, drips | done |
| Dismemberment at death; corpse cuts with baked models | done (1.4) |
| Explosions: fragments and blast resolved per body; overpressure patch over G.A.M.M.A.; gibs only from RPG and IED | done (1.5.0) |
| Single mod folder; baker writes into it; MCM switch | done (1.5.0) |
| Settings registry, explanations (eng, rus), quality presets, kid mode, co-op authority via xrRazom | done (1.6.0) |
| Dev container (`dev/`: mingw-w64, Python + numpy, LuaJIT, Wine) | done (1.6.0) |
| Kid mode for the game's own blood puffs on bullet hits | Phase 0 (needs a particle shader) |
| Chunks out of bodies, progressive wounds | **not built**: Phase C |
| Stump-cap geometry fitted to the cut | not built (meat-mesh attachments today): Phase B |
| World impacts and destruction | not built: Phases D and E |
| Native DLL | not built: Phase F |

## Phase 0: in-game smoke tests (S, one play session)

These are cheap and decide which route each later phase takes. Ship them as a debug-only `zgo_probe.script`: one console call runs each probe and logs PASS or FAIL.

1. **Off shader** (gates B and C). Write `shaders/r3/zgo_off.s` with only `l_special`. Call `set_shader(child, "zgo\\off")` on one baked sub-mesh of:
   - a live NPC;
   - a ragdoll.

   Then call `reset_shader`. Expect the part to vanish with no pinch, then come back.
2. **Pass-through damage shader** (gates C). Write a `zgo_dmg.s` that only wraps the stock skinned shader. Check:
   - all weight formats (1W–4W);
   - the G-buffer, shadows and TAA;
   - running under SSS and Atmospherics.
3. **Digit textures** (gates C). Read back per-NPC numbers from the second texture string (4 vertex slots, 6 pixel slots).
4. **FFI** (gates F). Log:
   - `pcall(require, "ffi")` and `jit.version`;
   - `GetModuleHandleA(nil) == 0x140000000`.

   Then `ffi.load` a hello-world DLL from `bin/` under MO2 usvfs and Proton.
5. **Save and reload with cut corpses nearby.** This is still open from 1.4.
6. **Co-op, two machines.**
   - Cut parts match on both machines.
   - set_shader state from 1 and 2 matches on both machines.
7. **Props:** does `set_visual_name` on a one-bone prop swap its model? (objects.md §6.7)
8. **Kid mode, in game.** Check the shader bus lane `zgo_view` registers (the log says so) and that blood decals vanish and come back.
9. **Baked-model sanity at runtime.** Check that the child count (`get_shaders`) matches the bake index. If another mod overrides a model at a higher priority, ZGO should treat that model as unbaked.

## Phase 0.5: finish what 1.6.0 started (S–M)

1. **Shader check tool (`dev/`).** Assemble the shader tree the game sees (base `shaders.db0`, then mods in MO2 priority, as the baker does for models) and compile ZGO's shaders offline (vkd3d-compiler or fxc under Wine). Every shader change after this gets compiled before it ships.
2. **Kid mode for particles.** Write `zgo\particle_blend`, `_add` and `_aadd` (Lua `.s` files and a wrapper pixel shader around the stock `particle.ps` that reads `bus_zgo_view`). Then point ZGO's gory `.pe` effects at them, including the `hit_fx\hit_flesh_*` the game plays on flesh hits.
3. **Stale-bake notice in game.** When models in the mod list have changed since the last bake, show a notice saying which mod changed and that `bake.py` should be re-run. The baker itself stays a command-line tool.

## Phase B: cleaner cuts (baker phase 2a, M). Needs probe 1.

1. **Off shader instead of hidden bones.** With baked models, sever by switching the section's sub-meshes to `zgo\off`, not by hiding bones. This brings three wins:
   - no joint pinch, so cuts work before the ragdoll exists;
   - no "wait for the ragdoll" queue;
   - and possibly no save-time unhide trick.

   Shader state isn't saved, so it is re-applied on load and when an NPC comes online. The bone-hiding path stays as the fallback.
2. **Baked stump caps (K_s).**
   - The baker triangulates each cut's seam ring, then adds a bulge, a ragged rim and a bone stub.
   - The rim copies the seam's weights, so the cap follows the body exactly. It ships as `zgo\off` and is switched on at the cut.
   - This replaces the meat-mesh attachment caps.
3. **Limb pieces as baked skeleton OGFs.** They are deduplicated and replace "the victim's model with everything else collapsed". The result is cheaper and lighter, and set_shader works on them.

## Phase C: chunks and progressive wounds (baker phase 2b plus shaders, L). Needs probes 1–3.

This is the "chunking / wounds" you asked about; npc.md §4 has the full design.

1. **Baker:**
   - **Wound sites:** Poisson disk, 8–10 cm apart. Counts: torso 12–20, head 4–6, limbs 1–4.
   - **Damage meshes (D_s):** site patches subdivided to edges of 1.5 cm or less.
   - **Bone and organ proxies:** ribs, spine, long bones, skull shell, jaw.
   - **Gib chunks** carved from the crater volume.
   - **Index:** site tables and bind matrices.
2. **Shaders:**
   - **Vertex shader (`zgo_dmg`):** pushes bind-space positions inward per active site, clamped to the baked thickness. It follows animation and ragdolls, and the shadow pass does the same.
   - **Pixel shader:** draws layers by depth: skin, bloody rim, fat, muscle, bone, cavity, wet gloss.
3. **Runtime:**
   - The host maps each hit to the nearest site and adds up energy per calibre class.
   - The total energy sets the stage:
     1. bruise;
     2. open wound;
     3. crater;
     4. down to bone;
     5. sever or gib.
   - At stage 3 and above, gibs come off the crater.
   - The sync line is `zgo_d|id|section|digits`.
   - On damage, a section swaps C_s to D_s; undamaged NPCs cost nothing extra.
4. **Limits:**
   - Dents can't make overhangs.
   - Bullets and decals still hit the undented collision.
   - Real holes (L4D2-style) need the per-NPC texture route (C6, untested) or native code.

## Phase D: impact layer for the world (M, script and data only; can run alongside B and C)

1. **`zgo_impacts`:**
   - Driven by `bullet_on_impact`, which gives material, normal, ammo and speed.
   - Decals scale with calibre.
   - A damage grid per surface escalates from chip to crack to gouge to "breach" decal.
   - Dust, chips and sparks run through the existing deterministic debris sim.
2. **Data:**
   - DLTX `material_pairs_zz_zgo.ltx`;
   - bigger `[explosion_marks]`;
   - wallmarks with a lifetime budget.
3. **Explosion craters:**
   - a scorch mark;
   - a rim or rubble mesh on the ground normal;
   - clods, a dust ring and lingering smoke;
   - ceiling grit indoors.
4. **Props:**
   - hit feedback per material, plus host-side extra impulse;
   - leaks from barrels and canisters;
   - dust, splinter and glass bursts when a native destroyable breaks;
   - lamps throw shards and flicker.
5. **ZGO wallmark shader:** parallax gouges, scorch, cracks, age fade.

## Phase E: destruction (M–L)

1. **More destroyables from data alone.** zgo_*.ltx files give crates, chairs and lab boxes `[destroyed]` parts made from models that already ship. That covers about 660 placements.
2. **Host-driven scripted break for any prop.**
   - Health is tracked by material and mass.
   - When it runs out, the host releases the prop and sends a "B" line with a seed. Each machine then spawns a debris rig.
   - This covers barrels, chairs, TVs and bottles.
3. **Fracture baker in zgo_baker:**
   - Voronoi shells for barrels, cans, bottles and glass; plank splits for wood.
   - First targets: barrels (274 placements) and crates (137).
4. **Glass broken by explosions.**
5. **Optional terrain dents** through shader_bus lanes into the terrain parallax. This patches another mod's shader (Glossy Puddles), so it needs your call.

## Phase F: native track (approved; gated on probe 4)

1. **Toolchain:** the `zgo-dev` container (`dev/setup.sh`) has mingw-w64 GCC 16 and Wine.
2. **`zgo_native.dll` plus a Lua bootstrap:**
   - It finds offsets at runtime (RTTI, fixed base), verifies their bytes, and fails closed.
   - It publishes a capability bitmask. Co-op peers exchange capabilities, and a feature runs only when every machine has it.
3. **Hooks, in order:**
   1. post-process CalculateBones: crush, bend and real bone moves on ragdolls;
   2. per-NPC shader constants, which replace digit textures and allow arbitrary wound positions;
   3. a prop `OnHit` callback plus a seeded RNG for native breaks, so breaks match in co-op;
   4. later, holes in thin level geometry (CDB and index buffers) driven by a replayable per-level log.
4. **Cost:** every xrRazom release can move offsets, so expect hours to days of checking per release. It would help to ask the xrRazom author for PDBs.

## Phase G: "Alive Zone"

This needs a separate discovery pass once B–D have shipped.

## Decisions (2026-11-13)

1. **Native code:** approved, along with extending the engine where needed. Compatibility with G.A.M.M.A. and xrRazom co-op is the hard line.
2. **Disk space:** doesn't matter. Phase C bakes everything it needs.
3. **Shaders:** we may write new shaders and extend existing ones anywhere, as long as compatibility holds.
4. **GitHub:** URL to come.

## Suggested order

1. Phase 0 probes and Phase 0.5.
2. Phase B.
3. Phase C, with Phase D in parallel (independent, script only).
4. Phase E.
5. Phase F alongside, starting with the loader and the CalculateBones hook once probe 4 passes.
