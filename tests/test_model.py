import json
import math
import unittest

from terminal_ants.instincts import construction_need, labor_needs
from terminal_ants.model import Colony, MAX_OFFLINE, SURFACE, WIDTH, catch_up
from collections import Counter


def clone(colony):
    return Colony.from_dict(json.loads(json.dumps(colony.to_dict())))


class ColonyTests(unittest.TestCase):
    def test_ants_move_through_open_adjacent_cells_and_physically_dig(self):
        colony = Colony.new(seed=7)
        for _ in range(900):
            previous = {ant.ident: ant.pos for ant in colony.ants}
            old_tiles = list(colony.tiles)
            colony.advance(1)
            for ant in colony.ants:
                self.assertIn(ant.pos, colony._open)
                if ant.ident in previous:
                    self.assertLessEqual(colony.distance(previous[ant.ident], ant.pos), 1)
            for pos, tile in enumerate(colony.tiles):
                if tile == "." and old_tiles[pos] != ".":
                    self.assertTrue(any(colony.distance(pos, old) == 1 for old in previous.values()))
            self.assertEqual(colony.total_dug, colony.spoil + sum(a.amount for a in colony.ants if a.cargo == "soil"))
        self.assertGreater(colony.rooms, 1)
        self.assertGreater(colony.total_dug, 40)
        self.assertGreater(colony.total_gathered, 0)
        self.assertGreater(colony.total_hatched, 0)

    def test_food_gift_is_left_on_the_surface(self):
        colony = Colony.new(seed=2)
        before_food = colony.food
        before_surface = sum(colony.patches.values())
        colony.scatter_food()
        self.assertEqual(colony.food, before_food)
        self.assertEqual(sum(colony.patches.values()), before_surface + 25)
        colony.scatter_food()
        self.assertEqual(colony.gifts, 1)
        colony.advance(60)
        colony.scatter_food()
        self.assertEqual(colony.gifts, 2)

    def test_save_resume_and_frame_sizes_preserve_the_simulation(self):
        one = Colony.new(seed=41)
        split = clone(one)
        for chunk in (0.25, 20.25, 123.5, 340, 416):
            split.advance(chunk)
            split = clone(split)
        one.advance(900)
        self.assertEqual(one.to_dict(), split.to_dict())

    def test_away_uses_the_same_ant_simulation(self):
        live = Colony.new(seed=42)
        away = clone(live)
        live.advance(1800)
        report = catch_up(away, 1000, 2800)
        self.assertEqual(live.to_dict(), away.to_dict())
        self.assertEqual(report.dug, live.total_dug)
        self.assertEqual(report.hatched, live.total_hatched)

    def test_backwards_clock_does_not_reverse_time(self):
        colony = Colony.new(seed=1)
        report = catch_up(colony, 2000, 1000)
        self.assertEqual(report.simulated, 0)
        self.assertEqual(colony.ticks, 0)

    def test_full_day_away_is_healthy_and_long_absences_are_bounded(self):
        colony = Colony.new(seed=7)
        report = catch_up(colony, 1000, 1000 + MAX_OFFLINE * 2)
        self.assertEqual(report.simulated, MAX_OFFLINE)
        self.assertEqual(colony.ticks, MAX_OFFLINE)
        self.assertGreaterEqual(colony.workers, 60)
        self.assertGreater(colony.food, colony.food_capacity * 0.5)
        self.assertGreater(colony.queen_care, 50)
        self.assertGreater(colony.total_hatched, colony.workers)
        self.assertGreaterEqual(colony.rooms, 8)
        self.assertEqual(colony.total_dug, colony.spoil + sum(a.amount for a in colony.ants if a.cargo == "soil"))
        clone(colony)

    def test_needs_change_the_work_the_colony_requests(self):
        fed = labor_needs(20, 4, 0.9)
        hungry = labor_needs(20, 4, 0.1)
        busy_nursery = labor_needs(20, 16, 0.9)
        self.assertGreater(hungry[0], fed[0])
        self.assertGreater(busy_nursery[1], fed[1])
        need = construction_need(Counter(nursery=1, pantry=1), 30, 3, 31, 96, 0.4, 3, 400)
        self.assertEqual(need[0], "nursery")

    def test_different_seeds_build_different_homes_without_intervention(self):
        homes = []
        for seed in (1, 7, 42):
            colony = Colony.new(seed=seed)
            colony.advance(3600)
            self.assertGreaterEqual(colony.rooms, 5)
            self.assertGreaterEqual(colony.workers, 40)
            self.assertGreater(colony.food, 10)
            self.assertLessEqual(colony.workers + colony.brood_count, colony.capacity)
            homes.append(tuple(p.center for p in colony.projects))
            clone(colony)
        self.assertEqual(len(set(homes)), 3)

    def test_invalid_elapsed_time_is_rejected(self):
        colony = Colony.new()
        for elapsed in (-1, math.inf, math.nan):
            with self.assertRaises(ValueError):
                colony.advance(elapsed)

    def test_save_validation_rejects_ants_inside_soil(self):
        data = Colony.new(seed=1).to_dict()
        data["ants"][0]["pos"] = 20 * WIDTH + 20
        with self.assertRaisesRegex(ValueError, "behavior"):
            Colony.from_dict(data)

    def test_save_validation_rejects_routes_crossing_soil(self):
        data = Colony.new(seed=1).to_dict()
        data["ants"][0]["path"] = [(SURFACE + 1) * WIDTH + 3]
        with self.assertRaisesRegex(ValueError, "solid soil"):
            Colony.from_dict(data)


if __name__ == "__main__":
    unittest.main()
