# Stump caps

A fitted cap closes the hole that a cut at section root `s` leaves in the body. Its parent bone is `p`, the parent of `s`.

The baker writes one cap per model and section. Identical seams in different models share one file (the files are content-named).

- File: `gamedata/meshes/zgo/baked/caps/<h2>/<h12>.ogf`.
- Engine name: `zgo\baked\caps\<h2>\<h12>`.
- Lua: `zgo_bake.cap(v, section)` → `{ model, parent, bones }`.

## Geometry

All geometry is built in the victim's bind pose.

- **Rim.** The rim is the seam itself: the boundary between the triangles of `s`'s subtree and the rest of the mesh. Rim vertices have the seam vertices' exact positions and the same cleaned bone weights. The cap therefore closes the hole without a gap and deforms with it.
- **Bulge.** Four interior rings at 16 / 40 / 64 / 86 % of the way to the centre make a dome. Its height is `clamp(0.22·r_mean, 4 mm, 3 cm)`.
  - Ring 1 is jittered (±9 % radial, −0.15…+0.3 of the height) into a ragged lip. The jitter is seeded from the seam, so equal seams give equal caps.
  - Interior weights blend from the rim's weights toward `p`, so the middle of the cap stays with `p`.
- **Bone stub.** A 7-sided jagged stub stands where the joint (`s`'s origin) projects onto the cap. Only the largest loop gets one.
  - Radius `clamp(0.2·r, 5 mm, 2 cm)`, length `clamp(0.45·r, 8 mm, 3.5 cm)`, with a sunken marrow end.
  - The stub is weighted 100 % to `p`.
- **Several loops.** A section can have several seam loops: mutant necks, for example, also cut the front legs. Each loop gets its own cap.
- **Fallback.** If a loop is not star-shaped even after smoothing the inner rings, it is ear-clipped flat. A loop under 4 mm in radius is not capped.
- **Orientation.** Faces point away from what remains, toward where the limb was (front face: `cross(b−a, c−a)` along the outward normal).

Textures: no new files are needed. Every Anomaly install has these.

| Sub-mesh | Texture | Shader | UV area |
|---|---|---|---|
| 0: face | `food\food_raw_flesh` (a raw-steak cross-section) | `models\model` | (0.15, 0.15)–(0.85, 0.85), planar |
| 1: stub (if any) | `act\act_skeleton` (pale skull region) | `models\model` | (0.02, 0.70)–(0.10, 0.76) |

A dedicated stump texture would look better. The wounds workstream owns `textures/zgo/wounds/**`, and swapping it in is a baker constant (`caps.FLESH_TEX`) plus a re-bake.

## OGF layout

- Model type `MT_SKELETON_RIGID` (10). This is CKinematics with no motions, because `add_attachment` R_ASSERTs `dcast_PKinematics` and `set_shader` needs a skeleton.
- Chunks: `HEADER` (bbox and bsphere of the vertices), `S_DESC`, `CHILDREN`, `S_BONE_NAMES`, `S_IKDATA`.
- Children: vertex format 1–4 links (`OGF_VERTEXFORMAT_FVF_*`), as many as the weights need.
- Bones, in order:
  1. Bone 0 is `p`. It is the root (empty parent), with an **identity bind** (rotation 0, position 0) and no shape.
  2. Then the bones on the paths from `s` down to every bone a cap vertex uses. They keep the victim's names, parents and **local binds verbatim**, with no shapes.
  3. Rarely, a seam is also weighted to a bone outside the limb (for example `bip01_spine2` on some neck seams). Such a bone becomes a child of `p`, with its bind relative to `p`.
- Each bone's OBB bounds the cap in that bone's frame.
- `zgo_bake.cap(v, s).bones` lists the bone names in file order, so `bones[1] == parent == p`.

### The frame (exact)

For every cap bone `b`, cap bind(b) = inverse(Bind_p) · Bind_b. Here `Bind_x` is the victim's bind-pose model-space matrix. So:
- the cap's model space **is** `p`'s bind frame;
- vertices are stored as inverse(Bind_p) · P_bind.

## Attaching

Use either mode. Both are exact; `tests/baker/test_geometry.py` checks them in random poses.

**Mode A (rigid):**
```lua
local c = zgo_bake.cap(npc, "bip01_l_thigh")
local att = npc:add_attachment("zgo_cap_l_thigh", c.model)
att:set_parent_bone(c.parent)       -- no position, rotation or scale offset
```

- Attachment XFORM = owner XFORM · bone_transform(p) · identity. A vertex lands at World_p · inverse(Bind_p) · P_bind.
- For vertices held by `p` alone, this is exactly where the victim's own skinning puts them.
- Rim vertices that are also weighted to bones below `p` follow `p` rigidly.
  - Stumps are small and `s`'s bones are hidden after the cut, so this is the cheap default.

**Mode B (follows the victim's skinning exactly):**
```lua
for _, b in ipairs(c.bones) do att:bone_callback(b, b, true) end   -- bone 0 too
```

- `bone_callback(bone, parent_bone, true)` copies the victim's model-space matrix for that bone. With bone 0 called back, the attachment XFORM becomes the owner XFORM (`script_attachment_manager.cpp`).
- Every cap vertex then skins as Σ w · M_b · inverse(capbind_b) · v. That equals Σ w · M_b · inverse(Bind_b) · P_bind, which is the victim's own seam.
- Not yet verified in game (see the integration note): the engine sources have the call, but the binding must be checked in the GAMMA build.

Hidden bones: after a cut the victim's `s` subtree bones are hidden. Their matrices collapse to the parent's origin (`SkeletonRigid.cpp`), and in Mode B any rim weight on them collapses too.

The runtime should therefore either:
- use Mode A, or
- in Mode B, call back only `bones[1]` and give the others the parent's matrix as well.

The rim vertices are on the body side of the seam, and the baker keeps their weights. Expect them to be weighted to `s`-subtree bones exactly like the body's own seam vertices, which also collapse when hidden. Mode A matches what the body does after the cut.

## K_s (experimental)

`--experimental-caps` also appends the same geometry to the baked model itself. `zgo_bake.kcap_ids(v, s)` gives the ids, face first and then stub.

- These sub-meshes are in the model's bind space and use the model's bone ids.
- Their shader is **`zgo\off`**, which draws nothing until the runtime calls `npc:set_shader(id, "models\\model", "food\\food_raw_flesh")` (or the zgo flesh shader) at the cut.
- They belong to the parent section (`p`'s section), so hiding `s` does not drop them.
- This needs the `zgo\off` shader that the wounds workstream ships. It also needs the in-game probe described in the integration note. Without the shader, every NPC would show its caps from the start, which is why the flag is off.
