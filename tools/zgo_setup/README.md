# Umbra Effects Setup

Bakes Umbra Gore & Effects' body models for **your** mod list, checks whether
that bake still fits your mod list, and removes it. It finds Mod Organizer 2,
your profile and the game by itself (it lives inside the Umbra Effects folder), and you
can change all three in the window.

Close the game before baking. A full bake of G.A.M.M.A. takes a few minutes
and about 6.5 GB (most of it the limb pieces, which you can untick).

## Starting it

| System | Start |
| --- | --- |
| Windows | double-click `Umbra Effects Setup.exe` |
| Linux (MO2 under Wine / Proton) | double-click `zgo-setup.sh` (or run `sh zgo-setup.sh`) |
| Linux, by hand | `./zgo-setup-linux` |
| Any system with Python 3.8+, numpy and tkinter | `python3 zgo_setup.py` |

The ready-made programs need nothing installed. `zgo-setup.sh` starts
`zgo-setup-linux`, and if that cannot run on your system it uses your own
`python3` instead (Debian/Ubuntu: `sudo apt install python3-numpy python3-tk`;
Fedora: `sudo dnf install python3-numpy python3-tkinter`; Arch:
`sudo pacman -S python-numpy tk`). `Umbra Effects Setup.exe` also runs under Wine or
Proton, next to MO2.

Keep the program in this folder: it runs the baker that came with this Umbra Effects
(`tools/zgo_baker`), so it always matches the installed version.

## The window

- **Your game**: the MO2 folder, the profile you play with, the game folder
  (the one with `db` and `bin`) and the Umbra Effects folder. Red text says what is
  missing; orange text is worth knowing but does not stop a bake (for example
  a second copy of Umbra Effects enabled in MO2).
- **What to bake**: body models (always), stump caps, limb pieces, wound
  sites, breakable props and kid mode for particles. Each box says what it
  gives and what it costs. The experimental parts are hidden under "Show the
  experimental parts" and are off; leave them off unless you are testing Umbra Effects.
- **Kid mode for particles** (on by default) lets kid mode hide blood and gore
  particles that are already flying (MCM: General -> Kid mode: hide particles
  already flying). With each bake it rebuilds Umbra Effects' particle shaders from your
  mod list and copies the gory effects other mods play (knife hits on flesh,
  anomalies tearing a body) into the Umbra Effects folder, changing only which shader
  they use. Under 1 MB, a few seconds. **Apply now** switches it on at once
  without a bake; **Undo...** sets every particle effect back to the game's
  own particle shaders (use it if particles look wrong). After an undo, kid
  mode cannot hide particles already flying, and the box stays unticked so a
  later bake keeps the undo.
- **Models your mod list loads**: how many character and mutant models come
  from which mod, and the size and time the bake will take. A red line means
  a mod that loads after Umbra Effects replaces baked models: drag Umbra Gore & Effects below it in MO2.
- **Your bake**: whether the bake still matches your mod list, and if not,
  why (a mod was added, removed, reordered or updated; Umbra Effects was updated; the
  game changed) and what to do.
- **Bake** (with a progress bar and **Cancel**: nothing in the Umbra Effects folder
  changes until the bake is complete), **Check if my bake is up to date**,
  **Remove bake** (also removes the copies of other mods' particle effects;
  Umbra Effects' own particle shader changes stay), **Cut props only**.
- The **Log** tab shows everything that happened; **Save log...** for bug
  reports. It is also written to `%LOCALAPPDATA%\zgo_setup\zgo_setup.log`
  (Windows) or `~/.cache/zgo_setup/zgo_setup.log` (Linux).

The game also checks the bake when a save loads, and tells you when Umbra Effects Setup
should be run again (MCM: Umbra Gore & Effects, Baked models).

## Without the window

    zgo-setup-linux --check            is the bake up to date? (exit code 0 = yes)
    zgo-setup-linux --plan             what a bake would make, and how large
    zgo-setup-linux --bake --yes       bake in the terminal
    zgo-setup-linux --remove --yes     remove the bake
    zgo-setup-linux --kid-particles-apply --yes    kid mode for particles on (no bake)
    zgo-setup-linux --kid-particles-revert --yes   undo: the game's own particle shaders
    zgo-setup-linux --selftest         check that the program works on this computer

Options: `--mo2 DIR --profile NAME --game DIR --jobs N`, `--no-caps`,
`--no-pieces`, `--no-wounds`, `--no-props`, `--no-kid-particles`,
`--cache DIR` (the work folder, needs as much free space as the bake),
`--log FILE`. On Windows the same
options work for `"Umbra Effects Setup.exe"`; it has no console, so add `--log FILE` to
read the output.

## When something goes wrong

- Run `--selftest` (or `Umbra Effects Setup.exe --selftest --log selftest.txt`) and
  include its output and the log in your bug report.
- "not allowed to change": close the game, and check that the Umbra Effects folder is
  not read-only.
- "The disk is full": free some space, untick "Limb pieces", or move the work
  folder to another drive with `--cache DIR`.
- Particles look wrong, or the game has trouble starting since Umbra Effects: press
  **Undo...** next to "Kid mode for particles" (or run
  `--kid-particles-revert --yes`), then start the game again.
- "Kid mode for particles was not updated for your mod list": the body models
  are baked all the same, and kid mode still hides Umbra Effects' own particles; the
  log says what was missing.
