# Body gibs (`gamedata/meshes/zgo/baked/gibs/`, since 1.7.1)

The pieces an explosion or a head burst tears out of a body, cut from that
body's own model by the baker (`tools/zgo_baker/gibs.py`). They carry the
model's own clothes, skin or fur on top and ZGO's flesh texture underneath.

## The model

One skeleton model (`MT_SKELETON_RIGID`, no motions) per baked model, content
named like caps and pieces: `zgo\baked\gibs\<h12[1..2]>\<h12>`.

- Bone 0 `zgo_gibs` is the root and holds no geometry.
- Bone `i` (`gib_i`, i = 1..N, N ≤ 14) holds piece i, every vertex 100%
  weighted to it.
- Each piece is stored in its own frame: origin halfway down the piece, +z
  along the surface normal at its centre.

The runtime shows one piece per level attachment: every other `gib_*` bone is
hidden (`CSkeletonX` drops a sub-mesh whose bones are all hidden), and the
piece's bone is driven with `bone_callback`.

## How a piece is cut

For up to 14 of the model's wound sites (`wounds.bake_sites`), chosen far
apart: farthest-point order from the site nearest the middle of the body. Hand
and foot sections (`wounds.section_class` "end") give none.

1. The outline: a convex, 9-cornered torn shape of radius 5-8.5 cm in the
   site's tangent plane, its noise seeded from the site, so every machine
   bakes the same bytes.
2. The top: every non-glass triangle of the site's section that faces out
   there (normal · n ≥ 0.2) and lies between the flesh depth below and
   3 cm above the surface. Each is clipped exactly to the outline, with
   positions, normals, tangents and UVs interpolated. Corners shared by
   neighbouring triangles stay shared.
3. Loose bits whose flat area is under 8% of the outline are dropped (strap
   ends, pouch corners). A piece covering less than 30% of its outline is not
   made.
4. Flesh: walls from every open top edge down to a floor 2-5 cm deep (0.65
   of the outline's width), closed by a fan. An open edge is one with no top
   surface of any layer just outside it, so holes and under-layers get no
   walls. Texture: `zgo\wounds\stump` over `caps.FLESH_BOX`.

## `zgo_bake_parts.script`

The body section's token gets `/b:<h12>.<g>`, and the file a list `gibsets`:

```lua
gibsets = {
	"bip01_spine1,0,9998,12,-170,40,52,-1210,834;bip01_head,0,...",   -- one entry per distinct set
}
```

Entry `g` lists piece 1..N in order as `bone,0,qw,qx,qy,qz,cx,cy,cz`:

- `bone`: the body's bone the piece came from;
- `qw..qz`: the piece frame's rotation in that bone's bind frame, a unit
  quaternion x10000;
- `cx..cz`: the piece frame's origin in the same frame, in 0.1 mm.

This is the bind-pose format of `zgo_bake_wounds.skels`, so
`zgo_bake.decode_skel` reads it. Older readers ignore the tag and the list.

## Runtime (`zgo_bake.gibs(obj)`, `zgo_debris.spawn_gibs`)

`zgo_bake.gibs(v)` returns `{ model, count, pieces = { [i] = { bone, m = { i, j, k, c } } } }`,
decoded once per model.

`spawn_gibs(pos, dir, count, body, seed, opts)` uses the body's pieces when
all of these hold:

- MCM "Gib look" is not "Meat models";
- the body is a creature with a set;
- `loaded_matches` is not false;
- the file exists.

How it throws them:

- **Which pieces:** it takes `count` pieces nearest `pos` (or from
  `opts.prefer` bones first: wound chunks pass their section's site bones),
  with a little seeded shuffling, and pieces already thrown from that body
  last.
- **Placement:** each starts at `bone_transform(bone) * m`, exactly where it
  was on the body.
- **Flight:** each flies as a stick body ("limb" item, `chunk = true`).
- **The rest:** anything still short of `count` is meat.

It returns the piece list. The co-op line carries it:
`G|x|y|z|dx|dy|dz|n|body|seed|pieces` (`"3,7,1"`, `"-"` = none). A client
throws exactly those pieces; a 10-field line from an older host lets the
client choose.

## Size and time (full G.A.M.M.A. bake, 4790 models)

- 54,500 pieces in 4526 files: 657 MB.
- Average 11.4 pieces per model, about 190 KB per file.
- The parts script grows from about 3.0 to 3.76 MB.
- The bake takes 158 s instead of about 100 s.
