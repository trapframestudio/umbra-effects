# NPC model deformation and destruction: discovery report

(Saved by the parent session from the NPC agent's hand-back; the agent could not write it. The sources, engine copies, vanilla r3 shaders, web_research.md and tools/ are next to this file.)

Tags:
- [V] checked in engine source b86d733f4a or on disk.
- [I] inference.
- [T] needs an in-game test.

The installed exe (xrRazom's build) does include set_shader, reset_shader, get_shaders, place_skeleton and bone_callback; the level agent confirmed the names are in the exe.

## Key findings

1. **`obj:set_shader(child_id, shader, tex, false)` swaps the shader and texture of one sub-mesh on one NPC only.** Each NPC owns duplicated sub-meshes. It works alive and on ragdolls, and skinning stays correct [V]. Three GAMMA mods already use it.
2. **Sub-meshes can name ZGO's own shader.** The engine tries a Lua `.s` file first, so `zgo\dmg` loads `shaders/r3/zgo_dmg.s` [V]. In R4 the shadow pass is element 2 (`l_point`); define it, or the mesh casts no shadow [V].
3. **A `.s` file that defines only `l_special` is a free "off" switch.** The renderer skips that sub-mesh in every pass, whatever its bones or physics are doing [V code path][T].
4. **The vertex shader receives the bind-pose position for every weight format.** SSS computes the previous-frame position from the same input. So bind-space dents follow animation, ragdolls and TAA [V]. The only free per-vertex channel is the integer part of the UV [V].
5. **Per-NPC data without native code:**
   - tiny "digit" textures named in the second texture string and parsed by the `.s` [V][T];
   - DDS files written from Lua into $game_saves$ followed by a rescan [V pieces][T];
   - bone callbacks, but only on script attachments [V].
6. **Skeleton wallmarks follow ragdolls,** but they change colour only, never normals or depth [V].
7. **Corpses never process ragdoll splits** [V].
8. **No other GAMMA mod ships gore geometry or skinned gore shaders** [V].

## 1. How shipped games do it

PRIMARY = talk, slides or code. SECONDARY = interview or press.

- **Left 4 Dead 2** (Vlachos, GDC 2010, PRIMARY: https://cdn.cloudflare.steamstatic.com/apps/valve/2010/gdc2010_vlachos_l4d2wounds.pdf)
  - Two active ellipsoids per zombie, sent as per-draw constants.
  - The vertex shader tests the pre-skinned position; the pixel shader clips and adds a ragged projected texture.
  - Wound insert meshes are skinned to the same skeleton (up to 54).
  - The cut must also apply in the depth and shadow passes ("phantom shadows").
  - Fit for ZGO: very high.
- **Fallout 3 / New Vegas and Skyrim:** body-part partitions with pre-modelled caps for the piece and the stump (nif.xml https://github.com/niftools/nifxml/blob/develop/nif.xml; caps 101–113 and 201–213). Fit: high.
- **GHOUL2** (SoF2 / Jedi Academy, OpenJK G2_misc.cpp): surfaces and `*_cap_*` surfaces turned on and off. Gore decals are CPU-projected and re-drawn skinned, like our skeleton wallmarks.
- **Dying Light 2** (interview): hierarchical cut zones. The cut part is "hidden with shaders" and "covered by a correctly shaped mesh".
- **Shadow Warrior 2013** (ZTG slides): pre-cut meshes, skinned decals split per chunk, decals that grow by moving the alpha-test threshold.
- **Dead Island 2 (FLESH):** runtime cutting and deformation with layered viscera and unique UVs (secondary sources).
- **Dead Space remake:** skin, fat, muscle and bone layers built from layered meshes and vertex transforms (secondary).
- **Doom Eternal:** authored per-region states (secondary).
- **Arma 3:** a section's material is swapped as damage rises.
- **Unreal:** HideBoneByName scales a bone to zero. Tom Looman's approach uses bind-pose sphere masks, with a practical limit of 3–5; render targets cost 1.6–4.5 ms.

**Ranking for us:**
1. Bind-space wound volumes in the vertex shader.
2. Fixed cut zones with caps.
3. Baked nested layers revealed by the volumes.
4. Vertex-shader craters.
5. Per-region material state.
6. Skinned decals.

Not feasible without native code: per-instance render targets, runtime cutting, blend shapes.

## 2. The R4 skinned-model shader path [V]

**Shaders in use** (686 of 4,796 models sampled):

| Shader | Sub-meshes |
|---|---|
| models\model | 1662 |
| models\model_pn | 1001 |
| models\window | 126 |
| model_fur | 10 |
| antigas_glass | 9 |
| transparent | 8 |
| selflight | 7 |
| model_aref | 6 |

- Weight formats: 1W 962, 2W 869, 4W 817, 3W 207.
- Most models have 47 bones.
- model, model_pn, fur and aref use the 'MODEL   ' class (CBlender_deffer_model). window, antigas and weapons use 'MODELEbB'.
- model_pn and model_hm tessellate, which is only possible from C++ blenders.

**Model blender:**
- E0 (HQ): uber_deffer("model","base") → deffer_model_{bump|flat}[_d][-hq] with deffer_base_*. Stencil ref 1; ATOC for alpha test.
- E1: the LQ version.
- E2 (shadow): shadow_direct_model + dumb (or the aref pair).

**Files:**
- R4 reads the r3 folder (r4.h:324).
- Winning copies in GAMMA:
  - skin.h, deffer_model_bump.vs and common_iostructs.h come from SSS 23, which adds sbones_array_prev and v_model.P_prev from the same P.
  - deffer_base_bump.ps comes from Atmospherics 2.69 RC8.
  - shadow_direct_model.vs is vanilla.
  - ZGO already overrides effects_wallmark_blood.ps.
- `.s` files load only from the root of r3 (FS_RootOnly, dx10ResourceManager_Scripting.cpp:470); a backslash in a name becomes "_".

**Vertex inputs** (FSkinned.cpp:60–330):
- P is a float4 with w = 1; N, T and B are D3DCOLOR.
- Bone indices:
  - 1W: N.w = index × 3.
  - 2W: uv = (u, v, i0×3, i1×3).
  - 3W: B.w = i2.
  - 4W: indices in TEXCOORD1.
- UV is a full float. Nothing else from the OGF reaches the GPU.

**Bones:**
- sbones_array[234] holds 3 rows per bone, uploaded per sub-mesh draw from mRenderTransform (current × inverse bind) (SkeletonX.cpp:128–138). So P is in bind-pose model space.
- Only bones 0..RMS_bonecount−1 are uploaded; anything higher is stale.
- RM_SINGLE sub-meshes use m_W = world × bone with SKIN_0; P is still bind space.

**Constants:** no stock constant carries per-NPC data. m_script_params is global (Blender_Recorder_StandartBinding.cpp).

**Skinning variants:**
- _CreateVS appends _0.._4 to the shader name (Resources.cpp:143–160), and shader_compile defines SKIN_* (r4.cpp:1278).
- SetShaderTexture restores m_skinning before creating the shader (FBasicVisual.cpp:124–152).

**Custom shader names in OGFs:**
- OGF_TEXTURE is read in FBasicVisual.cpp:66–75.
- CResourceManager::Create tries _lua_HasShader first (it needs `normal` or `l_special`), then a C++ blender, then stub_default (ResourceManager.cpp:325–350).
- Without ZGO's .s files present, baked names fall back to stub_default and the mesh becomes VISIBLE.

**Lua elements** (Scripting.cpp:515–612):

| Element | Lua function |
|---|---|
| E0 | normal_hq or normal |
| E1 | normal |
| E2 | l_point (the shadow pass) |
| E3 | l_spot |
| E4 | l_special |

- Each is called as fn(shader, t_0, t_1, detail). t_0 and t_1 are the first two texture-list entries, lowercased, without extension, up to 127 characters each (_ParseList :104–130).
- adopt_compiler (:92–231) supports:
  - begin(vs,ps) or begin(vs,gs,ps);
  - sorting, emissive, distort, wmark, fog, zb, blend, aref, color_write_enable;
  - dx10texture, dx10sampler, dx10stencil, dx10stencil_ref, dx10cullmode, dx10atoc, dx10zfunc.
- It does not support tessellation or literal constants.
- The `.s` VM has the string library.

## 3. Per-NPC data channels without native code

- **C1. set_shader(id, shader, tex, false)** [V]
  - Per sub-mesh, per NPC: each NPC's hierarchy duplicates its children (FHierrarhyVisual.cpp:116).
  - Code: script_game_object.cpp:1520/1596; exported in script3.cpp:712–715 along with reset_shader, get_shaders and get_default_shaders.
  - id = OGF child index + 1; id < 1 means all children. Hidden children are included. A nil shader keeps the current one.
  - **Not saved:** re-apply on load and when the NPC comes online.
  - Already used by Hideout Cat, Gadgets and 3DSS.
- **C2. The "off" shader** (only l_special defined) [V][T]
  - E0, E1 and E2 are null, so r_dsgraph_insert_dynamic returns early in every pass (r__dsgraph_build.cpp:69–70).
  - E4 is only used when distort or emissive is set. "null" vertex and pixel shader names are special-cased (Resources.cpp:165/280).
  - Fallback if this fails: a pass whose vertex shader outputs degenerate positions.
- **C3. Digit textures in t_1,** parsed in the .s and bound by name [V binding][T]
  - Slots: 4 in the vertex shader, 16 in the pixel shader (R_Backend.h:65–66). Vertex-shader textures are supported (dx10r_constants.cpp:229–266).
  - Make them 1×1 DDS with a single mip: Reduce needs more than one mip, so a single-mip texture survives every quality setting (dx10Texture.cpp:104–130).
  - Read them with Load (no sampler), and give vertex and pixel textures different names.
  - 256 files give 8 bits per slot; 4,096 files give 12 bits. That is about 32–48 bits in the vertex shader.
  - Each unique string creates one cached Shader.
- **C4. Integer part of the UV, baked in** [V]
  - About 10 bits each in u and v, for site id, layer and thickness.
  - Only safe with WRAP samplers.
- **C5. Per-model static site-table texture** [V]. Costs one vertex-shader slot.
- **C6. DDS written from Lua** [V pieces][T]
  - io and ffi are open; popen, execute and remove are removed (script_storage.cpp:325–340, 416–425).
  - Steps:
    1. io.open appdata\savedgames\zgo_w_<id>.dds.
    2. getFS():rescan_path("$game_saves$"), then rescan_pathes() (fs_registrator_script.cpp:25–35; LocatorAPI.cpp:1652).
    3. The texture search order is $level$, then $game_saves$, then $game_textures$ (dx10Texture.cpp:374–376).
    4. Clean up with file_delete.
  - w_open has no binding for its IWriter.
  - Risks: USVFS redirection, rescan cost, file churn.
- **C7. Hidden-bone switches:** about 2 bits, but hiding a bone collapses its vertices. Not recommended.
- **C8. Tangent handedness:** not free; it breaks normal maps.
- **C9. Lua bone callbacks on script attachments** [V]
  - bone_callback(bone, fn → Fmatrix) (script_attachment_manager.cpp:683–745, 1962–2037).
  - Only the attachment's own shader can use it. Good for flaps and intestines. Possible one-frame lag [T].
- **C10. Skeleton wallmarks** [V]
  - place_skeleton(obj, sec, start, dir, size, ttl) (script_wallmarks_manager.cpp:97–108).
  - CPU-skinned every frame, FVF::LIT with no normal (SkeletonCustom.cpp:851–934). Colour target only, RGB (r4_rendertarget_phase_combine.cpp:856–869).
  - wm_blood_* textures use effects\wallmark_blood (dxWallMarkArray.cpp:17–38). We can override its .s and branch on the texture name.
  - Decals are built from every visible child, including children switched off with zgo\off.
- **C11. Ragdoll joint API** [V exports][T]
  - Available: limits, springs and damping, max force.
  - No joint destroy.

## 4. Recommended design [I]

**Sub-meshes per section s** (the torso is split front/back and never severed):
- C_s: the intact section, with the stock shader.
- D_s: a damage mesh, default zgo\off.
- K_s: a stump cap, default zgo\off.

**Runtime switches:**
- Damage: set_shader(C_s, "zgo\\off") and set_shader(D_s, "zgo\\dmg", "<tex>,<bump>:<digits>").
- Sever: hide the bones as today, then set_shader(K_s, "models\\model", "zgo\\flesh_cap").
- An undamaged NPC costs nothing extra.

**zgo\dmg vertex shader:**
- Per active site: depth = D(stage, progress) × profile × noise, clamped to the baked thickness.
- Push the bind-space P inward and recompute N, then run the stock vertex shader. Wrap it with #define main zgo_stock_main + #include so motion vectors stay correct.
- Bone proxies are weighted 100% to their bone and sit at real depth, so the depth test reveals them.

**Pixel shader:**
- Layers by depth: skin, bloody rim, fat, muscle (bind-space triplanar), bone, cavity; wet gloss.
- Writes the G-buffer through the stock sload and pack_gbuffer.

**Shadows and textures:**
- l_point applies the same displacement with dumb.
- The bump name is passed in t_1, since Lua can't call bump_get (the baker resolves it).

**Damage stages:**

| Stage | Large parts | Forearm / calf | Hands / feet | Head |
|---|---|---|---|---|
| 1 | bruise or graze wallmark | same | same | same |
| 2 | open-wound wallmark, plus a small dent near a site | same | wallmark | wallmark |
| 3 | crater, r ≈ 6 cm, d 3–4 cm | ≤ 50% thickness | mangled sever | dent |
| 4 | down to the rib, spine or long-bone proxy | ≤ 70%, bone shaft visible | — | skull shell, jaw collapse |
| 5 | sever: D off, cap on, limb piece; torso: several stage-4 sites plus gibs, or a full gib | same | same | decap or burst |

A per-site progress digit allows continuous deepening within a stage.

**Baker additions** (deduplicate geometry by src_md5):
1. **Sites:** Poisson disk, 8–10 cm apart. Counts: torso 12–20, thigh or upper arm 2–4, forearm or calf 1–2, head 4–6. Each site stores centre, normal, radius, inward-ray thickness and bone.
2. **D_s:**
   - subdivide site patches to edges of 1.5 cm or less, with interpolated weights;
   - write UV integer codes;
   - add proxies (ribs, sternum, vertebrae, long-bone shafts, skull shell, mandible);
   - an optional inset cavity shell.
   - Bones must stay within the section's subtree.
3. **K_s:** triangulate the seam ring, then add a bulge, a ragged rim and a bone stub. The rim copies the ring's weights; the interior is weighted to the parent bone. Use the stock shader with a flesh texture.
4. **Limb pieces:** make them skeleton OGFs, because set_shader silently does nothing on rigid meshes (dcast_PKinematics). Deduplicate them and apply the texture at spawn.
5. **Gib chunks:** generic blobs carved from the crater volume.
6. **Index:**
   - sub-mesh ids;
   - the site table;
   - per-bone bind matrices, so P_bind = Bind_b · inv(bone_transform(b)) · P_world, with bone_transform in world space;
   - piece names.
7. **Shared assets:**
   - flesh, fat and bone atlases;
   - 256 digit DDS files;
   - zgo_off.s, zgo_dmg.s and the dmg vs/ps/shadow vs;
   - a wound-decal branch in effects_wallmark_blood.s.

**Disk:** today's bake is 2.97 GB, with a median of 18 sub-meshes. Expect 2–3× more, unless we bake only models that are actually spawned.

**Runtime:**
1. The host maps a hit to its section and the nearest site within ~1.3 R.
2. Energy accumulates per calibre class and sets the stage.
3. On a stage change: pack the digits, apply them locally, broadcast `zgo_d|<id>|<sec>|<digits>`, and spawn gibs at stage 3 and above.
4. Hits that miss every site, and stages 1–2, become wallmarks.

Clients replay the sync line; nothing touches xrRazom. Re-apply on load, when an NPC comes online, and on the 2.5 s tick. Prewarm shader compilation (cached in appdata\shaders_cache) on a hidden dummy.

**Optional upgrade (C6):** a per-NPC ellipsoid list texture for L4D2-style arbitrary wounds, clipped with inset shells. Only after the C6 round-trip is proven.

**Gotchas:** bullets and decals hit the undented CPU geometry, and bones above RMS_bonecount must never be read.

**Test plan:**
1. zgo_off on one sub-mesh of a live NPC and a ragdoll, then reset_shader.
2. zgo_dmg with an empty dent on 1W, 2W, 3W, 4W and RM_SINGLE meshes; check the G-buffer, shadows and TAA under SSS and Atmospherics.
3. Read back digits through 4 vertex and 6 pixel slots.
4. Dent and proxy reveal, first on a hand-made model, then on baker output.
5. The C6 round-trip, with timing.
6. Co-op with 2 clients.

## 5. Continuous ragdoll deformation

**Without native code:**
- Bind-space vertex-shader deformations driven by C3 or C6 data. They follow animation and ragdolls exactly, and they can keep deepening on corpses:
  - dents;
  - crush or flatten (skull, chest);
  - swelling or burn shrink;
  - a visual "broken limb" bend (collision stays straight).
- Sub-mesh switching (C1, C2).
- Joint softening through the joint API (C11) [T]. There is no joint destroy.
- Collapsing bones that have no physics element (as today).
- Attachments with bone callbacks (flaps, intestines).

**Native hooks:**
1. **Per-instance constant arrays:**
   - hook CSkeletonX::_Render (SkeletonX.cpp:59), or register an R_constant_setup "zgo_wounds" keyed by the object from CRender::apply_object;
   - add a Lua setter.
2. **Per-instance displacement:**
   - vertex buffers are immutable and shared (FSkinned.cpp:459 _Load_hw);
   - add a per-sub-mesh StructuredBuffer indexed by SV_VertexID, filled from the CPU copies Vertices1W..4W;
   - optionally displace the copy used by FillVertices / PickBone so decals and bullets match.
3. **Corpse ragdoll split:**
   - breakable joints already exist (PHShell.cpp:828–1000);
   - only CPHSkeleton owners split (PHSplit → SplitProcess → SpawnCopy, PHSkeleton.cpp:284–316, PHShellSplitter.cpp:401–481), and CAI_Stalker isn't one (ai_stalker.h:90);
   - either call SplitProcess from the hook, or detach the joint inside the same mesh, with baked seams and caps hiding the cut.
4. **Lua shader API:** tessellation passes and literal constants (adopt_compiler, Scripting.cpp:92–231).
5. **G-buffer wound decals** that write normals and gloss.
6. LuaJIT ffi is open (script_storage.cpp:425), so a DLL can be loaded with ffi.load.

## 6. Existing gore-model mods [V]

- **ZGO plus its local Baked Models output** is the only mod that touches body geometry: 4,790 models, median 18 sub-meshes, 6,522 triangles, 2.97 GB.
- **Painter of the Zone** (disabled): textures and particles only.
- **bvcx bone hiding** is folded into zgo_dismember.
- **Gibs** use TDLemon dynamics\zpf\meat_* and vanilla mutant_food.
- **Blood, sound and animation mods:** Better blood decals (disabled), blood pools (disabled), Wepl Hit Effects (sounds and camera), Death Animations.
- **No mod ships stump caps, wound geometry or skinned gore shaders.**

## 7. Risks

- **The off shader** is verified only on the render paths read [T].
- **Shader packs:** SSS and Atmospherics updates can change skin.h, iostructs and sload. Wrapping their files keeps coupling small, but each update needs a smoke test.
- **Performance:**
  - dents cost a few dozen instructions, and only on damaged sections;
  - the pixel shader adds 3–6 texture reads.
- **Dent limits:**
  - dents can't make overhangs, so they need a thickness clamp;
  - real holes need C6 or native code.
- **Decals and bullets don't see dents.**
- **C6 under MO2/USVFS** is untested.
