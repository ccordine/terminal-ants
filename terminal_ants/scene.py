"""ASCII view of the actual dirt box. This module also renders headless snapshots."""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import math
import textwrap

from .model import Colony, HEIGHT, SURFACE, WIDTH


class Ink(IntEnum):
    TEXT = 1
    DIM = 2
    EARTH = 3
    CLAY = 4
    EDGE = 5
    GRASS = 6
    ANT = 7
    FOOD = 8
    BROOD = 9
    QUEEN = 10
    SOIL = 11
    WATER = 12
    PLAN = 13
    SCENT = 14
    BORDER = 15


class Canvas:
    def __init__(self, width: int, height: int):
        self.width, self.height = max(1, width), max(1, height)
        self.chars = [[" "] * self.width for _ in range(self.height)]
        self.inks = [[Ink.TEXT] * self.width for _ in range(self.height)]

    def put(self, x: int, y: int, text: str, ink: Ink = Ink.TEXT) -> None:
        if 0 <= y < self.height:
            for offset, char in enumerate(text):
                if 0 <= x + offset < self.width:
                    self.chars[y][x + offset] = char
                    self.inks[y][x + offset] = ink

    def blit(self, source: Canvas, x: int, y: int) -> None:
        for sy in range(source.height):
            for sx in range(source.width):
                self.put(x + sx, y + sy, source.chars[sy][sx], source.inks[sy][sx])

    def lines(self) -> list[str]:
        return ["".join(row) for row in self.chars]


@dataclass
class View:
    hud: bool = True
    scent: bool = False
    panel: str = ""
    speed: int = 1
    paused: bool = False
    notice: str = ""
    selected_ant: int = -1


def duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60:02d}s"
    if seconds < 86400:
        return f"{seconds // 3600}h {(seconds % 3600) // 60:02d}m"
    return f"{seconds // 86400}d {(seconds % 86400) // 3600}h"


