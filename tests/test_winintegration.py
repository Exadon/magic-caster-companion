import time
import winreg

import pytest

import winintegration as W

TEST_KEY = "Software\\MagicCasterCompanionTest\\Run"       # a throwaway key: never the real Run key


@pytest.fixture
def temp_key():
    yield TEST_KEY
    for k in (TEST_KEY, "Software\\MagicCasterCompanionTest"):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, k)
        except OSError:
            pass


def test_autostart_on_off_roundtrip(temp_key):
    assert not W.autostart_enabled(temp_key)
    assert W.set_autostart(True, temp_key, command='"C:/x/app.exe" --minimized')
    assert W.autostart_enabled(temp_key)
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, temp_key) as k:
        assert winreg.QueryValueEx(k, W.RUN_VALUE)[0] == '"C:/x/app.exe" --minimized'
    assert W.set_autostart(False, temp_key)
    assert not W.autostart_enabled(temp_key)
    assert W.set_autostart(False, temp_key)                  # removing something already gone is fine


def test_autostart_command_starts_minimised():
    cmd = W.autostart_command()
    assert cmd.endswith("--minimized") and cmd.startswith('"')


def test_this_test_run_does_not_touch_the_real_run_key():
    assert W.RUN_KEY.endswith("CurrentVersion\\Run") and TEST_KEY != W.RUN_KEY


def test_single_instance_second_launch_signals_first():
    first = W.SingleInstance("MCC_unit_test_instance")
    second = W.SingleInstance("MCC_unit_test_instance")
    assert not first.already_running and second.already_running
    hits = []
    first.watch(lambda: hits.append(1))
    second.ask_existing_to_show()
    for _ in range(40):
        if hits:
            break
        time.sleep(0.05)
    assert hits == [1]


def test_tray_wrapper_builds_menu_without_starting():
    from PIL import Image
    calls = []
    t = W.Tray(Image.new("RGBA", (16, 16)), "t", on_open=lambda: calls.append("open"),
               on_toggle_recognition=lambda: calls.append("toggle"), is_recognising=lambda: True,
               on_connect=lambda: calls.append("connect"), on_quit=lambda: calls.append("quit"))
    labels = [str(i.text) for i in t.icon.menu.items if getattr(i, "text", None) and not str(i.text).startswith("-")]
    assert labels == ["Open the spell book", "Recognise casts", "Connect wand and base", "Quit"]
    t.set_title("x" * 300)                                    # an over-long tooltip is trimmed, not an error
    assert len(t.icon.title) <= 127
