# Level-geometry damage / destruction in Anomaly / GAMMA (discovery report)

(Written by the parent session from the level-research agent's hand-back; the
agent could not write files. Sources, tools and dumps are next to this file.)

Tags: [V] verified in source / data, [V-exe] Lua binding name found in the installed exe, [I] inference, [W] web.

## Exe caveat [V-exe]

The installed exe (anomaly/bin/AnomalyDX11AVX.exe) identifies itself as "Modded Exes MT-TEST". It does not have several b86d733f4a script APIs:

- **Absent:** set_collidable, set_obstacle, set_use_ph_shapes, ph_freeze, set_ph_contact_callback, get_visbox, bone_shape, model_instance, set_custom_fov.
- **Present:** add_attachment, bone_callback, set_parent_level, get_shaders / set_shader / reset_shader, shader_bus, try_register, wallmarks_manager, place_skeleton, material_name, get_normal, CBulletOnImpact / CBulletOnInit, material_pairs.ltx, set_visual_name.

Treat level attachments as visual only on this exe.

## 1. Level geometry

### Files (level_l01_escape.db0)

| File | Contents |
|---|---|
| level | chunks fsL_HEADER=1, SHADERS=2, VISUALS=3, PORTALS=4, LIGHT_DYNAMIC=6, GLOWS=7, SECTORS=8 (xrLevel.h:37-60) |
| level.geom / level.geomx | VB, IB and SWI (fsL_VB=9, IB=10, SWIS=11) |
| level.cform | hdrCFORM, then verts and CDB::TRI (xrLevel.h:94-100) |
| level.hom | occluders |
| level.details + build_details.dds | grass |
| level.ai | navigation / cover |
| level.game, level.spawn | game and spawn data |
| level.ps_static, level.snd_static, level.som, level.env_mod, level.fog_vol | static particles, sounds, sound occlusion, environment modifiers, fog volumes |
| lmap#N_1/2.dds, level_lods(_nm).dds, terrain\terrain_<lvl>(_lm).dds | lightmaps, LOD atlas, terrain |
| meshes\brkbl#N.ogf | xrLC breakables, mostly glass: 0 per level up to 190 (Warlab); Escape 51 |

Escape in numbers:
- 457 shaders.
- 22,453 static visuals: 4,248 MT_NORMAL, 2,901 hierarchy, 417 progressive, 3,167 LOD, 7,729 MT_TREE_ST and 3,991 MT_TREE_PM. TREE_* is the instanced "MU" model type, not only trees.
- 32 sectors and 128 portals.
- level.cform: 1.57 M verts and 2.95 M tris (66 MB).
- Terrain: about 125k verts at roughly 3.9 m spacing [I].

### Static render geometry (R4)

- **Load order:** IGame_Level::Load → ObjectSpace.Load (IGame_Level.cpp:111) → Render->level_Load (:124).
- **r4_loader.cpp:**
  - shaders: :37-53;
  - wallmarks and details: :57-58;
  - LoadBuffers: :66-79. The CPU copy is freed after upload (:239-242, :269-272), and the buffers are D3D_USAGE_DEFAULT (dx10BufferUtils.cpp:11);
  - LoadVisuals: :280-297;
  - LoadSectors (portal CDB): :313-369;
  - HOM.Load: :103.
- **Sector root:** CSector::load gives one root visual per sector (r__sector.cpp:265-288).
- **Per frame:** the portal traversal runs, then add_Geometry(sector root) (r4_R_render.cpp:72-92). CRender::add_Static (r__dsgraph_build.cpp:1127-1272) handles each visual:
  - IsValuableToRender check (:650);
  - frustum test on vis.sphere/box (:1140);
  - HOM test (:1144);
  - recursion into hierarchy children (:1189-1207);
  - leaf insert (:331).
  The sun shadow pass takes the same path.
