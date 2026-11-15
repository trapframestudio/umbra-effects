# Baked models and `zgo_bake_index.script`

## Baked models

The baker writes `gamedata/meshes/<source path>.ogf` for every actor and monster model the game would load: the MO2 winner, otherwise the base archives. The skeleton, motions references, user data and every other chunk are copied unchanged. Only `OGF_CHILDREN` is rebuilt:

- Each source sub-mesh is split by section. A triangle goes to the section of the lowest common ancestor of the bones its vertices really use (weight > 0.0025).
- A section is a cut root (the bones in `zgo_tables.script` `limb_map`) or `body` (everything else).
- The children come in source order. Within each source sub-mesh, `body` comes first, then the cut roots by bone id.
- Every triangle is kept, and the format, texture and shader are unchanged. Unused bone slots point at the vertex's main bone.

The `set_shader` id of a child is its index + 1. `zgo_bake_parts` lists the ids of each section ([parts.md](parts.md)).

With `--experimental-caps` / `--experimental-damage`, extra children (K_s, D_s) are appended **after** these. The model's own ids do not change.

## `gamedata/scripts/zgo_bake_index.script`

```lua
version = 2
bake_id = "20261113-150000-1a2b3c4d"
features = { caps = true, damage = false, kcaps = false, pieces = true, wounds = true }

local S1 = { bip01_head = true, bip01_l_calf = true, ... }   -- shared section sets

models = {
	["actors\\stalker_bandit\\stalker_bandit1a"] = S1,          -- lower case, '\', no .ogf
	...
}
```

- `models[visual]` is the set of section roots that are separate sub-meshes in that model. This is the same shape as 1.4–1.6, and `zgo_bake.info / has_section / is_baked` read it.
- `bake_id` is the bake's time plus a hash of the inputs and options. It ties this file to `zgo_bake_parts` and `zgo_bake_wounds`.
- `features` says what the bake made. `kcaps` = `--experimental-caps`, `damage` = `--experimental-damage`.
- Before 1.7 there was no `bake_id` and no `features`. `zgo_bake.features()` then reports everything as `false`.

Size: about 290 KB for the full G.A.M.M.A list.
