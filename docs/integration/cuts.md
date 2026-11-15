# Integration note: cuts (PLAN Phase B runtime)

Workstream `cuts`: how a cut is drawn when the 1.7 bake is installed. It covers off-shader cuts, fitted stump caps, the caps inside the model, and light severed limbs. All four are new ways of drawing. Each is experimental and off by default. With the defaults, every cut looks and behaves exactly as in 1.6, bake or no bake.

## 1. Summary

**Off-shader cuts** (MCM Dismemberment → "Cut with the off shader (experimental)", each player's own, off by default)

With the option on, a section of a body baked by 1.7 is cut differently. Its sub-meshes, and those of every section below it, are switched to `zgo\off` with `set_shader(id, "zgo\\off", "", false)`, instead of hiding the section's bones.

Benefits:
- The joint above the cut never pinches.
- The cut shows the moment it is decided, even while the body is still falling. The old wait-for-the-ragdoll queue (up to 1.5 s) is not used for these cuts.

Once the ragdoll exists, the section's bones are hidden as well. The physics keeps writing those bones, so nothing visible changes. Hiding them removes the missing part from:
- the collision form (`CCF_Skeleton::BuildState` skips hidden bones, xr_collide_form.cpp:136-148), so bullets stop hitting thin air;
- skeleton wallmarks (`CKinematics::AddWallmark` only picks visible bones, SkeletonCustom.cpp:714-770).

Bones are never hidden before the ragdoll exists. This mod tracks which bones it hid on each body, so the save trick (show the parts for the instant of a save) only touches bones it actually hid.

`set_shader` state belongs to one online object and is not saved. The mod puts it back:
- after a load;
- when a body comes online again;
- when its model changes;
- when anything else resets it.

To catch that last case, one `get_shaders(false)` per cut body within 150 m every 2.5 s compares the shaders against what this mod set.

The off shader is used only when all of these hold; otherwise the cut falls back to bones, as in 1.6:
- the option is on and kid mode is off;
- the object has `set_shader` / `reset_shader` / `get_shaders`;
- `gamedata\shaders\r3\zgo_off.s` exists (it is the probe workstream's file);
- the bake has the section's sub-mesh ids;
- the game loaded the baked model itself. The new `zgo_bake.loaded_matches(obj)` compares the sub-mesh count from `get_shaders` with the bake's count, and logs a mismatch once per model.

If `set_shader` ever raises, nothing half-done is left behind, and every cut goes back to bones until the next level.

**Fitted stump caps** (MCM "Stump cap shape": Meat disk (default) / Fitted to the cut / Fitted, fixed to the joint / Inside the model; the last three are experimental)

- **Fitted to the cut:** the bake's cap (`zgo_bake.cap`) is attached to the body as a World attachment on the parent bone, with no offset, rotation or scale. Then `bone_callback(b, b, true)` is called for every boneset bone (caps.md Mode B), so the rim follows the body's seam as it bends, hidden bones included.
- **Fixed to the joint:** Mode A only.
- If the named `bone_callback` overload raises, the cap is attached again in Mode A. All later caps use Mode A as well, and this is logged once.
- A boneset bone missing on the body forces Mode A.
- The meat disk is used instead when the bake has no cap for that cut, its `.ogf` is missing (checked with `getFS`, because a missing model is fatal), or the body wears another model.
- **Inside the model** shows the `K_s` sub-meshes of an `--experimental-caps` bake through `set_shader(id, "models\\model", "", false)`. The baked texture stays. Moving the cut up the limb switches the lower cap off again. Without the off shader, or without `K_s`, it falls back to fitted caps.
- Kid mode removes every cap. Turning kid mode off brings the caps back in the chosen shape.
- Bug fixed on the way: caps are now keyed by object, parent bone **and cut bone**. Before, the second thigh's cap replaced the first one's, because both thighs hang on the pelvis.

**Light severed limbs** (MCM "Light severed limbs (experimental)", off by default)

The flying limb is the bake's piece model (`zgo_bake.piece`, used only when its file exists and the body wears the baked model). Every piece bone gets the pose captured at the cut, bone 0 (the cut root) included. No collapse callback is used. Parts already shot off are hidden on the piece through its own bone ids.

If the piece is missing, does not start at the root, or cannot be attached, the old whole-model attachment with the collapsed bone 0 is used, unchanged.

**Co-op**

- D lines are unchanged.
- New **Q** line: one body's complete list of cuts. It replaces the old 20 s per-cut D rebroadcast, and is also sent with no cuts when the host forgets a body or sees its id reused. A client applies the cuts it is missing and puts back the ones the host no longer has.
- No sub-mesh ids or bake ids go on the wire. Each machine maps root bone names onto its own bake, with its own method.

**API**

Public functions of `zgo_debris` and `zgo_dismember` are unchanged, with these additions:
- `zgo_debris`: `add_fitted_cap`, `add_meat_cap`, `baked_piece`, `cap_style`, `caps_of`, `drop_cap`.
- `zgo_dismember`: `uses_shader`, `shown`, `cut_overrides`, `set_state`, `get_views`.
- `zgo_debris.add_stump_cap(obj, parent_bone, size, cut_bone)` keeps its signature. It now picks the shape from the MCM, and returns the attachment name.

## 2. Files

Changed (all owned by cuts):
- `gamedata/scripts/zgo_dismember.script`: rewritten as a whole file. Off-shader path, per-body view tracking, post-ragdoll bone hide, verification and reapply, kid mode, save hooks, Q line, `set_state`, `shown`, `cut_overrides`.
- `gamedata/scripts/zgo_debris.script`: rewritten as a whole file. Piece limbs, fitted and rigid caps, cap keys per cut, `caps_of`, `drop_cap`, `add_meat_cap`, `add_fitted_cap`, `baked_piece`, `cap_style`. The stick-body physics, gibs and meat caps are unchanged.
- `gamedata/scripts/zgo_bake.script`: extended. Adds `loaded_matches(obj, raw)` (cached per model; cleared by `reset()`), plus a header line. Nothing else changed.
- `gamedata/configs/text/eng/ui_st_zgo_mcm.xml`, `gamedata/configs/text/rus/ui_st_zgo_mcm.xml`: regenerated with `luajit dev/gen_mcm_text.lua`. These are generated files; regenerate them again after merging other workstreams' options.

Added:
- `gamedata/scripts/zgo_settings_cuts.script`: three options on the Dismemberment page.
- `tests/zgo_test_cuts.lua`: single player, then itself as co-op host and client.
- `tests/mocks/cuts.lua`: inert unless `CUTS_MOCKS = true`. It mocks the shader API per child id, and baked cap and piece attachments that must exist on disk and be registered skeletons. It also mocks the named `bone_callback` overload and its failure, and recursive `set_bone_visible` on attachments.
- `docs/integration/cuts.md`: this note.

Downloads: read-only engine sources from `raw.githubusercontent.com`, xray-monolith at the pinned commit b86d733f4a. The files were `xr_collide_form.cpp`, `SkeletonCustom.cpp`, `SkeletonRigid.cpp`, `fbv.cpp`/`fbv.h`, `script_game_object.cpp`, `script_attachment_manager.cpp`, `ResourceManager_Scripting.cpp`, `Blender_Particle.cpp`, `sam.h`, the `fs_registrator*` and `script_fs_script` files, `script_engine.cpp` and `script_storage.cpp`. They were saved to the session scratchpad only, not into the mod. No packages were installed, no Wine prefix was used, and nothing personal was sent.

## 3. Requests to the integrator

**R1. PROTO bump** (`zgo_sync.script`, together with the other workstreams' kinds).
- Q is new: `Q|id|section|root,root,...`, where `-` means no cuts.
- The 20 s rebroadcast now sends Q instead of D. A 1.6 peer on protocol 2 would therefore no longer get the periodic resync, and would ignore Q.
- The D format itself is unchanged.

**R2. `zgo_sync.script` header comment:** change "Q zgo_dismember sub-mesh cuts (baked models)" to "Q zgo_dismember one body's complete list of cuts (resync rounds; `-` = none)". Also add Q to the "Kinds in use" line once merged.

**R3. Probe 5 and probe 6** (probe's file, `zgo_probe.script`). With the off shader, a cut part may keep its bones visible for a moment before the ragdoll exists, and two machines may draw the same cut differently: one with the off shader, one with bones. To keep the comparisons fair:
- In probe 5 (line ~873) and probe 6 `cut_sig` (line ~904), treat a root as cut when `zgo_dismember.shown(o, r)` is non-nil (`"shader"`, `"bones"` or `"waiting"`), in addition to `bone_visible(r) == false`. Both functions are guarded by pcall if you prefer.
- In probe 6 `shader_sig`, leave out the child ids that `zgo_dismember.cut_overrides(o)` returns (`{ [child id] = shader }`). Otherwise a host with the off shader and a client without it always report a mismatch.

**R4. README:** add the section 6 texts (BAKED MODELS paragraph, SETTINGS line, LIMITS edits, CHANGES bullet).

**R5. tests/README.md:** add a line for the new suite, for example:
`luajit zgo_test_cuts.lua [seed]    # 1.7 bake drawing: off-shader cuts, fitted / in-model caps, limb pieces, kid mode, save/load, co-op host + client`.
`dev/test-all.sh` already picks it up; no harness change is needed.

**R6 (information, no action). zgo_main does not reset zgo_bake on a level change.** `B` in zgo_main is `zgo_ballistics`. This is harmless: the new `loaded_matches` cache is per model and stays valid across levels, and the cuts test resets zgo_bake itself when it swaps bakes.

## 4. Settings added (page `dismember`, all `coop = "local"`)

| id | type | default | what |
|---|---|---|---|
| `cap_style` | list `meat` / `fitted` / `fitted_rigid` / `in_model` | `meat` | Stump cap shape. The meat disk as before; the bake's fitted cap following the body (Mode B); the same cap fixed to the joint (Mode A); or the caps inside an `--experimental-caps` model, shown through the off shader. Each falls back to the next simpler shape. Shown while "Stump caps" is ticked. |
| `baked_pieces` | check | off | Light severed limbs (experimental): the bake's piece model instead of the whole body with everything else collapsed. |
| `offshader_cuts` | check | off | Cut with the off shader (experimental): `zgo\off` on the section's sub-meshes, with bones hidden only once the ragdoll exists. |

Every description is in English and Russian. Each says what changes, what is needed (a 1.7 bake), what to look at in game, and when to switch it back. The descriptions of `offshader_cuts` and `baked_pieces` name probe 1 and say to save first. The MCM string tables were regenerated.

## 5. Co-op

- **Sync kinds:** D (unchanged), G (unchanged), Q (new, see R1).
- **Who decides:** the host decides what comes off and sends D at the moment a cut is shown. That is the start of the flying piece, so the limb flies the same way everywhere.
- **Q rounds:** every 20 s the host sends Q lines, 40 bodies per round, rotating. Each line lists the cuts of one online body. Cuts whose D line is still on its way (a body waiting for its ragdoll) are left out of the rounds for up to 3 s, so a round can't overtake the D. Q with `-` is sent from `forget(id)`, and when the host sees a cut id alive again (id reuse).
- **Client side:** `set_state` keeps the host's order. Cuts the client is missing are shown without a flying piece. Cuts the host dropped are put back: shader overrides reset, bones of baked bodies unhidden, caps dropped. The rest is then shown again. A body that is still alive on the client is cut once it dies, through the regular upkeep.
- **Per machine:** off shader or bones, cap shape, pieces and kid mode are each player's own. Kid mode on any machine still sends every line; a kid-mode machine records the cuts and shows them when kid mode goes off.
- **Wire content:** never sub-mesh ids, model names or bake ids. Every machine maps the root names onto its own bake (or has none).
- **Tested:** `zgo_test_cuts.lua` runs a host, then a client that replays the host's wire. The client compares its state with the host's and replays Q with an added and a removed cut. It also switches the client to bones, and runs a kid-mode client.

## 6. README text

BAKED MODELS, add after "...no noticeable FPS loss in a crowded base;":

```
  With a bake from version 1.7 three experimental ways of drawing a cut
  can be tried on the Dismemberment page (each player's own, all off by
  default; save first, and run probe 1 on the Diagnostics page before the
  first one):
    Cut with the off shader   a part is switched off by ZGO's own shader
                              instead of hiding its bones: it goes at once,
                              before the body has fallen, and the joint
                              above it never pinches
    Stump cap shape           the bake's cap for that cut (flesh and a bone
                              stub shaped like the wound) instead of a meat
                              disk; or the caps inside the model (bake with
                              --experimental-caps, needs the off shader)
    Light severed limbs       a flying limb is the bake's piece (only the
                              part that came off, with a closed end)
  Bodies whose model another mod replaced, or a bake from before 1.7, are
  drawn the old way.
```

SETTINGS, in the "Dismemberment" line of the page list:

```
    Dismemberment   heads, limbs, mutants, shooting bodies, chance, severed
                    limbs, gibs, stump caps and their shape, full gibbing,
                    baked models, cutting with the off shader, light
                    severed limbs
```

LIMITS, append to the ragdoll bullet after "...re-applied from this mod's save data.":

```
    With "Cut with the off shader" (experimental) a baked part is switched
    off by a shader at once, and its bones are hidden only once the ragdoll
    exists, so the joint never pinches.
```

LIMITS, replace the "Severed limbs are the victim's own model..." bullet's first sentence with:

```
  * Severed limbs are the victim's own model with everything but the limb
    collapsed into the stump (or, with "Light severed limbs" and a 1.7
    bake, the bake's piece of that limb), as level script attachments,
```

CHANGES bullet:

```
  1.7.0  Experimental, off by default: cuts drawn with ZGO's off shader
         (no pinched joints, no waiting for the ragdoll), stump caps fitted
         to the cut from the bake, caps inside the model, light severed
         limbs from the bake's pieces. Both thighs now keep their stump
         caps. Co-op: bodies resync with one line per body.
```

## 7. In-game checks

Do these with a 1.7 bake installed, Debug log on, and a save made first. Run probe 1 (Off shader) on the Diagnostics page before check 1.

1. **Off-shader cuts, fresh kills** (`offshader_cuts` on). Kill NPCs with shots that take a forearm, a thigh and a head.
   - Each part and its shadow must vanish in the frame of the kill, before the body falls.
   - The elbow, knee or neck stump must not stretch or pinch while the body falls and lies.
   - The ragdoll must behave normally: the remaining limbs flop as before.
2. **Off-shader cuts, corpses.** Shoot a lying body until a limb comes off: same results as check 1. Then shoot where the missing limb was. No blood spray and no blood mark may appear in thin air: the bones are hidden once the ragdoll exists.
3. **Kept up.**
   - Save and load: the parts stay off and nothing falls again. Probe 5 should pass; see R3.
   - Walk more than ~200 m away until the bodies go offline, then come back: still cut.
   - Toggle kid mode on and off: bodies whole, then cut again.
   - Untick the option with cut bodies in view: they stay cut (now by bones).
4. **Another mod's model.** If a body's log line says "the game loaded N sub-meshes, the bake has M", that model must be cut the old way, without errors.
5. **Fitted caps** (`cap_style` = Fitted to the cut).
   - Cut a forearm, both thighs and a head off bodies. A flesh cap with a bone stub must close each stump with no gap, both thighs included.
   - Drag a body around (or let it slide): the cap must stay on the seam.
   - Cut the same arm higher up: the elbow cap goes, a shoulder cap comes.
   - Then try "Fitted, fixed to the joint": the same, possibly with a small gap while the joint is bent.
   - The log must not say "no bone_callback(bone, bone, true)". If it does, the engine lacks the named overload, and the caps are rigid.
6. **Caps inside the model** (a bake made with `--experimental-caps`, `cap_style` = Inside the model, off shader on). Same cuts as check 5. The cap must be raw flesh, appear only after the cut, and switch off when the cut moves up the limb.
7. **Light severed limbs** (`baked_pieces` on).
   - Shoot an arm off: the flying arm must start exactly where the arm was and look like it, with a closed end and no stretched skin.
   - Shoot a hand off first, then the forearm: the flying forearm has no hand.
   - No "limb piece ... could not be attached" in the log.
8. **Co-op** (host and one client, same bake).
   - Host with the off shader and client without, then the other way round: both see the same parts missing.
   - Probe 6: see R3; until then a shader mismatch between machines using different methods is expected.
   - A client that joins after cuts were made sees them within 20 s.
9. **Performance.** In a base with ~20 cut bodies in view, FPS must not drop with `offshader_cuts` on. It costs one `get_shaders` per body every 2.5 s.

## 8. Risks and open questions

- **The window before the ragdoll.** An off-shader cut keeps the part's bones visible for the 1-2 frames before the ragdoll is built. During that window, bullets can hit the invisible part and wallmarks can land on it. In 1.6 the same window showed the part itself, so this is no worse.
- **Untested in game.** Everything here relies on engine paths read from source but not seen in game. Each sits behind an experimental option that is off by default:
  - `zgo\off` set from a script on skinned children;
  - the named `bone_callback(name, name, true)` overload on object attachments, and its Mode B render path (`script_attachment::Render` uses the owner's XFORM when bone 0 is bound to a parent bone);
  - piece models as level attachments with a function callback on bone 0.
  A broken shader compile closes the game, so probe 1 must be run first.
- **Other mods that also call `set_shader` on NPC bodies.** None known in GAMMA; 3DSS touches weapons only.
  - This mod only touches the child ids it owns, and resets only those.
  - A mod that periodically resets *all* shaders on bodies would make cut parts flicker back for up to 2.5 s.
- **`loaded_matches` compares counts only.** Another model with exactly the bake's sub-mesh count would pass. This is unlikely; probe 9 compares more.
- **Mixed methods in co-op are fine for gameplay but trip probe 6** until R3 lands.
- **Q replaces the per-cut D rebroadcast.** A partner on 1.6 with the same PROTO would miss the resync, which is why R1 asks for the PROTO bump.
- **Visual change on a corpse** (outfit swap scripts) drops the view and re-cuts on the new model. Bones this mod hid on the old model are not unhidden; the engine gives the new visual a fresh mask anyway. Not seen in the mock.
- **Open question:** is `get_shaders` on a body with hidden bones complete in the real engine, including `children_invisible`? The source says yes. If it were not, `loaded_matches` would fall back to bones on cut bodies only, which is safe.
