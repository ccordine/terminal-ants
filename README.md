# Terminal Ants

A box of dirt, a queen, and a handful of workers. Leave it open and watch them
make a home. They dig tunnels one cell at a time, carry the dirt outside,
follow food trails, tend their brood, and expand the nest as the colony grows.

The colony runs itself. The default experience is a living ASCII screensaver
with a little colony simulation underneath it.

## Start watching

```sh
./ants
```

Or run `python3 -m terminal_ants` from this directory. Requires Python 3.10+
with its standard `curses` module, on Linux, macOS, or WSL. There are no runtime
packages to install. A terminal of 80 x 28 or larger is comfortable; the whole
dirt box fits automatically as you resize, down to 40 x 14.

```sh
./ants --no-hud                 # Just the dirt box
./ants --speed 20               # Watch construction happen faster
./ants --demo                   # An established, disposable colony
./ants --save saves/fern.json --name "Fern Hollow"  # A separate new colony
```

`--name` and `--seed` apply when creating a colony. Resume it using the same
`--save` path without those options. `--demo` never reads or writes your save.

## Watching and interacting

| Key | Action |
| --- | --- |
| `h` | Hide or show the HUD |
| `s` | Cycle 1x, 5x, 20x, and 60x simulation speed |
| `Space` | Pause or resume this viewing session |
| `f` | Scatter a few seeds on the surface |
| `i` | See the colony's needs, jobs, and planned excavation |
| `v` | Show the pheromone trails left by returning foragers |
| `a` | Inspect the next individual ant |
| `j` | Read the colony journal |
| `?` / `Esc` | Open help / close a panel |
| `q` | Save and quit |

`a` is a worker, `&` carries food, `%` carries soil, and `Q` is the queen.
`o`, `~`, and `O` are eggs, larvae, and pupae. `*` marks food. The selected ant
appears as `A`. Colors distinguish soil, ants, brood, and trails; use
`--monochrome` or `NO_COLOR=1` for plain terminals.

The ants can share a tile, so crowded passages may show several workers as
one character. Small terminals compress the view; the underlying dirt box
and the ants' positions stay the same.

## What the ants do

- **Gather food.** Foragers walk to surface seeds, collect a load, and carry it
  to the nest. Returning workers leave a fading pheromone trail that helps
  recruit others. Seeds naturally replenish, so the colony is self-sustaining.
- **Raise the next generation.** Nurses care for brood and attendants care for
  the queen. Food, care, and available nest space govern growth. Workers age
  and are replaced; the founding population is protected from collapse.
- **Build a home.** Brood calls for a nursery, crowding calls for more space,
  and full food stores call for a pantry. The colony chooses a location and
  shares a dig plan. Workers pathfind to exposed soil, excavate it, and haul
  its spoil to the surface. Dense soil takes more work.
- **Explore.** When essential needs are met, workers extend the nest with
  galleries and patrol the passages. Different seeds yield different homes.

The world contains individual ants, routes, soil cells, cargo, brood,
pheromones, surface food, and construction projects. Colony needs choose the
work; rooms only become usable after their cells have actually been dug.
The world is finite: a 78 x 34 dirt box supporting up to 96 workers and brood.

## Persistence

Your default colony lives in `saves/colony.json` beside the launcher, regardless
of the directory you launch it from. Set `TERMINAL_ANTS_SAVE` or use `--save`
to choose another location.

The game saves every ten seconds, after scattering seeds, and on normal exit,
Ctrl-C, or a termination signal. Saves use an atomic replacement and retain a
last-good `.bak` file. A process lock prevents two viewers from writing the
same colony. Damaged saves recover from the backup when possible and preserve
the damaged original; otherwise the game reports the problem and keeps the
files untouched.

When reopened, the same ant simulation catches up **up to 24 hours at 1x**,
including excavation, hauling, food collection, and hatching. Longer absences
receive the first 24 hours of progress. Catch-up can take a few seconds. No
background service is needed. Viewing speed and pause affect only the current
session; an exited colony resumes normal idle progress.

Inspect or render a colony without opening the viewer:

```sh
./ants --status
./ants --status --json
./ants --snapshot --width 100 --height 36
```

These commands also catch up and save. To experiment without changing your
colony, add `--demo`. `--advance SECONDS` adds up to 86,400 seconds of simulation
to a status or snapshot command; it intentionally advances that save.

## Programming instincts

Start with [`terminal_ants/instincts.py`](terminal_ants/instincts.py).
`labor_needs()` decides how many ants the colony wants gathering food and
nursing. `construction_need()` chooses the next kind of space the group needs.
Both are small functions intended for experiments: change the hunger threshold,
recruit more nurses, or change which needs take priority.

[`terminal_ants/model.py`](terminal_ants/model.py) contains individual behavior
in `_choose_job()` and `_act()`, pathfinding, excavation, lifecycle, and room
placement. [`terminal_ants/scene.py`](terminal_ants/scene.py) draws the actual
world; animation does not invent tunnels or ant positions.

Run the behavioral and persistence tests with the standard library:

```sh
python3 -m unittest discover -s tests -v
```
