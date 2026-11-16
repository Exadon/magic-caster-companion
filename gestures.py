"""Gesture segmentation, storage and matching (dynamic time warping)."""
import json
import math
import os
import statistics
import time
from typing import Dict, List, Optional, Tuple

N_POINTS = 40            # every gesture is resampled to this many points
START_SPIN = 2.0         # rad/s: motion above this starts a gesture
STOP_SPIN = 1.0          # rad/s: motion below this for QUIET_S ends it
QUIET_S = 0.35
MIN_S, MAX_S = 0.3, 4.0
ACCEPT_DIST = 0.9        # default: larger DTW distance than this = "no match"
MAX_RAW_PER_SPELL = 20
UNLOCK_AT = 3            # recorded casts needed before a spell counts as "unlocked"


class Segmenter:
    """Feed IMU samples; returns a finished gesture (list of 6-vectors) or None."""

    def __init__(self):
        self.active = False
        self.buf: List[List[float]] = []
        self.t_start = 0.0
        self.t_quiet: Optional[float] = None

    def feed(self, sample, now: Optional[float] = None):
        now = now if now is not None else time.monotonic()
        vec = [*sample.gyro, *sample.accel]
        spin = math.sqrt(sum(g * g for g in sample.gyro))
        if not self.active:
            if spin > START_SPIN:
                self.active, self.buf, self.t_start, self.t_quiet = True, [vec], now, None
            return None
        self.buf.append(vec)
        if spin < STOP_SPIN:
            self.t_quiet = self.t_quiet or now
            if now - self.t_quiet >= QUIET_S:
                return self._finish(now)
        else:
            self.t_quiet = None
        if now - self.t_start > MAX_S:
            return self._finish(now)
        return None

    def _finish(self, now):
        dur = now - self.t_start - (QUIET_S if self.t_quiet else 0)
        buf, self.active, self.buf, self.t_quiet = self.buf, False, [], None
        return buf if dur >= MIN_S and len(buf) >= 6 else None


def resample(seq: List[List[float]], n: int = N_POINTS) -> List[List[float]]:
    if len(seq) == 1:
        return [list(seq[0])] * n
    out = []
    for i in range(n):
        pos = i * (len(seq) - 1) / (n - 1)
        lo = int(pos)
        hi = min(lo + 1, len(seq) - 1)
        f = pos - lo
        out.append([a + (b - a) * f for a, b in zip(seq[lo], seq[hi])])
    return out


def features(seq: List[List[float]]) -> List[List[float]]:
    """Resample, then scale gyro (rad/s) and accel (g) to comparable ranges."""
    r = resample(seq)
    return [[g[0] / 8, g[1] / 8, g[2] / 8, g[3], g[4], g[5]] for g in r]


NORM_K = 0.4   # rms gyro magnitude after normalisation; keeps distances on the same scale as before


def normalize(f: List[List[float]], k: float = NORM_K) -> List[List[float]]:
    """Compare the SHAPE of a motion, not how hard it was cast.

    Scales the gyro channels so the cast's rms rotation is always k (hard and gentle casts of the same motion then
    look alike). Accelerometer channels carry posture information and are left alone. Stored casts keep their
    un-normalised features, so older recordings need no migration.
    """
    rms = math.sqrt(sum(p[0] ** 2 + p[1] ** 2 + p[2] ** 2 for p in f) / len(f)) if f else 0.0
    s = k / rms if rms > 1e-9 else 1.0
    return [[p[0] * s, p[1] * s, p[2] * s, p[3], p[4], p[5]] for p in f]


def dtw(a: List[List[float]], b: List[List[float]], band: int = 8) -> float:
    n, m = len(a), len(b)
    inf = float("inf")
    prev = [inf] * (m + 1)
    prev[0] = 0.0
    for i in range(1, n + 1):
        cur = [inf] * (m + 1)
        for j in range(max(1, i - band), min(m, i + band) + 1):
            d = math.dist(a[i - 1], b[j - 1])
            cur[j] = d + min(prev[j], cur[j - 1], prev[j - 1])
        prev = cur
    return prev[m] / (n + m)


def _valid_features(f) -> bool:
    return (isinstance(f, list) and len(f) == N_POINTS and
            all(isinstance(p, list) and len(p) == 6 and all(isinstance(x, (int, float)) for x in p) for p in f))


