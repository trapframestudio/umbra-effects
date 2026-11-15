# Bake library API (for the setup GUI)

`tools/zgo_baker/bake.py` is both a command-line tool and an importable module. A GUI imports it and calls `bake()`. That call runs on the GUI's worker thread, uses a `multiprocessing.Pool` for the models, and reports back through callbacks.

```python
import sys; sys.path.insert(0, '<mod>/tools/zgo_baker')
import bake

opts = bake.default_options()          # reads MO2's ModOrganizer.ini next to the mod
opts.experimental_caps = False         # every Options field is listed below
report = bake.bake(opts, progress=on_progress, cancel=should_stop)
n = bake.remove(opts.out)              # undo: delete everything the last bake wrote
```

Requirements:
- Python 3.8 or later and numpy;
- `luajit` on PATH, which reads the creature tables from `zgo_tables.script`;
- the game's `db/` archives for the base models (read only).

Unpacked base models are cached in `~/.cache/zgo_baker`, or `%LOCALAPPDATA%\zgo_baker` on Windows. A temporary build folder is also kept there.

## `Options`

| Field | Default | Meaning |
|---|---|---|
| `mo2` | the MO2 folder this mod sits in (`<mo2>/mods/<this mod>`) | MO2 instance folder (holds `mods/`, `profiles/`) |
| `profile` | `selected_profile` in `ModOrganizer.ini`, or the only profile | MO2 profile whose `modlist.txt` decides which model wins |
| `anomaly` | `gamePath` in `ModOrganizer.ini` (a `Z:\...` Wine path becomes `/...`) | game folder (holds `db/`) |
| `out` | this mod's folder | where models, scripts and the report go |
| `only` | `None` | bake only model paths containing this text (for testing) |
| `jobs` | CPU count − 2 | worker processes |
| `caps` / `pieces` / `wounds` | `True` | stump caps, limb pieces, wound sites |
| `experimental_caps` | `False` | K_s sub-meshes inside every model (see caps.md) |
| `experimental_damage` | `False` | D_s sub-meshes inside every model, plus gib chunks (see damage.md) |
| `cache` | see above | cache folder |

`bake.default_options(mod_root)` fills `mo2`, `profile` and `anomaly` from MO2's config. Any of them may come back `None` (no `ModOrganizer.ini`, several profiles), and the GUI should then ask for it. `bake.mo2_defaults(mod_root)` returns the raw triple `(mo2, profile, game)`.

## Callbacks

- `progress(stage, done, total, message)` is called on the calling thread.
  - `stage` is one of `bake.STAGES`, and the stages come in this order: `prepare`, `unpack`, `resolve`, `bake`, `scripts`, `install`, `done`.
  - `0 <= done <= total`, and `message` is a short English line.
  - It is called often during `bake` and `install`, about every 25 models and every 1000 files.
- `cancel()` returns `True` to stop. It is polled between steps and between models.
  - Cancelling raises `bake.Cancelled`, a subclass of `BakeError`.
  - Once the `install` stage has begun, `cancel` is no longer polled. By then everything is built, and the install only moves files.
  - Before `install`, cancelling never changes the output folder.

## Errors

`bake.BakeError(message)` covers anything that stops a bake. The message is meant to be shown to the player. It is raised for:
- a wrong MO2 folder, profile or game folder;
- missing or unreadable game archives;
- another bake running into the same folder (a lock file, `<cache>/building-<hash>.lock`, holds the pid);
- an output file that the baker did not write, which it refuses to overwrite.

A model that fails to bake is not an error for the whole bake. It shows up in `report['results']` with `status: 'error'`, and the game loads that model unbaked.

## The report (manifest)

`<out>/zgo_bake_report.json`, also returned by `bake()`:

```json
{
  "baked": 4784, "skipped": 6, "errors": 0,
  "profile": "G.A.M.M.A", "time": "2026-11-13 15:00:00", "version": 2,
  "bake_id": "20261113-150000-1a2b3c4d",
  "options": {"caps": true, "pieces": true, "wounds": true,
              "experimental_caps": false, "experimental_damage": false},
  "seconds": 103.3, "replaced": 0, "bytes": 6513000000,
  "counts": {"models": 4784, "files": 79085, "caps": 61679, "cap_files": 23801,
             "pieces": 62746, "piece_files": 50497, "chunk_files": 0, "sites": 248209,
             "bonesets": 255, "skeletons": 402, "site_tables": 8295,
             "kids_in": 19759, "kids_out": 89580, "bytes_in": 3113266035, "bytes_out": 2967781591},
  "files": ["gamedata/meshes/actors/...ogf", "...", "gamedata/scripts/zgo_bake_index.script"],
  "results": [{"key": "actors\\stalker_bandit\\stalker_bandit1a", "status": "ok",
               "sections": ["bip01_head", "..."], "kids_in": 3, "kids_out": 17, "tris": 6302,
               "caps": 13, "pieces": 13, "sites": 54, "src": "<path>", "src_md5": "...",
               "bytes_in": 406311, "bytes_out": 412907}]
}
```

- `files` is sorted and relative to `out`, with `/` separators. It lists every file the bake wrote, and only those. The report is not in the list.
- `previous_files(out)` reads this list back. It only ever accepts `gamedata/meshes/**` and the three generated scripts, so a damaged report cannot make `--remove` delete anything else.
  - 1.4.x reports, which have no `files`, are rebuilt from `results`.
- While files are being moved into place, the report temporarily holds `"status": "installing"` and the union of the old and new files. A bake that dies half-way can still be removed or replaced by the next run.
- `version` is 2. In version 1 (1.4–1.6) only the `options`, `bake_id`, `counts`, `seconds`, `replaced` and `bytes` fields are missing.

## Command line

```
python3 bake.py [--mo2 DIR] [--profile NAME] [--anomaly DIR] [--out DIR] [--only TEXT] [--jobs N]
                [--no-caps] [--no-pieces] [--no-wounds]
                [--experimental-caps] [--experimental-damage] [--quiet]
python3 bake.py --remove [--out DIR]
```

Exit code 0 means success. Exit code 2 means a `BakeError`, whose message goes to stderr. The flags map one-to-one onto `Options`.
