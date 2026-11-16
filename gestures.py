"""Gesture segmentation, storage and matching (dynamic time warping)."""
import json
import math
import os
import time
from typing import Dict, List, Optional, Tuple

N_POINTS = 40            # every gesture is resampled to this many points
START_SPIN = 2.0         # rad/s: motion above this starts a gesture
STOP_SPIN = 1.0          # rad/s: motion below this for QUIET_S ends it
QUIET_S = 0.35
MIN_S, MAX_S = 0.3, 4.0
ACCEPT_DIST = 0.9        # larger DTW distance than this = "no match"


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


class GestureStore:
    def __init__(self, path: str):
        self.path = path
        self.data: Dict[str, List[List[List[float]]]] = {}
        self.load()

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                self.data = json.load(f)
        except (OSError, ValueError):
            self.data = {}

    def save(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f)

    def add(self, name: str, seq: List[List[float]]):
        self.data.setdefault(name, []).append(features(seq))
        self.save()

    def remove(self, name: str):
        self.data.pop(name, None)
        self.save()

    def match(self, seq: List[List[float]]) -> Tuple[Optional[str], float, Dict[str, float]]:
        if not self.data:
            return None, float("inf"), {}
        f = features(seq)
        scores = {n: min(dtw(f, t) for t in ts) for n, ts in self.data.items()}
        best = min(scores, key=scores.get)
        return (best if scores[best] <= ACCEPT_DIST else None), scores[best], scores