class GestureStore:
    def __init__(self, path: str):
        self.path = path
        self.raw_path = os.path.splitext(path)[0] + "_raw.json"
        self.data: Dict[str, List[List[List[float]]]] = {}
        self.raw: Dict[str, List[List[List[float]]]] = {}
        self.load()

    # ---- persistence ----
    def load(self):
        self.data, self.raw = self._read(self.path), self._read(self.raw_path)

    @staticmethod
    def _read(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def save(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f)
        with open(self.raw_path, "w", encoding="utf-8") as f:
            json.dump(self.raw, f)

    # ---- progress ----
    def casts(self, name: str) -> int:
        return len(self.data.get(name, []))

    def state(self, name: str) -> str:
        """'locked' (no casts), 'learning' (1 to UNLOCK_AT-1 casts) or 'unlocked' (UNLOCK_AT or more).

        Recognition works for learning spells too; more casts just make it more reliable.
        """
        n = self.casts(name)
        return "unlocked" if n >= UNLOCK_AT else "learning" if n >= 1 else "locked"

    def unlocked(self) -> List[str]:
        return sorted(n for n in self.data if self.state(n) == "unlocked")

    # ---- recording ----
    def check(self, name: str, seq: List[List[float]]) -> Tuple[bool, str, Optional[float]]:
        """Is this new cast consistent with the ones already recorded for the spell?"""
        existing = [normalize(t) for t in self.data.get(name, [])]
        if not existing:
            return True, "", None
        f = normalize(features(seq))
        d = min(dtw(f, t) for t in existing)
        # closer to a different spell than to this one? (catches a stray motion contaminating the set)
        for other, ts in self.data.items():
            if other != name and ts:
                od = min(dtw(f, normalize(t)) for t in ts)
                if od < d:
                    pretty = other.replace("_", " ").title()
                    return False, f"That cast looks more like {pretty} than this spell.", d
        if len(existing) >= 2:
            pair = [dtw(a, b) for i, a in enumerate(existing) for b in existing[i + 1:]]
            typical = statistics.median(pair)
            if d > max(2.0 * typical, 0.2):
                return False, "That cast looked quite different from your others for this spell.", d
        return True, "", d

    def add(self, name: str, seq: List[List[float]]):
        self.data.setdefault(name, []).append(features(seq))
        raws = self.raw.setdefault(name, [])
        raws.append([[round(x, 4) for x in v] for v in seq])
        del raws[:-MAX_RAW_PER_SPELL]
        self.save()

    def remove(self, name: str):
        self.data.pop(name, None)
        self.raw.pop(name, None)
        self.save()

    # ---- matching ----
    def match(self, seq: List[List[float]], accept: float = ACCEPT_DIST
              ) -> Tuple[Optional[str], float, Dict[str, float]]:
        if not self.data:
            return None, float("inf"), {}
        f = normalize(features(seq))
        scores = {n: min(dtw(f, normalize(t)) for t in ts) for n, ts in self.data.items()}
        best = min(scores, key=scores.get)
        return (best if scores[best] <= accept else None), scores[best], scores

    def self_check(self) -> Optional[dict]:
        """Leave-one-out test of your recorded casts.

        Returns {'correct', 'total', 'confused': [(spell, mistaken_for)], 'suggested_accept'} or None
        when there is not enough data (needs a spell with 2+ casts).
        """
        total = correct = 0
        same_dists: List[float] = []
        confused = []
        norm = {n: [normalize(t) for t in ts] for n, ts in self.data.items()}
        for name, samples in norm.items():
            if len(samples) < 2:
                continue
            for i, s in enumerate(samples):
                best_n, best_d = None, float("inf")
                for n2, ts in norm.items():
                    for j, t in enumerate(ts):
                        if n2 == name and j == i:
                            continue
                        d = dtw(s, t)
                        if d < best_d:
                            best_n, best_d = n2, d
                total += 1
                if best_n == name:
                    correct += 1
                    same_dists.append(best_d)
                else:
                    confused.append((name, best_n))
        if not total:
            return None
        sugg = None
        if same_dists:
            same_dists.sort()
            p90 = same_dists[min(len(same_dists) - 1, int(0.9 * len(same_dists)))]
            sugg = round(min(2.0, max(0.3, p90 * 1.3)), 2)
        return {"correct": correct, "total": total, "confused": confused, "suggested_accept": sugg}

    # ---- sharing ----
    def export_to(self, path: str):
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"format": "magic-caster-companion-gestures", "version": 1, "gestures": self.data}, f)

    def import_from(self, path: str) -> int:
        """Merge casts from an exported file. Returns the number of casts added. Raises ValueError if invalid."""
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        g = d.get("gestures") if isinstance(d, dict) else None
        if not isinstance(g, dict):
            raise ValueError("not a Magic Caster Companion gestures file")
        added = 0
        for name, samples in g.items():
            if not isinstance(name, str) or not isinstance(samples, list):
                continue
            for s in samples:
                if _valid_features(s):
                    self.data.setdefault(name, []).append(s)
                    added += 1
        if added:
            self.save()
        return added
