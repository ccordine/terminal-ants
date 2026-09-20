"""Run with ./ants or python3 -m terminal_ants."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import math
import os
from pathlib import Path
import sys
import time

from . import __version__
from .model import AwayReport, Colony, MAX_OFFLINE, catch_up
from .scene import View, duration, render
from .storage import SaveError, SaveStore

DEFAULT_SAVE = Path(__file__).resolve().parent.parent / "saves" / "colony.json"


def name_arg(value: str) -> str:
    value = value.strip()
    if not 1 <= len(value) <= 32 or not all(32 <= ord(c) <= 126 for c in value):
        raise argparse.ArgumentTypeError("use 1-32 printable ASCII characters for the colony name")
    return value


def elapsed_arg(value: str) -> float:
    try:
        seconds = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("advance time must be a number of seconds") from exc
    if not math.isfinite(seconds) or not 0 <= seconds <= MAX_OFFLINE:
        raise argparse.ArgumentTypeError(f"advance time must be between 0 and {MAX_OFFLINE} seconds")
    return seconds


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="A persistent box of dirt. Ants build their own home. Just watch.")
    result.add_argument("--save", type=Path, default=Path(os.environ.get("TERMINAL_ANTS_SAVE", str(DEFAULT_SAVE))), help="colony save file (default: saves/colony.json beside the launcher)")
    result.add_argument("--name", type=name_arg, help="name for a new colony")
    result.add_argument("--seed", type=int, help="world seed for a new colony")
    result.add_argument("--speed", type=int, choices=(1, 5, 20, 60), default=1, help="viewing speed; offline time always runs at 1x")
    result.add_argument("--no-hud", action="store_true", help="start with just the dirt box")
    result.add_argument("--monochrome", action="store_true", help="disable terminal colors")
    result.add_argument("--demo", action="store_true", help="watch a disposable established colony; never read or write saves")
    outputs = result.add_mutually_exclusive_group()
    outputs.add_argument("--status", action="store_true", help="catch up, save, print a summary, and exit")
    outputs.add_argument("--snapshot", action="store_true", help="catch up, save, print an ASCII frame, and exit")
    result.add_argument("--json", action="store_true", help="machine-readable output with --status")
    result.add_argument("--advance", type=elapsed_arg, default=0, metavar="SECONDS", help="simulate extra time with --status or --snapshot")
    result.add_argument("--width", type=int, default=100, help="snapshot width (40-240; default 100)")
    result.add_argument("--height", type=int, default=36, help="snapshot height (14-100; default 36)")
    result.add_argument("--version", action="version", version=f"Terminal Ants {__version__}")
    return result


def summary(colony: Colony, path: Path | None, report: AwayReport) -> dict:
    project = colony.current_project
    return {
        "name": colony.name, "workers": colony.workers, "brood": colony.brood_count,
        "food": round(colony.food, 2), "food_capacity": colony.food_capacity,
        "nest_capacity": colony.capacity, "rooms": colony.rooms, "soil_dug": colony.total_dug,
        "soil_carried_out": colony.spoil, "total_hatched": colony.total_hatched,
        "colony_age_seconds": round(colony.seconds, 3), "day": colony.day,
        "building": project.kind if project else None,
        "building_progress": round(colony.digging_progress, 3),
        "jobs": dict(colony.roles), "away": asdict(report),
        "save": str(path) if path else None,
    }


def output(colony: Colony, args: argparse.Namespace, path: Path | None, report: AwayReport) -> None:
    if args.snapshot:
        print("\n".join(render(colony, args.width, args.height, View(hud=not args.no_hud, speed=args.speed)).lines()))
    elif args.json:
        print(json.dumps(summary(colony, path, report), indent=2))
    else:
        print(f"{colony.name} / day {colony.day}")
        print(f"{colony.workers} workers, {colony.brood_count} brood, {colony.rooms} rooms")
        print(f"Food: {colony.food:.0f}/{colony.food_capacity} | Soil dug: {colony.total_dug} | Nest places: {colony.capacity}")
        if colony.current_project:
            print(f"Building: {colony.current_project.kind} ({colony.digging_progress:.0%})")
        if report.elapsed >= 5:
            print(away_notice(report))
        print(f"Save: {path}" if path else "Demo colony; nothing saved.")


def away_notice(report: AwayReport) -> str:
    message = f"Away {duration(report.elapsed)}: {report.hatched} hatched, {report.dug} soil dug, {report.rooms} rooms finished."
    if report.elapsed > MAX_OFFLINE:
        message += " Caught up the first 24 hours."
    return message


def main(argv: list[str] | None = None) -> int:
    arg_parser = parser()
    args = arg_parser.parse_args(argv)
    if args.json and not args.status:
        arg_parser.error("--json requires --status")
    if args.advance and not (args.status or args.snapshot):
        arg_parser.error("--advance requires --status or --snapshot")
    if args.seed is not None and not 0 <= args.seed < 2**31:
        arg_parser.error("--seed must be between 0 and 2147483647")
    if not 40 <= args.width <= 240 or not 14 <= args.height <= 100:
        arg_parser.error("snapshot dimensions must be 40-240 columns and 14-100 rows")
    interactive = not (args.status or args.snapshot)
    if interactive and (not sys.stdin.isatty() or not sys.stdout.isatty()):
        arg_parser.error("the viewer needs an interactive terminal; use --status or --snapshot for plain output")
    if os.name != "posix":
        arg_parser.error("run Terminal Ants on Linux, macOS, or Windows through WSL")
    try:
        if args.demo:
            colony = Colony.new(args.name or "A Life Beneath the Grass", args.seed if args.seed is not None else 7)
            colony.advance(2400 + args.advance)
            if interactive:
                from .ui import run
                run(colony, lambda: None, args.speed, not args.no_hud, "Demo colony. Nothing here is saved.", args.monochrome)
            else:
                output(colony, args, None, AwayReport(0, 0, 0, 0, 0))
            return 0
        with SaveStore(args.save) as store:
            loaded = store.load()
            now = time.time()
            if loaded is None:
                colony = Colony.new(args.name or "Mosslight Colony", args.seed)
                report = AwayReport(0, 0, 0, 0, 0)
            else:
                colony, saved_at = loaded
                if args.name is not None or args.seed is not None:
                    raise SaveError("--name and --seed are for a new colony. Use --save PATH to give it a separate home.")
                if interactive and now - saved_at > 300:
                    print(f"The colony has been busy. Catching up {duration(min(MAX_OFFLINE, now - saved_at))}...", flush=True)
                report = catch_up(colony, saved_at, now)
            if args.advance:
                colony.advance(args.advance)
            store.save(colony, now)
            if interactive:
                from .ui import run
                colony.advance(max(0.0, time.time() - now))
                notice = store.recovery_message or (away_notice(report) if report.elapsed >= 5 else "Just watch. The ants will make themselves at home. Press ? for controls.")
                run(colony, lambda: store.save(colony), args.speed, not args.no_hud, notice, args.monochrome)
                print(f"Colony saved. The ants will keep busy while you are away.\n{store.path}")
            else:
                if store.recovery_message:
                    print(store.recovery_message, file=sys.stderr)
                output(colony, args, store.path, report)
        return 0
    except (OSError, SaveError, ValueError) as exc:
        print(f"Terminal Ants: {exc}", file=sys.stderr)
        return 2
    except ImportError as exc:
        print(f"Terminal Ants needs Python's curses module: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nStopped. Your last saved colony is intact.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