- **Visual flags:** only eIgnoreOptimization and eNoShadow exist (RenderVisual.h:10-13). There is no hidden flag.
- **Injection precedent:** Load3DFluid pushes a child into a sector root hierarchy (r4_loader.cpp:436-445).
- **HOM:** its own CDB, with occTri.skip counters (HOM.cpp:70-127, 121, 164). A see-through hole needs its occluder disabled [I].
- **Grass:** DetailSlot (DetailFormat.h:67-85); dtSlots is a "pointer into VFS" (DetailManager.h:177). Grass benders are native only; explosions already use them (IGame_Persistent.h:69-87, Explosive.cpp:372).

### Static collision (CDB)

- **Material remap:** the build callback CLevel::Load_GameSpecific_CFORM (IGame_Level.cpp:81-84, Level_load.cpp:224-266) remaps materials and sets suppress_shadows / suppress_wm.
- **Triangle layout:** CDB::TRI holds verts[3], material:14, suppress_shadows:1, suppress_wm:1, sector:16 (xrCDB.h:37-55).
- **Build:** build_internal makes a non-quantised OPCODE no-leaf tree (xrCDB.cpp:119-176). build asserts S_INIT (:93): there is no rebuild in place and no Refit.
- **Queries read tris and verts live** (xrCDB_ray.cpp:320-340, 413-428). det < EPS rejects a triangle (:289-292), so a degenerate triangle is invisible to rays.
- **Accessors:** GetStaticTris / GetStaticVerts / GetStaticModel return mutable pointers (xr_area.h:89-91). Native use only.
- **Users of the static CDB:**
  - bullets: firetrace_callback, which sends EVENT_HIT with tri.material (Level_Bullet_Manager.cpp:839-845);
  - ODE physics: dTriList box_query, skipping flPassable triangles (dSortTriPrimitive.h:93-113, 235-237; PHWorld.cpp:95-99);
  - AI vision (Feel_Vision.cpp:43-44, 219-244);
  - sound occlusion (IGame_Level.cpp:113);
  - static wallmarks (WallmarksEngine.cpp:215-235);
  - script ray_pick (xr_area_raypick.cpp:67-107).
- **Dynamic ray targets must be CObjects** (xr_area_raypick.cpp:171-172, 254-255). Script attachments are not, so bullets never hit them.
- **level.ai is baked.** Physics objects become AI obstacles by default (PhysicObject.cpp:577-579). Cover stays baked.

### What is mutable at runtime

| Thing | Lua | Native |
|---|---|---|
| Static visuals | no | Drop hierarchy children, zero vis bounds, or write degenerate IB triangles with UpdateSubresource (needs a CPU copy of level.geom). |
| CDB triangles | read-only (ray_pick element, material, normal) | Shrink only: degenerate triangles or swap the material. Adding triangles needs a full rebuild of about 3 M triangles. |
| HOM | no | occTri.skip = 0xFFFFFFFF |
| Grass | no | Edit the dtSlots palette and invalidate the cache [I] |
| Terrain height | no | VB edit plus CDB edit plus a refit (not implemented). Hard. |
| AI graph | no | Not practical. Use dynamic obstacles. |
| Lightmaps | no | No. |

## 2. Hit effects on surfaces

### Material libraries

- Binary gamemtl.xr (GameMtlLib.cpp:70-108).
- materials\materials.ltx: add or override materials (:117-200).
- materials\material_pairs.ltx: [mtlA@mtlB] sections with collide_particles, collide_marks, collide_sounds, step_sounds and breaking_sounds (:236-320).
- The base files are in anomaly/gamedata/materials/. DLTX works.

### Bullet impact (FireShotmark, Level_bullet_manager_firetrace.cpp:171-255)

1. Pair lookup (:174).
2. Static target: add_StaticWallmark (:202-209); a suppress_wm triangle returns early (r4.cpp:851).
3. Object target: add_SkeletonWallmark (:185-197).
4. Random sound (:212-222) and random particle (:224-248).
5. Explosive bullets play the explode particle (:250-253).

### Explosions

