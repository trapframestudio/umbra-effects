# Game bed: Umbra Gore & Effects in the real engine, headless

`gamebed.py` builds a throwaway copy of the game from an MO2 install (read only: it links the
winning files, never writes the install, its profile or its saves), runs it in gamescope's
headless backend under GE-Proton, and lets a driver script (`zz_zgo_gamebed.script`) play
scripted scenarios and log checks. This repo's files stand in for the mod's folder the way
`dev/deploy.py` would deploy them, so it tests the working tree, bake included.

    python3 dev/gamebed/gamebed.py run                     # single player: start, cut, gib, respawn, respawn_unfixed
    python3 dev/gamebed/gamebed.py run cut gib             # some scenarios
    python3 dev/gamebed/gamebed.py run --without bake      # bisect: no bake / no textures' archive / no ZGO
    python3 dev/gamebed/gamebed.py coop                    # host + client over xrRazom's LAN session on 127.0.0.1
    python3 dev/gamebed/gamebed.py coop --client-without bake
    python3 dev/gamebed/gamebed.py coop --client-baked-models-off

Exit code 0 means every driver finished and every check passed. Each run writes
`~/.cache/zgo-gamebed/out/<stamp>/`: `summary.txt`, the engine logs, the console output and the
screenshots (the driver asks; the runner takes them with `gamescopectl`).

## What it checks

| Scenario | Checks |
|---|---|
| `start` | the version is this repo's; the bake is in use and has models; textures from `db/mods/zgo_static.db0` are found |
| `cut` | a spawned stalker, killed, loses its left forearm and right calf (`zgo_dismember.sever_wound`): shown, capped, recorded, and the engine agrees (bones hidden, caps attached) |
| `gib` | a second stalker torn apart by a blast at its feet: the gibs are the body's own pieces |
| `respawn` | the cut body goes offline and comes back as a new game object (`alife():teleport_object` to where it lies): cuts and caps are back (the 1.8.3 fix) |
| `respawn_unfixed` | control: the same with ZGO's `net_destroy` handler skipped; the engine checks must see the cut lost, or `respawn` proves nothing |
| `load` | the save loads (for bisecting a crash, with `--without zgo`) |

`coop` runs a host bed (loads the save, hosts) and a client bed (`~/.cache/zgo-gamebed-client`,
joins from the main menu through xrRazom's direct-IP flow and starts from the faction screen).
The host runs `start`, `cut` and `gib` and relays each body's id; the client checks the same
things on its own copy of each body, and logs which objects lie around the gibbed body on both
sides. Both beds' gamedata must match (xrRazom's mod check), so the driver's role is in
`appdata/zgobed_role.txt`; at the main menu only `modxml_` scripts run, so
`modxml_zz_zgobed.script` hands the menu to the driver.

`--client-without bake` and `--client-baked-models-off` play a client whose bake isn't in use,
the setup co-op players reported as "no cuts, no stumps, odd gibs". Its cut and gib checks fail by
design (it exits 1); what to read is the client's `[ZGO]` lines (the handshake and each cut say
why it isn't shown) and its screenshots (intact bodies, nothing stray around them).

## Needs

- gamescope (with `gamescopectl`), GE-Proton (`ZGO_GAMEBED_PROTON`), and the runtime DLLs
  Umbra Setup keeps (`ZGO_GAMEBED_RUNTIME`; copied into the bed's own prefix once).
- A save in the game's `appdata/savedgames` (`--save`, default `player - autosave`).
- The MO2 install may be open: the bed only reads it. The mod may be unticked in the profile;
  the bed puts it at its place in `modlist.txt` either way.

The runner reads `--mo2`, `--profile`, `--game` and `--zgo` (see `--help`); the bed lives in
`ZGO_GAMEBED` (default `~/.cache/zgo-gamebed`).
