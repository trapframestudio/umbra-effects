# `zgo_bake_parts.script`

This script lists, per model and section:
- the sub-mesh ids;
- the stump cap;
- the limb piece;
- the experimental extras.

Read it through `zgo_bake.parts(v)` and the per-field accessors. Do not parse it yourself.

```lua
version = 1
bake_id = "..."                      -- must equal zgo_bake_index.bake_id

names = { "body", "bip01_head", ... }               -- section names, 1-based
bonesets = { "bip01_neck bip01_head", ... }         -- cap skeletons, bone 0 first, 1-based
gibsets = { "bip01_spine1,0,9998,...;...", ... }   -- body gib pieces (gibs.md), 1-based

models = {
	["actors\\stalker_bandit\\stalker_bandit1a"] = "1:1,3/-/- 2:2,10/d38fdfaf8ca7.1/ba12ffc74615 ...",
}
```

## One model's line

The line is a space-separated list of tokens, one per section:

```
<sec>:<ids>/<cap>/<piece>[/k:<ids>][/d:<c>=<d>,...][/g:<chunk>x<n>][/b:<gibs>.<g>]
```

| Field | Meaning |
|---|---|
| `<sec>` | index into `names` |
| `<ids>` | comma-separated `set_shader` ids (OGF child index + 1) of this section's own sub-meshes. Child sections are not included: the head's ids don't include anything else, and the thigh's don't include the calf. |
| `<cap>` | `<h12>.<b>`: the stump cap left on the body when this section comes off. The file is `zgo\baked\caps\<h12[1..2]>\<h12>` and its skeleton is `bonesets[b]`. `-` means none: `body`, a root with no parent, or a seam that could not be found. |
| `<piece>` | `<h12>`: the limb piece, file `zgo\baked\pieces\<h12[1..2]>\<h12>`. `-` means none. |
| `k:` | (experimental caps) ids of the K_s sub-meshes (face, then stub) that close this section's stump inside the model. They start with shader `zgo\off`. |
| `d:` | (experimental damage) `C=D` pairs. Sub-mesh `C` of this section has the damage mesh `D`. |
| `g:` | (experimental damage) gib chunk model `zgo\baked\chunks\<h2>\<h12>` with `n` chunks (one per wound site of the section). |
| `b:` | (1.7.1, body section only) body gibs: model `zgo\baked\gibs\<h2>\<h12>`, pieces listed in `gibsets[g]` (see gibs.md). |

## Decoded (`zgo_bake.parts(v)[section]`)

```lua
{
  kids  = { 2, 10 },
  cap   = { model = "zgo\\baked\\caps\\d3\\d38fdfaf8ca7", parent = "bip01_neck",
            bones = { "bip01_neck", "bip01_head" } },          -- nil if none
  piece = { model = "zgo\\baked\\pieces\\ba\\ba12ffc74615", root = "bip01_head" },   -- nil if none
  kcap  = { 29, 30 },            -- nil unless experimental caps
  dmg   = { [2] = 44, [10] = 52 },   -- nil unless experimental damage
  chunks = { model = "zgo\\baked\\chunks\\a4\\a48dd3222137", count = 6 },            -- nil unless experimental damage
  cap_hash, piece_hash, chunk_hash, chunk_count,             -- raw fields
}
```

Lines are decoded on the first call for a model and cached; `zgo_bake.reset()` clears the cache.

Size on the full G.A.M.M.A bake: about 3 MB (4784 models, 255 bone sets). A load of this script with the wounds script is measured in `docs/integration/baker2.md`.