- explode_particles (Explosive.cpp:130, 394) and grass benders (:372).
- CWalmarkManager::PlaceWallmarks box-queries the CDB and places up to max_count marks from [explosion_marks] (wallmark_manager.cpp:86-188).
- Base values (system.ltx:248-252): wm\wm_grenade, dist 0.5, size 0.6, max_count 5. DLTX-overridable.

### Script hooks

- _G.CBulletOnImpact runs before the engine effects (Level_Bullet_Manager.cpp:1251-1277). Its table: pos, dir, speed, distance, section, bullet id, weapon id, parent id, target id (65535 = static), material name, lifetime, element (triangle).
- callbacks_gameobject.script:104-133 turns it into bullet_on_impact. bullet_on_init, _update, _remove and _hit also exist.
- ray_pick get_result(): element, material_name, flags, shoot factor, vis transparency factor. get_normal() returns the triangle normal (raypick.h:62-104).

### Current data

- The winning gamemtl.xr comes from G.A.M.M.A. Footsteps (modlist line 311); EFT footsteps is line 767.
- Teamson & Oleh's Bullet and Grenade Impact Sounds overrides every X@objects\bullet pair (sounds, plus restated particles and marks).
- Dumps: notes_materials.txt, notes_bullet_pairs.txt.

### Overridable

**Without scripts:**
- pair particles, marks and sounds;
- material flags and factors (shoot-through, suppress_wm);
- new materials;
- [explosion_marks];
- per-explosive particles and wm_size;
- loose .pe/.pg particles over particles.xr;
- wallmark textures.

**From scripts:** extra effects, but scripts cannot suppress the engine's pair effects (only by emptying the pair in LTX).

**Load order:** ZGO's DLTX should restate only collide_particles and collide_marks, and load after Oleh's file (e.g. material_pairs_zz_zgo.ltx; that the include order is alphabetical is [I]).

### Static wallmarks: limits [V]

| Aspect | Fact | Source |
|---|---|---|
| Count | No cap. Visible marks are re-streamed per frame in 16k-tri batches. | WallmarksEngine.cpp:39, 94-130, 411-436 |
| Lifetime | Default TTL ps_r__WallmarkTTL*15. Script TTL wins; -1 = permanent. Alpha = age/TTL. | :105, 119-122, 252, 439-455 |
| Removal | Expiry, clear on unload, or same-shader replacement within 2 cm. No per-mark delete. | :274-291 |
| Persistence | None (lost on load and level change). | |
| Geometry | Projected on the collision triangles (box query of sz*2.5), not the render mesh. | :209-270 |
| Range | Engine marks beyond 100 m are dropped; the script path ignores the range. | |
| Rotation | Engine ±20° random; the script overload takes an explicit rotation. | script_wallmarks_manager.cpp:63-95 |
| Texture | Random from the section list (differs per co-op peer). | dxWallMarkArray.cpp:51-62 |
| Shader | Hardcoded effects\wallmark (or effects\wallmark_blood for wm_blood_* with SSS). | dxWallMarkArray.cpp:17-39 |
| Render target | rt_Color albedo only, RGB; no normals or gloss. | r4_rendertarget_phase_combine.cpp:856-869 |
| Vertex format | FVF::LIT (position, colour, uv), no tangent. | |

**Custom wallmark shader:**
- Base effects_wallmark.s is in shaders.db0 only, and no enabled mod overrides it.
- Shader scripts get string, math and table (ResourceManager_Scripting.cpp:344-350) plus t_base.
- So ZGO's own effects_wallmark.s can branch on a zgo\ texture prefix to a ZGO pixel shader: alpha blend plus parallax/POM inside the decal, with the tangent frame from ddx/ddy [I] (Mick West's parallax bullet holes [W]).
- The lighting normal stays flat; writing normals needs native code.

## 3. Fake destruction now

Ratings are payoff / cost / co-op / effort.

