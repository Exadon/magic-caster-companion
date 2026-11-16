import io
import struct
import sys
import time
import types
import wave

import pytest

import actions as A
import sounds as S


def samples(wav_bytes):
    with wave.open(io.BytesIO(wav_bytes)) as w:
        assert w.getnchannels() == 1 and w.getsampwidth() == 2
        raw = w.readframes(w.getnframes())
        return list(struct.unpack("<%dh" % (len(raw) // 2), raw)), w.getframerate()


@pytest.mark.parametrize("style", S.STYLES)
def test_each_style_is_a_short_clean_wav(style):
    s, rate = samples(S.page_turn_wav(1, style, 0.6))
    assert rate == S.RATE
    assert 0.3 < len(s) / rate < 0.7
    assert abs(s[0]) < 40 and abs(s[-1]) < 40            # faded: never starts or ends with a click
    assert max(abs(v) for v in s) <= 0.85 * 0.6 * 32767 + 2   # never louder than the volume allows


@pytest.mark.parametrize("style", S.STYLES)
def test_deterministic_per_seed_and_varies_between_seeds(style):
    assert S.page_turn_wav(1, style) == S.page_turn_wav(1, style)
    assert S.page_turn_wav(1, style) != S.page_turn_wav(2, style)


def test_styles_differ_and_heavy_is_longest_crisp_shortest():
    d = {st: len(samples(S.page_turn_wav(1, st))[0]) for st in S.STYLES}
    assert d["crisp"] < d["soft"] < d["heavy"]
    assert S.page_turn_wav(1, "soft") != S.page_turn_wav(1, "crisp")


def test_volume_scales_the_peak_and_zero_is_silent():
    loud = max(abs(v) for v in samples(S.page_turn_wav(1, "soft", 1.0))[0])
    quiet = max(abs(v) for v in samples(S.page_turn_wav(1, "soft", 0.3))[0])
    assert 2.5 < loud / quiet < 4.0                      # roughly 1.0 / 0.3
    assert max(abs(v) for v in samples(S.page_turn_wav(1, "soft", 0.0))[0]) == 0
    assert max(abs(v) for v in samples(S.page_turn_wav(1, "soft", 5.0))[0]) <= 0.85 * 32767   # clamped


def test_swell_then_fade():
    s, _ = samples(S.page_turn_wav(2, "soft"))
    n = len(s)
    rms = lambda seg: (sum(v * v for v in seg) / len(seg)) ** 0.5
    assert rms(s[int(n * .2):int(n * .5)]) > 3 * rms(s[:int(n * .03)])     # starts soft, swells
    assert rms(s[int(n * .2):int(n * .5)]) > 3 * rms(s[int(n * .70):int(n * .78)])   # lull before the landing


def test_energy_stays_in_the_paper_range():
    """Most of the energy must sit below 6 kHz, otherwise it is hiss rather than paper."""
    import math
    for style in S.STYLES:
        x = S.page_turn_samples(1, style)
        step = 200                                           # crude low/high split: first difference vs. signal
        hi = sum((x[i] - x[i - 1]) ** 2 for i in range(1, len(x)))
        lo = sum(v * v for v in x)
        assert hi / (4 * lo) < 0.5, style                   # fraction of energy near Nyquist stays small


def test_play_cue_page_really_plays_wav_bytes(monkeypatch):
    """play_cue swallows errors, so a missing import fails silently: check the real path end to end."""
    played = []
    fake = types.SimpleNamespace(SND_MEMORY=4, SND_ASYNC=1, PlaySound=lambda data, flags: played.append((data, flags)),
                                 Beep=lambda f, d: None)
    monkeypatch.setitem(sys.modules, "winsound", fake)
    A._page_cache.clear()
    A.play_cue("page", style="crisp", volume=0.5)
    for _ in range(100):
        if played:
            break
        time.sleep(0.05)
    assert played, "play_cue('page') produced no sound"
    data, flags = played[0]
    assert data[:4] == b"RIFF" and flags == 4              # a WAV held in memory, played synchronously


def test_play_cue_page_zero_volume_and_bad_style(monkeypatch):
    played = []
    fake = types.SimpleNamespace(SND_MEMORY=4, SND_ASYNC=1, PlaySound=lambda d, f: played.append(d),
                                 Beep=lambda f, d: None)
    monkeypatch.setitem(sys.modules, "winsound", fake)
    A.play_cue("page", style="soft", volume=0.0)
    time.sleep(0.3)
    assert played == []                                    # volume 0 stays silent
    A.play_cue("page", style="nonsense", volume=0.5)       # an unknown style falls back to soft
    for _ in range(100):
        if played:
            break
        time.sleep(0.05)
    assert played
