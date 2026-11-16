"""Windows integration: single running copy, start with Windows, and a system-tray icon."""
import ctypes
import ctypes.wintypes as wt
import os
import sys
import threading

try:
    import winreg
except ImportError:          # not Windows
    winreg = None

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "MagicCasterCompanion"
_ERROR_ALREADY_EXISTS = 183
_INFINITE = 0xFFFFFFFF


# ---------------------------------------------------------------- start with Windows
def autostart_command() -> str:
    """The command Windows should run at sign-in (always starts minimised to the tray)."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --minimized'
    exe = sys.executable
    pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.exists(pyw):
        exe = pyw
    return f'"{exe}" "{os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py")}" --minimized'


def autostart_enabled(key: str = RUN_KEY, value: str = RUN_VALUE) -> bool:
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_READ) as k:
            winreg.QueryValueEx(k, value)
            return True
    except OSError:
        return False


def set_autostart(on: bool, key: str = RUN_KEY, value: str = RUN_VALUE, command: str | None = None) -> bool:
    """Add or remove the per-user start-up entry. Returns True if it now matches `on`."""
    if winreg is None:
        return False
    try:
        if on:
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as k:
                winreg.SetValueEx(k, value, 0, winreg.REG_SZ, command or autostart_command())
        else:
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as k:
                    winreg.DeleteValue(k, value)
            except FileNotFoundError:
                pass
    except OSError:
        return False
    return autostart_enabled(key, value) == on


# ---------------------------------------------------------------- single instance
class SingleInstance:
    """A named mutex marks the running copy; a named event lets a second launch ask it to show its window."""

    def __init__(self, name: str = "MagicCasterCompanion"):
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateMutexW.restype = wt.HANDLE
        k32.CreateMutexW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR]
        k32.CreateEventW.restype = wt.HANDLE
        k32.CreateEventW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.BOOL, wt.LPCWSTR]
        k32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
        k32.WaitForSingleObject.restype = wt.DWORD
        k32.SetEvent.argtypes = [wt.HANDLE]
        self._k32 = k32
        self._mutex = k32.CreateMutexW(None, False, f"Local\\{name}_mutex")
        self.already_running = ctypes.get_last_error() == _ERROR_ALREADY_EXISTS
        self._event = k32.CreateEventW(None, False, False, f"Local\\{name}_show")   # auto-reset

    def ask_existing_to_show(self):
        self._k32.SetEvent(self._event)

    def watch(self, callback):
        """Call `callback()` (from a background thread) whenever another launch asks us to show the window."""
        def loop():
            while True:
                if self._k32.WaitForSingleObject(self._event, _INFINITE) != 0:
                    return
                try:
                    callback()
                except Exception:
                    pass
        threading.Thread(target=loop, daemon=True).start()


# ---------------------------------------------------------------- tray icon
class Tray:
    """System-tray icon with Open / Recognise casts / Connect / Quit. Callbacks run on the tray thread."""

    def __init__(self, image, title, on_open, on_toggle_recognition, is_recognising, on_connect, on_quit):
        import pystray
        self._pystray = pystray
        menu = pystray.Menu(
            pystray.MenuItem("Open the spell book", lambda *_: on_open(), default=True),
            pystray.MenuItem("Recognise casts", lambda *_: on_toggle_recognition(),
                             checked=lambda _item: bool(is_recognising())),
            pystray.MenuItem("Connect wand and base", lambda *_: on_connect()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda *_: on_quit()))
        self.icon = pystray.Icon("magic-caster-companion", image, title, menu)

    def start(self):
        self.icon.run_detached()

    def set_title(self, text: str):
        try:
            self.icon.title = text[:120]          # Windows tooltips are limited to 127 characters
        except Exception:
            pass

    def notify(self, message: str, title: str = "Magic Caster Companion"):
        try:
            self.icon.notify(message, title)
        except Exception:
            pass

    def refresh_menu(self):
        try:
            self.icon.update_menu()
        except Exception:
            pass

    def stop(self):
        try:
            self.icon.stop()
        except Exception:
            pass
