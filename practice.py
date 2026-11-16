"""Practice mode logic: choose a spell to cast, judge the cast, keep per-spell accuracy."""
import json
import os
import random
from typing import Dict, List, Optional


class PracticeStats:
    """Lifetime hits/tries per spell and best streak, kept in a small JSON file."""

    def __init__(self, path: str):
        self.path = path
        self.spells: Dict[str, Dict[str, int]] = {}
        self.best_streak = 0
        self.load()

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                d = json.load(f)
            for name, v in (d.get("spells") or {}).items():
                if isinstance(v, dict) and isinstance(v.get("tries"), int) and isinstance(v.get("hits"), int):
                    self.spells[name] = {"tries": max(0, v["tries"]), "hits": max(0, min(v["hits"], v["tries"]))}
            if isinstance(d.get("best_streak"), int):
                self.best_streak = max(0, d["best_streak"])
        except (OSError, ValueError, AttributeError):
            pass

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump({"spells": self.spells, "best_streak": self.best_streak}, f)
        except OSError:
            pass

    def record(self, target: str, hit: bool, streak: int = 0):
        s = self.spells.setdefault(target, {"tries": 0, "hits": 0})
        s["tries"] += 1
        s["hits"] += int(hit)
        self.best_streak = max(self.best_streak, streak)
        self.save()

    def accuracy(self, name: str):
        s = self.spells.get(name)
        return (s["hits"], s["tries"]) if s else (0, 0)

    def totals(self):
        return (sum(v["hits"] for v in self.spells.values()), sum(v["tries"] for v in self.spells.values()))

    def weakest(self, n: int = 5):
        """Spells with the lowest hit rate first (only those that have been tried)."""
        tried = [(name, v["hits"] / v["tries"], v["tries"]) for name, v in self.spells.items() if v["tries"]]
        return sorted(tried, key=lambda t: (t[1], -t[2]))[:n]


def pick_target(names: List[str], last: Optional[str] = None, stats: Optional[PracticeStats] = None,
                rng: Optional[random.Random] = None) -> Optional[str]:
    """Random spell, leaning towards ones you are worse at, never the same twice in a row if avoidable."""
    rng = rng or random
    pool = [n for n in names if n != last] or list(names)
    if not pool:
        return None
    weights = []
    for n in pool:
        hits, tries = stats.accuracy(n) if stats else (0, 0)
        weights.append(2.0 if tries == 0 else 1.0 + 2.0 * (1.0 - hits / tries))
    return rng.choices(pool, weights=weights, k=1)[0]


def evaluate(store, gesture, target: str, accept: float) -> dict:
    """Judge one cast against the target spell.

    Returns {ok, got, dist, target_dist, scores}: `got` is what the book recognised (None if nothing within
    the limit), `target_dist` is how far the cast was from the target spell.
    """
    best, dist, scores = store.match(gesture, accept)
    return {"ok": best == target, "got": best, "dist": dist, "target_dist": scores.get(target),
            "scores": scores}
