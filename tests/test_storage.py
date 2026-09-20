import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from terminal_ants.model import Colony, SCHEMA_VERSION
from terminal_ants.storage import FutureSave, SaveError, SaveInUse, SaveStore


class SaveTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "nest" / "colony.json"

    def test_round_trip_preserves_each_ant_and_the_world(self):
        colony = Colony.new(seed=7)
        colony.advance(600.25)
        with SaveStore(self.path) as store:
            self.assertIsNone(store.load())
            store.save(colony, 1000)
        with SaveStore(self.path) as store:
            loaded, saved_at = store.load()
        self.assertEqual(loaded.to_dict(), colony.to_dict())
        self.assertEqual(saved_at, 1000)

    def test_concurrent_writer_is_rejected_then_lock_is_released(self):
        with SaveStore(self.path):
            with self.assertRaises(SaveInUse):
                with SaveStore(self.path):
                    pass
        with SaveStore(self.path):
            pass

    def test_corruption_recovers_last_good_backup_and_keeps_original(self):
        colony = Colony.new(seed=9)
        with SaveStore(self.path) as store:
            store.save(colony, 1000)
            colony.advance(60)
            store.save(colony, 1060)
        self.path.write_text("broken data")
        with SaveStore(self.path) as store:
            recovered, stamp = store.load()
            self.assertEqual(stamp, 1000)
            self.assertEqual(recovered.ticks, 0)
            self.assertIn("Recovered", store.recovery_message)
            store.save(recovered, 1100)
        self.assertEqual(next(self.path.parent.glob("*.corrupt-*")).read_text(), "broken data")
        self.assertEqual(json.loads(self.path.with_suffix(".json.bak").read_text())["saved_at"], 1000)

    def test_no_backup_never_silently_replaces_corrupt_save(self):
        self.path.parent.mkdir()
        self.path.write_text("do not lose me")
        with SaveStore(self.path) as store:
            with self.assertRaises(SaveError):
                store.load()
        self.assertEqual(self.path.read_text(), "do not lose me")

    def test_future_save_is_never_replaced_with_old_backup(self):
        with SaveStore(self.path) as store:
            store.save(Colony.new(seed=2), 1000)
            store.save(Colony.new(seed=2), 1001)
        data = json.loads(self.path.read_text())
        data["version"] = SCHEMA_VERSION + 1
        self.path.write_text(json.dumps(data))
        with SaveStore(self.path) as store:
            with self.assertRaises(FutureSave):
                store.load()

    def test_failed_atomic_replace_leaves_previous_save_intact(self):
        with SaveStore(self.path) as store:
            store.save(Colony.new(seed=3), 1000)
            original = self.path.read_bytes()
            with patch("terminal_ants.storage.os.replace", side_effect=OSError("disk failure")):
                with self.assertRaises(OSError):
                    store.save(Colony.new(seed=4), 1001)
            self.assertEqual(self.path.read_bytes(), original)
            self.assertEqual(list(self.path.parent.glob(".colony*")), [])

    def test_malformed_task_type_is_a_save_error(self):
        with SaveStore(self.path) as store:
            store.save(Colony.new(), 1000)
        data = json.loads(self.path.read_text())
        data["colony"]["ants"][0]["task"] = []
        self.path.write_text(json.dumps(data))
        with SaveStore(self.path) as store:
            with self.assertRaises(SaveError):
                store.load()

    def test_external_damage_cannot_poison_last_good_backup(self):
        with SaveStore(self.path) as store:
            store.save(Colony.new(seed=3), 1000)
            self.path.write_text("externally damaged")
            store.save(Colony.new(seed=3), 1001)
        backup = json.loads(self.path.with_suffix(".json.bak").read_text())
        self.assertEqual(backup["saved_at"], 1000)


if __name__ == "__main__":
    unittest.main()
