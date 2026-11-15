# Limb pieces

A limb piece is the part that comes off at section root `s`, built as its own small model. It contains:
- the sub-meshes of `s` and of every section below it, for example thigh + calf + foot;
- a fitted cap closing its open end.

One piece is written per model and section, content-named and deduplicated. The old way of dropping limbs (spawning the full victim model with bones hidden, in `zgo_debris`) keeps working, because the new files sit at their own paths.

- File: `gamedata/meshes/zgo/baked/pieces/<h2>/<h12>.ogf`.
- Engine name: `zgo\baked\pieces\<h2>\<h12>`.
- Lua: `zgo_bake.piece(v, section)` → `{ model, root }`, where `root == section`.

## OGF layout

- `MT_SKELETON_RIGID` (10), with the same chunk set as the caps (`HEADER`, `S_DESC`, `CHILDREN`, `S_BONE_NAMES`, `S_IKDATA`).
- Bones:
  1. Bone 0 is `s`. It is the root, with an **identity bind** and the victim's shape and OBB.
  2. Then every other bone of `s`'s subtree, in victim bone-id order. Names, parents, local binds, shapes, OBBs, mass and joint data are copied verbatim.
- The skeleton is at most 64 bones; a larger subtree gets no piece.
- Children:
  - first, the victim's baked sub-meshes for each section in the subtree, in the model's order, with texture, shader and vertex format unchanged;
  - then the end cap: face (`food\food_raw_flesh`), then stub (`act\act_skeleton`), both `models\model`.
- A piece keeps one sub-mesh per section. If the runtime hides a bone below `s` (a second cut on the dropped limb), the engine drops that section's sub-meshes just as on the body.

### The frame (exact)

- Piece bind(b) = inverse(Bind_s) · Bind_b.
- Vertices are stored as inverse(Bind_s) · P_bind, so the piece's model space is `s`'s bind frame.

## Posing it like the victim's limb

Place the attachment or object at World_s (the victim's world matrix of `s` at the moment of the cut). Bone 0 then needs no correction.

For the other bones, this is what `zgo_debris` does today: give each bone `b` a callback that returns inverse(XFORM_piece) · World_b(victim), the world bone matrix relative to the piece. The piece then matches the victim's limb exactly. `tests/baker/test_geometry.py` checks this in random poses.

With no callbacks, the piece shows the limb in its bind pose, relative to `s`.

The end cap's rim copies the seam's weights. If a seam also follows bones above `s` (rare), those weights are moved to `s`, since the piece has no other bones.

Bone shapes come from the victim. A runtime that wants physics on the piece can use them as they are; the piece is light and has no motions.