- **A. Material-pair upgrade:** DLTX particles and marks, new zgo\ effects, a bigger [explosion_marks]. Medium / low / local cosmetic only (engine effects run only where the bullet is simulated, randomly per machine) / low.
- **B. Scripted impact layer (core):** driven by bullet_on_impact (material, triangle, normal, ammo, speed).
  - Caliber-scaled decals (the Max Payne 3 rule), dust, chips through the deterministic sim, sparks.
  - A cumulative damage grid (quantised position, normal and material) escalates chip → crack → gouge → "breach" decal.
  - High / low-medium / safe with host events carrying seeds / medium.
- **C. ZGO wallmark shader** (parallax gouges, scorch, cracks, age fade): medium-high / low / safe / medium.
- **D. Explosion craters:** scorch wallmark, a rim or rubble attachment mesh on the ground normal, clods, a dust ring, lingering smoke. High / medium / safe / medium (art).
- **E. Rubble:**
  - Visual-only attachments in the existing deterministic sim: safe.
  - Persistent and collidable: alife():create("physic_object") + set_visual_name. xrRazom's sync of those is unknown [I], so don't use them for cosmetics.
- **F. Damage overlay meshes:** chipped-rim patches with a recessed dark interior, S/M/L per material class, flush on the ray_pick normal, retextured by class with set_shader [I] (check that attachments support it). The F.E.A.R. / Bad Company 2 micro-destruction look. High / low / safe / high (art).
- **G. Dust and particles:** material dust, lingering indoor dust, ceiling grit after blasts, sparks, splinters, shards. High / medium (overdraw) / safe / low-medium.
- **H. Glass and props:** breakable_object (BreakableObject.cpp:209-230) and physic_destroyable_object (PHDestroyable.cpp:137-190) exist. Add shards and decals, and let explosions break glass. Shard impulses use ::Random, so they differ per machine (cosmetic only).
- **I. Terrain dent through the shader bus:** shader_bus lanes carry crater xyz and radius into the terrain POM height and colour.
  - The winning terrain shader is Glossy Puddles' deffer_terrain_high_flat_d.ps (SSS-based POM), so this patches another mod's shader.
  - Collision is unchanged (fine for shallow craters).
  - High / low / safe / high.
- **J. Frostbite-style see-through masks:** clip() static G-buffer pixels in slab volumes fed by bus lanes.
  - High conflict: SSS, Atmospherics and Enhanced Shaders all own deffer_base / gbuffer_stage.h.
  - Collision unchanged (invisible wall), HOM still culls, no shadows through.
  - Only worth it with the native CDB edit.

**Not useful:**
- Vertex-shader terrain displacement: verts are about 4 m apart. Tessellation exists (r4.cpp:444-445) but the terrain blender doesn't use it.
- Grass can't be removed from Lua; benders flatten it during blasts.
- AI is unchanged by all of the above, except physics rubble.

## 4. Existing mods

No destruction, crater or debris mod exists.

- **Teamson & Oleh's Bullet and Grenade Impact Sounds** (+422): restates particles and marks on all bullet pairs and adds an objects\grenade material. Load-order conflict.
- **Oleh's Bolt Impact Sounds** (+421) and **Misc Sound Improvements** (+150): no conflict.
- **G.A.M.M.A. Footsteps** (+311, the winning gamemtl.xr) and **EFT footsteps** (+767): don't ship a gamemtl.xr.
- **Particles Cinematic VFX 3.5** (+214): replaces particles.xr wholesale, so use new zgo\ names.
- **SSS 23** (+164): overrides the wallmark vertex shader, the blood wallmark, terrain POM, gbuffer_stage.h and deffer_base*, but not effects_wallmark.s.
- **Glossy Puddles** (+5), **Atmospherics 2.69** (+13), **Enhanced Shaders** (+166), **3DSS** (+170): terrain and deffer owners (conflict for I and J).
- **GAMMA CQC** (+341): momo_multihit_fix uses bullet_on_impact; harmless.
- **Reusable assets:** dynamics\fence\debris_01, scene_objects\hospital\hospital_debris_01 (6 parts), brkbl# glass, destroyable crates and barrels.

