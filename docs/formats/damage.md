# (experimental) Damage meshes D_s and gib chunks

These files exist only with `bake.py --experimental-damage`. That flag is off by default. It adds sub-meshes to every baked model, and needs:
- the `zgo\off` and `zgo\dmg` shaders from the wounds workstream;
- the in-game probes in `docs/integration/baker2.md`.

It makes models about 10× larger: the bandit set grew from 6 MB to 73 MB. Do not ship it until the runtime uses it.

## D_s: damage meshes

For every baked sub-mesh `C` whose section has wound sites near it, the baker appends a copy `D`. The id pairs are in `zgo_bake.damage_ids(v, section)`: `{ [C id] = D id }`.

- Shader `zgo\off`, texture as `C`. It draws nothing until the runtime switches it on: `set_shader(C, "zgo\\off")`, then `set_shader(D, "zgo\\dmg", ...)`.
- Same surface as `C`:
  - every original vertex is kept, in the same order (ids 0..n−1 of `C` are 0..n−1 of `D`);
  - new vertices are exact midpoints, so positions stay on the original triangles and the mesh looks identical while undisplaced.
- **Subdivision.** Every triangle with a corner within **6 cm** of a site (`damage.PATCH`) is split by longest-edge bisection until none of its edges is longer than **1.5 cm**.
  - The split runs on the welded surface: a split edge is split in every triangle that shares it, across UV and normal seams, so nothing cracks.
  - New vertices interpolate normal, tangent, binormal and UV, and blend the bone weights of the two ends, keeping the top 4 and renormalising.
  - **Open-border edges are never split.** These are where `C` meets the next section's sub-mesh. Their vertices carry site code 0 and **must never move**: the neighbouring mesh has the same vertices.
  - Slivers (height under 1 mm) are split only as neighbours, never on their own.
- Bones stay inside the section's subtree, as for `C`.

### UV integer codes

The integer part of the UV is free: the samplers use WRAP, and the vertex shader receives the raw float. D_s stores two codes there:

```
u' = u + 4 · site      site  = 1-based index into the section's site list (wounds.md);
                               0 = outside every patch, or on the open border (never move)
v' = v + 4 · thick     thick = local thickness under the vertex in 2 mm steps, 0..255 (0..510 mm)

decode (vertex shader):  site  = floor((u' + 1.5) / 4)
                         thick = floor((v' + 1.5) / 4) · 0.002 m
                         uv    = (u', v') unchanged for texture lookups
```

- This needs the original `u, v` within [−1.5, 2.5). The baker first moves each sub-mesh's UVs by a whole number of tiles to fit. A sub-mesh whose UVs span more than 4 tiles gets no D mesh.
- `thick` is the inward-ray thickness (as for sites) at each original vertex inside a patch, linearly interpolated at new vertices. Where no exit is found, the site's thickness is used.
- Float precision: |u'| < 1023, so the fractional UV keeps about 1/8192 precision.

The Python reference decoder is `damage.decode_uv(uv)`.

## Gib chunks

There is one model per (model geometry, section). Lua: `zgo_bake.chunks(v, section)` → `{ model, count }`.

- File: `gamedata/meshes/zgo/baked/chunks/<h2>/<h12>.ogf`.
- `MT_SKELETON_RIGID`, with bones:
  - bone 0 `zgo_chunks` (the root);
  - bones `site_1` … `site_<count>`, children of the root.
  - All binds are identity and there are no shapes.
- Site *i*'s chunk is weighted 100 % to bone `site_i` (bone id *i*). An empty site keeps its bone, with no geometry.
- **Chunk *i* geometry:**
  - the skin within `clamp(0.6·radius, 2.5 cm, 6 cm)` of the site, copying the victim's sub-meshes (texture, shader, UV);
  - side walls from the patch border down to a floor `clamp(0.6·thick, 1 cm, 4 cm)` below the surface, shrunk to 55 % toward the site axis;
  - a fan floor, in `food\food_raw_flesh` / `models\model`.
- **Frame:** chunk *i*'s vertices are in the victim's bind frame of the site's bone `b`, stored as inverse(Bind_b) · P_bind.
  - Placed at World_b (the victim's world matrix of `b`), a chunk sits exactly where its patch is on the victim.
  - To show one chunk, hide the other `site_*` bones (or the root and re-show one bone, as the engine allows) and place the model at World_b.
