"""Synthesised page-turn sounds (no audio files to ship).

A page turn is built from four layers, mixed and normalised:
  1. friction  - a soft rub as the page starts to lift
  2. swish     - band-passed noise whose centre frequency sweeps upward as the page travels
  3. crackle   - a few short, bright paper crinkles
  4. landing   - a brief flap of noise plus a low thump as the page settles
"""
import io
import math
import random
import struct
import wave

RATE = 44100
STYLES = ("soft", "crisp", "heavy")
STYLE_LABELS = {"soft": "Soft rustle", "crisp": "Crisp turn", "heavy": "Heavy tome"}

# per-style shaping: duration, sweep range (Hz), band Q, crackle count/brightness, landing flap/thump level
_STYLE = {
    "soft":  dict(dur=0.46, f0=1100, f1=3300, q=2.0, lp=4200, crackles=3, crack_amp=0.22, flap=0.35, thump=0.45, fric=0.5),
    "crisp": dict(dur=0.36, f0=1900, f1=5200, q=2.4, lp=7000, crackles=6, crack_amp=0.40, flap=0.45, thump=0.20, fric=0.3),
    "heavy": dict(dur=0.62, f0=600,  f1=2000, q=1.6, lp=3000, crackles=2, crack_amp=0.18, flap=0.55, thump=0.90, fric=0.7),
}


class _Biquad:
    """RBJ band-pass / low-pass filter whose frequency can be changed while running."""

    def __init__(self, kind: str, rate: int = RATE):
        self.kind, self.rate = kind, rate
        self.x1 = self.x2 = self.y1 = self.y2 = 0.0
        self.b0 = self.b1 = self.b2 = self.a1 = self.a2 = 0.0

    def tune(self, f0: float, q: float):
        w = 2 * math.pi * max(20.0, min(f0, self.rate * 0.45)) / self.rate
        alpha = math.sin(w) / (2 * q)
        cw = math.cos(w)
        if self.kind == "bp":      # constant 0 dB peak gain
            b0, b1, b2 = alpha, 0.0, -alpha
        else:                      # low-pass
            b0, b1, b2 = (1 - cw) / 2, 1 - cw, (1 - cw) / 2
        a0 = 1 + alpha
        self.b0, self.b1, self.b2 = b0 / a0, b1 / a0, b2 / a0
        self.a1, self.a2 = -2 * cw / a0, (1 - alpha) / a0

    def __call__(self, x: float) -> float:
        y = self.b0 * x + self.b1 * self.x1 + self.b2 * self.x2 - self.a1 * self.y1 - self.a2 * self.y2
        self.x2, self.x1, self.y2, self.y1 = self.x1, x, self.y1, y
        return y


def _bell(t: float, peak: float = 0.38) -> float:
    """Smooth 0..1..0 swell over t in [0, 1], peaking at `peak`."""
    if t <= 0 or t >= 1:
        return 0.0
    u = t / peak if t < peak else (1 - t) / (1 - peak)
    return math.sin(u * math.pi / 2) ** 2


def page_turn_samples(seed: int = 0, style: str = "soft", rate: int = RATE):
    """Return the page turn as a list of floats in [-1, 1] (peak-normalised to 1.0)."""
    p = _STYLE[style]
    rnd = random.Random(seed)
    n = int(rate * p["dur"])
    swish_end = 0.78                                   # the swish occupies the first 78% of the sound
    flap_at = int(n * 0.84)
    fric, sweep, thump_lp = _Biquad("lp", rate), _Biquad("bp", rate), _Biquad("lp", rate)
    fric.tune(900, 0.7)
    crack_at = {int(rnd.uniform(0.10, 0.72) * n): rnd.uniform(0.6, 1.0) for _ in range(p["crackles"])}
    flutter_hz, ph = rnd.uniform(24, 40), rnd.uniform(0, 6.28)
    out, crack_amp, crack_len = [], 0.0, 0
    for i in range(n):
        t = i / n
        ts = min(1.0, t / swish_end)                       # progress through the swish, 0..1
        env = _bell(ts)
        if i % 32 == 0:                                    # sweep the band upward as the page travels
            sweep.tune(p["f0"] + (p["f1"] - p["f0"]) * ts ** 0.8, p["q"])
        white = rnd.uniform(-1.0, 1.0)
        s = 0.0
        s += p["fric"] * 0.5 * fric(white) * _bell(min(1.0, t / 0.30), 0.5) * (1 - ts) ** 0.5   # 1. friction
        s += 1.6 * sweep(white) * env * (0.75 + 0.25 * math.sin(2 * math.pi * flutter_hz * t + ph))   # 2. swish
        if i in crack_at:                                  # 3. crackle: short bright bursts
            crack_amp, crack_len = crack_at[i] * p["crack_amp"], int(rate * rnd.uniform(0.003, 0.008))
        if crack_len > 0:
            s += crack_amp * rnd.uniform(-1.0, 1.0) * (crack_len / (rate * 0.008))
            crack_len -= 1
        k = i - flap_at                                    # 4. landing: flap of noise + low thump
        if 0 <= k < int(rate * 0.09):
            decay = math.exp(-k / (rate * 0.022))
            s += p["flap"] * 0.6 * white * decay * 0.5
            f = 150 - 70 * min(1.0, k / (rate * 0.05))     # thump pitch glides down
            s += p["thump"] * 0.55 * math.sin(2 * math.pi * f * k / rate) * decay
        out.append(s)
    tone = _Biquad("lp", rate)                              # keep the energy where paper sounds, not hiss
    tone.tune(p["lp"], 0.707)
    out = [tone(v) for v in out]
    fade = int(rate * 0.004)                               # 4 ms fades so there is never a click
    for j in range(fade):
        g = j / fade
        out[j] *= g
        out[n - 1 - j] *= g
    peak = max(abs(v) for v in out) or 1.0
    return [v / peak for v in out]


def page_turn_wav(seed: int = 0, style: str = "soft", volume: float = 0.6, rate: int = RATE) -> bytes:
    """Mono 16-bit WAV bytes. `volume` is 0..1 and sets the peak level (0.6 is comfortable, never clips)."""
    volume = max(0.0, min(1.0, volume))
    peak = 0.85 * volume
    pcm = b"".join(struct.pack("<h", int(v * peak * 32767)) for v in page_turn_samples(seed, style, rate))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()
