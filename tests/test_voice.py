import base64
import json
import os
import subprocess
import time
import wave

import pytest

import voice as V


def test_clean_phrase_keeps_only_letters_and_spaces():
    assert V.clean_phrase("Lumos") == "Lumos"
    assert V.clean_phrase("  Wingardium   Leviosa ") == "Wingardium Leviosa"
    assert V.clean_phrase("Lumos'; Remove-Item x ") == "Lumos Remove Item x"      # nothing executable survives
    assert V.clean_phrase("$(evil)`n") == "evil n"
    assert V.clean_phrase("123 !!") == ""


def test_phrase_map_has_names_alternatives_and_no_duplicates():
    pm = V.phrase_map(["lumos", "wingardium_leviosa", "the_cheering_charm"])
    assert pm["Lumos"] == "lumos" and pm["Loo mos"] == "lumos"
    assert pm["Wingardium Leviosa"] == "wingardium_leviosa"
    assert pm["The Cheering Charm"] == "the_cheering_charm"
    assert len({p.lower() for p in pm}) == len(pm)
    assert V.phrase_map(["lumos"], alternates={}) == {"Lumos": "lumos"}
    assert V.phrase_map([]) == {}


def test_every_alternate_belongs_to_a_known_spell():
    import spells_data as SD
    assert set(V.ALTERNATES) <= set(SD.SPELLS)


def test_parse_line():
    assert V.parse_line("READY\n") == ("ready",)
    assert V.parse_line("HEARD\tLumos\t0.912\r\n") == ("heard", "Lumos", 0.912)
    assert V.parse_line("ERROR\tNo audio input\n") == ("error", "No audio input")
    assert V.parse_line("HEARD\tLumos\tnot-a-number") is None
    assert V.parse_line("tick queue=0") is None and V.parse_line("") is None


def test_friendly_errors():
    assert "Microphone" in V.friendly_error("Access is denied to the audio device")
    assert "No microphone" in V.friendly_error("No audio input device found")
    assert V.friendly_error("something odd") == "something odd"


def test_script_builds_a_flat_json_list_and_is_injection_safe():
    s = V.build_script(["Lumos", "Nox'; calc.exe #", "Wingardium Leviosa"])
    body = s.split("@'\n")[1].split("\n'@")[0]
    assert json.loads(body) == ["Lumos", "Nox calc exe", "Wingardium Leviosa"]
    # regression: wrapping ConvertFrom-Json's array in @() nests it, which turned the whole list into ONE phrase
    assert "@(@'" not in s
    assert "SetInputToDefaultAudioDevice" in s and "RecognizeAsync" in s


def test_encode_command_roundtrip():
    s = "Write-Output 'hi'"
    assert base64.b64decode(V.encode_command(s)).decode("utf-16-le") == s


# ---------------------------------------------------------------- real recognition from synthesised speech
def _make_wav(path, text):
    ps = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
          f"$s.SetOutputToWaveFile('{path}'); $s.Speak('{text}'); $s.Dispose()")
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True, timeout=60,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    with wave.open(path) as r:                        # a microphone always has silence after speech: add some
        params, frames = r.getparams(), r.readframes(r.getnframes())
    pad = b"\x00" * int(params.framerate * params.sampwidth * params.nchannels * 1.5)
    with wave.open(path, "wb") as w:
        w.setparams(params)
        w.writeframes(frames + pad)


@pytest.fixture(scope="module")
def have_speech():
    if not V.available():
        pytest.skip("no English Windows speech recogniser installed")
    return True


@pytest.mark.parametrize("name,key", [("Protego", "protego"), ("Wingardium Leviosa", "wingardium_leviosa"),
                                      ("Nox", "nox")])
def test_listener_recognises_spoken_spell_from_a_wav(have_speech, tmp_path, name, key):
    wav = str(tmp_path / "spoken.wav")
    try:
        _make_wav(wav, name)
    except Exception as e:
        pytest.skip(f"cannot synthesise speech here: {e}")
    heard, states = [], []
    pm = V.phrase_map(["lumos", "nox", "wingardium_leviosa", "protego"])
    listener = V.VoiceListener(pm, lambda k, p, c: heard.append((k, p, c)), lambda s, d: states.append(s), wav=wav)
    listener.start()
    t0 = time.time()
    while time.time() - t0 < 30 and not heard:
        time.sleep(0.1)
    listener.stop()
    assert heard, f"nothing heard; states: {states}"
    assert heard[0][0] == key and heard[0][2] > 0.8
    assert states[:2] == ["starting", "listening"] and states[-1] == "stopped"
    assert not listener.running


def test_stop_kills_the_process_and_is_safe_twice():
    states = []
    listener = V.VoiceListener({"Lumos": "lumos"}, lambda *a: None, lambda s, d: states.append(s))
    listener.stop()                                    # stopping something never started is harmless
    listener.stop()
    assert not listener.running
