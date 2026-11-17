# Umbra Gore & Effects

Umbra Gore & Effects ("Umbra Effects" for short) overhauls blood, gore, dismemberment,
explosions and bullet impacts in S.T.A.L.K.E.R. G.A.M.M.A. (Anomaly), in single player and in
xrRazom co-op. Every hit is classified from the round that caused it, and the blood, wounds,
severed limbs, craters and debris follow from that. It is based on Painter of the Zone by sunn, with large amounts of additions and updates.

What changed in each version: [CHANGELOG.md](CHANGELOG.md).


## Requirements

- S.T.A.L.K.E.R. Anomaly with G.A.M.M.A., run through Mod Organizer 2 (MO2).
- Painter of the Zone and its xrRazom patch switched off: Umbra Effects does their job.
- For co-op: xrRazom, with the same mod list and the same Umbra Effects version on every
  machine.
- About 7.2 GB of disk space. Standard GAMMA installs just download from our mirror, nonstandard must bake the extra assets. The window shows the figure for your mod list before it
  starts. The program runs on Windows and Linux and needs nothing else installed.
- Some experimental options need the DirectX 10 or 11 renderer, and the native extensions need
  the xrRazom game executables.


## Install

1. In MO2, install the zip as a new mod ("Install a new mod from an archive") and name it
   **Umbra Gore & Effects**.
2. Disable "Painter of the Zone" and "Painter of the Zone - xrRazom Patch". If either stays on,
   Umbra Effects pauses itself and says so on screen: both would paint everything twice.
   Coming from Zone Gore Overhaul? Disable or remove it too. It is the same mod under its new
   name, and MO2 installs it as a new mod. Your MCM settings carry over; your old bake stays in
   the old folder, so run Umbra Effects Setup again (step 4).
3. Enable Umbra Gore & Effects. In MO2's left pane a mod lower in the list wins over the ones
   above it. Keep Umbra Gore & Effects above Screen Space Shaders, and below every mod that
   ships character models. (The second part only matters for baked models; Umbra Effects Setup
   names such mods.)
4. Recommended: run Umbra Effects Setup once (see "Baked models" below). It rebuilds the body
   models of your mod list so that limbs come off corpses too and wounds have somewhere to
   open. Run it again after changing mods with character models; the game reminds you.
5. Co-op: see "Co-op (xrRazom)" below.

**Updating.** Install the new zip under the same name. If you pick Replace in MO2, the old
folder is deleted, and your bake with it. Then load a save (the game checks the bake) or press
"Check if my bake is up to date" in Umbra Effects Setup, and bake again if it says so.
Coming from 1.8.1 or earlier, the check says your bake "needs packing": press **Bake** once.
It packs the bake's small parts into a few archives in a minute or two, without baking again,
and the game starts much faster afterwards.


## Baked models (Umbra Effects Setup)

