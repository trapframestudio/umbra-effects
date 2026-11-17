# Integration note: setup (ZGO Setup: bake GUI, fingerprints, in-game bake check)

## 1. Summary

**ZGO Setup** (`tools/zgo_setup`) is the player-facing way to bake, check and
remove the per-mod-list bake (body models, caps, pieces, wound sites, and the
props cut by `tools/zgo_fracture`). It is a tkinter window over a logic layer
that has no GUI code (`setup_core.py`), plus a command line on the same layer.

- **Finds everything itself.** It lives in `<MO2>/mods/<ZGO>/tools/zgo_setup`,
  so the MO2 folder is two levels up; profile and game folder come from
  `ModOrganizer.ini` (a Wine `Z:\` path becomes a Linux path). All three can be
  changed in the window (Change... / profile list) or with `--mo2/--profile/--game`.
- **Shows what will be baked** before baking: models per source mod (the
  game's archives included once unpacked), the size of each part and a time
  estimate (G.A.M.M.A.: 4796 models, "about 6.4 GB" vs 6.5 GB real), free space
  on each drive the bake touches, and mods that load after ZGO and would hide
  baked models (red line, with "drag ZGO below it").
- **Ready-made bakes (1.8.1).** Bake first looks for a published bake that fits
  (`prebaked.py`): it reads `umbra-effects/index.json` in Umbra's public bucket
  (written by Umbra's `dev/b2_upload.py`; format in Umbra's `packdef.py`), downloads a
  candidate's small report volume, relocates its path tokens to this machine and runs
  the prebaked `check()` against this mod list and these ticks. On a fit it downloads
  the volumes (resumable, sha256-checked), unpacks only bake outputs, relocates them,
  swaps them in and adopts this machine's file dates into the report; otherwise, or on
  any failure, it bakes here. `--no-download` / the "Download a ready-made bake" box
  turn it off; `ZGO_PREBAKED_SOURCE` points it at another bucket URL or folder (`off`
  disables it; the tests use a local folder and a local HTTP server).
- **Packed ready-made bakes (1.8.3).** A manifest of format 2 holds the bake as it is
  installed since 1.8.2: the small parts already inside `db/mods/zgo_bake_*.db0`, in
  LZMA zip volumes (G.A.M.M.A.: 4,941 files, 3.5 GB to download, against 83,789 files and
  4.7 GB for format 1). The index lists a fingerprint's format-1 entry first, since Setup
  1.8.1/1.8.2 stop at a format they can't read; 1.8.3 takes the format-2 entry of a
  fingerprint first (`prebaked.candidates`). Volumes download three at a time, are hashed
  as they arrive, and each is unpacked as soon as it is in (two at a time), so the download
  and the unpacking overlap. A volume that arrives damaged is fetched once more.
- **Putting it in** writes an `installing` report listing the files first, so a move that
  fails half-way (a virus scanner holding a file) leaves a bake that **Bake** replaces and
  **Remove bake** removes. Bake, Pack and Remove delete a `.zgo-prebaked` folder a hard
  kill left in the Umbra Effects folder, and old job folders in the temp folder go after
  two days. An installed bake that already matches the fingerprint and the ticks is not
  downloaded again. `--adopt-dates --yes` records this machine's dates in a bake another
  program put in place (Umbra's installer, after its own download).
- **`unused` (1.8.3).** A bake that checks out but that the game won't load: the folder
  isn't `<MO2>/mods/<name>` (compared by real path), the mod is unticked in the profile, or
  the MCM key `zgo/dismember/baked_models` is `false` in the `axr_options.ltx` the game
  reads (overwrite, then the enabled mods by priority). The window shows it in orange and
  `--check` exits 1.
- **Only into the copy the game loads; Repair (1.8.3).** `loaded_copy()` is the copy of ZGO
  the game loads: the highest-priority ticked copy in `<MO2>/mods` (a copy: `zgo_main.script`
  or a bake report in it), else this copy when it is in `mods`, else the one copy there is;
  `None` when MO2 has none. `install_problems()` (part of `problems()`, so it gates Bake,
  the download, `--bake` and the worker) refuses a bake unless Setup's own copy is that one:
  started from the unpacked zip before the zip was installed through MO2, a bake used to land
  where the game never reads it (no cuts, stumps or body gibs; in co-op only on that player's
  screen). `repair_needed()` lists what `repair()` fixes, cheaply (no check); `repair()`
  (worker action `repair`, `--repair`, the **Repair** button) installs this copy into
  `<MO2>/mods/Umbra Gore & Effects` when MO2 has none (the bake files moved, the rest copied),
  moves the first stray bake that `check()`s as fitting into the loaded copy when that has
  none that fits (reports first, files, then the source reports, so a cut-off move leaves a
  bake Bake replaces), removes the other stray bakes (unticked copies, the unpacked copy), and
  clears `.zgo-prebaked`, then ticks the loaded copy in the profile when it isn't
  (`tick_in_profile()`: `-name` flipped where it is, a new line on top under xrRazom, whose fomod
  asks for the highest priority; the old list kept as `modlist.txt.zgo-bak`) unless
  `mo2_running()` (tasklist on Windows; `/proc`, or `Z:\proc` under Wine, as Umbra's installer
  does): MO2 rewrites `modlist.txt` from memory when it closes. The window asks to close MO2
  first, labels the button "Install into MO2" when that is the fix, and afterwards offers to
  start Setup from the installed copy (`open_setup_in()`). A bake is moved only between copies
  of the same `zgo_version()`; a
  newer unpacked copy keeps its bake until its zip is installed. A bake into another folder on
  purpose (`out` other than the copy itself: the tests, the self-test) is not checked.
- **Options** as checkboxes with an explanation beside each: caps (250 MB),
  pieces (3.2 GB), wound sites, breakable props; the three experimental parts
  are folded away under "Show the experimental parts", are off, and ask for
  confirmation (damage meshes: 25-30 GB warning). The last bake's ticks are
  restored.
- **Bake** runs in a worker process (the program started again with
  `--worker`), with a progress bar over all stages, time left, and **Cancel**
  (nothing in the ZGO folder changes before the baker's install step). Then
  the props (if ticked); a props failure after the models are in is a warning,
  not a failure. **Remove bake** removes body bake and props.
- **"Check if my bake is up to date"** compares the bake's recorded inputs
  with the mod list now, model by model: added / gone / moved to another mod /
  changed (size, then md5 when the date differs; `--deep` always hashes),
  ZGO's creature tables, the baker version, the profile, the game's archives,
  missing baked files, a half-installed bake, and the load-order case ("a mod
  above ZGO hides N baked models: drag ZGO below it, no new bake needed").
  G.A.M.M.A.: 3.9 s for 4790 models.
- **Plain-language errors** (disk full, read-only folder, missing folder, out
  of memory, the baker's own messages as they are, with a hint for the lock
  and "refusing to overwrite"); every traceback goes to the **Log** tab (with a
  "N new warnings" marker), Save log / Copy log, and a log file
  (`%LOCALAPPDATA%\zgo_setup\zgo_setup.log`, `~/.cache/zgo_setup/zgo_setup.log`).
- **Fits small screens**: Bake and Log tabs, buttons and progress always in
  view, the Bake tab scrolls when the screen is too small (checked at
  1366x768 and 1920x1080; screenshots looked at).
- **Cross-platform**: `ZGO Setup.exe` (Windows, also under Wine/Proton),
  `zgo-setup-linux`, `zgo-setup.sh` (starts the program, falls back to the
  player's python3, else explains what to install), or `python3 zgo_setup.py`
  anywhere with numpy and tkinter. The programs bundle Python, numpy and
  tkinter **only**; they always run the `.py` files of the ZGO folder they sit
  in, worker processes included, so a ZGO update never runs a stale baker and
  needs no rebuild. `--selftest` checks numpy, every module, parallel workers
  (and that they load the same baker), the worker process and the window.

**Baker changes** (allowed by the contract): `limbs.py` reads
`zgo_tables.script` in pure Python (no LuaJIT; identical result to LuaJIT on
the real tables, tested); `bake.py` records **fingerprints**: per model the
winning source mod, size, md5 and date, and per bake the ZGO version, baker
version (`BAKER_VERSION = 2`), flags, creature tables line, profile, MO2
folder, game archive sizes, the model mods and one `fingerprint` md5; other
enabled copies of ZGO are never bake sources; `ZGO_BAKER_CACHE` moves the work
folder. The game-readable form is `gamedata/scripts/zgo_bake_inputs.script`
(format in §3 request 6). `bake()`, `Options`, `STAGES`, `BakeError`,
`Cancelled`, `remove` and the report fields are unchanged (only added to).

**In-game stale-bake notice** (`zgo_setup_notice.script`, MCM page "Baked
models", all local): a few seconds after a save loads it checks, cheapest
first, and tells the player once per problem (news message + log line, both
languages, Windows-1251 on screen) to run ZGO Setup or fix the load order:
nothing baked (a reminder once per ZGO version), a bake by an older/newer
baker, changed creature tables (`zgo_tables.limb_map` against the recorded
line, built by the same rule as the baker), an incomplete bake, and every
baked model the game does not load as baked: `getFS():exist("$game_meshes$",
key .. ".ogf").size_real` against the recorded size, which catches a mod that
loads after ZGO and missing files. The size check calibrates on
`zgo_bake_index.script` (its size is recorded too) and is skipped quietly if
that does not match. 400 look-ups per frame (G.A.M.M.A.: 12 frames).
(experimental, off) It can also read MO2's `modlist.txt` and the source
files through `io`/`lfs` (via `Z:\` under Proton) to name the mod that was
added, removed, reordered or updated, and who hides the baked models.

**Verified** (tests): everything above offline, with a real bake of the
synthetic character into a fake MO2 + game (real `.db` archives), the CLI
end to end, the window driven by a script on a virtual display, the launcher,
and a frozen Linux program built with PyInstaller from pip (container
Python 3.14: self-test incl. window, bake, check, remove all pass). On the real
G.A.M.M.A. list, read-only: `--plan`, `--check` and the window.

**Not done: the release binaries.** `tools/zgo_setup/zgo-setup-linux` and
`ZGO Setup.exe` are not built. The portable Linux build needs
python-build-standalone 3.12.10 (glibc 2.17 baseline) and the Windows build
needs python.org's 3.12.10 installer run under Wine; both are downloaded and
hash-pinned, but this session's permission check refused to run a downloaded
Python runtime (see §8). A build from the container's own Python works (it
is how the frozen program was tested) but needs glibc 2.43, so it would not
start on Ubuntu, Debian or SteamOS, and it is not shipped. Until the
binaries exist, players use `zgo-setup.sh` / `python3 zgo_setup.py`, or the
baker CLI as before.

**Not verified (needs the game):** `getFS():exist()` returning `fs_file`
with `size_real` for files under MO2 (the binding is in the exe's strings and
the engine source; the calibration makes a mismatch harmless), the news
message, and the experimental mod-files check under Proton.

## 2. Files

Added:

- `tools/zgo_setup/zgo_setup.py`: entry point: window, command line
  (`--check --plan --bake --props --remove --selftest --version`, options), worker
  mode, self-test; `freeze_support` and the worker paths for the frozen program
- `tools/zgo_setup/setup_core.py`: logic layer (paths, detection, problems,
  warnings, choices, plan and estimate, check, plain-language errors, Job /
  worker, log)
- `tools/zgo_setup/setup_gui.py`: the window
- `tools/zgo_setup/zgo-setup.sh`: Linux launcher (program, python3 fallback, message)
- `tools/zgo_setup/README.md`: player docs for the tool
- `gamedata/scripts/zgo_setup_notice.script`, `gamedata/scripts/zgo_settings_setup.script`
- `tests/zgo_test_setup.lua`: the in-game check (picked up by `dev/test-all.sh` automatically)
- `dev/build_setup/`: `build.sh` (linux / windows / all / local), `zgo_setup.spec`,
  `requirements.txt` (hash-pinned), `README.md`, `test_setup.py` (46 tests),
  `fakezgo.py` (fake MO2 + game), `gui_driver.py` (drives the window)
- `docs/integration/setup.md`

Changed:

- `tools/zgo_baker/limbs.py`: rewritten, pure-Python Lua table reader
  (`load`, `read_tables`, `roots_from_limb_map`, `canonical`, `LuaReadError`)
- `tools/zgo_baker/bake.py`: `BAKER_VERSION`, `INPUTS`, `GENERATED_SCRIPTS`,
  per-model source info, `zgo_version`, `game_path`, `other_zgo_mods`,
  `model_mods`, `source_mod`, `archives_info`, `fingerprint`, `inputs_record`,
  `inputs_lines`; writes `zgo_bake_inputs.script`; report key `inputs`;
  `ZGO_BAKER_CACHE`
- `gamedata/configs/text/eng|rus/ui_st_zgo_mcm.xml`: regenerated by `luajit dev/gen_mcm_text.lua`

Not produced (see §1, §8): `tools/zgo_setup/zgo-setup-linux`,
`tools/zgo_setup/ZGO Setup.exe`, `tools/zgo_setup/SHA256SUMS.txt`.

Downloads (all under `~/.cache/zgo-setup-build/downloads`, none shipped):

| File | From | sha256 / note |
|---|---|---|
| `cpython-3.12.10+20250409-x86_64-unknown-linux-gnu-install_only.tar.gz` (66 MB) | github.com/astral-sh/python-build-standalone release 20250409 | `e9cf6f7da499a4400ba30ae1da8f7ef25ce97827bd8c1084717aa05438035186` (matches the release's SHA256SUMS); not run |
| `pbs-SHA256SUMS` | same release | the checksum list |
| `python-3.12.10-amd64.exe` (27 MB) | python.org/ftp/python/3.12.10 | `67b5635e80ea51072b87941312d00ec8927c4db9ba18938f7ad2d27b328b95fb`; not run |
| `python-3.12.10-amd64.exe.spdx.json`, `rel.html` | python.org | SBOM and release page |
| `pyinstaller.json`, `pyinstaller-hooks-contrib.json`, `altgraph.json`, `packaging.json`, `setuptools.json`, `pefile.json`, `pywin32-ctypes.json`, `numpy.json` | pypi.org/pypi/<name>/json | metadata; the wheel hashes in `requirements.txt` come from here |

Installed (pip, inside the zgo-dev container, into the venv
`~/.cache/zgo-setup-build/local/venv`, `--require-hashes`): pyinstaller 6.22.3,
pyinstaller-hooks-contrib 2026.9, altgraph 0.17.5, packaging 26.3, setuptools
84.2.1, numpy 2.3.5. Built from them: `~/.cache/zgo-setup-build/local/zgo-setup-linux`
(test only). Nothing was installed system-wide or into the container image.

## 3. Requests to the integrator

1. **`tests/zgo_harness.lua`** (line ~463): don't load the generated data
   script either (it's large and has no `on_game_start`). Replace
   `n ~= "zgo_bake_index"` with
   `n ~= "zgo_bake_index" and n ~= "zgo_bake_inputs"`.

2. **`dev/test-all.sh`**: run the Python suites too. Before the final `echo`:

   ```bash
   for suite in "tests/baker test_*.py" "dev/build_setup test_*.py"; do
   	set -- $suite
   	runs=$((runs+1))
   	out=$(cd .. && python3 -m unittest discover -s "$1" -p "$2" 2>&1)
   	case "$(tail -1 <<<"$out")" in OK*) ;; *) fails=$((fails+1)); echo "FAIL python $1"; tail -5 <<<"$out";; esac
   done
   ```

   (The window and frozen-program tests skip themselves without tkinter /
   xvfb-run / a built program; in the container they run.)

3. **`dev/distrobox.ini`**: add
   `additional_packages="python3-tkinter xorg-x11-server-Xvfb xwd ImageMagick binutils"`
   (window tests, screenshots, the glibc check of builds). They are already
   installed in the current container.

4. **`dev/package.py`**: a safety net so a bake never ships even without a
   report: add to the skip test in `main()`
   `or (rel.startswith('gamedata/scripts/zgo_bake_') and rel != 'gamedata/scripts/zgo_bake.script')`.
   Nothing else: `tools/zgo_setup/*` ships as is (`zipfile` keeps the
   executable bit of `zgo-setup-linux` / `zgo-setup.sh`; the launcher also
   works without it).

5. **`.gitignore`**: add `/gamedata/scripts/zgo_bake_*.script`,
   `!/gamedata/scripts/zgo_bake.script` and `/gamedata/meshes/zgo/baked/`
   (the parts/wounds/inputs scripts and caps/pieces are generated too).

6. **`docs/formats/bake-api.md`**: add a section "Fingerprints and
   zgo_bake_inputs.script":

   ```
   Every result in zgo_bake_report.json also has src (path), src_mod (MO2 mod,
   "" = the game's archives), bytes_in, src_md5, src_mtime and (baked) bytes_out.
   report.inputs = { version: 1, baker: BAKER_VERSION, zgo: "1.7.0", tables:
   "kind=root,root;...", flags: [..], profile, mo2 (as the game sees it: Z:\..
   under Wine), mo2_game, anomaly, zgo_mod, archives: {rel: [size, mtime]},
   model_mods: [highest priority first], fingerprint: md5 }
   fingerprint = md5 of [BAKER_VERSION, tables, sorted flags, sorted [key, src_md5]].
   gamedata/scripts/zgo_bake_inputs.script (CRLF, generated, listed in files):
     version = 1, bake_id (= the index's), baker, zgo, flags ("caps pieces
     wounds"), fingerprint, tables, profile, mo2, zgo_mod, index_bytes (the
     size of zgo_bake_index.script), mods = { "Mod", ... },
     models = { ["actors\\x\\y"] = "<baked bytes> <mods index, 0 = game> <source bytes>" }
   BAKER_VERSION (bake.py) and BAKER (zgo_setup_notice.script) must match:
   raise both when a ZGO update needs a new bake.
   ```

7. **`tools/zgo_baker/README.md`**: replace "Needs Python 3 + numpy and
   LuaJIT (to read zgo_tables.script)." with "Needs Python 3 + numpy.
   Players use ZGO Setup (tools/zgo_setup), which runs this baker.
   ZGO_BAKER_CACHE=DIR moves the work folder (it needs as much free space as
   the bake).", and the `limbs.py` line with "`limbs.py` cut roots per
   creature kind, read from zgo_tables.script (a small Lua table reader; no
   LuaJIT needed)".

8. **`README.md`**: the BAKED MODELS section, §6; the CHANGES bullet goes into `CHANGELOG.md`. Note
   the current text says to keep ZGO "above every mod that ships character
   models in MO2's left pane (higher priority)": in MO2 the mod **lower** in
   the left pane wins (modlist.txt lists it first), so that sentence tells
   players the opposite of what works; §6 fixes it.

9. **Builds** (needs the user's go-ahead, see §8): `dev/build_setup/build.sh all`
   on the dev machine (about 10 minutes; it self-tests both programs), then
   ship `tools/zgo_setup/zgo-setup-linux`, `tools/zgo_setup/ZGO Setup.exe`
   and `tools/zgo_setup/SHA256SUMS.txt`.

10. **props (owner of `tools/zgo_fracture`)**: record `bytes_in` / `src_md5`
    per prop like the body bake, so "Check if my bake is up to date" can
    notice a prop mod updated in place (today it compares the winning paths
    only).

11. **co-op (later)**: a client/host handshake could compare
    `zgo_bake_inputs.fingerprint` (one string) to say "your bake differs from
    the host's".

12. **`docs/PLAN.md`**: mark "Setup GUI" done except the release binaries.

## 4. Settings added

Page `setup` ("Baked models" / "Запечённые модели"), after Dismemberment,
`coop = "local"` (each player has their own bake):

| Key | Type | Default | What |
|---|---|---|---|
| `setup/notice` | check | on | check the bake a few seconds after a save loads, tell once per problem |
| `setup/remind` | check | on | (shown with notice) remind once per ZGO version when nothing is baked |
| `setup/check_mods` | check | **off, experimental** | also read MO2's modlist and the source files (io/lfs via `Z:\`) to name the mod |
| `setup/check_now` | button | | `zgo_setup_notice.check_now`: run the check after the menu closes and show the result, even "up to date" |

English and Russian names and explanations; MCM xml regenerated. Kid mode:
nothing to do (text only).

## 5. Co-op

No sync kinds, nothing sent. Bakes are per machine; the notice and all its
options are local; host and clients each see only their own messages. The
"shown before" list is `appdata\zgo_setup_notice.txt` on each machine.

## 6. README text

Replace the BAKED MODELS section (README.md, CRLF):

```
BAKED MODELS (optional, recommended)
  ZGO Setup rebuilds every character and mutant model your mod list uses so
  that each part that can come off (head, upper arm, forearm, hand, thigh,
  calf, foot) is its own sub-mesh, with a fitted stump cap for every cut,
  light severed-limb models and wound sites. The game drops a sub-mesh once
  its bones are hidden, ragdoll or not, so with baked models limbs come off
  corpses too, and blasts that arrive after death still take parts.
  Start it from the ZGO folder (close the game first):
    Windows                      tools\zgo_setup\ZGO Setup.exe
    Linux (MO2 under Proton)     tools/zgo_setup/zgo-setup.sh
                                 (or "ZGO Setup.exe" with Wine/Proton)
    any system with Python 3, numpy and tkinter
                                 python3 tools/zgo_setup/zgo_setup.py
  It finds MO2, your profile and the game by itself (you can change them),
  shows how many models come from which mod and how much space the bake will
  take, and bakes with a progress bar (Cancel leaves everything as it was).
  The bake is about 6.5 GB and a few minutes for G.A.M.M.A.: 3 GB of models,
  3.2 GB of severed-limb models ("Limb pieces"; untick to leave them out) and
  250 MB of stump caps. "Breakable props" also cuts barrels, crates and
  stools for "Objects break apart". The experimental parts stay off.
  Everything is written into this mod's own folder and listed in
  zgo_bake_report.json; "Remove bake" deletes exactly those files.
  Bake again when you add, remove or update a mod with character models:
  "Check if my bake is up to date" tells you whether you need to, and the
  game tells you too when a save loads (MCM -> Baked models). In MO2's left
  pane keep Umbra Gore & Effects BELOW every mod that ships character models
  (lower in the list wins), or the game shows their unbaked models; ZGO Setup
  names such mods. MCM -> Dismemberment -> Use baked models turns the bake off
  without deleting it.
  Co-op: every player bakes for their own mod list. A client without a bake
  in use (none, "Use baked models" off, or another mod's model wins) sees
  almost none of a baked host's cuts: they arrive once the host's ragdoll
  exists, and an un-baked ragdoll keeps the part on screen. Its gibs are meat
  models. The client's log says why, once per cut, and the co-op handshake
  tells both players.
  Cost: about 4.5 times as many sub-meshes per NPC (draw calls; roughly 15
  extra per stalker), and distant NPCs lose the models' built-in level of
  detail. In testing there was no noticeable FPS loss in a crowded base.
  Without a window: ZGO Setup --check / --bake / --remove (see
  tools/zgo_setup/README.md); tools/zgo_baker/bake.py still works as before.
```

CHANGES bullet:

```
  1.7.0  ZGO Setup (tools/zgo_setup): a window for Windows and Linux that bakes
         the models for your mod list, shows what and how much, checks whether
         the bake is still up to date and names the mod that changed, and
         removes it. The game checks the bake when a save loads and tells you
         when to run ZGO Setup (MCM -> Baked models). The baker no longer
         needs LuaJIT.
```

## 7. In-game checks

Before 1-4: bake once with ZGO Setup (so `zgo_bake_inputs.script` exists),
ZGO enabled and below every model mod in MO2. Turn on MCM -> General -> debug
log for the extra lines.

1. **The size check works** (the one engine assumption). Load a save and wait
   10 s. The log (`appdata/logs/xray_steamuser.log`) must have
   `[ZGO] bake check: Your baked models are up to date (4790 models checked).`
   with no message on screen. If instead (debug log) it says
   `file sizes not compared (the index reads as X bytes, the bake wrote Y)`,
   report X and Y: the check then stays quiet but cannot see load-order problems.
2. **Load order.** In MO2 drag a mod with character models (e.g. "Dux's
   Innemurable Characters") below ZGO, start the game, load a save: within
   10 s a news message says how many baked models are hidden and names an
   example model and the fix. Load again: the message does not come back.
   Drag ZGO back below, reload: no message.
3. **MCM button.** MCM -> Baked models -> "Check the bake now", close the
   menu: a message "Your baked models are up to date (N models checked)".
4. **Russian.** Switch the game to Russian, press the button: the message is
   readable Cyrillic (not "Р"-garbage).
5. **Nothing baked.** "Remove bake" in ZGO Setup, load a save: one reminder
   naming tools\zgo_setup; load again: none.
6. **(experimental) mod files**, on Proton: tick "Also look at the other
   mods' files", press "Check the bake now". With debug log, either the
   check runs quietly (it could read `Z:\...\modlist.txt`), or the log says
   `cannot read ... modlist.txt from the game (skipped)`: report which.
   Then disable a model mod in MO2 and reload: the message should name it
   "(disabled or removed)".
7. **ZGO Setup itself** (once the binaries exist): double-click
   `ZGO Setup.exe` on Windows and `zgo-setup.sh` on Linux; both must find MO2,
   the profile G.A.M.M.A and the game without help, and "Check if my bake is
   up to date" must say up to date right after a bake.

## 8. Risks and open questions

- **Release binaries need the user's permission.** The portable builds need
  a downloaded Python to run: python-build-standalone 3.12.10 for Linux, and
  the python.org 3.12.10 installer inside a Wine prefix for Windows. This
  session's permission check refused extracting and running the downloaded
  Python runtime, so neither was run. The safer route, PyInstaller from pip
  inside the dev container, works (all frozen tests pass) but uses the
  container's Python, which needs glibc 2.43: not shippable. If the user
  agrees, `dev/build_setup/build.sh all` does both builds from the pinned,
  hash-checked downloads and tests them; until then players have the launcher
  / `python3 zgo_setup.py` (needs numpy + tkinter) and the baker CLI.
- Windows `ZGO Setup.exe` is built without a console; the command line works,
  but output only with `--log FILE`. SmartScreen / antivirus may flag an
  unsigned PyInstaller program; signing is out of scope.
- The frozen programs run the ZGO folder's `.py` files; a future tool that
  imports a standard-library module the bundle lacks fails with an
  ImportError (`--selftest` imports every module and shows it). The spec
  bundles a generous list.
- The in-game size check sees load-order problems and missing files, not a
  mod updated in place that keeps its file size and its place; ZGO Setup's
  check (md5) and the experimental mod-files check see those.
- The size check assumes `fs_file.size_real` of a loose file equals its size
  on disk (true for loose files; the index calibration guards it).
- Mods with non-ASCII names are skipped by the experimental mod-files check
  (the game opens files with ANSI calls); ZGO Setup handles them.
- Windows Python 3.12 uses `spawn`, Linux 3.12 `fork`, the container's 3.14
  `forkserver`; the worker-path fix (`ZGO_SETUP_MOD` + `child_paths`) was
  tested with forkserver frozen and fork/forkserver from source, not yet with
  a frozen Windows `spawn`. `--selftest`'s "parallel workers" step checks
  exactly this on any build.
- While testing the launcher's error path on the host, it opened a KDE error
  dialog (kdialog) twice on the desktop for a few minutes before it was
  closed; the tests now set `ZGO_SETUP_NO_DIALOG=1`.
