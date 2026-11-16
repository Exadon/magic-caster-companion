"""The matcher compares the SHAPE of a motion, not how hard it was cast."""
import math
import random

import gestures as G


def motion(kind, vigour, n):
    out = []
    for t in range(n):
        u = t / n * 6.28
        if kind == "a":
            g = (vigour * 3 * math.cos(u), vigour * 3 * math.sin(u), 0.0)
        else:  # a similar, but different, figure-of-eight-ish motion
            g = (vigour * 3 * math.cos(u), vigour * 3 * math.sin(2 * u) * 0.9, 0.0)
        out.append([g[0] + random.gauss(0, .15), g[1] + random.gauss(0, .15), g[2], 0.1, 0.0, 1.0])
    return out


def test_normalize_sets_rms_and_keeps_accel():
    f = G.features(motion("a", 1.7, 60))
    n = G.normalize(f)
    rms = math.sqrt(sum(p[0] ** 2 + p[1] ** 2 + p[2] ** 2 for p in n) / len(n))
    assert abs(rms - G.NORM_K) < 1e-9
    assert [p[3:] for p in n] == [p[3:] for p in f]          # posture channels untouched


def test_normalize_is_safe_for_no_motion():
    still = [[0.0, 0.0, 0.0, 0.1, 0.0, 1.0] for _ in range(G.N_POINTS)]
    assert G.normalize(still) == still
    assert G.normalize([]) == []


def test_normalize_does_not_modify_input():
    f = G.features(motion("a", 1.0, 60))
    before = [list(p) for p in f]
    G.normalize(f)
    assert f == before


def test_hard_and_gentle_casts_look_alike():
    random.seed(7)
    a_gentle = G.normalize(G.features(motion("a", 0.4, 60)))
    a_hard = G.normalize(G.features(motion("a", 2.6, 60)))
    b_hard = G.normalize(G.features(motion("b", 2.6, 60)))
    assert G.dtw(a_gentle, a_hard) < 0.5 * G.dtw(a_hard, b_hard)


def test_similar_motions_at_random_strength_are_told_apart(tmp_path):
    random.seed(11)
    ok = total = 0
    for trial in range(25):
        st = G.GestureStore(str(tmp_path / f"s{trial}.json"))
        for kind in "ab":
            for _ in range(3):
                st.add(kind, motion(kind, random.uniform(0.4, 2.6), random.randint(50, 80)))
        for kind in "ab":
            best, _, _ = st.match(motion(kind, random.uniform(0.4, 2.6), random.randint(50, 80)), accept=5.0)
            ok += best == kind
            total += 1
    assert ok / total >= 0.97


def test_old_stored_casts_work_unchanged(tmp_path):
    """Stored features keep their original form, so existing recordings need no migration."""
    random.seed(3)
    st = G.GestureStore(str(tmp_path / "old.json"))
    raw = motion("a", 1.0, 60)
    st.add("a", raw)
    assert st.data["a"][0] == G.features(raw)
