"""What a recognised spell can trigger on the PC, plus small sound cues. Windows only."""
import ctypes
import ctypes.wintypes as wt
import json
import random
import subprocess
import threading
import urllib.request
import webbrowser

import sounds

ACTION_TYPES = ["None", "Press keys", "Run program", "Open web page", "Send webhook (POST)", "Play sound file"]
HINTS = {
    "Press keys": "Keys joined with +, for example ctrl+shift+m, f5, win+d, playpause, volup, mute.",
    "Run program": "A program or command line, for example notepad or \"C:\\Games\\game.exe\" -windowed.",
    "Open web page": "An http:// or https:// address to open in your browser.",
    "Send webhook (POST)": "An http(s) URL. The app POSTs {\"spell\": \"<name>\"} as JSON (works with Home Assistant, IFTTT...).",
    "Play sound file": "Path to a .wav file to play.",
}

_VK = {"ctrl": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B, "enter": 0x0D, "esc": 0x1B, "space": 0x20,
       "tab": 0x09, "backspace": 0x08, "delete": 0x2E, "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
       "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22, "playpause": 0xB3, "next": 0xB0,
       "prev": 0xB1, "stop": 0xB2, "volup": 0xAF, "voldown": 0xAE, "mute": 0xAD}
_VK.update({f"f{i}": 0x6F + i for i in range(1, 13)})
_EXTENDED = {0x26, 0x28, 0x25, 0x27, 0x24, 0x23, 0x21, 0x22, 0x2E}
_MODS = {"ctrl", "shift", "alt", "win"}


def parse_keys(spec: str) -> list:
    """'ctrl+shift+m' -> [0x11, 0x10, 0x4D]. Raises ValueError on unknown keys."""
    parts = [p.strip().lower() for p in spec.split("+") if p.strip()]
    if not parts:
        raise ValueError("no keys given")
    mods = [p for p in parts if p in _MODS]
    keys = [p for p in parts if p not in _MODS]
    if len(keys) != 1:
        raise ValueError("give exactly one key besides ctrl/shift/alt/win, e.g. ctrl+shift+m")
    out = [_VK[m] for m in mods]
    for k in keys:
        if k in _VK:
            out.append(_VK[k])
        elif len(k) == 1 and k.isalnum():
            out.append(ord(k.upper()))
        else:
            raise ValueError(f"unknown key '{k}'")
    return out


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class _INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", _KEYBDINPUT), ("pad", ctypes.c_byte * 32)]
    _anonymous_ = ("u",)
    _fields_ = [("type", wt.DWORD), ("u", _U)]


def send_keys(spec: str):
    vks = parse_keys(spec)
    events = []
    for vk in vks:
        events.append((vk, 0))
    for vk in reversed(vks):
        events.append((vk, 2))
    arr = (_INPUT * len(events))()
    for i, (vk, flag) in enumerate(events):
        if vk in _EXTENDED:
            flag |= 1
        arr[i].type = 1
        arr[i].ki = _KEYBDINPUT(vk, 0, flag, 0, 0)
    ctypes.windll.user32.SendInput(len(events), arr, ctypes.sizeof(_INPUT))


def _check_url(url: str):
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("address must start with http:// or https://")


def validate(action: dict):
    """Raise ValueError if the action is incomplete or unsafe."""
    t, v = action.get("type"), (action.get("value") or "").strip()
    if t in (None, "None"):
        return
    if not v:
        raise ValueError("enter a value for this action")
    if t == "Press keys":
        parse_keys(v)
    elif t in ("Open web page", "Send webhook (POST)"):
        _check_url(v)
    elif t == "Play sound file":
        if not v.lower().endswith(".wav"):
            raise ValueError("only .wav files are supported")
    elif t != "Run program":
        raise ValueError(f"unknown action type '{t}'")


def run_action(action: dict, spell: str) -> str:
    """Run an action without blocking the caller. Returns a short description."""
    validate(action)
    t, v = action["type"], action["value"].strip()
    if t == "Press keys":
        threading.Thread(target=send_keys, args=(v,), daemon=True).start()
    elif t == "Run program":
        subprocess.Popen(v, shell=False)
    elif t == "Open web page":
        webbrowser.open(v)
    elif t == "Send webhook (POST)":
        def post():
            req = urllib.request.Request(v, data=json.dumps({"spell": spell, "source": "magic-caster-companion"}).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
            try:
                urllib.request.urlopen(req, timeout=5).read()
            except Exception:
                pass
        threading.Thread(target=post, daemon=True).start()
    elif t == "Play sound file":
        import winsound
        winsound.PlaySound(v, winsound.SND_FILENAME | winsound.SND_ASYNC)
    return f"{t}: {v}"


_CUES = {"success": [(660, 90), (880, 90), (1320, 160)], "fail": [(300, 160), (220, 220)],
         "saved": [(880, 70)], "connect": [(520, 80), (780, 120)]}


_page_cache: dict = {}


def play_cue(name: str, **opts):
    def go():
        try:
            import winsound
            if name == "page":
                style = opts.get("style", "soft")
                vol = float(opts.get("volume", 0.6))
                if style not in sounds.STYLES:
                    style = "soft"
                if vol <= 0:
                    return
                key = (style, round(vol, 2))
                if key not in _page_cache:
                    _page_cache[key] = [sounds.page_turn_wav(sd, style, vol) for sd in (1, 2, 3)]
                # SND_MEMORY cannot be combined with SND_ASYNC, so this plays (blocking) inside the thread
                winsound.PlaySound(random.choice(_page_cache[key]), winsound.SND_MEMORY)
                return
            for f, d in _CUES.get(name, []):
                winsound.Beep(f, d)
        except Exception:
            pass
    threading.Thread(target=go, daemon=True).start()