Umbra Effects works without a bake, but dismemberment and wounds only work fully with one.
Umbra Effects Setup rebuilds every character and mutant model your mod list uses so that each
part that can come off (head, upper arm, forearm, hand, thigh, calf, foot) is its own
sub-mesh. The models look the same as the originals. The game drops a sub-mesh once its bones
are hidden, ragdoll or not, so with baked models limbs come off corpses too, and blasts that
arrive after death still take parts. The bake also adds a fitted stump cap for every cut,
light severed-limb models, wound sites and body gibs (the pieces a blast tears out of a body,
cut from that body's own model).

Without a bake, limbs only come off at the moment of death, wounds get the usual entry and
exit marks only, and explosions throw meat models (see "Known limits").

### Starting it

Close the game first. The program is in the mod's folder,
`<MO2>/mods/Umbra Gore & Effects/tools/zgo_setup/`. To get there from MO2, right-click
Umbra Gore & Effects in the left pane, pick "Open in Explorer", then open `tools\zgo_setup`.

| System                                         | Start                               |
|------------------------------------------------|-------------------------------------|
| Windows                                        | `Umbra Effects Setup.exe`           |
| Linux                                          | `zgo-setup-linux` or `zgo-setup.sh` |
| Any system with Python 3.8+, numpy and tkinter | `python3 zgo_setup.py`              |

`zgo-setup.sh` starts `zgo-setup-linux`, and if that cannot run on your system it uses your
own Python 3 instead. `Umbra Effects Setup.exe` also runs under Wine or Proton, next to MO2.
Keep the program in its folder: it runs the baker that came with this version of Umbra
Effects.

### Baking

Umbra Effects Setup finds MO2, your profile and the game by itself (you can change them under
"Your game"). It shows how many models come from which mod and how much space and time the
bake will take. A red line names a mod that loads after Umbra Effects and replaces baked
models: drag Umbra Gore & Effects below it in MO2.

Press **Bake**. With "Download a ready-made bake when one fits" ticked (the default), Umbra
Effects Setup first looks on Umbra's public download server for a bake made for G.A.M.M.A.'s
own mod list. If it fits your mod list and your bake settings, it downloads it
(about 3.5 GB) instead of baking. Otherwise, or if the download fails, it bakes on your
computer: about 3 minutes for G.A.M.M.A., with a progress bar. **Cancel** leaves everything as
it was; nothing in the mod's folder changes until the bake is complete.

What it bakes (sizes for G.A.M.M.A.):

| Tick box               | Size         | What it gives                                           |
|------------------------|--------------|---------------------------------------------------------|
| Body models (always)   | about 3 GB   | every body part can be cut off cleanly                  |
| Stump caps             | about 250 MB | a fitted flesh-and-bone cap for every cut               |
| Limb pieces            | about 3.2 GB | light severed limbs, closed at the cut (1)              |
| Wound sites            | a few MB     | where wounds can open (progressive wounds need them)    |
| Body gibs              | about 650 MB | the pieces an explosion tears out of a body (2)         |
| Breakable props        | a few MB     | barrels, crates, bottles and stools cut into pieces (3) |
| Kid mode for particles | under 1 MB   | particle shaders fitted to your mod list (4)            |

(1) Without them a cut limb is drawn from a copy of the whole body. (2) Without them explosions
throw meat models. (3) For "Objects break apart"; see "Objects (props)". (4) See "Kid mode".

The experimental parts are hidden under "Show the experimental parts" and stay off unless you
tick them; leave them off unless you are testing Umbra Effects.

Everything is written into the mod's own folder and listed in `zgo_bake_report.json`. The body
models are loose files under `gamedata/meshes` (they must win over other mods' copies); the
small parts (stump caps, limb pieces and gibs, about 79,000 files for G.A.M.M.A.) are packed
into a few game archives, `db/mods/zgo_bake_*.db0`, because the game reads every loose file
through MO2 each time it starts. **Remove bake** deletes exactly those files (and kid mode's copies of other mods' particle
effects). MCM -> Dismemberment -> "Use baked models" turns the bake off without deleting it.

### Keeping it up to date

Bake again when you add, remove or update a mod with character models. **Check if my bake is
up to date** tells you whether you need to, and why: a mod was added, removed, reordered or
updated, Umbra Effects was updated, or the game changed. The game also checks when a save
loads and tells you (MCM -> Baked models). **Cut props only** redoes just the breakable props,
for example after changing mods that replace prop models.

Keep Umbra Gore & Effects below every mod that ships character models in MO2's left pane, or
the game shows those mods' unbaked models.

**Cost:** about 4.5 times as many sub-meshes per NPC (draw calls; roughly 15 extra per
stalker), and distant NPCs lose the models' built-in level of detail. In testing there was no
noticeable FPS loss in a crowded base.

**Co-op:** every player runs Umbra Effects Setup for their own mod list. A player without a
bake in use (none, or "Use baked models" off) misses many cuts on bodies, with their severed
limbs and stump caps, and sees meat gibs; Umbra Effects tells them so when they join, and the
game log's `[ZGO]` lines say why the bake is not used.

### Experimental ways of drawing a cut

With a bake from 1.7 or newer, three experimental options can be tried on the Dismemberment
page. They are each player's own and off by default. Save first, and run probe 1 on the
Diagnostics page before the first one.

- **Cut with the off shader (experimental):** a part is switched off by Umbra Effects' own
  shader instead of by hiding its bones. It goes at once, before the body has fallen, and the
  joint above it never pinches.
- **Stump cap shape:** instead of "Meat disk", "Fitted to the cut" or "Fitted, fixed to the
  joint" use the bake's cap for that cut (flesh and a bone stub shaped like the wound), and
  "Inside the model" uses the caps inside the model (bake with `--experimental-caps`; needs the
  off shader).
- **Light severed limbs (experimental):** a flying limb is the bake's piece (only the part that
  came off, with a closed end).

Bodies whose model another mod replaced, and bakes from before 1.7, are drawn the old way.

### Without the window

    zgo-setup-linux --check            is the bake up to date? (exit code 0 = yes)
    zgo-setup-linux --plan             what a bake would make, and how large
    zgo-setup-linux --bake --yes       bake in the terminal (or download a ready-made bake that fits)
    zgo-setup-linux --list-prebaked    list the ready-made bakes (nothing is downloaded)
    zgo-setup-linux --pack --yes       pack a bake made before 1.8.2 into archives (Bake does it too)
    zgo-setup-linux --remove --yes     remove the bake
    zgo-setup-linux --selftest         check that the program works on this computer

`--no-download` bakes on your computer without looking for a ready-made bake. On Windows the
same options work for `"Umbra Effects Setup.exe"`; it has no console, so add `--log FILE` to
read the output. All options: `tools/zgo_setup/README.md`.

The baker also runs on its own: `python3 tools/zgo_baker/bake.py` (needs Python 3 with numpy;
`--no-pieces` leaves the limb pieces out, `--remove` deletes the bake).


## Features

### Hit profiles

Every hit is classified from the actual round (ammo section and impact speed): pistol,
intermediate rifle, full-power rifle, magnum or slug, anti-materiel, buckshot, explosion, melee
or claws. Everything below scales with it.

### Blood

**Trajectory blood.** Each hit throws several blood streams out of the exit wound, and some
back toward the shooter. The streams fly under gravity and are traced step by step; where and
how they land picks the decal:

- distance flown: thick splashes and heavy spatter only close to the wound (the range grows
  with calibre), medium spatter further out, then only fine spray and mist;
- glancing: directional spatter aimed along its travel;
- head-on: a radial splash (buckshot clusters, gore for heads);
- steep onto floors: a splash close by, drops further out;
- slow: single drops.

Bystanders in the way get stained. There are 15 categories with about 170 generated textures,
plus Painter's graded set.

**Drip runs.** Wet blood high on a wall runs: thin rivulets creep down over about 6 to 15
seconds, at different speeds, and stop with a bead (10 shapes; the length is limited by how
much wall there is above the floor). It is the same shader trick as the pools, so it costs
nothing per frame.

**Bodies and bleeding.** Entry and exit wounds on the victim (exits larger), smears when
someone dies against a wall, and slowly spreading death pools (12 shapes). The wounded bleed
by the engine's own bleeding value for that NPC: a sparse line of drops behind them as they
move, drops piling up and a small pool when a heavy bleeder stands still, and drips falling
from the wound itself. It stops when the bleeding stops (bandaged, healed). While they bleed,
the stain around the wound on their clothes spreads.

### Particles

Painter's particle library, picked by calibre and armour, plus this mod's own droplet effects:
stretched, gravity-driven drops that die on contact, so sprays read as streams instead of
puffs.

- **Armour:** sparks on every exoskeleton and helmet hit (penetrating or not), plate and cloth
  fragments, visor glass.
- **Wounds:** back spray from the entry, exit sprays that grow with energy.
- **Arteries:** hits to the neck, thigh (femoral), collarbone, upper arm, calf and forearm can
  open an artery. A jet pulses out of the wound on every heartbeat, follows the body as it
  moves, weakens beat by beat, dribbles in between, and paints the wall or floor where it
  lands. A killing shot still gets the last few beats.
- **Stumps** gush the same way.

### Dismemberment

Kills and corpses only. Big calibres and explosions take heads and limbs off from the hit bone
downward. Damage builds up on a body part, so a few rifle rounds into a dead man's arm will
take it off. Jaws can be shot off alone. Heads either come off whole or burst.

Severed parts fly off and tumble with simple physics: they bounce, roll and come to rest on
the ground, dripping, and leave a small pool. Gibs fly, and stumps get a cap and gush. A shot
that takes off a limb with an artery in it leaves the stump pumping. Direct RPG hits and IEDs
going off underfoot take the whole body apart: head, two to four limbs and a shower of gibs.
Dismemberment is saved with the game.

On a body that is already a ragdoll the engine can't hide arms, legs or the head (see "Known
limits"), so without baked models those cuts are only made at the moment of death; corpses can
still have the jaw shot off and get torn open by blasts.

### Progressive wounds (baked models)

Damage builds up where a body is hit. Every hit lands on the nearest wound spot the baker
marked on the model and adds to it by calibre: bruise, open wound, crater, down to the bone,
destroyed. A pistol opens and craters wounds but never reaches the bone by itself; rifles do;
slugs, magnums, anti-materiel rounds and explosions go all the way. Fragments and the blast
tear the side that faced the explosion. From a crater on, chunks of meat fly out of the wound
and a larger torn mark goes on the body. A destroyed head or limb on a dead body comes off
(the Dismemberment settings apply; the living never lose parts).

Experimental, off by default: MCM -> Wounds -> "Wound craters in the body (experimental, your
own)". With models baked with `--experimental-damage` (Umbra Effects Setup's "Damage meshes and
gib chunks (experimental)", 25-30 GB), wounds become real craters in the body that move with it
and its shadow: a bloody rim, fat and muscle on the walls, bone at the bottom of the deepest,
and the chunk that flies out is the piece cut from that very spot. DirectX 10/11 only.