## 5. Native unlocks

1. **CDB holes.** At a frame sync point, use GetStaticModel + COLLIDER::box_query (xrCDB.h:159), then either:
   - degenerate the triangles (rays miss them; check ODE for NaN normals [I]); or
   - swap them to a ZGO material with flPassable, shoot 0, vis 1 and suppress_wm (physics skips passable triangles, dSortTriPrimitive.h:235-237).
   Removal only; mind multithreaded readers.
2. **Render holes.**
   - Keep a CPU copy of level.geom.
   - Map the breach to visuals through CSector::root hierarchies and vis.box.
   - Write degenerate IB triangles with UpdateSubresource. Coarse alternative: drop a hierarchy child or zero its vis bounds.
   - Add edge meshes the way Load3DFluid does, or use attachments.
3. **HOM:** occTri.skip.
4. **Decals:** bind the normal/gloss MRT in phase_wallmarks, make the texture choice deterministic, allow a per-section shader, per-mark removal.
5. **Terrain:** VB + CDB + refit (hard). **Grass:** zero the dtSlots palettes and invalidate the cache.
6. **Wall texture lookup:** only native code can find which render texture covers a point (visual boxes and shader). That would let overlay meshes match the wall.

All native edits reset on level load. Keep a per-level command log in the save, replay it on load, and send it to late joiners (Teardown's model [W]).

## 6. Other games [W]

- **Frostbite:**
  - health states (https://docs.veniceunleashed.net/vext/ref/fb/healthstatedata);
  - Kihl, SIGGRAPH 2010, distance-field volume masks: https://www.advances.realtimerendering.com/s2010/Kihl-Destruction%20in%20Frostbite(SIGGRAPH%202010%20Advanced%20RealTime%20Rendering%20Course).pdf
  - BF3 terrain destruction depth map: https://media.contentapi.ea.com/content/dam/eacom/frostbite/files/gdc12-terrain-in-battlefield3.pdf
  - Bad Company 2 micro-destruction: https://www.shacknews.com/article/57920/battlefield-bad-company-2-first
- **F.E.A.R.:** https://www.bit-tech.net/reviews/gaming/ten-years-on-fear/2/
- **Max Payne 3:** https://www.gamesradar.com/rockstar-interview-shines-new-light-guns-max-payne-3/2/
- **Ready or Not:** https://readyornot.wiki.gg/wiki/Bullet_penetration
- **Insurgency Sandstorm:** https://www.unrealengine.com/spotlights/how-insurgency-sandstorm-raises-the-bar-for-realistic-first-person-shooters
- **Rainbow Six Siege:** https://www.pcgamer.com/rainbow-six-siege-interview-how-destruction-works-moddability-hostage-design/2/
- **The Finals:** https://www.sidefx.com/community/making-the-procedural-buildings-of-the-finals-using-houdini/
- **Teardown multiplayer:** deterministic commands on a reliable ordered channel, with a log replayed to late joiners: https://blog.voxagon.se/2026/03/13/teardown-multiplayer.html
- **Parallax bullet holes:** https://cowboyprogramming.com/2007/01/05/parallax-mapped-bullet-holes/

## 7. Recommended order

1. **B + A + G:** a zgo_impacts module, a material table, a damage grid with decal escalation, DLTX [explosion_marks] and material_pairs_zz_zgo.ltx. Host-authoritative; one texture per wallmark section; a TTL budget (avoid -1).
2. **C:** the wallmark shader.
3. **D + E (visual) + H.**
4. **F:** the overlay-mesh kit.
5. **I:** the terrain dent, coordinated with the terrain-shader owners or shipped as an optional patch.
6. **Native breaches in thin materials:** CDB plus IB degeneration, HOM skip, overlay edges (F), and J only for finer-than-triangle holes. Everything driven by a replayable log.
