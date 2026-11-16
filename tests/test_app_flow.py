"""End-to-end behaviour of the real App: Practice, wand + book de-duplication, tray hide/show.

Needs a desktop to open a (hidden-from-view) Tk window; skipped where that is impossible.
"""
import math
import os
import random
import time

import pytest

import gestures as G
import practice as P
import settings as S


def circle():
    return [[3 * math.cos(t / 60 * 6.28), 3 * math.sin(t / 60 * 6.28), .2, .1, 0, 1] for t in range(60)]


def line():
    return [[0, 0, 4 * math.sin(t / 45 * 3.14), .8, .1, .2] for t in range(45)]


KIND = {"lumos": circle, "nox": line, "protego": circle}


class FakeWand:
    connected = True

    def __init__(self):
        self.played = []

    async def play(self, steps):
        self.played.append(steps)

    async def imu_start(self):
        pass

    async def imu_stop(self):
        pass


class FakeTray:
    def __init__(self):
        self.notes, self.titles = [], []

    def notify(self, m, t="x"):
        self.notes.append(m)

    def set_title(self, t):
        self.titles.append(t)

    def refresh_menu(self):
        pass

    def stop(self):
        pass


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("MCC_NO_AUTOCONNECT", "1")
    monkeypatch.setenv("MCC_NO_TRAY", "1")
    random.seed(4)
    import app as A
    import ui_kit
    ui_kit._btn_cache.clear()                     # cached images belong to the previous test's window
    ui_kit._ink_cache.clear()
    try:
        a = A.App()
    except Exception as e:                       # no display / Tk unavailable
        pytest.skip(f"cannot open a window here: {e}")
    a.withdraw()
    a.settings = S.Settings(str(tmp_path / "s.json"))
    a.store = G.GestureStore(str(tmp_path / "g.json"))
    a.pstats = P.PracticeStats(str(tmp_path / "p.json"))
    a.wand = FakeWand()
    for n in ("lumos", "nox", "protego"):
        for _ in range(3):
            a.store.add(n, KIND[n]())
    yield a
    try:
        a.destroy()
    except Exception:
        pass


def pump(a, ms=120):
    end = time.time() + ms / 1000
    while time.time() < end:
        a.update()
        time.sleep(0.01)


def test_practice_flow(app):
    a = app
    a.show("practice", animate=False)
    pump(a)
    a._practice_start()
    pump(a)
    p = a.practice
    t1 = p["target"]
    assert p["active"] and p["state"] == "waiting" and t1 in KIND
    assert a.cv.itemcget(a.p_wins["stop"], "state") == "normal" and a.cv.itemcget(a.p_wins["start"], "state") == "hidden"
    a._gesture_done(KIND[t1]())
    assert p["result"]["ok"] and p["streak"] == 1 and a.pstats.accuracy(t1) == (1, 1)
    a._practice_next()
    t2 = p["target"]
    assert t2 != t1                                            # never the same spell twice in a row
    wrong = line if KIND[t2] is circle else circle
    a._gesture_done(wrong())
    assert not p["result"]["ok"] and p["streak"] == 0
    assert a.cv.itemcget(a.p_wins["add"], "state") == "normal"  # offered: teach it this cast
    before = a.store.casts(t2)
    a._practice_add()
    assert a.store.casts(t2) == before + 1
    a._practice_stop()
    assert not p["active"]


def test_practice_needs_taught_spells_and_a_wand(app):
    a = app
    a.show("practice", animate=False)
    a.store.data.clear()
    a._practice_start()
    assert not a.practice["active"] and "not taught" in a.practice["msg"]
    for _ in range(3):
        a.store.add("lumos", circle())
    a.wand = None
    a._practice_start()
    assert not a.practice["active"] and "Connect your wand" in a.practice["msg"]


def test_book_then_wand_counts_once(app):
    a = app
    a.show("cast", animate=False)
    a._gesture_done(circle())                                  # the book recognises lumos
    a._native_spell("Lumos")                                   # and the wand names it too
    pump(a)
    assert len(a.wand.played) == 1
    assert [(n, s) for _, n, _, s in a.cast_log] == [("lumos", "both")]


def test_wand_first_wins_conflict_with_book(app):
    a = app
    a.show("cast", animate=False)
    a._native_spell("Protego")                                 # the wand names protego...
    a._gesture_done(circle())                                  # ...the book would say lumos for the same cast
    pump(a)
    assert len(a.wand.played) == 1
    assert [n for _, n, _, _ in a.cast_log] == ["protego"]


def test_wand_known_and_stats_are_remembered(app):
    a = app
    a._native_spell("Wingardium Leviosa")
    a._native_spell("Some Unknown Spell")
    assert a.settings.get("wand_known") == ["wingardium_leviosa"]
    assert a._mark("wingardium_leviosa").strip() == "★"
    assert a._mark("lumos").strip() == "✦"                # taught beats "the wand knows it"
    ns = a.settings.get("native_stats")
    assert ns["streaming_on"] == 2 and ns["streaming_off"] == 0
    a.stream_var.set(False)
    a._streaming_changed()
    a._native_spell("Protego")
    assert a.settings.get("native_stats")["streaming_off"] == 1


def test_tray_hide_show_and_close_choices(app):
    a = app
    a.tray = FakeTray()
    closed, asked = [], []
    a._close = lambda: closed.append(1)
    a._close_dialog = lambda: asked.append(1)
    a.settings.set("close_to_tray", "tray")
    a._on_close_request()
    pump(a)
    assert a.hidden and a.state() == "withdrawn" and len(a.tray.notes) == 1     # one-time hint
    a._last_fire = None
    a._cast(circle())                                          # a cast while hidden notifies, no on-page flash
    assert a.tray.notes[-1].endswith("recognised") and not a.cv.find_withtag("flash")
    a.show_window()
    pump(a)
    assert not a.hidden and a.state() == "normal"
    a.settings.set("close_to_tray", "quit")
    a._on_close_request()
    assert closed == [1]
    a.settings.set("close_to_tray", "ask")
    a._on_close_request()
    assert asked == [1]
    a.tray = None
    a._on_close_request()                                      # no tray available: just quit
    assert closed == [1, 1]
