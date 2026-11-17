# ZGO bake formats

Everything the mesh baker (`tools/zgo_baker/bake.py`) writes, and how the runtime reads it.
Three other workstreams build on these files:
- **setup** drives the bake from a GUI;
- **cuts** attaches caps and pieces;
- **wounds** reads the wound sites and draws damage.

Treat every field below as a contract. A change bumps the file's `version`.

| Output | Path (inside the output folder, normally this mod) | Default | Format |
|---|---|---|---|
| Baked models | `gamedata/meshes/<same path as the source>.ogf` | on | [index.md](index.md) |
| Index | `gamedata/scripts/zgo_bake_index.script` | on | [index.md](index.md) |
| Parts table | `gamedata/scripts/zgo_bake_parts.script` | on | [parts.md](parts.md) |
| Stump caps | `gamedata/meshes/zgo/baked/caps/<h2>/<h12>.ogf` | on (`--no-caps`) | [caps.md](caps.md) |
| Limb pieces | `gamedata/meshes/zgo/baked/pieces/<h2>/<h12>.ogf` | on (`--no-pieces`) | [pieces.md](pieces.md) |
| Wound sites and bind poses | `gamedata/scripts/zgo_bake_wounds.script` | on (`--no-wounds`) | [wounds.md](wounds.md) |
| K_s cap sub-meshes inside each model | (inside the baked models) | off (`--experimental-caps`) | [caps.md](caps.md#k_s-experimental) |
| D_s damage sub-meshes inside each model | (inside the baked models) | off (`--experimental-damage`) | [damage.md](damage.md) |
| Gib chunks | `gamedata/meshes/zgo/baked/chunks/<h2>/<h12>.ogf` | off (`--experimental-damage`) | [damage.md](damage.md#gib-chunks) |
| Manifest | `zgo_bake_report.json` (output root) | always | [bake-api.md](bake-api.md#the-report-manifest) |

The library API that the setup GUI calls is documented in [bake-api.md](bake-api.md).

Not a bake output, but the same archive format: the mod's own textures ship in `db/mods/zgo_static.db0`, described in [static.md](static.md).

## Rules that hold for every output

- **The default bake leaves the models as they were.** Splitting into sections is all a default bake does to a model. With the default options, every baked model is byte-identical to a 1.6 bake (`tests/baker/test_bake.py` checks this). Caps, pieces and sites are separate files that nothing loads until the runtime asks for them. Only the experimental flags add sub-meshes (K_s, D_s) to the models, and those sub-meshes come after the model's own.
- **Content-named files.** A cap, piece or chunk file is named by the first 12 hex digits of the SHA-1 of its bytes (`<h12>`). It sits in a folder named after the first two of those digits (`<h2>`). Identical files from different models are therefore written once.
  - The engine model name is `zgo\baked\caps\<h2>\<h12>`, with no `.ogf`. That is what `add_attachment` takes.
- **Everything is listed in the manifest.** Every file a bake writes appears in `zgo_bake_report.json` → `files`. A re-bake, `bake.py --remove` and `dev/package.py` work from that list.
- **One `bake_id` per bake.** The id appears in all three generated scripts. If the parts or wounds script carries a different `bake_id` from the index, `zgo_bake.script` ignores it and logs this once.
  - An index from before 1.7 has no `bake_id`. Its models still count as baked, but they have no parts and no sites.
- **Generated scripts load at game start.** Anomaly loads every root script when the game starts (`axr_main.on_game_start` → `_G[name]`). So each big table is a flat list of strings that is decoded on first use and cached per model.
  - Measured on the full G.A.M.M.A bake: see `docs/integration/baker2.md`.
- **Spaces.** "Bind space" means the model's own space in its bind pose: what the OGF vertices store, and what the vertex shader receives.
  - Matrices are X-Ray `Fmatrix` objects, rows `i j k c`: a point maps as `p' = x·i + y·j + z·k + c`.
  - In Python (`ogf.py`) the same transforms are 4×4 matrices for column vectors.

## Runtime accessors (`gamedata/scripts/zgo_bake.script`)

Every accessor takes a game object or a visual name. In the name, `/` or `\` both work, case does not matter and a trailing `.ogf` is ignored.

An accessor returns `nil` in three cases:
- no bake exists;
- the model is not baked;
- the MCM switch *Dismemberment → Use baked models* is off. Pass `raw = true` as the last argument to ignore the switch.

| Call | Returns |
|---|---|
| `is_baked(v)`, `info(v)`, `has_section(v, root)`, `count()` | as in 1.4–1.6 (index) |
| `bake_id()`, `features()` | the bake's id; `{caps, pieces, wounds, kcaps, damage}` booleans |
| `parts(v)` | `{ [section] = entry }`, see [parts.md](parts.md) |
| `submeshes(v, section)` | `set_shader` ids of the section's own sub-meshes |
| `cap(v, section)` | `{ model, parent, bones }`, see [caps.md](caps.md) |
| `piece(v, section)` | `{ model, root }`, see [pieces.md](pieces.md) |
| `kcap_ids(v, section)` | (experimental) ids of the K_s sub-meshes |
| `damage_ids(v, section)`, `has_damage_mesh(v, section)` | (experimental) `{ [C id] = D id }` |
| `chunks(v, section)` | (experimental) `{ model, count }` |
| `wound_sites(v)` | `{ skel, sections = { [section] = { site, ... } } }`, see [wounds.md](wounds.md) |
| `sites(v, section)`, `nearest_site(v, section, p_bind)` | one section's sites; the nearest site and its distance |
| `bind(v, bone)`, `to_bind(bind, world, p)` | a bone's bind pose; a world point taken into bind space |
| `decode_parts`, `decode_skel`, `decode_sites`, `reset` | decoders (for tools and tests); cache reset |

"section" is a cut-root bone name (`bip01_head`, `bip01_l_thigh`, ...) or `body`, which means everything outside the cut roots.
