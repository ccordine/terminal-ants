"""The colony's small, editable behavior policy.

Change these functions to experiment with instincts. They choose what the
group needs; individual ants in model.py still have to do the physical work.
"""
from collections import Counter
import math


def labor_needs(workers: int, brood: int, food_ratio: float) -> tuple[int, int]:
    """Hunger recruits foragers; a growing brood recruits nurses."""
    foragers = max(3, math.ceil(workers * (0.65 if food_ratio < 0.35 else 0.38)))
    nurses = max(1, math.ceil(brood / 4)) if brood else 0
    return foragers, nurses


def construction_need(
    kinds: Counter, population: int, brood: int, capacity: int,
    max_population: int, food_ratio: float, rooms: int, ticks: int,
) -> tuple[str, str] | None:
    """A shared need becomes one dig plan. Nothing is built by this function."""
    if brood and not kinds["nursery"]:
        return "nursery", "The brood needs a sheltered nursery. Workers begin a new branch."
    if food_ratio > 0.55 and not kinds["pantry"]:
        return "pantry", "Food is piling up. The colony begins digging a pantry."
    if population >= capacity * 0.75 and capacity < max_population:
        return "nursery", "The nest is getting crowded. Workers make room for the next generation."
    if food_ratio > 0.85 and kinds["pantry"] < 3:
        return "pantry", "The stores are filling. A new pantry will hold the surplus."
    if ticks % 600 == 0 and rooms < 18:
        return "gallery", "Explorers choose a promising patch of earth for another passage."
    return None
