# ZGO development tooling

Nothing in `dev/` (or `tests/`, `docs/`) ships in the release zip.

## Container

All building happens in a distrobox container defined in `distrobox.ini`
(Fedora 44: mingw-w64 cross compiler for the native add-on, Python 3 + numpy
for the mesh baker, LuaJIT for the tests, Wine to run Windows builds).

    dev/setup.sh              # create / re-create zgo-dev after editing distrobox.ini
    dev/run.sh <command>      # run a command inside it, from the mod root

## Scripts

| Script | What it does |
|---|---|
| `test-all.sh` | every test suite in both model modes over several seeds (`SEEDS="2 9" dev/test-all.sh` to choose) |
| `gen_mcm_text.lua` | writes the MCM string tables (eng, rus) from `zgo_settings.script`; `--check` tells whether they are current (the settings test runs it) |
| `package.py` | builds `~/Desktop/Zone Gore Overhaul <version>.zip` without dev tooling, tests, docs or baked models |

## Rules for new features

- Every option goes into `zgo_settings.script` (name and explanation in both
  languages, grouped on the page for its concern), then
  `luajit dev/gen_mcm_text.lua`. Anything performance-relevant goes on the
  Performance page with a value per preset (potato .. ultra).
- Anything gory checks `zgo_util.gore()` before drawing (kid mode) but still
  sends its co-op line, so partners get it.
- Co-op: decisions on the host, drawing on every machine; say in
  `zgo_settings` whether a page or option is host- or player-decided.
- Run `dev/test-all.sh` before packaging.
