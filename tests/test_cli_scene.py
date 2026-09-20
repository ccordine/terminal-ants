import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from terminal_ants.model import Colony
from terminal_ants.scene import View, render

ROOT = Path(__file__).resolve().parent.parent


class ViewerTests(unittest.TestCase):
    def test_render_fits_resized_terminals_and_panels(self):
        colony = Colony.new(seed=11)
        colony.advance(1200)
        for width, height in ((20, 6), (40, 14), (80, 24), (100, 36), (160, 50)):
            for panel in ("", "help", "journal", "instincts", "ant"):
                for hud in (True, False):
                    view = View(hud=hud, panel=panel, scent=True)
                    lines = render(colony, width, height, view).lines()
                    self.assertEqual(len(lines), height)
                    self.assertTrue(all(len(line) == width for line in lines))
                    self.assertTrue(all(line.isascii() for line in lines))
                    if width >= 40 and not panel:
                        self.assertIn("Q", "".join(lines))

    def cli(self, *args):
        return subprocess.run([sys.executable, "-m", "terminal_ants", *args], cwd=ROOT, text=True, capture_output=True, timeout=30)

    def test_status_creates_and_resumes_a_named_colony(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "farm.json")
            first = self.cli("--save", path, "--name", "Fern Hollow", "--seed", "7", "--advance", "600", "--status", "--json")
            self.assertEqual(first.returncode, 0, first.stderr)
            initial = json.loads(first.stdout)
            second = self.cli("--save", path, "--status", "--json")
            self.assertEqual(second.returncode, 0, second.stderr)
            resumed = json.loads(second.stdout)
            self.assertEqual(resumed["name"], "Fern Hollow")
            self.assertGreaterEqual(resumed["colony_age_seconds"], initial["colony_age_seconds"])
            self.assertGreater(initial["soil_dug"], 0)

    def test_demo_snapshot_never_touches_save(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "farm.json"
            result = self.cli("--demo", "--save", str(path), "--snapshot", "--width", "80", "--height", "24")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(path.exists())
            self.assertEqual(len(result.stdout.splitlines()), 24)
            self.assertIn("Q", result.stdout)

    def test_noninteractive_viewer_explains_how_to_run(self):
        result = self.cli()
        self.assertEqual(result.returncode, 2)
        self.assertIn("interactive terminal", result.stderr)

    def test_rejects_invalid_cli_values(self):
        for args in (("--json",), ("--advance", "nan", "--status"), ("--name", "\x1b"), ("--seed", "-1"), ("--width", "1")):
            result = self.cli(*args)
            self.assertEqual(result.returncode, 2, result.stdout)
            self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
