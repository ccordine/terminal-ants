"""Atomic saves, a last-good backup, and a lock against concurrent writers."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import tempfile
import time
from typing import Any

from .model import Colony, SCHEMA_VERSION


class SaveError(Exception):
    pass


class SaveInUse(SaveError):
    pass


class FutureSave(SaveError):
    pass


class SaveStore:
    def __init__(self, path: Path):
        self.path = path.expanduser().resolve()
        self.backup = self.path.with_suffix(self.path.suffix + ".bak")
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        self._lock: Any = None
        self._primary_valid = False
        self._last_good_payload: bytes | None = None
        self.recovery_message = ""

    def __enter__(self) -> SaveStore:
        import fcntl

        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._lock = self.lock_path.open("a+")
            try:
                fcntl.flock(self._lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise SaveInUse(f"This colony is already open in another terminal: {self.path}") from exc
        except (OSError, SaveError):
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *args: Any) -> None:
        if self._lock is not None:
            self._lock.close()
            self._lock = None

    def _read(self, path: Path) -> tuple[Colony, float]:
        if path.stat().st_size > 1_000_000:
            raise ValueError("Save file is unexpectedly large")
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except RecursionError as exc:
            raise ValueError("Save data is nested too deeply") from exc
        if not isinstance(document, dict):
            raise ValueError("Save must be an object")
        version = document.get("version")
        if type(version) is not int:
            raise ValueError("Save version is missing or invalid")
        if version > SCHEMA_VERSION:
            raise FutureSave(f"{path} was created by a newer version of Terminal Ants. Please update the game.")
        if version != SCHEMA_VERSION:
            raise ValueError(f"Unsupported save version: {version}")
        saved_at = document.get("saved_at")
        if type(saved_at) not in (int, float) or not 0 <= saved_at <= 10**13 or not math.isfinite(saved_at):
            raise ValueError("Save timestamp is invalid")
        try:
            colony = Colony.from_dict(document.get("colony"))
        except (TypeError, KeyError, OverflowError, RecursionError) as exc:
            raise ValueError("Save contains malformed colony data") from exc
        return colony, saved_at

    def load(self) -> tuple[Colony, float] | None:
        self._require_lock()
        if not self.path.exists() and not self.backup.exists():
            return None
        try:
            result = self._read(self.path)
            self._primary_valid = True
            self._last_good_payload = self._encode(*result)
            return result
        except (OSError, ValueError) as primary_error:
            try:
                result = self._read(self.backup)
            except (OSError, ValueError) as backup_error:
                raise SaveError(
                    f"Cannot read colony save: {self.path}\n"
                    f"Save: {primary_error}\nBackup: {backup_error}\n"
                    "The files have been left untouched. Use --save PATH for a separate colony."
                ) from primary_error
            if self.path.exists():
                recovery = self.path.with_name(self.path.name + f".corrupt-{time.time_ns()}")
                self._atomic_write(recovery, self.path.read_bytes())
            self.recovery_message = "Recovered the colony from its last good backup."
            self._primary_valid = False
            return result

    def save(self, colony: Colony, now: float | None = None) -> None:
        self._require_lock()
        # The backup is always an already-validated primary, never a corrupt file.
        payload = self._encode(colony, time.time() if now is None else now)
        if self._primary_valid and self._last_good_payload is not None:
            self._atomic_write(self.backup, self._last_good_payload)
        self._atomic_write(self.path, payload)
        self._primary_valid = True
        self._last_good_payload = payload

    @staticmethod
    def _encode(colony: Colony, now: float) -> bytes:
        document = {"version": SCHEMA_VERSION, "saved_at": now, "colony": colony.to_dict()}
        return (json.dumps(document, indent=2, allow_nan=False) + "\n").encode("utf-8")

    def _require_lock(self) -> None:
        if self._lock is None:
            raise SaveError("The save must be locked before it can be read or written")

    @staticmethod
    def _atomic_write(path: Path, payload: bytes) -> None:
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            # Persist the rename as well as its contents on Unix filesystems.
            directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
