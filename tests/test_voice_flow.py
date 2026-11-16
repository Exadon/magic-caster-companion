"""How the app reacts to spoken spells: voice-only and voice + a swish of the wand."""
import time

import pytest

from test_app_flow import FakeWand, circle, line, pump
from test_app_flow import app  # noqa: F401  (the fixture)
import common


@pytest.fixture
def va(app, monkeypatch):
    a = app
    a.settings.set("voice_mode", "motion")
    a.settings.set("voice_confidence", 0.7)
    a._voice_starts = []
    monkeypatch.setattr(type(a), "_voice_start", lambda self: self._voice_starts.append(1))
    a.show("cast", animate=False)
    pump(a)
    return a


def history(a):
    return [(n, s) for _, n, _, s in a.cast_log]


def test_voice_only_fires_immediately(va):
    va.settings.set("voice_mode", "voice")
    va._voice_heard("lumos", "Lumos", 0.9)
    pump(va)
    assert len(va.wand.played) == 1 and history(va) == [("lumos", "voice")]
    assert va.last_cast["via"] == "voice" and va.last_cast["heard"] == "Lumos"


def test_low_confidence_is_ignored(va):
    va.settings.set("voice_mode", "voice")
    va._voice_heard("lumos", "Lumos", 0.5)
    pump(va)
    assert va.wand.played == [] and va.cast_log == []
    assert va.voice_last == ("Lumos", 0.5)                 # but it is shown, so you can see what it heard


def test_off_mode_does_nothing(va):
    va.settings.set("voice_mode", "off")
    va._voice_heard("lumos", "Lumos", 0.99)
    assert va.wand.played == [] and va._voice_pending is None


def test_motion_mode_waits_for_a_swish_and_any_shape_will_do(va):
    va._voice_heard("lumos", "Lumos", 0.9)                 # said it...
    pump(va)
    assert va.wand.played == [] and va._voice_pending is not None
    va._gesture_done(line())                               # ...then ANY swish (a line, not lumos's circle)
    pump(va)
    assert len(va.wand.played) == 1 and history(va) == [("lumos", "voice")]
    assert va._voice_pending is None
    assert va.last_cast["name"] == "lumos"                 # the book did not also answer "nox" for that swish


def test_swish_first_then_voice_within_the_window(va):
    va.cast_mode.set(False)                                # book recognition off: the swish alone does nothing
    va._gesture_done(circle())
    va._voice_heard("protego", "Protego", 0.9)
    pump(va)
    assert len(va.wand.played) == 1 and history(va) == [("protego", "voice")]


def test_a_stale_swish_does_not_count(va):
    va.cast_mode.set(False)
    va._gesture_done(circle())
    va._last_swish = time.monotonic() - 10                 # that swish was long ago
    va._voice_heard("protego", "Protego", 0.9)
    pump(va)
    assert va.wand.played == [] and va._voice_pending is not None


def test_pending_voice_expires_without_a_swish(va, monkeypatch):
    va._voice_heard("lumos", "Lumos", 0.9)
    key, phrase, conf, t = va._voice_pending
    va._voice_pending = (key, phrase, conf, t - common.VOICE_WINDOW_S - 1)
    va._voice_expire()
    assert va._voice_pending is None and va.wand.played == []
    assert "no swish" in va.log_lines[-1]
    va._gesture_done(circle())                             # a later swish must not resurrect it
    assert history(va) != [("lumos", "voice")]


def test_same_spell_seen_by_book_and_voice_counts_once(va):
    va._gesture_done(line())                               # the book recognises nox
    va._voice_heard("nox", "Nox", 0.9)                     # and the user also said nox
    pump(va)
    assert len(va.wand.played) == 1 and history(va) == [("nox", "both")]


def test_voice_is_ignored_while_teaching_or_practising(va):
    va.rec = {"name": "lumos", "need": 3, "got": 0}
    va._voice_heard("lumos", "Lumos", 0.95)
    assert va._voice_pending is None and va.wand.played == []
    va.rec = None
    va.show("practice", animate=False)
    va.store.add("lumos", circle())
    va._practice_start()
    va._voice_heard("lumos", "Lumos", 0.95)
    assert va._voice_pending is None and va.wand.played == []


def test_swish_during_teaching_never_triggers_voice(va):
    va._voice_pending = ("lumos", "Lumos", 0.9, time.monotonic())
    va.rec = {"name": "nox", "need": 1, "got": 0}
    va._gesture_done(line())                               # this swish is a recording, not a cast
    assert va._voice_pending is not None                   # still waiting: the swish was not used for the voice cast
    assert all(src != "voice" for _, src in history(va))


def test_voice_keys_use_your_spells_but_fall_back_to_all(va):
    assert set(va._voice_keys()) == {"lumos", "nox", "protego"}                  # the three taught in the fixture
    va.store.data.clear()
    assert set(va._voice_keys()) == set(common.SPELLS)                           # fewer than 3: listen for all
    va.settings.set("voice_scope", "all")
    assert set(va._voice_keys()) == set(common.SPELLS)


def test_turning_voice_on_needs_consent_and_can_be_declined(va, monkeypatch):
    va.settings.set("voice_mode", "off")
    monkeypatch.setattr(common, "voice_available", lambda: True)
    import voicing
    monkeypatch.setattr(voicing, "voice_available", lambda: True)
    monkeypatch.setattr(type(va), "_voice_consent", lambda self: False)          # the user says no
    va._voice_set_mode("motion")
    assert va.settings.get("voice_mode") == "off" and va._voice_starts == []
    monkeypatch.setattr(type(va), "_voice_consent", lambda self: self.settings.set("voice_consented", True) or True)
    va._voice_set_mode("motion")
    assert va.settings.get("voice_mode") == "motion" and va._voice_starts == [1]
    assert va.settings.get("voice_consented") is True
    va._voice_set_mode("voice")                            # already agreed: no second prompt
    assert va.settings.get("voice_mode") == "voice"
    va._voice_set_mode("off")
    assert va.settings.get("voice_mode") == "off" and va.voice is None


def test_unavailable_speech_recogniser_is_reported(va, monkeypatch):
    va.settings.set("voice_mode", "off")
    import voicing
    shown = []
    monkeypatch.setattr(voicing, "voice_available", lambda: False)
    monkeypatch.setattr(voicing.messagebox, "showinfo", lambda *a, **k: shown.append(a))
    va._voice_set_mode("voice")
    assert shown and va.settings.get("voice_mode") == "off"


def test_state_changes_from_an_old_listener_are_ignored(va):
    class L:
        pass
    old, new = L(), L()
    va.voice = new
    va._voice_state_changed(old, "error", "stale problem")
    assert va.voice is new and va.voice_state != "error"
    va._voice_state_changed(new, "listening", "")
    assert va.voice_state == "listening"
    shown = [va.cv.itemcget(i, "state") for i in va.voice_light]
    assert shown == ["normal", "normal"]                   # the red "Listening" light is on while the mic is in use
    va._voice_state_changed(new, "error", "No microphone")
    assert va.voice is None and va.voice_state == "error"
    assert [va.cv.itemcget(i, "state") for i in va.voice_light] == ["hidden", "hidden"]


def test_note_text_follows_the_state(va):
    va.settings.set("voice_mode", "off")
    assert "Off" in va._voice_note()
    va.settings.set("voice_mode", "motion")
    va.voice_state, va._voice_n = "listening", 12
    assert "Listening for 12 spells" in va._voice_note() and "swish" in va._voice_note()
    va._voice_pending = ("lumos", "Lumos", 0.9, time.monotonic())
    assert "Heard Lumos" in va._voice_note()
