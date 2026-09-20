"""A quiet curses viewer; the model never depends on a screen or frame rate."""
from __future__ import annotations

import curses
import os
import signal
import time
from collections.abc import Callable

from .model import Colony
from .scene import Canvas, Ink, View, render

SPEEDS = (1, 5, 20, 60)


def palette(monochrome: bool) -> dict[Ink, int]:
    colors = {ink: 0 for ink in Ink}
    colors[Ink.QUEEN] = colors[Ink.ANT] = curses.A_BOLD
    if monochrome or os.environ.get("NO_COLOR") is not None or not curses.has_colors():
        return colors
    curses.start_color()
    try:
        curses.use_default_colors()
        background = -1
    except curses.error:
        background = curses.COLOR_BLACK
    if curses.COLORS >= 256:
        choices = {
            Ink.TEXT: 252, Ink.DIM: 244, Ink.EARTH: 238, Ink.CLAY: 240,
            Ink.EDGE: 137, Ink.GRASS: 108, Ink.ANT: 215, Ink.FOOD: 150,
            Ink.BROOD: 223, Ink.QUEEN: 221, Ink.SOIL: 173, Ink.WATER: 110,
            Ink.PLAN: 66, Ink.SCENT: 72, Ink.BORDER: 240,
        }
    else:
        choices = {
            Ink.TEXT: 7, Ink.DIM: 7, Ink.EARTH: 0, Ink.CLAY: 3,
            Ink.EDGE: 3, Ink.GRASS: 2, Ink.ANT: 3, Ink.FOOD: 2,
            Ink.BROOD: 7, Ink.QUEEN: 3, Ink.SOIL: 1, Ink.WATER: 6,
            Ink.PLAN: 4, Ink.SCENT: 6, Ink.BORDER: 7,
        }
    for ink, color in choices.items():
        if int(ink) < curses.COLOR_PAIRS:
            curses.init_pair(int(ink), color, background)
            colors[ink] = curses.color_pair(int(ink))
    for ink in (Ink.ANT, Ink.FOOD, Ink.QUEEN, Ink.BROOD):
        colors[ink] |= curses.A_BOLD
    if curses.COLORS < 256:
        colors[Ink.EARTH] = curses.color_pair(int(Ink.DIM)) | curses.A_DIM
    return colors


def paint(screen: curses.window, canvas: Canvas, colors: dict[Ink, int]) -> None:
    screen.erase()
    for y in range(canvas.height):
        start = 0
        while start < canvas.width:
            ink = canvas.inks[y][start]
            end = start + 1
            while end < canvas.width and canvas.inks[y][end] == ink:
                end += 1
            try:
                screen.addstr(y, start, "".join(canvas.chars[y][start:end]), colors[ink])
            except curses.error:
                # Writing the lower-right cell and an in-flight resize can raise.
                pass
            start = end
    screen.noutrefresh()
    curses.doupdate()


def run(
    colony: Colony, save: Callable[[], None], speed: int = 1,
    hud: bool = True, notice: str = "", monochrome: bool = False,
) -> None:
    view = View(hud=hud, speed=speed, notice=notice)
    stop = False
    original_handlers = {}

    def stop_handler(signum: int, frame: object) -> None:
        nonlocal stop
        stop = True

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        original_handlers[sig] = signal.signal(sig, stop_handler)

    def loop(screen: curses.window) -> None:
        nonlocal stop
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        screen.keypad(True)
        screen.timeout(100)
        colors = palette(monochrome)
        last = last_save = time.monotonic()
        notice_until = last + (18 if notice else 0)
        try:
            while not stop:
                now = time.monotonic()
                if not view.paused:
                    colony.advance((now - last) * view.speed)
                last = now
                if now >= notice_until:
                    view.notice = ""
                if now - last_save >= 10:
                    try:
                        save()
                    except OSError as exc:
                        view.notice = f"Save failed: {exc.strerror or exc}. Retrying in 10s."
                        notice_until = now + 11
                    last_save = now
                height, width = screen.getmaxyx()
                paint(screen, render(colony, width, height, view), colors)
                key = screen.getch()
                # Account for time spent waiting under the old speed/pause state.
                after_input = time.monotonic()
                if not view.paused:
                    colony.advance((after_input - last) * view.speed)
                last = after_input
                if key in (ord("q"), ord("Q"), 3):
                    stop = True
                elif key == ord("h"):
                    view.hud = not view.hud
                elif key in (ord("?"), 27):
                    view.panel = "" if view.panel else ("help" if key != 27 else "")
                elif key in (ord("i"), ord("j")):
                    panel = "instincts" if key == ord("i") else "journal"
                    view.panel = "" if view.panel == panel else panel
                elif key == ord("v"):
                    view.scent = not view.scent
                elif key == ord("s"):
                    view.speed = SPEEDS[(SPEEDS.index(view.speed) + 1) % len(SPEEDS)]
                elif key == ord(" "):
                    view.paused = not view.paused
                elif key == ord("f"):
                    view.notice = colony.scatter_food()
                    notice_until = after_input + 6
                    try:
                        save()
                    except OSError as exc:
                        view.notice = f"Save failed: {exc.strerror or exc}. Retrying automatically."
                        notice_until = after_input + 11
                elif key == ord("a"):
                    ids = [ant.ident for ant in colony.ants]
                    current = ids.index(view.selected_ant) if view.selected_ant in ids else -1
                    view.selected_ant = ids[(current + 1) % len(ids)]
                    view.panel = "ant"
        finally:
            if not view.paused:
                colony.advance((time.monotonic() - last) * view.speed)
            save()

    try:
        try:
            curses.wrapper(loop)
        except curses.error as exc:
            raise ValueError(f"Cannot use this terminal ({exc}). Check TERM, or use --snapshot.") from exc
    finally:
        for sig, handler in original_handlers.items():
            signal.signal(sig, handler)
