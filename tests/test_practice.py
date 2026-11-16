import math
import random

import gestures as G
import practice as P


def circle(scale=1.0, n=60):
    return [[scale * 3 * math.cos(t / n * 6.28), scale * 3 * math.sin(t / n * 6.28), 0.2, 0.1, 0.0, 1.0]
            for t in range(n)]


def line(n=45):
    return [[0, 0, 4 * math.sin(t / n * 3.14), 0.8, 0.1, 0.2] for t in range(n)]


def make_store(tmp_path):
    st = G.GestureStore(str(tmp_path / "g.json"))
    for _ in range(3):
        st.add("circle", circle(random.uniform(.9, 1.1)))
        st.add("line", line(random.randint(40, 50)))
    return st


def test_stats_record_and_persist(tmp_path):
    p = str(tmp_path / "p.json")
    s = P.PracticeStats(p)
    s.record("lumos", True, streak=1)
    s.record("lumos", False, streak=0)
    s.record("nox", True, streak=2)
    again = P.PracticeStats(p)
    assert again.accuracy("lumos") == (1, 2) and again.accuracy("nox") == (1, 1)
    assert again.totals() == (2, 3) and again.best_streak == 2
    assert again.accuracy("never") == (0, 0)


def test_stats_weakest_orders_by_hit_rate(tmp_path):
    s = P.PracticeStats(str(tmp_path / "p.json"))
    for hit in (True, True, True):
        s.record("easy", hit)
    for hit in (False, True, False):
        s.record("hard", hit)
    assert [n for n, _, _ in s.weakest(5)] == ["hard", "easy"]


def test_stats_ignore_corrupt_file(tmp_path):
    p = tmp_path / "p.json"
    p.write_text('{"spells": {"a": {"tries": "x"}, "b": {"tries": 3, "hits": 9}}, "best_streak": "no"}')
    s = P.PracticeStats(str(p))
    assert "a" not in s.spells and s.spells["b"] == {"tries": 3, "hits": 3}   # hits clamped to tries
    assert s.best_streak == 0
    p.write_text("not json")
    assert P.PracticeStats(str(p)).totals() == (0, 0)


def test_pick_target_avoids_repeat_and_handles_edges():
    rng = random.Random(1)
    for _ in range(50):
        assert P.pick_target(["a", "b", "c"], last="a", rng=rng) != "a"
    assert P.pick_target(["only"], last="only") == "only"      # nothing else to choose
    assert P.pick_target([]) is None


def test_pick_target_leans_towards_weak_spells(tmp_path):
    s = P.PracticeStats(str(tmp_path / "p.json"))
    for _ in range(10):
        s.record("strong", True)
        s.record("weak", False)
    rng = random.Random(3)
    picks = [P.pick_target(["strong", "weak"], stats=s, rng=rng) for _ in range(400)]
    assert picks.count("weak") > 2 * picks.count("strong")


def test_evaluate_hit_and_miss(tmp_path):
    random.seed(2)
    st = make_store(tmp_path)
    hit = P.evaluate(st, circle(1.05), "circle", accept=0.9)
    assert hit["ok"] and hit["got"] == "circle" and hit["target_dist"] is not None
    miss = P.evaluate(st, line(), "circle", accept=0.9)
    assert not miss["ok"] and miss["got"] == "line"
    assert miss["target_dist"] > miss["dist"]                    # closer to what it thought than to the target
    nothing = P.evaluate(st, line(), "circle", accept=-1.0)       # a limit nothing can meet
    assert not nothing["ok"] and nothing["got"] is None
