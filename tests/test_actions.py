import ctypes

import pytest

import actions as A
import settings as S


def test_parse_keys():
    assert A.parse_keys("ctrl+shift+m") == [0x11, 0x10, ord("M")]
    assert A.parse_keys("F5") == [0x74]
    assert A.parse_keys("win+d") == [0x5B, ord("D")]
    assert A.parse_keys("playpause") == [0xB3]


@pytest.mark.parametrize("bad", ["", "ctrl+", "ctrl+banana", "a+b"])
def test_parse_keys_rejects(bad):
    with pytest.raises(ValueError):
        A.parse_keys(bad)


def test_input_struct_size_matches_windows():
    # SendInput silently fails if this size is wrong (40 bytes on 64-bit Windows)
    assert ctypes.sizeof(A._INPUT) == (40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)


@pytest.mark.parametrize("action", [
    {"type": "Open web page", "value": "javascript:alert(1)"},
    {"type": "Send webhook (POST)", "value": "ftp://x"},
    {"type": "Play sound file", "value": "song.mp3"},
    {"type": "Press keys", "value": ""},
    {"type": "Nonsense", "value": "x"},
])
def test_validate_rejects(action):
    with pytest.raises(ValueError):
        A.validate(action)


def test_validate_accepts():
    A.validate({"type": "None"})
    A.validate({"type": "Open web page", "value": "https://example.com"})
    A.validate({"type": "Run program", "value": "notepad"})
    A.validate({"type": "Press keys", "value": "ctrl+c"})


def test_settings_roundtrip(tmp_path):
    p = str(tmp_path / "s.json")
    s = S.Settings(p)
    assert s.get("accept") == 0.9
    s.set("accept", 1.2)
    s.set_color("lumos", (1, 2, 3))
    s.set_action("lumos", {"type": "Press keys", "value": "ctrl+l"})
    t = S.Settings(p)
    assert t.get("accept") == 1.2 and t.color("lumos") == (1, 2, 3)
    assert t.action("lumos")["value"] == "ctrl+l"
    t.set_action("lumos", {"type": "None"})
    assert t.action("lumos") is None


def test_settings_ignores_bad_types(tmp_path):
    p = tmp_path / "s.json"
    p.write_text('{"accept": "high", "sounds": false, "junk": 1}')
    s = S.Settings(str(p))
    assert s.get("accept") == 0.9 and s.get("sounds") is False


def _samples(wav_bytes):
    import io
    import struct
    import wave
    with wave.open(io.BytesIO(wav_bytes)) as w:
        assert w.getnchannels() == 1 and w.getsampwidth() == 2
        raw = w.readframes(w.getnframes())
        return list(struct.unpack("<%dh" % (len(raw) // 2), raw)), w.getframerate()


def test_page_turn_sound_is_a_short_quiet_wav():
    s, rate = _samples(A.page_turn_wav(1))
    assert 0.25 < len(s) / rate < 0.45
    peak = max(abs(v) for v in s)
    assert 0.4 * 32767 < peak <= 0.55 * 32767          # audible but not startling, never clipped


def test_page_turn_sound_is_deterministic_and_varies_by_seed():
    assert A.page_turn_wav(1) == A.page_turn_wav(1)
    assert A.page_turn_wav(1) != A.page_turn_wav(2)


def test_page_turn_sound_swells_then_fades():
    s, _ = _samples(A.page_turn_wav(2))
    n = len(s)
    rms = lambda seg: (sum(v * v for v in seg) / len(seg)) ** 0.5
    assert rms(s[int(n * .1):int(n * .3)]) > 2 * rms(s[int(n * .85):])   # louder in the swell than at the end
    assert rms(s[:int(n * .02)]) < rms(s[int(n * .1):int(n * .3)])       # starts soft
