# Breaking world objects with combat damage (discovery report)

(Saved by the parent session from the objects agent's hand-back; condensed only where noted. Supporting data is in this folder: engine/, vanilla/, tools/, *.json, xrrazom/, web/.)

Tags: [V] verified in source / config / assets / log; [I] inference or needs an in-game test.
Engine citations refer to b86d733f4a. Copies are in engine/; each file name is its repo path with "/" replaced by "_".

## 0. TL;DR

1. **Three break systems; Anomaly really uses one.**
   - **A, in use:** CDestroyablePhysicsObject + CPHDestroyable replace a prop with pre-made part models.
   - **B:** breakable joints or fractures inside one multi-bone model (CPHSkeleton::PHSplit). Used only by a few skeleton models and car doors.
   - **C:** CBreakableObject (glass). It has no placements and no config section in Anomaly.
2. **Breaking is data in the OGF userdata.** The sections are [destroyed], [immunities], damage_section, [collision_damage], [particles], [sound], [autoremove_parts] and [impulse_transition_*]. Most userdata is just `#include "models\objects\<x>.ltx"`, resolved against $game_config$ (SkeletonCustom.cpp:205-206). So config alone can make a model breakable; GAMMA's hideout-furniture mod already does this for doors.
3. **Plain physic_object props have no hit callback.** CPhysicObject has no Hit override, and CPhysicsShellHolder::Hit only applies the impulse. Scripts see them only through bullet_on_impact (target id, material, bone, position) and our own blast sphere. Destroyables, lamps and cars do fire callback.hit and callback.death.
4. **The stock engine already gives hit feedback:** bullet decals on dynamic props, per-material sparks, splinters and sounds, and bullet impulse. Material pairs can be overridden with gamedata/materials/material_pairs_*.ltx (DLTX).
5. **Co-op:**
   - xrRazom syncs destroyables, glass and lamps (DESTR_HIT / DESTR_DEST) and props (PHYS_BULK, host-authoritative). It replicates host spawns and releases.
   - Clients cannot create ALife objects.
   - Safe pattern: the host decides and sends a line; each machine plays seeded local cosmetic debris; gameplay state changes only through a host release or a native destroy.

## 1. Engine systems

### 1.1 Class map

| Section | Engine class | Server class | Hit behaviour |
|---|---|---|---|
| physic_object (O_PHYSIC / O_PHYS_S) | CPhysicObject | CSE_ALifeObjectPhysic | impulse only |
| physic_destroyable_object, physic_door (P_DSTRBL / O_DSTR_S) | CDestroyablePhysicsObject | CSE_ALifeObjectPhysic | callback.hit, health, destroy |
| ph_skeleton_object (P_SKELET) | CPhysicsSkeletonObject | CSE_ALifePHSkeletonObject | impulse; joints may break |
| O_BRKBL | CBreakableObject | CSE_ALifeObjectBreakable | health → shatter |
| lights_hanging_lamp | CHangingLamp | CSE_ALifeObjectHangingLamp | callback.hit; the light dies |
| explosive_barrel etc. (S_EXPLO) | CExplosiveItem | CSE_ALifeItemExplosive | condition → fuse → explode |
| cars (SCRPTCAR) | CCar | CSE_ALifeCar | health → explode → destroy |

- Registration: object_factory_register.cpp:417/422/421/419/416/349/281.
- Base sections: configs/models/dynamic_objects.ltx:5-24 (physic_door has is_ai_obstacle = false).
- explosive_barrel (bochka_fuel.ogf: blast 5.4, radius 8.2, 78 frags) is defined in JSRS items/weapons/base.ltx:811-860.

### 1.2 How hits reach props

**Bullets.**
- _G.CBulletOnImpact(table) runs before DynamicObjectHit / StaticObjectHit (Level_Bullet_Manager.cpp:1251-1276). The table has pos, dir, speed, distance, section, bullet, weapon, parent, target (65535 = static), material, life, element.
- DynamicObjectHit (firetrace.cpp:267-366):
  - FireShotmark (:171-255): skeleton wallmark, pair sound, pair particle;
  - then GE_HIT with the impulse (:345-364).
- Impulse = hit_impulse × k_impulse × speed_factor × energy_lost (:529-533).
  - energy_lost is 1 if the bullet stops in the object, or 1 − shoot_factor if it passes through.
  - Vanilla hit_impulse is 25–45 and k_impulse 0.5–1; GBOOBS raises k_impulse to 1.5–2.8.
- _g.CBulletManager__ObjectHit(section, obj, pos, dir, material, speed, weapon_id) is also called (:377-379).

**Explosions.**
- Every CPhysicsShellHolder within blast_r gets GE_HIT with impulse blast_impulse × effect, at the object centre on bone 0 (Explosive.cpp:446-458, 737-777).
- A limited number of objects is processed per frame (:795-806).
- Frags are real bullets.

**Physics response.**
- Hit → PHHit → shell->applyHit (PhysicsShellHolder.cpp:148-165).
- Explosion hits go to ExplosionHit: random points and directions from the global ::Random (ShellHit.cpp:23-65).
- Other hits go to applyImpulseTrace → applyImpulseVsMC: force at the hit point, wake the body, BodyCutForce clamp (PHElement.cpp:611-632).
- Fracturable elements also queue the impact for breaking (:704-712).

**Collisions.** Only bones listed in [collision_damage] get a contact callback, which sends GE_HIT strike hits above 5 (PHCollisionDamageReceiver.cpp:19-67).

### 1.3 CDestroyablePhysicsObject + CPHDestroyable

- **Spawn** (DestroyablePhysicsObject.cpp:53-77) reads from userdata: [destroyed] (part list or destroyed_vis_name, PHDestroyable.cpp:162-177), [immunities], damage_section, [collision_damage], [sound] break_sound, [particles] destroy_particles.
- **Hit** (:80-103), in order: eHit callback, immunity and bone scale, impulse, then m_fHealth -= power.
- **Health** starts at 1.0 (:23) and is not saved, so partial damage resets on reload.
- **Destroy** (:105-144): eDeath callback → CPHDestroyable::Destroy, then sound and particles aligned to the fatal hit.
- **CPHDestroyable::Destroy** (PHDestroyable.cpp:137-160) spawns parts only if IsGameTypeSingle() (:152). Each part goes through GenSpawnReplace (OnServer() only, :52-105): a physic_destroyable_object with the part visual and source_id, sent as M_SPAWN with M_SPAWN_OBJECT_LOCAL.
- **When the parts arrive:**
  - spawn_notificate (PHDestroyableNotificate.cpp:12-24);
  - NotificatePart (:215-339): copies the source transform, applies the fatal impulse × imp_transition_factor plus a random-direction impulse random_min × mass + random_hit_imp × hit_impulse (unseeded ::Random, :282-315), copies velocities, and applies [autoremove_parts] time;
  - the source hides, then destroys itself after its fx (:204-213, 341-360).
- Parts are full server objects; a part can break again.

### 1.4 Breakable joints / fractures

- **Data:** in the bone IK record: SJointIKData::flBreakable, break_force and break_torque (bone.h:223-254), plus the shape flag sfRemoveAfterBreak (:185).
- **Build** (PHShell.cpp:828-990): a rigid breakable joint becomes a CPHFracture inside the parent element (64 bones max); a non-rigid one becomes a breakable ODE joint.
- **Update:** CPHFracture::Update sums contact feedback plus queued hit impulses (PHFracture.cpp:300-554). Weapon hits are scaled by phRigidBreakWeaponFactor; phBreakCommonFactor = 0.01.
- **Break:** CPHSkeleton::Update → PHSplit → SpawnCopy (PHSkeleton.cpp:143-150, 284-315). SpawnCopy creates a ph_skeleton_object with the same visual and runs only on Local(). UnsplitSingle splits the bone masks (:318-372). Pieces whose bones are all sfRemoveAfterBreak are removed after 60 s (:374-421).
- **Lua:** only block_breaking, unblock_breaking and is_breakable. Nothing can cause a break.
- **Furniture:** stul_wood_01 has 6 box bones, all jtRigid with flags 0. Flipping the IK flag is the cheapest "chair loses a leg".

### 1.5 CBreakableObject (glass)

- Before breaking it is a static geometry shell with a collision callback (BreakableObject.cpp:117-120).
- Non-strike hits above hit_break_threthhold lower health; any strike hit breaks it (:291-305).
- Break() turns each bone into a shard with Random.randF impulses, then DestroyObject after remove_time (:221-248). It spawns no server objects.
- Needs the keys remove_time, hit_break_threthhold, collision_break_threthhold and immunity_factor.
- Anomaly has no section for it and no placements; windows are level geometry. xrRazom's destroy handler does accept the class.

### 1.6 CExplosiveItem

- A hit applies the impulse, then lowers condition by damage × immunity (ExplosiveItem.cpp:45-58).
- When condition falls below condition_to_explode, the fuse starts, then GenExplodeEvent and _G.CExplosiveItem__OnExplode run (:78-93).
- Items on the ground lose condition the same way, silently.
- xrRazom syncs this as EXPL_EXPL.

### 1.7 CHangingLamp

- A hit fires eHit and applies the impulse. A hit on light_bone zeroes health; otherwise health drops by damage × 100. At zero it calls TurnOff (HangingLamp.cpp:461-480).
- State is saved.
- Lua: obj:get_hanging_lamp() gives turn_on / turn_off / set_color_animator / is_on.
- 1,150 are placed in vanilla. No glass shatter or sparks.

### 1.8 CCar

- Hit (Car.cpp:671-721): wheels, doors, immunity, an on_before_hit functor, _G.CCar__OnHit, fuse.
- [damage_particles] (CarDamageParticles.cpp:31-62).
- CarExplode (:2057-2079) then runs CPHDestroyable::Destroy when the model has parts: BTR 5, Mi-24 10, UAZ 4, ZAZ 7.
- Lua: GetfHealth / SetfHealth / CarExplode / PlayDamageParticles.

### 1.9 Doors

- physic_door is a destroyable with ph_door logic.
- It breaks only if its model has [destroyed]. Vanilla destr_door_wood_130x250_01.ltx is not included by any OGF.
- "385- Even More Hideout Furnitures" ships models/objects/destructible_doors.ltx: box and door parts plus [immunities].

### 1.10 Lua today

**Callbacks.**
- callback.hit and callback.death exist only on destroyables, lamps and cars.
- The vanilla binder re-sends physic_object_on_hit_callback and _on_use_callback (bind_physic_object.script:122, 135), but only for inventory boxes, objects with [logic], and box_metall_01 / box_wood_01 / box_wood_02.
- Its death handler spawns box loot through xr_box.

**Engine-called globals.** _G.CBulletOnInit / OnUpdate / OnImpact / OnRemove, _g.CBulletManager__ObjectHit, _G.CExplosiveItem__OnExplode, _G.CCar__OnHit, and a per-section on_physic_contact (which can veto a contact).

**Physics.** get_physics_shell() gives apply_force / apply_torque, linear and angular velocity, freeze, element and joint access, and block_breaking. Also get_physics_object() and set_const_force.

**Visual.**
- set_visual_name sends GE_CHANGE_VISUAL and sets the visual name, but does not rebuild the physics shell (script_game_object2.cpp:670-697).
- A destroyable deletes its shell on a visual change (DestroyablePhysicsObject.cpp:30-39).
- A 1-bone rigid prop probably keeps following XFORM [I].
- level.get_visual_userdata(visual).

**Lifetime.** destroy_object(), alife_release (host), explode.

**World.** level.iterate_nearest, level.add_attachment / remove_attachment, wallmarks_manager():place / place_skeleton, level.add_bullet.

**Missing:** a hit callback on plain props, forcing a joint break, per-instance parts or health, changing class in place, rebuilding the shell after a visual swap, a seeded ::Random, and client-local physics bodies.

## 2. Assets

**Survey:**
- tools/survey_props.py read 816 prop OGFs from meshes_dynamics.db0. Results are in vanilla_props_dyn.json, destroyable_visuals.json and spawn_visuals.json.
- 756 are MT_SKELETON_RIGID (type 10, PM/ST children, 1-link vertices) and 60 are MT_SKELETON_ANIM. They run about 70–2,500 tris (box_wood_01 296, bochka_close_1 386, bottle_3l 2,448).
- Userdata: 686 have none, 67 inline, 63 #include.

**54 models already have parts:**
- crates: box_wood_01 (7), box_metall_01 (2), box_paper;
- bottle_3l (8 shards), bottle_bar_stakan, ventilator_mike;
- wood_fence_1..5 (7 each), wooden_board_*, wood_board_br_*, wood_stolb_fixed;
- hospital arches, debris, fences and boards;
- pri_a25 antenna (8), red-forest rope, aes_zabor, door_locker, monolith generator and artefact;
- BTR, Mi-24 ×3, Mi-2 ×3, UAZ ×2, ZAZ, ZAZ-968, mounted guns.

No model ships [immunities] or damage_section, so a crate breaks to 1–3 rifle hits, one knife slash or any blast.

**Placements in vanilla all.spawn:**

| Section | Count | Notes |
|---|---|---|
| physic_destroyable_object | 2,353 | About 1,689 can break: box_wood_01 1,041, box_metall_01 439, bottle_3l 39, boards and fences about 100 |
| ↳ destroyable class, no parts | about 660 | box_1a/b/c 137, doors, bidon 30, bochka_close_* 48, gaz_balon 15, stul_wood_01 11, … |
| physic_object | 870 | bochka_close_1..4 226, extinguishers 32, vises, drinks, buckets, radios, fans, …; 46 have a breakable visual but the wrong class |
| lights_hanging_lamp | 1,150 | |
| explosives | 117 barrels + about 130 others | fuelcan 29, barrel_low 26, mobiltank 11, … |
| m_car | 12 | |
| glass (CBreakableObject) | 0 | |

- **Breakable joints:** 19 models: skelet_* poses, car doors (Niva / UAZ / ZAZ), konteyner_01, truba_bar_rostok, doski_br_02, tactical torch, hospital arch parts.
- **GAMMA additions:** destructible_doors.ltx and vehicle userdata edits. No new fracture meshes.

**Not breakable today:**
- barrels bochka_close_1..4 (3 cylinder bones, material objects\barrel), bidon, kanistra, gaz_balon;
- box_1a/b/c, box_wood_02 (9 bones), box_bottle_1;
- stul_* and taburet_* (6–9 box bones), stol_4;
- kitchenware, tv_1 (has a glass bone), monitors, notebook, radiola, fans, table_lamp_01, light_*_glass;
- bottles, extinguisher, bucket, paint can.

**Broken or damaged meshes that ship unused:**
- stul_school_01_br;
- kolyaska_01_braked, wheel_litter_01_braked, kolyaska_wheel_01_braked;
- wood_board_br_01_prt1..4;
- box\prt\box_lab_02_prt1..6 (it has an ltx, but nothing uses it);
- door_locker_prt1, crane_plita, misc\large_parts.

**Reusable one-bone part meshes:** 7 crate planks, 4 door slabs, 7 fence planks, 8 board pieces, 8 glass jar shards, 2 metal box halves, hospital concrete and metal. Wood, glass and light sheet metal are covered; barrels, ceramics, electronics and plastic are not.

**Making a prop breakable from shipped assets:**
1. Ship userdata, either way:
   - override configs/models/objects/<x>.ltx where an OGF already includes it (31 object models do); or
   - ship ZGO copies of the OGF with chunk 17 rewritten to `#include "models\objects\zgo_<x>.ltx"` (trivial with ogf.py).
2. Fill it: [destroyed] with kit-bashed parts, [immunities] per material, [collision_damage], [particles], [sound], [autoremove_parts], [impulse_transition_to_parts].
3. Make sure the placement has the destroyable class:
   - the ~660 class-only placements are fine as they are;
   - physic_object placements need a host swap: alife_release, then alife():create("physic_destroyable_object", …) with the same visual and angles, done lazily on the first damaging hit. xrRazom replicates both.

**Own fracture meshes:** ogf.py handles header types 3 and 10, PM/ST children and vertex formats 1–4, plus bones and IK (ik, shape). All 816 props parsed.

Output targets:

| Target | What it is | Notes |
|---|---|---|
| (a) native parts | N one-bone OGFs (box/cylinder shape and mass in IK) plus [destroyed] | ODE, real collisions; host server objects, replicated; spread from unseeded Random |
| **(b) debris rig — best fit** | one OGF, one bone per piece, run by zgo_debris through a single level.add_attachment, posed like severed limbs | identical on every machine, no ALife |
| (c) breakable-joint model | flBreakable rigid joints plus sfRemoveAfterBreak | spawns ph_skeleton_object copies on Local(); untested in xrRazom |

How to split, by prop kind:
- planks: connected components or UV islands;
- thin shells (barrels, cans, bottles, TV glass): surface Voronoi; no caps needed, though a back face helps;
- solids: 3D Voronoi with caps, which needs an interior texture.

Give each piece a PCA box shape, mass from volume × density, and the material of its source bone. Most props are not watertight, so start with shells and planks.

## 3. Hit feedback

**Bullet holes.**
- FireShotmark already places add_SkeletonWallmark on any dynamic object.
- CKinematics::AddWallmark projects onto the bone's triangles, skipping sfNoPickable bones (SkeletonCustom.cpp:714-812), and the marks follow the bones (:820-848).
- Lua: wallmarks_manager():place_skeleton(obj, sec, start, dir, size, ttl).
- Gaps: marks vanish on destroy or visual swap; TTL is global [I]; there are no exit holes and no floor splinter or scorch marks. ZGO can add those from bullet_on_impact.

**Materials.**
- Prop materials: objects\large_furniture (wood), barrel, metal_box, small_metal_trash, tin_can, glass, bottle, clothes, concrete_box, large_metal_trash.
- Teamson & Oleh's material_pairs_bullet.ltx already sets hit_wood_01/01a, hit_metal_00/01, hit_glass_01/01a, hit_cloth_01 and hit_concrete_01.
- GameMtlLib.cpp:117-200 and 237-330 read materials.ltx and material_pairs.ltx (with #include material_pairs_*.ltx and DLTX). ZGO can ship material_pairs_zgo_props.ltx.
- Extra layers from bullet_on_impact: wood splinters and chips; metal sparks, ricochet and pinholes; glass shards and tinkle; cardboard fluff; leaking barrels and canisters that run dry.

**Impulse.**
- The push follows the energy the bullet lost, applied at the hit point with torque.
- It is damped by the BodyCutForce clamp, IK masses (crate 100 kg, barrel 60, chair 10 per bone), pass-through and random explosion directions.
- To add: a host-only extra apply_force scaled by ammo ÷ mass (Source exaggerates ×3.5), an upward kick and spin on blasts, and a camera thump when the player breaks something big. Items on the ground could get a spark and a hop.

## 4. Co-op (xrRazom) — notes in xrrazom/

**What xrRazom does:**
- **Identity:** all.spawn objects have the same IDs on every machine. Host-created objects are seeded to clients under host IDs, mapped through XrrAlife():GetLocalItemIDByHostID. The world seed log shows "95 x ph_skeleton_object" and "8 x physic_destroyable_object".
- **Physics:** JOIN_PHYS, PHYS_BULK, PHYS_IMP and PEER_PUSH, host-authoritative.
- **Destroyables:** DESTR_HIT, DESTR_DEST and JOIN_DESTR. The handler only takes destroyables, glass and lamps, and fires death on clients. Box loot is host-only (xrr_patch_client.script:309-310).
- **Hits:** clients forward NPC hits. For objects only PEER_DESTROYABLE_HIT and PEER_HELI_HIT exist; nothing forwards hits on plain props, barrels or cars. Explosions use EXPL_EXPL.
- **Spawns and releases:** the host's replicate. On clients, alife_create returns nil and create/register are blocked (xrr_patch_client.script:137-149, 190-192), and they can't release host objects (xrr_core.script:169-180). Mods talk to each other through xrr_script_event.send.

**Host breaks a destroyable:**
- Parts spawn only if IsGameTypeSingle(); probably true, since host box loot works [I].
- Parts replicate, and clients get DESTR_DEST and run their own Destroy.
- **Unknown:** whether the client's GenSpawnReplace also fires (OnServer(); the client runs a local server). If it does, parts are duplicated. The local spread is unseeded.
- **Test:** break a crate on the host while a client watches, count parts on both, and grep the client log for WorldObject / DESTROYABLE_DESTROY. Repeat with a breakable-joint model.

**Safe for ZGO:**
- host decisions, host alife_release / create;
- zgo_sync lines (emit, send_up);
- seeded local cosmetics.

With care:
- set_callback(callback.hit / death) only on props with no binder;
- for bound props, use RegisterScriptCallback("physic_object_on_hit_callback") or wrap generic_physics_binder.death_callback. Replacing the binder's callback breaks ph_on_hit / ph_door and xrRazom's use callback.

Unsafe:
- client-side create, release, hit, explode or destroy_object on shared props;
- client-side forces (the host overwrites them) [I];
- relying on engine Random matching between machines;
- native breakable-joint models in co-op before the test above.

Client bullets on props: the host never sees them, so add a "P" up-line (id, material, pos, dir, ammo, element). Don't double-damage vanilla destroyables; xrRazom already forwards those hits.

**"Prop break" event sketch.**
- Host: decide, play locally, `emit{"B", id, visual, rig, pos, hpb, dir, impulse, seed, mtl}`, then alife_release if it is a scripted break.
- Client: don't rely on the object still existing; spawn the seeded rig at the line's transform; play the fx. Bump PROTO.

## 5. Other games (sources; notes in web/)

- **Half-Life 2 / Source:**
  - propdata.txt sets health and chunks by material class (Wooden.Small 20 / 2, Medium 30 / 4; wood bullets ×0.75, melee ×2, explosives ×1.5; Glass.Small 5 client-side only, Window 1; Metal 0 = unbreakable). https://github.com/SteamDatabase/GameTracking-CSGO/blob/master/game/csgo/pak01_dir/scripts/propdata.txt
  - func_breakable uses bullets 0.5 / melee 1.5 / explosives 1.25 (source-sdk-2013 props.cpp L80-82).
  - Gibs come generic (shared pool, debris collision group, 5–10 s fade) or as hand-made break pieces; there are per-break and per-frame caps and an LRU game_gib_manager.
  - With "auto", props under 15³ in are client-only and props under 8 kg non-solid (props_shared.h L86-89).
  - Bullet push uses real mass × velocity × 3.5 (hl2_gamerules.cpp L1786-1789), plus phys_pushscale.
  - A material impact table drives decal, flecks, particle and sound (fx_impact.cpp).
  - Objects under 1 kg moving over 8 in/s break glass (physics_impact_damage.cpp L169-188).
- **F.E.A.R.:** persistent holes, Havok 2, dust that blocks vision, sparks in slow-mo. Particles and decals, not geometry [I].
- **Red Faction Guerrilla / Armageddon:**
  - pre-broken parts with strength and weight, plus stress checks;
  - large and small destruction computed separately;
  - sounds and shake suppressed in big events; debris never kills the player;
  - server-authoritative MP;
  - debris audio by material × shape × size × event, with voice limits and creaks before collapse.
  - Armageddon: man-made objects destructible, terrain not.
- **Teardown:** MakeHole takes soft / medium / hard radii by material; debris thresholds and fire counts; MP sends deterministic commands on a reliable channel, transforms on an unreliable one, and late joiners replay (https://blog.voxagon.se/2026/03/13/teardown-multiplayer.html).
- **Escape from Tarkov:** material and bullet penetration and ricochet; minimal world destruction.
- **Hunt: Showdown:** per-layer damage loss (Compact ammo ×0.75 / ×0.5); damage states that tell players things (broken barrels, cracked fences); material occludes sound; static vs dynamic is a budget call that includes online limits.
- **Rainbow Six Siege** (GDC 2016, LHeureux): parts split by material; debris is replacement pieces with box collision and no debris-on-debris collision; about 6 ms per wall and 0.33 ms per bullet hole; **breaks replicated as events, randomness seeded from the impact position, debris not replicated.** That is ZGO's model.
- **Frostbite:** remove the part's geometry, add edge detail meshes, a damage mask, particles and debris. BF6 prioritises and culls debris over the network.
- **Control:** static mesh → rigid bodies → fragments → particles; at most 200 rigid bodies; under load it skips straight to particles; particles hide the swap.

**What transfers to ZGO:**
1. One material impact table.
2. Health by material and size, with damage-type multipliers; heavy metal can't break.
3. Exaggerated, mass-scaled push.
4. Damage-state swaps hidden by a burst.
5. 2–6 gibs with a burst: no player collision, 5–20 s fade, LRU and per-frame caps.
6. Debris audio by material × size, with voice limits.
7. Props that explode or burn, with a fire cap.
8. Keep debris out of gameplay and saves; store only "broken".
9. Penetration through thin props (native hook or a second ray).
10. Avoid runtime cutting.

## 6. Recommendations (S = days, M = 1–2 weeks, L = weeks)

**Tier 1 (script and config only):**
1. **Prop hit-feedback layer (S).**
   - Triggered by bullet_on_impact (target ≠ 65535, a physics-object class check, material) plus the zgo_blast sphere.
   - Adds per-material particles, exit and floor decals, sound sweeteners, host-only extra apply_force, and barrel and canister leaks.
   - Ships a DLTX material_pairs_zgo_props.ltx.
   - Co-op: "F" lines from the host, "P" up-lines from clients.
2. **Effects on native breaks (S).**
   - Hook death: our own callback on unbound destroyables, a patched binder on bound ones.
   - Dust and splinter bursts sized to the bounding box, a floor decal, a thump.
   - Lamps: glass shards, sparks and a flicker through set_color_animator.
3. **More destroyables from shipped parts (S–M).**
   - zgo_*.ltx files with [immunities] and kit-bashed [destroyed]:
     - box_1a/b/c and box_wood_02 → crate planks;
     - stul_school_01 → _br;
     - wheelchairs → _braked;
     - box_lab_02 → prt1..6.
   - Inline-userdata OGFs get ZGO copies with chunk 17 rewritten.
   - This covers the ~660 class-only placements at once.

**Tier 2:**
4. **Host-driven scripted break for any prop (M).**
   - ZGO tracks health by material and mass.
   - When it runs out: host alife_release, then a "B" line with a seed; each machine spawns a debris rig (target b) in zgo_debris plus fx.
   - Covers barrels, chairs, TVs, bottles and kitchenware, with no ALife on clients.
   - Pieces don't collide with players or props; loot is host-only.
5. **Class swap to destroyable for big furniture and doors (M),** once the §4 test is done.

**Tier 3:**
6. **Offline fracture baker in zgo_baker (M–L).**
   - Shell Voronoi for barrels, cans, bottles, TV and lamp glass; plank or UV-island splits for wood; volumetric later.
   - Outputs: (b), optionally (a), interior textures and an index script.
   - First targets: bochka_close_1..4 (274 placements), box_1a/b/c (137), bidon (43), extinguisher (32), gaz_balon (33), drinks (30), canisters (18), chairs and stools (22).
7. **Damaged-model swaps (M).**
   - set_visual_name on one-bone props may just work [I, test first].
   - Multi-bone props need a native shell rebuild or a release-and-create swap.
8. **Breakable-joint furniture (target c, S per asset).** IK flag plus thresholds; single player first.

**What native hooks add:**

| Hook | Unlocks |
|---|---|
| CPhysicsShellHolder::Hit → _G.CPhysicObject__OnHit(obj, SHit, bone), with veto and scale | damage for every prop from melee, collisions and blasts |
| seeded RNG in CPHDestroyable::NotificatePart, CBreakableObject::Break and CPHShell::ExplosionHit (seed from the host) | native spread that matches on every machine |
| Lua ph_destroy(who, dir, imp), set_destroyed_parts, set_ph_health (saved) | triggering native destroys, per-instance toughness, health that survives a reload |
| Lua shell:break_joint(bone) / set_breakable | scripted joint snaps |
| set_visual_name plus a shell rebuild | real damage-state swaps |
| client-local physics debris manager | colliding chunks with no network cost |
| per-model wallmark cap / TTL, exit-hole marks | persistent, riddled props |
| in-place physic_object → destroyable class change | breakable barrels and chairs without changing IDs |
