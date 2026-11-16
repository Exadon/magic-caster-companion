import ui_kit as U


def test_state_colors():
    assert U.state_color("connected") == "#3aa655"
    assert U.state_color("connecting...") == U.state_color("looking for the wand...") == "#e0a526"
    assert U.state_color("waiting for the base (wave it)...") == "#e0a526"
    assert U.state_color("failed: nope") == "#c0392b"
    assert U.state_color("not connected") == U.state_color("disconnected") == "#8c7b62"


def test_battery_helpers():
    assert U.battery_percent("82%") == 82
    assert U.battery_percent("100%") == 100
    assert U.battery_percent("250%") == 100
    assert U.battery_percent("-") is None and U.battery_percent("") is None
    assert U.battery_color(80) == "#3aa655" and U.battery_color(20) == "#e0a526" and U.battery_color(5) == "#c0392b"
    assert U.battery_color(None) == "#8c7b62"


def test_button_images_scale_with_text_and_have_alpha():
    short, long_ = U.btn_pil("Go"), U.btn_pil("Connect wand & base")
    assert long_.width > short.width and short.height == long_.height == 34
    assert short.mode == "RGBA"
    assert short.getpixel((0, 0))[3] == 0          # rounded corner is transparent
    assert short.getpixel((short.width // 2, 2))[3] == 255


def test_button_states_differ():
    a, b, c = (U.btn_pil("Save", s) for s in ("normal", "hover", "down"))
    assert a.tobytes() != b.tobytes() != c.tobytes()


def test_page_and_leather_sizes():
    assert U.make_page(450, 650, True).size == (450, 650)
    assert U.make_leather(1000, 730, (30, 25, 930, 675)).size == (1000, 730)


def test_page_centre_matches_widget_background():
    px = U.make_page(450, 650, False).getpixel((225, 325))
    assert px == (0xe8, 0xd9, 0xb5)   # flat centre must equal PARCH so widgets blend in


def test_tab_images():
    n, h, a = (U.tab_pil("Cast", "#243f73", s) for s in ("normal", "hover", "active"))
    assert n.size == (58, 92) and h.size == (58, 92) and a.size == (68, 92)   # active tab is wider
    assert n.tobytes() != a.tobytes()
    assert n.getpixel((0, 46))[3] == 255           # flush, square edge against the page
    assert n.getpixel((n.width - 1, 0))[3] == 0    # outer top corner is rounded away
    assert n.getpixel((n.width - 1, n.height - 1))[3] == 0
