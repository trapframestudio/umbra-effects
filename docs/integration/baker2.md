# Integration note: baker2 (bake library API, stump caps, limb pieces, wound sites)

## 1. Summary

The mesh baker (`tools/zgo_baker`) is now a library with a command line on top. On top of the baked models it now makes:
- fitted stump caps and limb pieces, as separate content-named attachment models;
- wound sites, with the bind poses they need;
- behind default-off flags, the K_s cap sub-meshes, the D_s damage meshes and the gib chunks.

`zgo_bake.script` gains accessors for all of it, and the old API is unchanged. `docs/formats/` documents every output and every table, field by field, for the **setup**, **cuts** and **wounds** workstreams.

### What a default bake now does

- **Library API.** `bake.bake(options, progress, cancel) -> report`.
  - Stages are reported in order: prepare, unpack, resolve, bake, scripts, install, done.
  - `cancel()` before `install` leaves the output folder untouched.
  - Errors raise `BakeError` / `Cancelled` with messages meant for players.
  - `bake.default_options()` reads the MO2 folder, profile and game path from `ModOrganizer.ini`, and turns Wine `Z:\` paths into Linux ones.
  - `bake.remove(out)` undoes a bake.
  - A lock file stops two bakes running into one folder.
  - The CLI keeps all its old flags and adds `--anomaly`, `--no-caps`, `--no-pieces`, `--no-wounds`, `--experimental-caps`, `--experimental-damage` and `--quiet`.
- **Baked models are unchanged.** All 4790 models from the default bake are byte-identical to the 1.6 bake that was installed. They were compared file by file before the 1.6 bake was replaced. A unit test also checks this.
- **Stump caps.** One per model and section: `gamedata/meshes/zgo/baked/caps/<h2>/<h12>.ogf`.
  - The rim is the seam itself, with its exact positions and weights.
  - Inside it: a bulge, a ragged lip and a bone stub.
  - Textures are ones every install has (`food\food_raw_flesh`, `act\act_skeleton`).
  - Each cap is a skeleton OGF whose bone 0 is the parent bone with an identity bind. It attaches either rigidly (`set_parent_bone`) or exactly (`bone_callback` per bone). The frames are in `docs/formats/caps.md`.
- **Limb pieces.** `gamedata/meshes/zgo/baked/pieces/<h2>/<h12>.ogf`: the section and everything below it, plus a capped open end.
  - Bone 0 is the cut root with an identity bind; the other bones are copied from the victim.
  - They pose exactly under today's `zgo_debris` callbacks.
  - The old way (spawning the full victim model) still works.
- **Wound sites.** `gamedata/scripts/zgo_bake_wounds.script`.
  - Sites are spread by Poisson-disk sampling at least 8 cm apart (10–15 cm on torsos). Counts: torso 12–20, head 4–6, upper limb 2–4, lower limb 1–2, hand/foot 1.
  - Each site has a bone, bind-space position and normal, inward-ray thickness, patch radius, bone depth and tissue hints.
  - Bind poses are stored per skeleton (quaternion plus origin).
- **Parts table.** `gamedata/scripts/zgo_bake_parts.script`: per model and section, the sub-mesh ids, the cap (file plus bone list) and the piece.

### Experimental (off, verified only offline)

- `--experimental-caps`: K_s sub-meshes inside every model, shader `zgo\off`.
- `--experimental-damage`: D_s meshes and gib chunks.
  - D_s are subdivided to edges of 1.5 cm or less within 6 cm of every site. The mesh stays watertight, open borders are never split, and UV integer codes carry the site and the local thickness.
  - Gib chunks are one model per section and one bone per site.

### Verified offline

- 27 Python unit tests in `tests/baker/` use a synthetic character and need no game files. They cover:
  - the OGF round trip;
  - cap rims equal to the seam;
  - cap Mode A and Mode B skinning against the victim in random poses;
  - pieces posed like the limb;
  - site counts, spacing, thickness, determinism and encoding;
  - D_s edge length, watertightness, UV codes and pinned borders;
  - chunk frames;
  - `bake()` progress, cancel, manifest, remove, refusing to overwrite, bad options, default output identical to plain splitting, the experimental structure, and fixture freshness.

  They pass on the host and in the container (`dev/run.sh`).
- `tests/zgo_test_baker2.lua` runs the accessors against the baker's real output for the synthetic model (`tests/baker/fixtures`). It passes in both bake modes and for every seed.
- `dev/test-all.sh`: **120 runs, 0 failures**. The real 1.7 bake was in the mod folder at the time, so ZGO_BAKED=0/1 and the MP runs all saw it.
- Every one of the 4790 models in the real bake decodes through `zgo_bake.script` (luajit with the harness). Every cap and piece it names exists on disk.
- Experimental bakes into scratch folders outside the mod: all 278 monster models (260 baked, 0 errors after the 64k-vertex guard), the 305 `actors\stalker_bandit` models, and the cat/boar rebake.
  - Every OGF re-read through `ogf.py` repacks byte for byte.
  - Every K_s/D_s has `zgo\off`, and every D_s keeps the vertices of its C.
  - UV codes decode in range; site codes on 99.8 % of D meshes.

### Not verified (needs the game)

All of these are in-game checks in section 7:
- attaching caps and pieces;
- `bone_callback`;
- the `zgo\off` behaviour behind K_s/D_s;
- how long the bigger generated scripts take to load at game start.

### The full bake into the mod folder (G.A.M.M.A, 16 CPUs)

| | |
|---|---|
| Time | 100 s; before 1.7 it was about 10 s |
| Models | 4790 baked, 6 skipped (poltergeist, tushkano fly: no cut roots), 0 errors |
| Files | 79125, 6.5 GB |
| Baked models | 2.97 GB (actors 2.6 GB, monsters 197 MB), as before |
| Caps | 61735 caps in 23805 files, 250 MB |
| Pieces | 62802 pieces in 50527 files, 3.2 GB |
| Wound sites | 248483 sites; 372 skeletons; 8274 site lists |
| `zgo_bake_index.script` | 294 KB |
| `zgo_bake_parts.script` | 2.5 MB |
| `zgo_bake_wounds.script` | 3.9 MB |
| Loading parts + wounds (LuaJIT, host) | 19 ms, about 8 MB |

The manifest lists exactly the 79125 generated files on disk, and `previous_files()` (what `--remove` deletes) is exactly that list. Nothing shipped is in it: `gamedata/meshes/zgo/world/**` is untouched. A second scratch bake gave identical bytes for every OGF, so the bake is deterministic.

Experimental sizes:

| Set | Stock | Experimental |
|---|---|---|
| Monsters | 197 MB | 1.08 GB (1.45 GB with attachments), 153 s |
| Bandits | 167 MB | 1.38 GB, 100 s |

A full experimental bake would be roughly 25–30 GB and take about an hour. It is not meant for players until the runtime uses it.

No packages were installed and nothing was downloaded.

## 2. Files

Added:
- `tools/zgo_baker/caps.py` (seams, fitted caps)
- `tools/zgo_baker/parts.py` (cap and piece models, K_s, content names)
- `tools/zgo_baker/wounds.py` (sites, thickness, hints, bind poses, encoding)
- `tools/zgo_baker/damage.py` (experimental D_s and chunks)
- `tools/zgo_baker/luagen.py` (generated scripts)
- `docs/formats/README.md`, `bake-api.md`, `index.md`, `parts.md`, `caps.md`, `pieces.md`, `wounds.md`, `damage.md`
- `tests/baker/synth.py` (synthetic character), `fakemo2.py` (fake MO2 and fixture generator), `test_geometry.py`, `test_bake.py`
- `tests/baker/fixtures/zgo_bake_index.script`, `zgo_bake_parts.script`, `zgo_bake_wounds.script`
- `tests/zgo_test_baker2.lua`
- `docs/integration/baker2.md`

Changed:
- `tools/zgo_baker/bake.py` (rewritten: library API, CLI, scripts, manifest)
- `tools/zgo_baker/ogf.py`: `Geom.new`, `build_skeleton_model`, `ik_record`, `default_bone`, `obb_bytes`, `rigid_inverse`, `transform_geom`, `xyzi_from_matrix`; it also keeps `ik_vers`
- `tools/zgo_baker/partition.py`: the info dict now has `roots`, `labels` and `section_of_bone`; outputs unchanged
- `tools/zgo_baker/unpack_base.py`, `resolve.py` (progress and cancel hooks)
- `tools/zgo_baker/README.md`
- `gamedata/scripts/zgo_bake.script`: new accessors; old functions unchanged; `info()` also takes a visual name

Generated, all listed in `zgo_bake_report.json` and ignored by `dev/package.py`:
- `gamedata/meshes/actors/**`, `monsters/**`, `zgo/baked/**`
- `gamedata/scripts/zgo_bake_index.script`, `zgo_bake_parts.script`, `zgo_bake_wounds.script`
- `zgo_bake_report.json`

## 3. Requests to the integrator

1. **`tests/zgo_harness.lua` line 463.** Do not run the generated data scripts in the `on_game_start` loop. They have no `on_game_start`, and loading 6.4 MB of them costs every test run about 20 ms. Replace
   ```lua
   if n and n ~= "zgo_main" and n ~= "zgo_bake_index" and n ~= "zgo_tables" and not n:match("^zgo_settings") then names[#names + 1] = n end
   ```
   with
   ```lua
   if n and n ~= "zgo_main" and not n:match("^zgo_bake_") and n ~= "zgo_tables" and not n:match("^zgo_settings") then names[#names + 1] = n end
   ```
   (`zgo_bake` itself still loads; only `zgo_bake_index/parts/wounds` are skipped.)
2. **`.gitignore`.** Under the existing baked-model block, add:
   ```
   /gamedata/meshes/zgo/baked/
   /gamedata/scripts/zgo_bake_parts.script
   /gamedata/scripts/zgo_bake_wounds.script
   ```
3. **`dev/package.py` (defence in depth).** A release must never carry generated files, even when the report is missing or half-written. In `main()`, after `rel = ...`, skip
   ```python
   rel.startswith(('gamedata/meshes/actors/', 'gamedata/meshes/monsters/', 'gamedata/meshes/zgo/baked/')) or rel in ('gamedata/scripts/zgo_bake_index.script', 'gamedata/scripts/zgo_bake_parts.script', 'gamedata/scripts/zgo_bake_wounds.script')
   ```
   If ZGO ever ships its own models under `actors/` or `monsters/`, drop the first two prefixes.
4. **`dev/test-all.sh` (optional).** Run the Python baker tests too. After the Lua loops, add:
   ```bash
   if python3 -c 'import numpy' 2>/dev/null; then
   	out=$(cd .. && python3 -m unittest discover -s tests/baker 2>&1); runs=$((runs+1))
   	case "$(tail -1 <<<"$out")" in OK*) ;; *) fails=$((fails+1)); echo "FAIL tests/baker"; tail -5 <<<"$out";; esac
   fi
   ```
   Adjust to the script's own counters and folder. They take about 10 s.
5. **setup** (owns the GUI; may change `bake.py`'s entry point and `limbs.py`):
   - Call `bake.bake(opts, progress, cancel)` on a worker thread, and show `progress` stage by stage. `bake.STAGES` gives the order; the `bake` and `install` stages carry counts.
   - Map the checkboxes onto `Options`:
     - "Stump caps" → `caps`, 250 MB;
     - "Limb pieces" → `pieces`, **3.2 GB**;
     - "Wound sites" → `wounds`;
     - two "(experimental)" boxes → `experimental_caps`, `experimental_damage`, with a warning that they need the in-game probes and that damage makes models about 10× larger.
   - Show a disk-space estimate before baking: about 1.4 MB per model at the defaults, 0.7 MB per model without pieces.
   - Show the `BakeError` text as is.
   - On Windows, `multiprocessing` needs the GUI entry point under `if __name__ == '__main__':`, and `multiprocessing.freeze_support()` if frozen (PyInstaller). `bake.py` itself is fine either way.
   - `report['errors']` and `results[*].why` hold per-model problems. Those models still load unbaked.
6. **cuts** (Phase B runtime; may extend `zgo_bake.script`):
   - Use `zgo_bake.cap(npc, section)`. Prefer Mode B (`bone_callback(b, b, true)` for every `cap.bones`, bone 0 included); it follows the hidden-bone collapse of the body's seam. Use Mode A (`set_parent_bone(cap.parent)`) only as a fallback (see caps.md).
   - Keep today's raw_flesh disks when `cap()` is nil: not baked, `--no-caps`, an index from before 1.7, or the MCM switch off.
   - Use `zgo_bake.piece(npc, section).model` instead of a full victim copy when it exists. The bone names are the victim's, so the existing callback code applies unchanged.
   - Severing the head with experimental caps: show `kcap_ids` with `set_shader(id, "models\\model", "food\\food_raw_flesh")`.
7. **wounds** (Phase C runtime and shaders):
   - Sites: `zgo_bake.wound_sites / sites / nearest_site`; hit point to bind space: `zgo_bake.bind` plus `to_bind`.
   - Site indices are 1-based per section and match the D_s `u` codes and the `site_<i>` chunk bones.
   - D_s decoding is specified in `docs/formats/damage.md`: `site = floor((u'+1.5)/4)`, `thick = floor((v'+1.5)/4)·2 mm`. **Vertices with site 0 must not move.** This includes open-border vertices shared with the next section's mesh.
   - The cap face texture is `caps.FLESH_TEX`. To use a ZGO stump texture from `textures/zgo/wounds/`, tell baker/setup the name and re-bake. No runtime change is needed.
8. **probe.** `zgo_probe` already calls `zgo_bake.parts(o, true)` and `zgo_bake.expected_children(o)`. Both now exist, and `expected_children` is exact (K_s and D_s included). Nothing to change.

## 4. Settings added

No MCM settings. The existing *Dismemberment → Use baked models* switch now also gates every new accessor; `raw = true` bypasses it, as before.

Bake options (CLI and GUI, not in game):

| Option | Default | Notes |
|---|---|---|
| `--no-caps` / `caps` | caps on | |
| `--no-pieces` / `pieces` | pieces on | |
| `--no-wounds` / `wounds` | wounds on | |
| `--experimental-caps` | **off** | (experimental) |
| `--experimental-damage` | **off** | (experimental) |
| `--anomaly DIR` | the game path from MO2's `ModOrganizer.ini` | |

## 5. Co-op

There are no new sync kinds; the bake is local to each player.

Caps, pieces and K_s are drawn locally from each player's own bake. If players' mod lists differ, their models, sites and file names may differ too. `bake_id` is local and must never be compared across machines.

For **wounds**: do not send site indices across the wire as they are. A client's model may come from another mod and have other sites. Send the hit in bind space (or the section plus the bind-space point), and let each machine map it with `nearest_site` on its own bake.

## 6. README text

Replace the BAKED MODELS paragraph's run line and size sentence (README.txt, CRLF):

```
    2. python3 tools/zgo_baker/bake.py   (about 2 minutes; reads MO2's
       profiles/G.A.M.M.A/modlist.txt and the game's db archives)
  The models are written into this mod's own folder (gamedata/meshes, plus
  gamedata/scripts/zgo_bake_*.script); every file it writes is listed in
  zgo_bake_report.json, and a re-run or "bake.py --remove" deletes exactly
  those. [...]
  The output is about 6.5 GB: 3 GB of models, 3.2 GB of severed-limb models
  (gamedata/meshes/zgo/baked/pieces; "bake.py --no-pieces" leaves them out)
  and 250 MB of fitted stump caps. It also maps where wounds can open on
  every body (zgo_bake_wounds.script).
```

CHANGES bullet:

```
  1.7.0  Baker: fitted stump caps (the cut surface of each body, flesh and
         bone, made for every model and cut), lighter severed-limb models with
         a closed end, and wound sites for every body; bake.py is now a library
         for the setup tool, with progress and cancel. Default baked models are
         unchanged; experimental in-model caps and damage meshes are off.
```

## 7. In-game checks

Check 1 needs nothing but the default bake that is now installed. The others need the cuts or wounds runtime, or a small test hook.

1. **Generated scripts load.**
   - Start the game with the 1.7 bake installed, load a save and note the load time against 1.6 (`zgo_bake_parts` 2.5 MB plus `zgo_bake_wounds` 3.9 MB, loaded at game start).
   - `[ZGO]` lines should show no "is from another bake".
   - Expect less than 0.1 s more load time. A visible stall is a finding.
2. **Baked models unchanged.**
   - Run probe 9 "baked models": PASS as in 1.6.
   - Cut off a limb on a corpse: the same behaviour as in 1.6.
3. **Cap attaches (Mode A).** With the cuts runtime, or a debug hook calling `npc:add_attachment("zgo_cap", zgo_bake.cap(npc, "bip01_l_thigh").model)` and then `att:set_parent_bone("bip01_pelvis")`:
   - no crash (the R_ASSERT on `dcast_PKinematics`);
   - the cap sits on the hip;
   - a flesh face with a pale bone stub, textured, no pink "missing texture".
4. **Cap follows exactly (Mode B).**
   - Same as check 3, plus `att:bone_callback(b, b, true)` for every `cap.bones`.
   - Kill the NPC and watch the ragdoll: the cap rim stays glued to the stump with no gap, including after the limb bones are hidden.
   - If `bone_callback` with three arguments is missing from the GAMMA exe, write that down; the cuts runtime then has to stay on Mode A.
5. **Pieces.**
   - Drop a limb using `zgo_bake.piece(...)` with today's callback code: the limb lies where it was cut and has a closed, fleshy end.
   - Cut the calf off a dropped thigh piece: the calf part disappears.
6. **Dog / boar heads.** Several seam loops occur there (mutant necks also cut the front legs). After decapitation, look for slivers or folds on the neck caps.
7. **(experimental) K_s and `zgo\off`.**
   - Bake with `--experimental-caps` into the mod only for this test, then restore the default bake.
   - NPCs look unchanged: probe 1 must PASS first.
   - After a cut, `set_shader(kcap_id, "models\\model", "food\\food_raw_flesh")` shows the cap.
8. **(experimental) D_s.** With the wounds shader, a D_s switched on in place of its C looks identical while undisplaced: no cracks at section borders, and the texture is unchanged (the WRAP sampler ignores the integer UV codes).

## 8. Risks and open questions

- **Disk and time.** A default bake grows from 3 GB to 6.5 GB, and from about 10 s to about 100 s. That is mostly limb pieces (3.2 GB, 50k files).
  - If that is too much, make pieces opt-in in the GUI (`pieces=False`), or have cuts keep spawning full victim copies.
  - The cap files are small (250 MB).
- **Game-start cost.**
  - Anomaly loads every root script at game start, and the parts and wounds scripts add 6.4 MB of source: about 20 ms and about 8 MB of Lua strings on the host.
  - Decoded models are cached with weak references. Decoding every model at once would take about 290 MB, but only models in view are ever decoded.
  - Moving the tables to a lazily read file would avoid the start-up cost, but needs an engine file-read path that has been probed in game.
- **Not probed in game.** The cap and piece frames are exact in the offline tests (both modes, random poses). Four things still need the game (checks 3, 4, 7, 8):
  - the attachment R_ASSERT;
  - `bone_callback(..., true)` on the GAMMA exe;
  - how the hidden-bone collapse affects Mode A;
  - `zgo\off`.
- **Textures.** `food\food_raw_flesh` is a steak cross-section at 128 px, and `act\act_skeleton` stands in for bone. They are fine for now, but a dedicated stump texture from wounds would be better.
- **Heuristic hints.** Tissue hints and head/limb classes come from bone names; unusual skeletons get generic letters. Site thickness uses a ray against the whole model with glass excluded. Thin clothing layers over a body can make a site "thin"; exits closer than 15 mm are ignored, but layered outfits may still mislead.
- **Experimental damage size.** D_s makes models about 10× larger, because the patches cover most of the body at 1.5 cm. Two sub-meshes (cat, boar) passed 65535 vertices and get no D mesh. Before anyone ships this, consider a coarser edge, smaller patches, or subdividing only the sites the runtime uses.
- **D_s at section borders.** Border vertices carry code 0 and must stay put, so a crater right at a seam is pinned at the seam. That needs care from the wounds shader.
- **`setup` may change `bake.py` and `limbs.py`.** Please keep `bake()`, `Options`, `STAGES`, `BakeError` / `Cancelled`, `remove` and the report fields stable; they are documented in `docs/formats/bake-api.md`. `tests/baker/test_bake.py` tests them.
- **Fixtures.** `tests/baker/fixtures` must be regenerated (`python3 tests/baker/fakemo2.py --fixtures`) whenever a format changes. `test_lua_fixtures_current` fails until it is.