### Explosions

The engine sends a grenade to a body as fragments (separate bullets) and a blast hit. Both are
collected per explosive and resolved once per body, so a grenade is one coherent event instead
of a pile of separate hits.

- **Fragments:** small entry wounds where each one actually hit, a short spray from the first
  few, sparks off exoskeletons and helmets (small fragments mostly stop there). Survivors
  bleed and can have an artery nicked.
- **Blast:** blood and meat thrown off the far side of the body, away from the explosion, and
  a stain on the side that faced it. No sparks, no exit wounds.
- **The dead:** decided on the hit that kills, before the body turns into a ragdoll. A part
  goes by how close its nearest point was to the charge (distance scaled by the size of the
  charge), and it is cut at the joint nearest the body that was still inside the blast: a
  grenade at someone's feet takes feet or lower legs, not arms or the head. Only heavy charges
  (a direct RPG hit, an IED going off underfoot) take the whole body apart; grenades, launcher
  rounds and mines never do.
- **Corpses:** the same, with baked models; without them corpses are torn open and showered
  with meat.

Dismemberment from explosions: always for yours and your co-op partners'. NPC explosives too
when they go off within the detail distance of you (MCM -> Performance -> "Detail distance
(m)", 55 m on the High preset) and General -> "NPC fights bleed too" is on; further away they
get no explosion gore from this mod.

Every body an explosion hurts or kills gets one line in the game log: distance, damage and
this mod's overpressure share, fragment hits, and what came off and why not. MCM -> General ->
"Log explosions" turns it off.

### World impacts

Rounds that hit walls, floors, trees and objects leave marks sized by calibre on top of the
game's own bullet holes: a pistol round chips, a rifle round gouges, buckshot peppers. Dust,
chips, splinters and sparks match the surface (concrete, brick, plaster, wood, metal, earth).
Keep firing at one spot and the damage builds up: chips turn into cracks, then a deep gouge,
and sustained fire knocks a dark breach into masonry and wood (metal dents and tears). Marks
only: walls don't open and bullets don't pass through.

Explosions leave a scorched crater sized by the charge (grenade, VOG, mine, RPG, IED), pock
marks from fragments on the walls and floor around it, a ring of dust rolling out along the
ground and smoke that hangs for a while. Indoors, grit and dust rain from the ceiling.
Optional (experimental): clods of earth and chunks of concrete thrown out of the crater, and a
rim of thrown-up dirt or rubble.

Settings: MCM -> World impacts; how many marks, effects and pieces, their lifetime and range
are on the Performance page. This is not gore, so kid mode leaves all of it alone.

### Objects (props)

Bullets throw splinters, dust, sparks, glass or fluff off crates, barrels, bottles, lamps and
furniture, and shove loose objects harder (heavier rounds more, heavy objects less).
Explosions lift and spin them. A hole in a barrel, canister or milk can below its fill line
leaks water, fuel, oil or chemicals into a growing puddle until it runs dry; gas bottles hiss
out a jet. Shot lamps shower glass, or flicker if they survive. Crates, boards and jars the
game can already break now burst with dust and splinters.

Small crates, chairs, stools, bottles and jars that the game can't break wear down under fire,
knife hits and explosions, and come apart into pieces (the game's own crate and bottle parts).
Barrels and milk cans break too once Umbra Effects Setup's "Breakable props" step has cut
pieces from the models your mod list uses (a few seconds; run it again after changing mods
that replace prop models). Explosions shatter glass nearby. Quest items, stashes, doors,
explosive barrels and anything with its own script never break.

Settings: MCM -> Props and destruction; how many effects, pieces and leaks, their lifetime and
range are on the Performance page. This is not gore, so kid mode leaves all of it alone.

### Native extensions (experimental, off by default)

An optional engine add-on (`bin\zgo_native.dll`) for the xrRazom game executables, for what
scripts can't do. It only switches on when it recognises the exact exe: it looks up every
engine function it needs and compares its code byte by byte. On any other exe it stays off and
says why in the log. There is nothing to set up or bake: it finds what it needs when the game
starts.

First feature: broken limbs. Bodies close to an explosion get arms and legs bent at broken
angles, and with a heavy charge a crushed chest or a dislocated shoulder. Only bodies, only
once they have gone limp, and the same on every co-op machine. It needs both switches on the
MCM page Native extensions, "Native extensions (experimental)" and "Bone hooks: bend and crush
bodies (experimental)", on every player's computer in co-op.


## Changes to G.A.M.M.A. explosions

This part is opinionated; its options are on MCM -> Explosions.

G.A.M.M.A. made NPCs very hard to hurt with explosives, for two reasons:

- armour subtracts its whole explosion protection from a blast (0.1 to 1.6, against 3 for a
  hand grenade before distance falloff), so a grenade at someone's feet could do nothing at
  all;
- "G.A.M.M.A. No NPC Friendly Fire" cancels every hit an NPC lands on a friendly or neutral
  NPC, a grenade's blast and shrapnel included, so an NPC's grenade hurt nobody but its target.

Umbra Effects overrides both, on purpose:

- **Realistic blast damage:** a blast hit on an NPC or mutant does at least what its
  overpressure would. From a hand grenade to the nearest of chest, pelvis, head or knees:
  about 1.9 at 0.5 m (a full health bar is 1), about 1.0 at 1 m, about 0.27 at 2 m, about 0.1
  at 3 m. Heavier charges reach further (cube-root scaling: an RPG warhead counts as 3
  grenades, an IED as 6, a mine as 1.5). Armour takes the edge off (an exoskeleton with helmet
  about a third, a jacket hardly anything), a wall between the body and the blast cuts it to
  about 30%, and the creature's own explosion immunity applies: story characters with 0 are
  untouched, as are the ones G.A.M.M.A.'s storyline script protects. Where the engine's own
  number is higher, it stands. Fragments are left as G.A.M.M.A. has them.
- **Grenades hurt allies:** explosions get past No NPC Friendly Fire. Bullets are still
  filtered and that mod still patches relations, so allies caught in a blast stay allies.

So a grenade at someone's feet kills them and takes feet or lower legs; at 2-3 m it wounds;
heavy armour can survive what kills a man in a jacket. The player is not affected
(G.A.M.M.A.'s own damage model still applies to you). In co-op the host decides, as with
everything else.


## Settings (MCM)

Everything is in MCM -> Umbra Gore & Effects; hover over an option for what it does.
Everything is on by default except Kid mode, Debug log and the options marked experimental.
The pages:

- **General:** on/off, kid mode (and hiding particles already flying, experimental),
  NPC-vs-NPC blood ("NPC fights bleed too"), the explosion log, the debug log.
- **Performance:** the quality preset and the sliders it sets (see "Quality presets").
- **Blood:** amount, wounds on bodies, blood on bystanders, trails, drip runs, death pools and
  their size.
- **Particles:** on/off, intensity, arterial spurts, armour feedback.
- **Dismemberment:** heads, limbs, mutants, shooting bodies, chance, severed limbs, gibs and
  their look, stump caps and their shape, full gibbing, baked models, cutting with the off
  shader, light severed limbs.
- **Baked models:** the bake check when a game loads, its reminder, and a button to check the
  bake now.
- **Wounds:** progressive wounds, how fast they deepen, marks, chunks, destroyed parts coming
  off, wound craters (experimental).
- **Explosions:** realistic blast damage and its strength, grenades hurting allies.
- **Props and destruction:** hit effects, pushes, blasts, leaks, bursting crates, lamps,
  objects breaking apart and how tough they are, melee, glass, sounds.
- **World impacts:** bullet marks, damage building up, mark size, hits on objects, NPC
  gunfire, craters, rubble (experimental), dust and sparks, deep marks (experimental).
- **Native extensions (experimental):** loading the engine add-on, its bone hooks, broken
  limbs from explosions and their strength, a status report for the log.
- **Diagnostics:** smoke tests for bug reports; shown while General -> "Debug log" is ticked.

Which of these the host decides in co-op: see "Co-op (xrRazom)" below.

### Quality presets

The Performance page has a "Quality preset": Potato, Low, Medium, High (the default) and
Ultra. Pick one, adjust any slider, then press Accept. Each preset sets these sliders:

| Slider                                    | Potato | Low | Medium | High | Ultra |
|-------------------------------------------|-------:|----:|-------:|-----:|------:|
| Blood lifetime (seconds)                  |    180 | 300 |    600 |  900 |  1800 |
| Blood streams per hit                     |      2 |   3 |      5 |    7 |    10 |
| Spreading wound stains                    |      6 |  10 |     16 |   24 |    40 |
| Particle effects per second               |      8 |  14 |     20 |   28 |    48 |
| Particle effects at once                  |     64 | 112 |    176 |  256 |   384 |
| Severed parts and gibs at once            |      3 |   6 |     10 |   14 |    24 |
| Severed parts: time on the ground (s)     |     45 |  90 |    150 |  240 |   480 |
| Severed parts: removal distance (m)       |     50 |  80 |    110 |  150 |   220 |
| Detail distance (m)                       |     25 |  35 |     45 |   55 |    80 |
| Explosion victims per frame               |      1 |   1 |      2 |    2 |     4 |
| Jobs per frame                            |      8 |  12 |     18 |   24 |    40 |
| World impacts: marks per second           |      6 |  10 |     16 |   24 |    40 |
| World impacts: mark lifetime (s)          |     60 | 120 |    240 |  480 |   900 |
| World impacts: dust and sparks per second |      6 |  10 |     18 |   28 |    48 |
| World impacts: distance (m)               |     30 |  45 |     60 |   80 |   120 |
| World impacts: damaged spots remembered   |     64 | 128 |    256 |  512 |  1024 |
| World impacts: rubble and clods at once   |      0 |   4 |      8 |   14 |    24 |
| Explosion smoke: hang time (s)            |      0 |   6 |     10 |   15 |    25 |
| Object effects per second                 |      6 |  10 |     16 |   24 |    40 |
| Pieces of broken objects at once          |      8 |  16 |     28 |   40 |    64 |
| Pieces: time on the ground (s)            |     20 |  40 |     60 |   90 |   180 |
| Leaking containers at once                |      1 |   2 |      4 |    6 |    10 |
| Object effects distance (m)               |     20 |  30 |     45 |   60 |    90 |
| Puddles: lifetime (s)                     |    120 | 240 |    480 |  900 |  1800 |
| Bodies with wound craters                 |      2 |   4 |      6 |   10 |    16 |
| Wounds kept per body                      |      4 |   6 |      8 |   12 |    16 |
| Wound updates per second                  |      1 |   2 |      3 |    4 |     6 |
| Bodies with broken limbs at once          |      4 |   8 |     12 |   16 |    24 |

### Diagnostics

The Diagnostics page appears while General -> "Debug log" is ticked. It holds smoke tests
("probes") for the engine features later versions of this mod build on. Each button runs one
probe when you close the menu. It writes PASS, FAIL or MANUAL (judge it by eye) to the log and
to `appdata\zgo_probe_report.txt`, says on screen what to look for, and puts back everything it
changed. After a probe you judge by eye, press "The last probe looked right" or "The last probe
looked wrong". Send the report file with a bug report.

- **Run all safe probes:** baked models in use, FFI, the kid mode shader lane, co-op
  comparison. Changes nothing; blood hides for a few seconds.
- **5. Save and reload: start:** press it, save, load that save and wait 8 seconds: bodies
  with parts cut off must come back the same.
- **6. Co-op: compare machines:** the host compares what every player sees of the bodies
  nearby (a client's button asks the host).
- **Experimental probes** (tick "Allow the experimental probes (experimental)", press Accept
  and reopen the menu; save first, because if a shader fails to compile the game closes):
  1 Off shader, 2 Pass-through shader, 3 Digit textures (Umbra Effects shaders on NPCs for a
  few seconds), 7 Props (single player: a loose object's model is swapped and back).

The probes need something near you (NPCs, bodies, cut bodies, a small loose object) and say so
when there is none. The ones you judge by eye can only tell you what to look for.


## Kid mode

MCM -> General -> "Kid mode": one tick and gore is gone from this computer at once. Blood on
walls, floors and bodies (the game's own included), blood sprays, pools, severed parts, gibs,
stump caps and the native extensions' broken limbs disappear, including what is already there,
and bodies cut up with baked models get their parts back. Explosions, sparks, dust and debris
stay, world impacts and breaking objects are not touched, and nothing about how the game plays
changes. Untick it and the gore comes back, cuts included. In co-op it only changes your
screen; your partners still see everything.

**Particles already flying.** Kid mode stops new blood effects at once, but blood droplets
already in the air finish their flight, and a few effects other mods play themselves (knife
hits, anomalies tearing a body) still show blood. "Kid mode: hide particles already flying
(experimental)" (off by default, shown while Kid mode is ticked) hides those too: the game
switches their particle shader off on your screen. It needs DirectX 10 or 11 and the xrRazom
game exe, and has not been tested in game yet. Sparks, dust, smoke and armour hits always stay
visible. The effects other mods play are only covered after Umbra Effects Setup's "Kid mode for
particles" step (on by default), which also covers gory effects a mod ships only inside its
`particles.xr` (as Cinematic VFX and HollywoodFX do).

**If particles look wrong** after installing Umbra Effects, press "Undo..." next to "Kid mode
for particles" in Umbra Effects Setup. It undoes Umbra Effects' particle shader change
completely; "Apply now" puts it back. Close the game first; only files in this mod's folder
change. After an undo, kid mode cannot hide particles already flying, and the box stays
unticked so a later bake keeps the undo. Without the window: `--kid-particles-revert --yes`
(and `--kid-particles-apply --yes`), or `python3 tools/zgo_kidfx/kidfx_pe.py revert` (and
`apply`).

**Limits.** A body cut up without baked models stays cut while kid mode is on (its ragdoll was
built without the parts), and one killed during kid mode stays whole afterwards.


## Co-op (xrRazom)

Every player needs the same mod list and the same Umbra Effects version, and every player
runs Umbra Effects Setup for their own mod list.

The host decides everything and sends compact effect lines to everyone; each client draws the
same decals, particles, pools, drip runs and severed limbs. Flying limbs and gibs use a seeded
fixed-step simulation, so they land in the same place on every machine. Clients forward their
own bullet impacts so the host knows their ammo, and draw the host's particle effects within
their own performance limits.

The host also tells every client which Umbra Effects version it runs and what it baked. When a
client differs (another version, no bake, a bake from a different mod list or with other
options), that player gets one notice in English or Russian, and the log says what differs.
Nothing is refused; the client just draws some things the simpler way. Players on 1.7 or newer
see each other's effects; older versions use another sync protocol, and the two simply don't
see each other's effects (the log says so).

**Settings in co-op.** Options that change what happens in the world are the host's: xrRazom
shows the host's values on clients and locks them.

- **The host's:** the Blood, Particles, Dismemberment, Wounds, Explosions, Props and
  destruction, and World impacts pages; General -> "NPC fights bleed too"; Native
  extensions -> "Broken limbs from explosions" and "Strength of broken limbs".
- **Each player's own:** General (apart from the above, so kid mode is per player),
  Performance, Baked models and Diagnostics; the first two switches on Native extensions; and
  on the host's pages: Dismemberment -> "Gib look", "Use baked models", "Stump cap shape",
  "Light severed limbs" and "Cut with the off shader"; Wounds -> "Wound craters in the body";
  World impacts -> "Draw impact dust and sparks" and "Deep impact marks"; Props and
  destruction -> "Hit effects on objects", "Breaking crates burst" and "Breaking sounds".

A native extension feature only runs when every player in the session has it switched on and
working. A player without the "Breakable props" pieces sees the game's own parts instead.
Umbra Effects Setup's experimental "Game breaks crates and stools itself" is untested in
co-op; leave it off there.


## Troubleshooting

- **"Umbra Gore & Effects is paused" on screen:** Painter of the Zone or its xrRazom patch is
  enabled. Disable it in MO2.
- **The game takes minutes to start:** a bake made before 1.8.2 is about 79,000 loose files, and
  the game reads each one through MO2 at every start (the log's `Init FileSystem` line says how
  long that took). Press "Check if my bake is up to date" in Umbra Effects Setup; if it says the
  bake needs packing, press **Bake** (or run `--pack --yes`).
- **Cuts, stumps or gibs don't show (a co-op partner sees props or meat instead):** run
  "Check if my bake is up to date" in Umbra Effects Setup on that computer. "The bake is up to
  date, but the game doesn't use it" names the reason: Umbra Gore & Effects unticked in MO2, a
  copy outside MO2's mods folder, or the MCM option "Use baked models" off. The game log's
  `[ZGO]` lines say the same (`body bake ... is not in use`).
- **You baked before installing the mod in MO2** (Setup run from the unpacked zip), **or in
  another copy than the one MO2 loads:** the game never sees that bake. Close MO2, start Umbra
  Effects Setup from that copy, choose MO2's folder and profile, and press **Install into MO2**
  (or **Repair**): it installs the copy into MO2 and ticks it if MO2 has none, and moves the bake
  into the copy the game loads (or removes it if it no longer fits your mod list), then offers to
  open Setup from the installed copy. Setup won't bake anywhere else.
- **The game crashed while loading:** before you start it again, copy
  `appdata\logs\xray_<name>.log` from the game's folder somewhere safe: the next start
  overwrites it, and the end of that log says why it crashed.
- **The game says to run Umbra Effects Setup again:** press "Check if my bake is up to date"
  in Umbra Effects Setup; it says what changed. A mod that loads after Umbra Effects and
  replaces baked models shows as a red line: move Umbra Gore & Effects below it in MO2.
- **Particles look wrong, or the game has trouble starting since Umbra Effects:** press
  "Undo..." next to "Kid mode for particles" in Umbra Effects Setup (or run
  `--kid-particles-revert --yes`), then start the game again.
- **"The disk is full" while baking:** free some space, untick "Limb pieces" (the largest
  part), or move the work folder to another drive with `--cache DIR`.
- **"not allowed to change":** close the game, and check that the mod's folder is not
  read-only.
- **"Kid mode for particles was not updated for your mod list":** the body models are baked
  all the same, and kid mode still hides Umbra Effects' own particles. The log says what was
  missing.
- **Reporting a bug:** for Umbra Effects Setup, run `--selftest` (on Windows:
  `"Umbra Effects Setup.exe" --selftest --log selftest.txt`) and include its output and the log
  ("Save log..." on the Log tab; it is also written to
  `%LOCALAPPDATA%\zgo_setup\zgo_setup.log` on Windows or `~/.cache/zgo_setup/zgo_setup.log` on
  Linux). In game, include the game log: "Log explosions" (on by default) writes a line for
  every body an explosion reaches, "Debug log" writes detailed `[ZGO]` lines, the Diagnostics
  probes write `appdata\zgo_probe_report.txt`, and Native extensions -> "Write a status report
  to the log" reports what the add-on found.


## Known limits

- **Ragdolls.** Once a body is a ragdoll, the engine's physics rewrites the position of every
  bone that has a physics part (pelvis, spine, head, upper arms, forearms, hands, thighs,
  calves, feet) every frame, so hiding one does nothing. A part removed before the ragdoll is
  built is gone for good (saved games keep it that way). So limbs come off at the moment of
  death, not afterwards, and this mod skips a cut it can't show rather than throwing a limb off
  a body that still has it. Baked models lift this: there a part is hidden once the ragdoll
  exists (hidden earlier, the joint above it would pinch), and for the instant of a save the
  cut parts are shown so the saved ragdoll loads back whole; the cuts are re-applied from this
  mod's save data. With "Cut with the off shader" (experimental) a baked part is switched off
  by a shader at once, and its bones are hidden only once the ragdoll exists, so the joint
  never pinches.
- **Wound craters** are experimental and off by default. They need models baked with
  `--experimental-damage` (much larger) and the DirectX 10/11 renderer, and up to four craters
  per body part are drawn. Without them wounds still deepen, throw chunks and tear limbs off
  bodies, shown with wound marks. Wounds need the wound sites of a bake from 1.7 or newer;
  without baked models bodies get the usual entry and exit marks only.
- **Severed limbs** are the victim's own model with everything but the limb collapsed into the
  stump (or, with "Light severed limbs" and a bake from 1.7 or newer, the bake's piece of that
  limb), as level script attachments, moved by this mod's own little physics (the engine gives
  attachments no physics). They collide with the level, not with other objects, and are not
  saved: after loading, bodies stay dismembered but the loose pieces are gone.
- **Drip runs** are pre-made shapes revealed over time by the shader; blood can't drip in real
  time on surfaces.
- **Body gibs** need a bake from 1.7.1 or newer. Without one, and with "Gib look" set to "Meat
  models (as before 1.7.1)", gibs and stump caps use meat meshes from another mod (G.A.M.M.A.
  has them). Body gibs show the body's skin and clothes but leave no hole where they came from.
- **World impact marks** are decals: walls never open, and marks are not kept in saves. The
  game's own marks around explosions (`[explosion_marks]`) are made a little larger and get
  scorch textures from this mod; they don't follow the MCM options.
- **Deep impact marks** (experimental) need the `effects_wallmark.s` file shipped with this
  mod; another mod that replaces that file turns them back into ordinary marks.
- **Broken objects** are gone for good (also after loading a save); their pieces, leaks and
  puddles are not saved. The pieces are visual only: they don't block bullets, can't be picked
  up and don't push other objects. Window panes are part of the level and never break.
- **The "Breakable props" pieces** are not in the mod's zip: Umbra Effects Setup makes them
  for your mod list.
- **"Game breaks crates and stools itself"** (experimental, in Umbra Effects Setup) replaces
  those crate and stool models with copies that the game breaks on its own. Untested in co-op.
- **Native extensions** are experimental and off by default. They only work on the xrRazom
  executables they recognise (all eight of xrRazom 1.4 and of xrRazom 1.5); after an xrRazom
  update they may switch themselves off until the mod is updated. Broken limbs are a visual
  change of the body's bones: the ragdoll's physics and collision stay as they were.


## Credits

Umbra Gore & Effects is built on, and redistributes parts of, Painter of the Zone by sunn,
which in turn builds on the work of others. [CREDITS.txt](CREDITS.txt) names everyone, and lists
what was taken from Painter of the Zone and how it was changed.


## License

The parts taken from Painter of the Zone are under the Apache License 2.0; the full text is in
[LICENSE-PainterOfTheZone.txt](LICENSE-PainterOfTheZone.txt), and CREDITS.txt lists those files.
The two typefaces in Umbra Effects Setup are under the SIL Open Font License 1.1 (texts in
`tools/zgo_setup/assets/fonts`).