def farm(colony: Colony, width: int, height: int, view: View | None = None) -> Canvas:
    view = view or View()
    canvas = Canvas(width, height)
    w, h = width - 2, height - 2
    if w < 2 or h < 4:
        return canvas
    sky = 3 if h >= 18 else 2

    def point(pos: int) -> tuple[int, int]:
        x, y = pos % WIDTH, pos // WIDTH
        py = y / SURFACE * sky if y <= SURFACE else sky + (y - SURFACE) / (HEIGHT - 1 - SURFACE) * (h - 1 - sky)
        return min(w - 1, int((x + 0.5) * w / WIDTH)), min(h - 1, round(py))

    def cell(x: int, y: int) -> int:
        wx = min(WIDTH - 1, int(x * WIDTH / w))
        wy = int(y / sky * SURFACE) if y <= sky else round(SURFACE + (y - sky) / (h - 1 - sky) * (HEIGHT - 1 - SURFACE))
        return min(HEIGHT - 1, wy) * WIDTH + wx

    opened = set()
    for y in range(sky + 1, h):
        for x in range(w):
            if colony.tiles[cell(x, y)] == ".":
                opened.add((x, y))
    # Preserve one-cell passages when a short terminal compresses vertical space.
    for pos in colony._open:
        if pos // WIDTH > SURFACE:
            opened.add(point(pos))
    for y in range(sky, h):
        for x in range(w):
            if y == sky:
                canvas.put(x + 1, y + 1, "_", Ink.GRASS)
            elif (x, y) not in opened:
                hashed = (x * 7919 + y * 104729 + colony.seed * 13) ^ ((x + y * 7) * 31)
                glyph = "." if hashed % 7 < 4 else (":" if hashed % 7 < 6 else " ")
                ink = Ink.CLAY if colony.tiles[cell(x, y)] == ":" else Ink.EARTH
                if any((nx, ny) in opened for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1))):
                    glyph, ink = ":", Ink.EDGE
                canvas.put(x + 1, y + 1, glyph, ink)
    # Roots disappear where workers actually excavate them.
    for rx in (8, 22, 55, 70):
        for depth in range(1, 6):
            pos = (SURFACE + depth) * WIDTH + rx + depth // 3
            x, y = point(pos)
            if (x, y) not in opened:
                canvas.put(x + 1, y + 1, "|" if depth % 3 else "\\", Ink.CLAY)
    for gx in (8, 22, 55, 70):
        x, y = point(SURFACE * WIDTH + gx)
        canvas.put(x, y, "\\|/", Ink.GRASS)
    if colony.night:
        for n in range(max(3, w // 13)):
            x = (n * 23 + colony.seed) % w
            canvas.put(x + 1, 1 + n % max(1, sky - 1), "." if n % 2 else "*", Ink.DIM)
        canvas.put(w - 6, 1, "(", Ink.QUEEN)
    elif w > 48:
        cloud_x = int(colony.seconds / 18 + colony.seed % w) % (w + 12) - 12
        canvas.put(cloud_x + 1, 1, " .--. ", Ink.DIM)
        canvas.put(cloud_x - 1, 2, "(____)", Ink.DIM)
    if colony.weather in ("drizzle", "mist"):
        for n in range(max(2, w // 12)):
            x = (n * 19 + int(colony.seconds * 2)) % w
            y = 1 + (n + int(colony.seconds * 3)) % max(1, sky)
            canvas.put(x + 1, y, "/" if colony.weather == "drizzle" else "'", Ink.WATER)
    entrance_x, entrance_y = point(SURFACE * WIDTH + WIDTH // 2)
    mound = min(5, int(math.sqrt(colony.spoil) / 3))
    if mound:
        canvas.put(entrance_x - mound + 1, entrance_y + 1, "," * mound + " " + "," * mound, Ink.SOIL)
    canvas.put(entrance_x + 1, entrance_y + 1, " ")
    if view.panel == "instincts":
        for p in colony.projects:
            if not p.complete:
                for pos in p.cells:
                    if colony.tiles[pos] != ".":
                        x, y = point(pos)
                        canvas.put(x + 1, y + 1, "+", Ink.PLAN)
    if view.scent:
        for pos, strength in colony.scent.items():
            if strength > 1:
                x, y = point(pos)
                canvas.put(x + 1, y + 1, ":" if strength > 12 else ".", Ink.SCENT)
    for pos, amount in colony.patches.items():
        if amount >= 1:
            x, y = point(pos)
            canvas.put(x + 1, y + 1, "*" if amount < 20 else "**", Ink.FOOD)
    pantries = [p for p in colony.projects if p.complete and p.kind == "pantry"]
    for pantry in pantries:
        places = [pos for pos in pantry.cells if abs(pos // WIDTH - pantry.center // WIDTH) <= 1 and abs(pos % WIDTH - pantry.center % WIDTH) <= 3]
        for pos in places[:max(1, int(colony.food / max(1, len(pantries)) / 8))]:
            x, y = point(pos)
            canvas.put(x + 1, y + 1, "*", Ink.FOOD)
    brood_places = [pos for pos in sorted(colony._open) if colony.distance(pos, colony.nursery) < 4 and pos // WIDTH > SURFACE]
    for i, brood in enumerate(colony.brood):
        if brood_places:
            x, y = point(brood_places[i % len(brood_places)])
            canvas.put(x + 1, y + 1, ("o", "~", "O")[min(2, int(brood.age // 75))], Ink.BROOD)
    # Rotating the draw order keeps overlapping workers visible without teleporting them.
    offset = colony.ticks % max(1, colony.workers)
    for ant in colony.ants[offset:] + colony.ants[:offset]:
        x, y = point(ant.pos)
        glyph, ink = "a", Ink.ANT
        if ant.cargo == "food":
            glyph, ink = "&", Ink.FOOD
        elif ant.cargo == "soil":
            glyph, ink = "%", Ink.SOIL
        elif ant.task in ("nurse", "tend"):
            ink = Ink.BROOD
        if ant.ident == view.selected_ant:
            glyph, ink = "A", Ink.QUEEN
        canvas.put(x + 1, y + 1, glyph, ink)
    x, y = point(colony.queen)
    canvas.put(x + 1, y + 1, "Q", Ink.QUEEN)
    canvas.put(0, 0, "+" + "-" * w + "+", Ink.BORDER)
    canvas.put(0, height - 1, "+" + "-" * w + "+", Ink.BORDER)
    for y in range(1, height - 1):
        canvas.put(0, y, "|", Ink.BORDER)
        canvas.put(width - 1, y, "|", Ink.BORDER)
    return canvas


def render(colony: Colony, width: int, height: int, view: View) -> Canvas:
    canvas = Canvas(width, height)
    if width < 40 or height < 14:
        canvas.put(1, 1, "A little more room for the ants?", Ink.QUEEN)
        canvas.put(1, 3, "Resize to at least 40 x 14.", Ink.TEXT)
        canvas.put(1, 5, "The colony is still living. q saves.", Ink.DIM)
        return canvas
    if view.hud:
        canvas.put(1, 0, colony.name, Ink.QUEEN)
        clock = f"day {colony.day} / {'night' if colony.night else colony.weather} / {view.speed}x"
        if view.paused:
            clock = "PAUSED / " + clock
        canvas.put(max(len(colony.name) + 3, width - len(clock) - 1), 0, clock, Ink.DIM)
        stats = f"{colony.workers} ants  {colony.brood_count} brood  food {int(colony.food)}/{colony.food_capacity}  {colony.rooms} rooms  {colony.total_dug} soil dug"
        canvas.put(1, 1, stats[:width - 2], Ink.TEXT)
        canvas.blit(farm(colony, width, height - 4, view), 0, 2)
        project = colony.current_project
        status = (f"Building {project.kind}: {colony.digging_progress:.0%}" if project else "The colony goes about its day.")
        canvas.put(1, height - 2, (view.notice or status)[:width - 2], Ink.DIM)
        canvas.put(1, height - 1, "? help   h hide HUD   i instincts   s speed   q save & quit"[:width - 2], Ink.DIM)
    else:
        canvas.blit(farm(colony, width, height - 1, view), 0, 0)
        canvas.put(1, height - 1, "PAUSED | space resume" if view.paused else "h HUD  /  ? help  /  q save & quit", Ink.DIM)
    if view.panel:
        title, lines = panel_content(colony, view)
        if view.panel == "instincts" and height >= 28:
            panel(canvas, title, lines, at_bottom=True)
        else:
            panel(canvas, title, lines)
    return canvas


def panel_content(colony: Colony, view: View) -> tuple[str, list[str]]:
    if view.panel == "help":
        return "A BOX OF DIRT, A LITTLE LIFE", [
            "Just watch. The ants make their own home.", "",
            "h       Show / hide the HUD", "s       Speed: 1x, 5x, 20x, 60x", "space   Pause / resume this viewing session",
            "f       Scatter seeds on the surface", "i       Colony instincts + dig plan", "v       Show / hide pheromone trails",
            "a       Inspect the next ant", "j       Colony journal", "? / Esc Close this panel", "q       Save and quit", "",
            "a worker   & carrying food   % hauling soil", "Q queen    o egg   ~ larva   O pupa   * seed", "",
            "Saves every 10 seconds and on exit. While away,",
            "up to 24 hours runs at 1x when you return.",
            "Pause lasts only while this window is open.",
        ]
    if view.panel == "journal":
        return "LIFE IN THE COLONY", [f"{duration(event.at):>7}  {event.text}" for event in colony.events[-10:]] or ["A quiet beginning."]
    if view.panel == "ant":
        ant = next((a for a in colony.ants if a.ident == view.selected_ant), colony.ants[0])
        return f"WORKER #{ant.ident}", [
            f"Instinct: {ant.task}", f"Carrying: {ant.cargo or 'nothing'}{f' ({ant.amount})' if ant.amount else ''}",
            f"Position: {ant.pos % WIDTH}, {ant.pos // WIDTH}", f"Age: {duration(ant.age)}",
            f"Steps to destination: {len(ant.path)}", "", "Press a to inspect the next worker.", "The highlighted A marks her position.",
        ]
    roles = colony.roles
    project = colony.current_project
    return "SHARED INSTINCTS", [
        f"Gather food: {roles['forage'] + roles['return']} workers; stores {colony.food / colony.food_capacity:.0%} full",
        f"Raise brood: {roles['nurse']} nurses; care {colony.care:.0f}%",
        f"Tend queen: {roles['tend']} attendants; care {colony.queen_care:.0f}%",
        f"Build home: {roles['dig']} digging, {roles['haul']} hauling soil",
        f"Make space: {colony.workers + colony.brood_count}/{colony.capacity} nest places occupied",
        f"Current plan: {project.kind} ({colony.digging_progress:.0%})" if project else "Current plan: rest and explore",
        "", "+ marks soil chosen for excavation.",
        "Hunger recruits foragers. Crowding prompts digging.",
        "Brood needs nurses. Full stores prompt a new pantry.",
    ]


def panel(canvas: Canvas, title: str, paragraphs: list[str], at_bottom: bool = False) -> None:
    w = min(62, canvas.width - 4)
    lines = []
    for paragraph in paragraphs:
        lines.extend(textwrap.wrap(paragraph, max(10, w - 4)) or [""])
    h = min(len(lines) + 4, canvas.height - 2)
    x = (canvas.width - w) // 2
    y = canvas.height - h - 2 if at_bottom else (canvas.height - h) // 2
    for row in range(h):
        canvas.put(x, y + row, " " * w)
        canvas.put(x, y + row, "|", Ink.BORDER)
        canvas.put(x + w - 1, y + row, "|", Ink.BORDER)
    canvas.put(x, y, "+" + "-" * (w - 2) + "+", Ink.BORDER)
    canvas.put(x + 2, y, f" {title} "[:w - 4], Ink.QUEEN)
    canvas.put(x, y + h - 1, "+" + "-" * (w - 2) + "+", Ink.BORDER)
    for i, line in enumerate(lines[:h - 3]):
        canvas.put(x + 2, y + 1 + i, line[:w - 4], Ink.TEXT)
    canvas.put(x + 2, y + h - 2, "? / Esc closes"[:w - 4], Ink.DIM)
