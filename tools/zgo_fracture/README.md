# Umbra Effects fracture baker

Cuts the physics props your mod list actually loads into pieces. When one of
these props breaks in the game (zgo_props, "Objects break apart"), it comes
apart into these pieces.

- **Barrels, milk cans, bottles:** Voronoi shells, each with a thin inner face.
- **Small crates and stools:** planks cut across each face.

The tool reads the winning model for each prop: MO2 priority first, then the
game's archives. With G.A.M.M.A. the barrels come from IXRTR. It writes into
this mod's own folder:

| File | What it is |
|---|---|
| `gamedata/meshes/zgo/props/fracture/*.ogf` | one-bone piece models, in the source model's space |
| `gamedata/scripts/zgo_props_fracture_index.script` | which pieces belong to which model |
| `zgo_fracture_report.json` | every file written |

Running it again, or with `--remove`, deletes exactly the files the report
lists. It never overwrites a file it didn't write.

These files are derived from your own game files. They are never shipped:
each player bakes their own.

Without a bake, crates, stools and bottles still break, into the game's own
parts (the "kit-bash" rigs in `zgo_props_data.script`). Barrels and cans only
break once they've been baked.

    python3 fracture.py                      # about 5 s
    python3 fracture.py --only bochka        # just the barrels
    python3 fracture.py --remove
    python3 selftest.py                      # synthetic meshes, no game files

## Experimental: `--experimental-native` (off by default)

This also writes copies of the crate and stool models at their stock paths
(`gamedata/meshes/dynamics/...`). Each copy gets model data
(`gamedata/configs/models/objects/zgo_props_*.ltx` plus a `[destroyed]` list
of the baked pieces), so the game breaks those objects itself: by knife, by
bullets and by explosions.

- The model data applies only to objects the level spawned as
  `physic_destroyable_object`.
- Unverified in co-op, because the game spawns the parts as objects.
- Like the body bake's experimental flags, the setup GUI should show this as
  an "experimental" checkbox.
- The runtime reads `native` in the index and leaves those models to the
  game.

## Library use (the setup GUI)

    import fracture
    opts = fracture.default_options()        # MO2 folder / profile / game from MO2's config
    opts.experimental_native = False
    report = fracture.bake(opts, progress=fn, cancel=fn)
    fracture.remove(opts.out)

`progress(stage, done, total, message)` is called from the calling thread.
`stage` is one of `fracture.STAGES`.

If `cancel()` returns True, the bake stops before it touches the output
folder and raises `Cancelled`. Errors raise `FractureError`, with a message
meant for the player.

Needs Python 3 and numpy. It imports `ogf`, `xdb` and `resolve` (and
`bake.mo2_defaults`) from `tools/zgo_baker` without changing them.

## Files

- `fracture.py`: the bake (targets, sources, piece models, index, report) and its CLI.
- `cut.py`: the cutting itself (Voronoi cells, planks, triangle clipping, inner faces).
- `selftest.py`: checks on synthetic meshes.
- `assets/`: developer generators for files that ship with the mod:
  - `gen_props_models.py` writes `zgo_props_models.script`, the boxes, masses and materials of the base game's prop models;
  - `gen_props_fx.py` writes `gamedata/particles/zgo/props/*.pe`;
  - `gen_props_textures.py` writes the puddle decals and `mod_system_zgo_props.ltx`.
