"""A dirt box, individual ants, and a shared set of colony instincts.

Workers must reach and excavate each soil cell, then carry its spoil outside.
The same fixed-step simulation runs while watching and while away.
"""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import asdict, dataclass, field
import math
import random
from typing import Any

from .instincts import construction_need, labor_needs

SCHEMA_VERSION = 1
STEP = 1.0
DAY = 600.0
MAX_OFFLINE = 24 * 60 * 60
MAX_ANTS = 96
WIDTH, HEIGHT, SURFACE = 78, 34, 3
WEATHERS = ("clear", "clear", "breezy", "drizzle", "clear", "mist")
TASKS = {"idle", "forage", "return", "dig", "haul", "nurse", "tend", "patrol", "rest"}


@dataclass
class Ant:
    ident: int
    pos: int
    task: str = "idle"
    target: int = -1
    path: list[int] = field(default_factory=list)
    cargo: str = ""
    amount: int = 0
    work: int = 0
    age: float = 0.0


@dataclass
class Brood:
    age: float = 0.0


@dataclass
class Project:
    kind: str
    center: int
    cells: list[int]
    complete: bool = False


@dataclass
class Event:
    at: float
    text: str


@dataclass
class Colony:
    name: str
    seed: int
    tiles: list[str]
    queen: int
    ants: list[Ant]
    brood: list[Brood]
    projects: list[Project]
    patches: dict[int, float]
    ticks: int = 0
    remainder: float = 0.0
    food: float = 38.0
    care: float = 85.0
    queen_care: float = 85.0
    egg_clock: float = 0.0
    next_ant: int = 9
    spoil: int = 0
    total_dug: int = 0
    total_hatched: int = 0
    total_gathered: float = 0.0
    gifts: int = 0
    last_gift: float = -60.0
    scent: dict[int, float] = field(default_factory=dict)
    events: list[Event] = field(default_factory=list)
    _routes: dict[int, dict[int, int]] = field(default_factory=dict, repr=False, compare=False)
    _open: set[int] = field(default_factory=set, repr=False, compare=False)
    _frontier: list[int] = field(default_factory=list, repr=False, compare=False)
    _counts: Counter = field(default_factory=Counter, repr=False, compare=False)

    def __post_init__(self) -> None:
        self._open = {i for i, cell in enumerate(self.tiles) if cell == "." or (cell == " " and i // WIDTH == SURFACE)}
        self._refresh_frontier()

    @classmethod
    def new(cls, name: str = "Mosslight Colony", seed: int | None = None) -> Colony:
        seed = random.SystemRandom().randrange(2**31) if seed is None else seed
        rng = random.Random(seed)
        tiles = [" " if i // WIDTH <= SURFACE else (":" if rng.random() < 0.13 else "#") for i in range(WIDTH * HEIGHT)]
        queen = 8 * WIDTH + WIDTH // 2
        for y in range(SURFACE + 1, 9):
            tiles[y * WIDTH + WIDTH // 2] = "."
        for pos in (queen - 1, queen + 1):
            tiles[pos] = "."
        colony = cls(
            name=name, seed=seed, tiles=tiles, queen=queen,
            ants=[Ant(i + 1, queen + (i % 3) - 1) for i in range(8)],
            brood=[Brood(20), Brood(95), Brood(165)], projects=[],
            patches={SURFACE * WIDTH + x: 30.0 for x in (12, 26, 51, 65)},
        )
        cells = colony._room_cells(WIDTH // 2, 8, 3, 2, rng)
        colony.projects.append(Project("queen's chamber", queen, sorted(cells)))
        colony._refresh_frontier()
        colony.note("A queen shelters in a crack in the soil. Her workers begin making a home.")
        return colony

    @property
    def seconds(self) -> float:
        return self.ticks * STEP + self.remainder

    @property
    def day(self) -> int:
        return self.ticks // int(DAY) + 1

    @property
    def night(self) -> bool:
        return self.ticks % int(DAY) >= DAY * 0.64

    @property
    def weather(self) -> str:
        index = self.ticks // 180
        return WEATHERS[(self.seed + index * 7 + index // 6) % len(WEATHERS)]

    @property
    def workers(self) -> int:
        return len(self.ants)

    @property
    def brood_count(self) -> int:
        return len(self.brood)

    @property
    def stages(self) -> tuple[int, int, int]:
        return tuple(sum(min(2, int(b.age // 75)) == stage for b in self.brood) for stage in range(3))

    @property
    def rooms(self) -> int:
        return sum(project.complete for project in self.projects)

    @property
    def capacity(self) -> int:
        return min(MAX_ANTS, 12 + sum(14 if p.kind == "nursery" else 5 for p in self.projects if p.complete))

    @property
    def food_capacity(self) -> int:
        return 60 + sum(75 for p in self.projects if p.complete and p.kind == "pantry")

    @property
    def pantry(self) -> int:
        return next((p.center for p in self.projects if p.complete and p.kind == "pantry"), self.queen)

    @property
    def nursery(self) -> int:
        return next((p.center for p in self.projects if p.complete and p.kind == "nursery"), self.queen)

    @property
    def current_project(self) -> Project | None:
        return next((p for p in self.projects if not p.complete), None)

    @property
    def digging_progress(self) -> float:
        project = self.current_project
        return sum(self.tiles[pos] == "." for pos in project.cells) / len(project.cells) if project else 1.0

    @property
    def roles(self) -> Counter:
        return Counter(ant.task for ant in self.ants)

    @staticmethod
    def neighbors(pos: int) -> tuple[int, ...]:
        x, y = pos % WIDTH, pos // WIDTH
        return tuple(ny * WIDTH + nx for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1))
                     if 1 <= nx < WIDTH - 1 and SURFACE <= ny < HEIGHT - 1)

    @staticmethod
    def distance(a: int, b: int) -> int:
        return abs(a % WIDTH - b % WIDTH) + abs(a // WIDTH - b // WIDTH)

    def note(self, message: str) -> None:
        self.events.append(Event(self.ticks * STEP, message))
        self.events = self.events[-40:]

    def scatter_food(self) -> str:
        if self.seconds - self.last_gift < 60:
            return "The last seeds are still settling. Give it a moment."
        pos = SURFACE * WIDTH + WIDTH // 2 + 6
        self.patches[pos] = min(100.0, self.patches.get(pos, 0.0) + 25.0)
        self.last_gift = self.seconds
        self.gifts += 1
        self.note("Seeds fall onto the soil. Foragers will have to find and carry them home.")
        return "Seeds scattered on the surface. Watch the foragers collect them."

    def advance(self, seconds: float) -> None:
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("Elapsed time must be finite and nonnegative")
        accumulated = self.remainder + seconds
        steps = int((accumulated + 1e-9) // STEP)
        self.remainder = max(0.0, accumulated - steps * STEP)
        for _ in range(steps):
            self.ticks += 1
            self._step()

    def _step(self) -> None:
        self._counts = self.roles
        for ant in self.ants:
            ant.age += STEP
            self._act(ant)
        self.food = max(0.0, self.food - (self.workers * 0.004 + self.brood_count * 0.002 + 0.006) * STEP)
        self.care = max(0.0, self.care - self.brood_count * 0.014 * STEP)
        self.queen_care = max(0.0, self.queen_care - 0.04 * STEP)
        growth = STEP * (0.30 + self.care * 0.007) * (1.0 if self.food > 1 else 0.15)
        hatchlings = 0
        for brood in self.brood:
            brood.age += growth
            if brood.age >= 225:
                self.ants.append(Ant(self.next_ant, self.nursery))
                self.next_ant += 1
                hatchlings += 1
        if hatchlings:
            self.brood = [b for b in self.brood if b.age < 225]
            self.total_hatched += hatchlings
            if self.total_hatched <= 8 or self.total_hatched % 10 == 0:
                self.note("A pale new worker emerges, stretches her legs, and joins the colony.")
        self.egg_clock = min(60.0, self.egg_clock + STEP)
        if self.egg_clock >= 60 and self.workers + self.brood_count < self.capacity and self.food > 12 and self.queen_care > 25:
            self.brood.append(Brood())
            self.food -= 1.5
            self.egg_clock = 0.0
        if self.ticks % 10 == 0:
            for pos in list(self.scent):
                self.scent[pos] *= 0.88
                if self.scent[pos] < 0.3:
                    del self.scent[pos]
            for ant in list(self.ants):
                if ant.age > 21600 + ant.ident % 7200 and self.workers > 8 and ant.task == "idle" and not ant.cargo:
                    self.ants.remove(ant)
            for pos in self.patches:
                self.patches[pos] = min(100.0, self.patches[pos] + (1.8 if self.weather == "drizzle" else 1.5))
            self._consider_building()

    def _set_task(self, ant: Ant, task: str, target: int, destination: int | None = None) -> bool:
        destination = target if destination is None else destination
        route = self._route(ant.pos, destination)
        if route is None:
            return False
        self._counts[ant.task] -= 1
        self._counts[task] += 1
        ant.task, ant.target, ant.path, ant.work = task, target, route, 0
        return True

    def _idle(self, ant: Ant) -> None:
        self._counts[ant.task] -= 1
        self._counts["idle"] += 1
        ant.task, ant.target, ant.path, ant.work = "idle", -1, [], 0

    def _choose_job(self, ant: Ant) -> None:
        foragers, nurses = labor_needs(self.workers, self.brood_count, self.food / self.food_capacity)
        if self._counts["forage"] + self._counts["return"] < foragers:
            patches = [pos for pos, amount in self.patches.items() if amount >= 1]
            if patches:
                targets = Counter(a.target for a in self.ants if a.task == "forage")
                target = min(patches, key=lambda p: self.distance(ant.pos, p) + targets[p] * 9 - self.scent.get(p, 0) * 0.2)
                if self._set_task(ant, "forage", target):
                    return
        if self.queen_care < 90 and not self._counts["tend"]:
            if self._set_task(ant, "tend", self.queen):
                return
        if self._counts["nurse"] < nurses and self.care < 98:
            if self._set_task(ant, "nurse", self.nursery):
                return
        if self._frontier:
            reserved = {a.target for a in self.ants if a.task == "dig"}
            available = [pos for pos in self._frontier if pos not in reserved]
            available.sort(key=lambda pos: self.distance(ant.pos, pos))
            for target in available:
                entries = [pos for pos in self.neighbors(target) if pos in self._open]
                entries.sort(key=lambda pos: self.distance(ant.pos, pos))
                for destination in entries:
                    if self._set_task(ant, "dig", target, destination):
                        return
        rooms = [p.center for p in self.projects if p.center in self._open]
        target = rooms[(ant.ident + self.ticks // 17) % len(rooms)] if rooms else self.queen
        self._set_task(ant, "patrol", target)

    def _act(self, ant: Ant) -> None:
        if ant.task == "idle":
            self._choose_job(ant)
        if ant.path:
            ant.pos = ant.path.pop()
            if ant.cargo == "food":
                self.scent[ant.pos] = min(40.0, self.scent.get(ant.pos, 0.0) + 4)
            return
        if ant.task == "forage":
            amount = min(3, int(self.patches.get(ant.pos, 0)))
            if amount:
                self.patches[ant.pos] -= amount
                ant.cargo, ant.amount = "food", amount
                self.scent[ant.pos] = min(40.0, self.scent.get(ant.pos, 0.0) + 10)
                self._set_task(ant, "return", self.pantry)
            else:
                self._idle(ant)
        elif ant.task == "return":
            self.food = min(self.food_capacity, self.food + ant.amount)
            self.total_gathered += ant.amount
            ant.cargo, ant.amount = "", 0
            self._idle(ant)
        elif ant.task == "dig":
            if self.tiles[ant.target] == ".":
                self._idle(ant)
                return
            ant.work += 1
            hardness = 7 if self.tiles[ant.target] == ":" else 4
            if ant.work >= hardness:
                self.tiles[ant.target] = "."
                self._open.add(ant.target)
                self.total_dug += 1
                self._routes.clear()
                self._refresh_frontier()
                ant.cargo, ant.amount = "soil", 1
                self._set_task(ant, "haul", SURFACE * WIDTH + WIDTH // 2)
        elif ant.task == "haul":
            self.spoil += ant.amount
            ant.cargo, ant.amount = "", 0
            self._idle(ant)
        elif ant.task in ("nurse", "tend"):
            ant.work += 1
            if ant.work >= 6:
                if self.food >= 0.1:
                    self.food -= 0.1
                    if ant.task == "nurse":
                        self.care = min(100.0, self.care + 12)
                    else:
                        self.queen_care = min(100.0, self.queen_care + 14)
                self._idle(ant)
        elif ant.task in ("patrol", "rest"):
            ant.work += 1
            if ant.work > 8:
                self._idle(ant)

    def _route(self, start: int, target: int) -> list[int] | None:
        if start == target:
            return []
        if target not in self._open:
            return None
        if target not in self._routes:
            toward = {target: target}
            queue = deque([target])
            while queue:
                pos = queue.popleft()
                for neighbor in self.neighbors(pos):
                    if neighbor in self._open and neighbor not in toward:
                        toward[neighbor] = pos
                        queue.append(neighbor)
            self._routes[target] = toward
        toward = self._routes[target]
        if start not in toward:
            return None
        path = []
        while start != target:
            start = toward[start]
            path.append(start)
        path.reverse()
        return path

    def _refresh_frontier(self) -> None:
        self._frontier = sorted({pos for p in self.projects if not p.complete for pos in p.cells
                                 if self.tiles[pos] != "." and any(n in self._open for n in self.neighbors(pos))})

    def _consider_building(self) -> None:
        for project in self.projects:
            if not project.complete and all(self.tiles[pos] == "." for pos in project.cells):
                project.complete = True
                self.note(f"The {project.kind} is ready. Another little room becomes a home.")
        if self.current_project is not None or len(self.projects) >= 24:
            return
        kinds = Counter(p.kind for p in self.projects if p.complete)
        need = construction_need(kinds, self.workers + self.brood_count, self.brood_count,
                                 self.capacity, MAX_ANTS, self.food / self.food_capacity,
                                 len(self.projects), self.ticks)
        if need is None:
            return
        kind, reason = need
        if self._plan_room(kind):
            self.note(reason)

    @staticmethod
    def _room_cells(cx: int, cy: int, rx: int, ry: int, rng: random.Random) -> set[int]:
        cells = set()
        for y in range(cy - ry, cy + ry + 1):
            for x in range(cx - rx, cx + rx + 1):
                if ((x - cx) / (rx + 0.4)) ** 2 + ((y - cy) / (ry + 0.4)) ** 2 <= 1:
                    if abs(y - cy) < ry or abs(x - cx) < rx - 1 or rng.random() > 0.35:
                        cells.add(y * WIDTH + x)
        return cells

    def _plan_room(self, kind: str) -> bool:
        rng = random.Random(self.seed + len(self.projects) * 104729)
        candidates = list(self.projects)
        rng.shuffle(candidates)
        for _ in range(120):
            anchor = candidates[rng.randrange(len(candidates))].center
            ax, ay = anchor % WIDTH, anchor // WIDTH
            cx = ax + rng.choice((-1, 1)) * rng.randint(9, 15)
            cy = ay + rng.randint(3, 7)
            if not (6 <= cx < WIDTH - 6 and 7 <= cy < HEIGHT - 4):
                continue
            if any(abs(cx - p.center % WIDTH) < 11 and abs(cy - p.center // WIDTH) < 6 for p in self.projects):
                continue
            cells = self._room_cells(cx, cy, rng.randint(3, 5), 2, rng)
            x, y = ax, ay
            bend = ay + max(1, (cy - ay) // 2)
            while y < bend:
                y += 1
                cells.add(y * WIDTH + x)
            direction = 1 if cx > x else -1
            while x != cx:
                x += direction
                cells.add(y * WIDTH + x)
            while y < cy:
                y += 1
                cells.add(y * WIDTH + x)
            self.projects.append(Project(kind, cy * WIDTH + cx, sorted(cells)))
            self._refresh_frontier()
            return True
        return False

    def to_dict(self) -> dict[str, Any]:
        data = {key: value for key, value in self.__dict__.items() if not key.startswith("_")}
        data["tiles"] = "".join(self.tiles)
        data["ants"] = [asdict(ant) for ant in self.ants]
        data["brood"] = [asdict(b) for b in self.brood]
        data["projects"] = [asdict(p) for p in self.projects]
        data["events"] = [asdict(e) for e in self.events]
        return data

    @classmethod
    def from_dict(cls, data: Any) -> Colony:
        if not isinstance(data, dict) or set(data) != {key for key in cls.__dataclass_fields__ if not key.startswith("_")}:
            raise ValueError("Colony fields are missing or unrecognized")
        name = data["name"]
        if not isinstance(name, str) or not 1 <= len(name) <= 32 or not all(32 <= ord(c) <= 126 for c in name):
            raise ValueError("Colony name must contain 1-32 printable ASCII characters")

        def number(value: Any, low: float, high: float, label: str, integer: bool = False) -> None:
            if type(value) not in (int, float) or (integer and type(value) is not int):
                raise ValueError(f"Invalid {label}")
            if not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"Out-of-range {label}")

        def position(value: Any, label: str) -> None:
            number(value, SURFACE * WIDTH, WIDTH * (HEIGHT - 1) - 1, label, True)
            if not 1 <= value % WIDTH < WIDTH - 1:
                raise ValueError(f"Invalid {label}")

        for key, low, high in (("seed", 0, 2**31 - 1), ("ticks", 0, 10**12), ("next_ant", 1, 10**12),
                               ("spoil", 0, WIDTH * HEIGHT), ("total_dug", 0, WIDTH * HEIGHT),
                               ("total_hatched", 0, 10**12), ("gifts", 0, 10**12)):
            number(data[key], low, high, key, True)
        for key, low, high in (("remainder", 0, STEP), ("food", 0, 10000), ("care", 0, 100),
                               ("queen_care", 0, 100), ("egg_clock", 0, 60), ("total_gathered", 0, 10**18),
                               ("last_gift", -60, 10**13)):
            number(data[key], low, high, key)
        if data["remainder"] >= STEP:
            raise ValueError("Invalid fractional clock")
        tiles = data["tiles"]
        if not isinstance(tiles, str) or len(tiles) != WIDTH * HEIGHT or set(tiles) - {" ", ".", "#", ":"}:
            raise ValueError("Invalid dirt box")
        if any((i // WIDTH <= SURFACE) != (tile == " ") for i, tile in enumerate(tiles)):
            raise ValueError("Invalid surface")
        opened = {i for i, tile in enumerate(tiles) if tile == "." or i // WIDTH == SURFACE}
        position(data["queen"], "queen position")
        if data["queen"] not in opened:
            raise ValueError("The queen cannot be inside soil")
        for key, limit in (("ants", MAX_ANTS), ("brood", MAX_ANTS), ("projects", 24), ("events", 40)):
            if not isinstance(data[key], list) or len(data[key]) > limit:
                raise ValueError(f"Invalid {key} list")
        if len(data["ants"]) < 8:
            raise ValueError("The founding colony is missing")
        ants = []
        for entry in data["ants"]:
            if not isinstance(entry, dict) or set(entry) != set(Ant.__dataclass_fields__):
                raise ValueError("Invalid ant")
            number(entry["ident"], 1, data["next_ant"] - 1, "ant identifier", True)
            position(entry["pos"], "ant position")
            if entry["pos"] not in opened or entry["task"] not in TASKS or entry["cargo"] not in ("", "food", "soil"):
                raise ValueError("Invalid ant behavior")
            if entry["target"] != -1:
                position(entry["target"], "ant target")
            if entry["task"] != "idle" and entry["target"] == -1:
                raise ValueError("Ant task has no target")
            number(entry["amount"], 0, 3, "cargo amount", True)
            number(entry["work"], 0, 20, "ant work", True)
            number(entry["age"], 0, 10**13, "ant age")
            route = entry["path"]
            if not isinstance(route, list) or len(route) > WIDTH * HEIGHT:
                raise ValueError("Invalid ant route")
            previous = entry["pos"]
            for pos in reversed(route):
                position(pos, "route position")
                if pos not in opened or pos not in cls.neighbors(previous):
                    raise ValueError("Ant route crosses solid soil")
                previous = pos
            ants.append(Ant(**entry))
        if len({a.ident for a in ants}) != len(ants):
            raise ValueError("Duplicate ants")
        broods = []
        for entry in data["brood"]:
            if not isinstance(entry, dict) or set(entry) != {"age"}:
                raise ValueError("Invalid brood")
            number(entry["age"], 0, 225, "brood age")
            if entry["age"] >= 225:
                raise ValueError("Mature brood should have hatched")
            broods.append(Brood(**entry))
        projects = []
        for entry in data["projects"]:
            if not isinstance(entry, dict) or set(entry) != set(Project.__dataclass_fields__):
                raise ValueError("Invalid building project")
            if entry["kind"] not in ("queen's chamber", "nursery", "pantry", "gallery") or type(entry["complete"]) is not bool:
                raise ValueError("Invalid room type")
            position(entry["center"], "room center")
            if not isinstance(entry["cells"], list) or not 1 <= len(entry["cells"]) <= WIDTH * HEIGHT:
                raise ValueError("Invalid room plan")
            for pos in entry["cells"]:
                position(pos, "room cell")
                if pos // WIDTH <= SURFACE or (entry["complete"] and tiles[pos] != "."):
                    raise ValueError("Invalid excavated room")
            projects.append(Project(**entry))
        if not projects or sum(not p.complete for p in projects) > 1:
            raise ValueError("Invalid nest plan")
        maps = {}
        for key, high in (("patches", 100.0), ("scent", 40.0)):
            if not isinstance(data[key], dict) or len(data[key]) > WIDTH * HEIGHT:
                raise ValueError(f"Invalid {key}")
            maps[key] = {}
            for raw_pos, amount in data[key].items():
                try:
                    pos = int(raw_pos)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"Invalid {key} location") from exc
                position(pos, key)
                number(amount, 0, high, key)
                if pos not in opened or (key == "patches" and pos // WIDTH != SURFACE):
                    raise ValueError(f"Invalid {key} location")
                maps[key][pos] = amount
        events = []
        for entry in data["events"]:
            if not isinstance(entry, dict) or set(entry) != {"at", "text"}:
                raise ValueError("Invalid event")
            number(entry["at"], 0, data["ticks"] * STEP, "event time")
            message = entry["text"]
            if not isinstance(message, str) or len(message) > 200 or not all(32 <= ord(c) <= 126 for c in message):
                raise ValueError("Invalid event text")
            events.append(Event(**entry))
        colony = cls(**{**data, **maps, "tiles": list(tiles), "ants": ants, "brood": broods, "projects": projects, "events": events})
        if colony.food > colony.food_capacity or colony.workers + colony.brood_count > colony.capacity:
            raise ValueError("Colony exceeds its nest capacity")
        if colony.last_gift > colony.seconds:
            raise ValueError("Colony has events in the future")
        colony._route(SURFACE * WIDTH + WIDTH // 2, colony.queen)
        reachable = set(colony._routes.get(colony.queen, {colony.queen: colony.queen}))
        if not opened - {SURFACE * WIDTH, (SURFACE + 1) * WIDTH - 1} <= reachable:
            raise ValueError("Disconnected tunnels in save")
        return colony


@dataclass(frozen=True)
class AwayReport:
    elapsed: float
    simulated: float
    hatched: int
    rooms: int
    dug: int


def catch_up(colony: Colony, saved_at: float, now: float) -> AwayReport:
    elapsed = max(0.0, now - saved_at)
    simulated = min(float(MAX_OFFLINE), elapsed)
    before = colony.total_hatched, colony.rooms, colony.total_dug
    colony.advance(simulated)
    return AwayReport(elapsed, simulated, colony.total_hatched - before[0], colony.rooms - before[1], colony.total_dug - before[2])
