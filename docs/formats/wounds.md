# Wound sites and bind poses: `zgo_bake_wounds.script`

Wound sites are points on a model's surface where damage gathers. The runtime maps a hit to the nearest site of the hit section and grows the wound there; the stage is the runtime's business. The baker makes them for every baked model, and `--no-wounds` turns them off.

The generator lives in `tools/zgo_baker/wounds.py`. It is deterministic and uses no random numbers.

## Placement

- **Candidates.** Every distinct vertex of the section (welded at 0.1 mm) plus every triangle centroid. Glass sub-meshes are skipped: a shader or texture matching `window|glass|transparent|selflight|lens|visor`.
- **Count.** Count = round(section area / per-site area), clamped per class:

| Class (by the section root's name) | Sites | m² per site |
|---|---|---|
| `body` (torso, never severed) | 12–20 | 0.035 |
| head: `head`, `neck`, `ponytail`, `jaw`, `skull`, or root `bone01` | 4–6 | 0.012 |
| upper limb: anything else (thigh, upper arm, ...) | 2–4 | 0.03 |
| lower limb: `forearm`, `calf`, `shin`, `leg_1`, `lower` | 1–2 | 0.035 |
| end: `hand`, `foot`, `toe`, `paw`, `finger`, `horselink`, `hoof` | 1 | 0.05 |

  Small sections can end up with fewer sites than the minimum, because spacing wins.
- **Spread.** Farthest-point sampling starts from the candidate nearest the centroid and stops early once the next point would be closer than **8 cm** (`MIN_SPACING`). Up to 6 Lloyd steps follow, each snapping a site to the candidate nearest its cell's centroid. Finally, any site that ended closer than 8 cm to an earlier one is dropped.
  - On the stock models, torso sites end up 10–15 cm apart.

## Per site

| Field | Meaning |
|---|---|
| `bone` | the bone with the largest weight at the site (a bone id in the file; `bone` is the name and `bone_id` the id once decoded). It always lies in the site's section. |
| `pos` | bind-space position, in metres. Stored in mm. |
| `normal` | outward unit normal: the vertex normal, or the face normal for a centroid. Stored ×100 and renormalised on decode. |
| `thick` | local thickness: a ray from 1 mm inside the surface along −normal, up to the first surface that faces away from it, where the ray leaves the body (glass ignored). Exits closer than 15 mm (eyelids, mask layers) count only when there is no other. With no exit it is 2·depth, or 5 cm. Stored in mm. |
| `radius` | how far the site's patch reaches: the 90th percentile of distances in its Voronoi cell, clamped to 2–15 cm. |
| `depth` | distance from the site to its bone's shaft (origin → mean of the child origins), capped at `thick`. Stored in mm. |
| `hint` | tissue letters, below |

Tissue hints (first letter = what lies under the site; second letter, torso only = side):

| Letter | Meaning |
|---|---|
| `s` | skull (head, not the face) |
| `f` | face or jaw (head with the normal pointing forward, z > 0.55) |
| `n` | neck |
| `x` | extremity: hand, finger, foot, toe, paw |
| `l` | limb shaft (muscle around a long bone) |
| `c` | chest: ribs (spine1/2/3 and chest bones) |
| `a` | abdomen (lower spine, pelvis front) |
| `k` | back (torso with the normal pointing backward) |
| `h` | shoulder (clavicle or upper-arm area of the torso) |
| `p` | pelvis / hip |
| second letter `F` / `B` / `S` | front (normal z > 0.3) / back (z < −0.3) / side |

Hints come from bone names and the normal; they are hints, not anatomy. Models face +z.

## File layout

```lua
version = 1
bake_id = "..."                                  -- must equal zgo_bake_index.bake_id
names = { "bip01_head", ..., "body" }            -- section names, 1-based
skels = { "root_stalker,-1,10000,0,0,0,0,0,0;bip01,0,...", ... }   -- 1-based
sites = { "4,104,1904,39,100,-2,0,201,99,201,s;...", ... }        -- 1-based
models = { ["actors\\...\\x"] = "<skel> <sec>=<sites> <sec>=<sites> ..." }
```

- `skels[i]` lists the bind pose of every bone, in bone-id order, as `name,parent,qw,qx,qy,qz,cx,cy,cz;...`.
  - `parent` is a bone id, or −1 for the root.
  - `q` is the rotation as a unit quaternion ×10000, with `w ≥ 0`. It maps bone-local to model space (column vectors).
  - `c` is the origin in 0.1 mm.
  - Decoded, each bone is `{ name, id, parent, i, j, k, c }` with the X-Ray rows: `i = R·x̂`, `j = R·ŷ`, `k = R·ẑ`.
  - Bind-pose error after rounding: < 0.2 mm, < 0.02°.
- `sites[i]` is `bone,x,y,z,nx,ny,nz,thick,radius,depth,hint;...`, with mm values and the normal ×100.
- Equal skeletons and equal site lists are stored once: 402 skeletons and 8295 site lists for 4784 G.A.M.M.A models. A model line names one skeleton and one site list per section.

## Lua

```lua
local w = zgo_bake.wound_sites(npc)          -- { skel = {bones, by_name, count}, sections = {...} }
local list = zgo_bake.sites(npc, "body")      -- { {index, bone, bone_id, pos, normal, thick, radius, depth, hint}, ... }
-- a world hit point into bind space, then the nearest site:
local bm = zgo_bake.bind(npc, bone_name)      -- bind pose of that bone
local world = npc:bone_transform(bone_name)   -- its world matrix now (Fmatrix: i j k c)
local p_bind = zgo_bake.to_bind(bm, world, hit_pos)
local site, dist = zgo_bake.nearest_site(npc, section, p_bind)
```

`to_bind` computes P_bind = Bind_b · inverse(World_b) · P_world. World_b must be rigid. Use the bone that holds the hit: for a rigid bone, any bone of the section gives the same answer up to skinning blend.

Site indices (1-based, in file order) are what the experimental D_s UV codes and the gib chunk bones refer to ([damage.md](damage.md)).

## Size

The file is about 4 MB for the full G.A.M.M.A bake.

Anomaly loads every root script at game start. Measured with LuaJIT on the host, `zgo_bake_parts` and `zgo_bake_wounds` together load in about 40 ms and hold about 13 MB of strings; decoding happens per model on first use. See the integration note for the risk discussion.
