# Umbra Effects mesh baker

Rebuilds every character / mutant model the game would load so that each
severable section (the cut roots in `zgo_tables.script` limb_map: head, upper
arm, forearm, hand, thigh, calf, foot, and the mutant equivalents) is its own
sub-mesh. Writes the models into this mod's own folder (`gamedata/meshes/...`)
with four generated scripts read by `zgo_bake.script`:

- `zgo_bake_index.script`   which models are baked, and their sections
- `zgo_bake_parts.script`   sub-mesh ids, stump caps and limb pieces per section
- `zgo_bake_wounds.script`  wound sites per section, bind poses
- `zgo_bake_inputs.script`  what the bake was made from, with one fingerprint
                            (the in-game bake check and the co-op handshake compare it)

Since 1.7 it also writes, at their own paths and loaded only when the runtime
asks for them:

- fitted stump caps   `gamedata/meshes/zgo/baked/caps/<h2>/<h12>.ogf`
- limb pieces         `gamedata/meshes/zgo/baked/pieces/<h2>/<h12>.ogf`
- body gibs (1.7.1)   `gamedata/meshes/zgo/baked/gibs/<h2>/<h12>.ogf`: one per
                      model, the pieces a blast tears out of it (docs/formats/gibs.md)

Since 1.8.2 the caps, pieces and gibs (about 79,000 files for G.A.M.M.A.) are packed
into engine archives, `db/mods/zgo_bake_<caps|pieces|gibs>_NN.db0` (at most 512 MB
each, like Anomaly's own; `xdb_write.py`), because the game indexes every loose file
of every mod through MO2 at each start: about a minute per 100,000 files under
Proton. The game mounts them at `gamedata\` like any `db/mods` archive, so the paths
above are unchanged. The body models stay loose: they must win over other mods'
loose copies, and the game prefers any loose file to an archived one. `--loose`
skips the archives; `--pack` packs a bake made before 1.8.2 in place.

The baked models themselves are the same as before: caps, pieces, gibs and sites
never change them. Every file it writes is listed in `zgo_bake_report.json` at the
mod root ("packed" lists what each archive holds); a re-run or `--remove` deletes exactly those files, and it refuses to
overwrite anything it didn't write. Builds in `~/.cache/zgo_baker/building-*`
(`%LOCALAPPDATA%\zgo_baker` on Windows), then moves the files in.

    python3 bake.py                   # whole library: about 160 s, 7.2 GB on G.A.M.M.A
    python3 bake.py --remove          # delete everything a bake wrote
    python3 bake.py --only stalker_bandit --out /tmp/test
    python3 bake.py --no-pieces       # skip the limb pieces (3.2 of the 7.2 GB)
    python3 bake.py --no-gibs         # skip the body gibs (650 MB; explosions throw meat models)

Experimental (off by default; see docs/formats/caps.md and damage.md, and
`docs/integration/baker2.md` for the in-game checks they need first):

    python3 bake.py --experimental-caps     # K_s caps inside every model, shader zgo\off
    python3 bake.py --experimental-damage   # D_s damage meshes inside every model + gib chunks

`dev/package.py` builds the release zip without any of these files (each
player bakes for their own mod list). A GUI drives the same code through
`bake.bake(options, progress, cancel)`; see `docs/formats/bake-api.md`.

Needs Python 3 + numpy. Players use Umbra Effects Setup (tools/zgo_setup), which runs this baker.
ZGO_BAKER_CACHE=DIR moves the work folder (it needs as much free space as the bake).

- `bake.py`       library API + command line: resolve, bake in parallel, scripts, install, manifest
- `ogf.py`        OGF reader/writer (skinned models; layouts from xray-monolith Fmesh.h / bone.h),
                  plus skeleton-model building for caps / pieces / chunks
- `partition.py`  the split: each triangle goes to the section of the lowest common
                  ancestor of the bones its vertices really use (weight > 0.0025);
                  padding references with no weight are pointed at the main bone
- `caps.py`       seam loops and fitted caps (rim = seam, bulge, ragged lip, bone stub)
- `parts.py`      cap and piece attachment models, K_s sub-meshes, content names
- `wounds.py`     wound sites, thickness, tissue hints, bind poses, their encoding
- `gibs.py`       body gibs: torn pieces of each model, clipped to an outline, flesh underneath
- `damage.py`     (experimental) D_s subdivision with UV codes, gib chunks
- `luagen.py`     writes the generated scripts
- `resolve.py`    MO2 winning file per model (modlist.txt, top wins), then base archives
- `xdb.py`        Anomaly .db archive reader (LZHUF file list, LZO data)
- `unpack_base.py` extracts base-game actor / monster models to the cache
- `limbs.py`      cut roots per creature kind, read from zgo_tables.script (a small Lua table reader; no
                  LuaJIT needed)

Tests: `python3 -m unittest discover -s tests/baker` (synthetic character,
no game files needed) and `luajit tests/zgo_test_baker2.lua` (the Lua
accessors against `tests/baker/fixtures`, regenerated with
`python3 tests/baker/fakemo2.py --fixtures`).

Why: `CSkeletonX::has_visible_bones()` drops a sub-mesh once none of the bones
its vertices reference are visible. Hiding a bone on an active ragdoll does not
move it (the physics writes its matrix), but its sub-mesh still disappears.
