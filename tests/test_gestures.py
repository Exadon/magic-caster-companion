import math
import random

import pytest

import gestures as G
from mcwand import ImuSample


def circle(scale=1.0, n=60, noise=0.05):
    return [[scale * 3 * math.cos(t / n * 6.28) + random.gauss(0, noise), scale * 3 * math.sin(t / n * 6.28),
             0.2, 0.1, 0.0, 1.0] for t in range(n)]


def line(n=45):
    return [[0, 0, 4 * math.sin(t / n * 3.14) + random.gauss(0, .05), 0.8, 0.1, 0.2] for t in range(n)]


@pytest.fixture
def store(tmp_path):
    random.seed(1)
    st = G.GestureStore(str(tmp_path / "g.json"))
    for _ in range(3):
        st.add("circle", circle(random.uniform(.9, 1.1), random.randint(50, 75)))
        st.add("line", line(random.randint(35, 55)))
    return st


def test_resample_length_and_endpoints():
    seq = [[float(i)] * 6 for i in range(10)]
    r = G.resample(seq, 40)
    assert len(r) == 40 and r[0][0] == 0.0 and r[-1][0] == 9.0


def test_dtw_identical_is_zero_and_different_is_not():
    a = G.features(circle())
    assert G.dtw(a, a) == pytest.approx(0.0)
    assert G.dtw(a, G.features(line())) > 0.3


def test_matching_accuracy(store):
    ok = 0
    for _ in range(10):
        ok += store.match(circle(random.uniform(.9, 1.1), random.randint(50, 75)))[0] == "circle"
        ok += store.match(line(random.randint(35, 55)))[0] == "line"
    assert ok == 20


def test_accept_threshold_rejects(store):
    best, dist, _ = store.match(circle(), accept=0.0)
    assert best is None and dist > 0


def test_quality_check_rejects_cast_that_looks_like_another_spell(store):
    ok, msg, _ = store.check("circle", line())
    assert not ok and "more like Line" in msg
    ok, _, _ = store.check("circle", circle())
    assert ok


def test_quality_check_rejects_outlier_for_single_spell(tmp_path):
    random.seed(2)
    st = G.GestureStore(str(tmp_path / "x.json"))
    for _ in range(3):
        st.add("circle", circle())
    ok, msg, _ = st.check("circle", line())
    assert not ok and "different" in msg


def test_quality_check_accepts_first_cast(tmp_path):
    st = G.GestureStore(str(tmp_path / "x.json"))
    assert st.check("circle", line()) == (True, "", None)


def test_self_check_and_suggestion(store):
    r = store.self_check()
    assert r["total"] == 6 and r["correct"] == 6
    assert 0.3 <= r["suggested_accept"] <= 2.0


def test_self_check_none_without_data(tmp_path):
    assert G.GestureStore(str(tmp_path / "e.json")).self_check() is None


def test_persistence_and_raw_cap(tmp_path):
    p = str(tmp_path / "p.json")
    st = G.GestureStore(p)
    for _ in range(G.MAX_RAW_PER_SPELL + 5):
        st.add("circle", circle())
    again = G.GestureStore(p)
    assert len(again.data["circle"]) == G.MAX_RAW_PER_SPELL + 5
    assert len(again.raw["circle"]) == G.MAX_RAW_PER_SPELL


def test_export_import_roundtrip(store, tmp_path):
    out = str(tmp_path / "share.json")
    store.export_to(out)
    other = G.GestureStore(str(tmp_path / "o.json"))
    assert other.import_from(out) == 6
    assert set(other.data) == {"circle", "line"}


def test_import_rejects_garbage(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"hello": 1}')
    st = G.GestureStore(str(tmp_path / "s.json"))
    with pytest.raises(ValueError):
        st.import_from(str(bad))
    junk = tmp_path / "junk.json"
    junk.write_text('{"gestures": {"x": [[1,2,3]]}}')
    assert st.import_from(str(junk)) == 0


def test_segmenter_produces_gesture():
    seg, res, t = G.Segmenter(), None, 0.0
    for i in range(120):
        spin = 5 if 20 <= i < 60 else 0.1
        r = seg.feed(ImuSample((spin, 0, 0), (0, 0, 1)), now=t)
        t += 0.02
        res = res or r
    assert res is not None and 40 <= len(res) <= 70


def test_segmenter_ignores_tiny_jolt():
    seg, t = G.Segmenter(), 0.0
    out = []
    for i in range(80):
        spin = 5 if 10 <= i < 12 else 0.1
        out.append(seg.feed(ImuSample((spin, 0, 0), (0, 0, 1)), now=t))
        t += 0.02
    assert not any(out)
