"""Magic Caster Companion: a spell-book desktop app for the Magic Caster Wand and Box."""
import asyncio
import collections
import math
import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk
from tkinter import font as tkfont

from PIL import Image, ImageTk

import gestures
from actions import ACTION_TYPES, HINTS, play_cue, run_action, validate
from gestures import UNLOCK_AT
from mcwand import Box, LED_GROUPS, Wand, scan
from practice import PracticeStats, evaluate, pick_target
from settings import DATA_DIR, Settings
from sounds import STYLE_LABELS, STYLES
from spells_data import (CAST_STEPS, DESCRIPTIONS, SPELLS, diagram_paths, pretty, resource_path,
                         spell_color, spell_effect, spell_key)
from ui_kit import (CARD, CARD_EDGE, FIELD, GOLD, INK, LEATHER, PARCH, PARCH_DARK, RED, SERIF,
                    RoundButton, Tip, apply_styles, battery_color, battery_percent, ink_image, make_leather,
                    make_page, state_color, style_titlebar, tab_pil)
from version import __version__
from winintegration import SingleInstance, Tray, autostart_enabled, set_autostart

W, H = 1000, 730
BX0, BX1, BY0, BY1 = 30, 930, 25, 675
SPINE = (BX0 + BX1) // 2
LX, RX = BX0 + 28, SPINE + 28          # left/right page content origins
PAGE_W = SPINE - BX0 - 56              # usable content width of a page
SX0, SX1 = BX0 + 36, BX1 - 36          # content edges of a full two-page spread
RETRY_S = 6                            # seconds between automatic reconnect attempts
MUTED = "#7a6a4a"

TABS = [("devices", "Devices", "#8a2323"), ("spells", "Spells", "#2f6b3a"), ("teach", "Teach", "#1f6b72"),
        ("practice", "Practice", "#b5541f"), ("cast", "Cast", "#243f73"), ("lights", "Lights", "#b8862b"),
        ("notes", "Notes", "#5a2f6b")]
MARK = {"unlocked": "✦ ", "learning": "◇ ", "locked": "   "}
FIRE_WINDOW_S = 2.5   # the wand and the book seeing the same cast within this window count as one cast
STATE_TEXT = {"unlocked": "✦ Unlocked", "learning": "◇ Learning", "locked": "Locked"}


def hexcolor(rgb):
    return "#%02x%02x%02x" % tuple(int(x) for x in rgb)


class App(tk.Tk):
    def __init__(self, start_hidden=False):
        super().__init__()
        self.title(f"Magic Caster Companion - Spell Book  v{__version__}")
        self.geometry(f"{W}x{H}")
        self.resizable(False, False)
        self.configure(bg=LEATHER)
        try:
            self.iconbitmap(resource_path(os.path.join("assets", "icon.ico")))
        except tk.TclError:
            pass
        self.q: "queue.Queue" = queue.Queue()
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        self.scan_lock = None

        self.settings = Settings()
        self.wand: Wand | None = None
        self.box: Box | None = None
        self.found = {}
        self.found_at = 0.0
        self.connecting = {"wand": False, "box": False}
        self.user_off = {"wand": False, "box": False}
        self.color = (255, 200, 80)
        self.sel_spell = "lumos" if "lumos" in SPELLS else SPELLS[0]
        self.spin = 0.0
        self.spin_hist = collections.deque(maxlen=400)      # (time, spin) for the live motion trace
        self.last_cast: dict | None = None                  # most recent free cast, for the Cast page
        self.cast_log: list = []                            # [(clock, spell or None, distance)]
        self.meter = None
        self.scope = None
        self.status_item = None
        self.note_item = None
        self.pip_item = None
        self.empty_item = None
        self.dev_dots: dict = {}
        self.batt_bars: dict = {}
        self.log_lines: list[str] = []
        self.logbox: tk.Text | None = None
        self.store = gestures.GestureStore(os.path.join(DATA_DIR, "gestures.json"))
        self.seg = gestures.Segmenter()
        self.rec: dict | None = None
        self.hidden = False                     # window hidden in the tray
        self.tray: Tray | None = None
        self._tray_hinted = False
        self._recognising = True                # mirror of cast_mode that the tray thread may read safely
        self._last_fire = None                  # (time, spell, source): de-duplicates wand + book recognition
        self.pstats = PracticeStats(os.path.join(DATA_DIR, "practice.json"))
        self.practice = {"active": False, "state": "idle", "target": None, "last": None, "streak": 0,
                         "session": [], "result": None, "gesture": None, "token": 0, "msg": ""}
        self.p_wins: dict = {}
        self.page = None
        self.busy = False
        self.widgets: list[tk.Widget] = []
        self._dlg = None
        self.vars = {k: tk.StringVar(value="-") for k in
                     ("w_state", "w_info", "w_batt", "b_state", "b_info", "b_batt", "b_lid", "b_wand", "b_usb")}
        self.vars["w_state"].set("not connected")
        self.vars["b_state"].set("not connected")
        self.t_status = tk.StringVar(value="Pick a spell, then press Record 3 casts.")
        self.t_status.trace_add("write", lambda *_: self._set_item("status_item", self.t_status.get(), "teach"))
        self.c_note = tk.StringVar(value="")
        self.c_note.trace_add("write", lambda *_: self._set_item("note_item", self.c_note.get(), "cast"))
        self.cast_mode = tk.BooleanVar(value=True)
        self.cast_mode.trace_add("write", lambda *_: self._recognising_changed())
        self.test_mode = tk.BooleanVar(value=self.settings.get("test_mode"))
        self.accept_var = tk.DoubleVar(value=self.settings.get("accept"))
        self.pref_vars = {k: tk.BooleanVar(value=self.settings.get(k))
                          for k in ("sounds", "auto_reconnect", "base_status_light")}
        self.stream_var = tk.BooleanVar(value=self.settings.get("streaming"))
        self.bg_vars = {"tray": tk.BooleanVar(value=self.settings.get("close_to_tray") == "tray"),
                        "notify": tk.BooleanVar(value=self.settings.get("tray_notify")),
                        "autostart": tk.BooleanVar(value=autostart_enabled())}
        self.chip_font = None
        apply_styles(self)

        self.cv = tk.Canvas(self, width=W, height=H, highlightthickness=0, bg=LEATHER)
        self.cv.pack()
        self.chip_font = tkfont.Font(family=SERIF, size=10)
        self.leather = ImageTk.PhotoImage(make_leather(W, H, (BX0, BY0, BX1, BY1)))
        self.cv.create_image(0, 0, image=self.leather, anchor="nw")
        self.cv.create_rectangle(BX0 - 10, BY0 - 10, BX1 + 10, BY1 + 10, outline=GOLD, width=3)
        self.cv.create_rectangle(BX0 - 5, BY0 - 5, BX1 + 5, BY1 + 5, outline="#6b4a1e", width=6)
        ph = BY1 - BY0
        self.left_img = ImageTk.PhotoImage(make_page(SPINE - BX0, ph, True))
        self.right_img = ImageTk.PhotoImage(make_page(BX1 - SPINE, ph, False))
        self.spread_img = ImageTk.PhotoImage(make_page(BX1 - BX0, ph, None))
        self.cv.create_image(BX0, BY0, image=self.left_img, anchor="nw")
        self.cv.create_image(SPINE, BY0, image=self.right_img, anchor="nw")
        self.cv.create_line(SPINE, BY0, SPINE, BY1, fill="#5a3c1c", width=2)
        self._draw_footer()
        for k in ("w_state", "w_batt", "b_state", "b_batt"):
            self.vars[k].trace_add("write", lambda *_: self._refresh_status())
        self._refresh_status()
        self._draw_tabs()
        for i, (key, _l, _c) in enumerate(TABS):
            self.bind_all(f"<Control-Key-{i + 1}>", lambda _e, k=key: self.show(k))

        self.after(50, self._poll)
        self.after(90, self._tick)
        self.after(150, lambda: style_titlebar(self))
        self.protocol("WM_DELETE_WINDOW", self._on_close_request)
        self.show("devices", animate=False)
        if not os.environ.get("MCC_NO_TRAY"):
            self._setup_tray()
        if start_hidden:
            self._tray_hinted = True                 # starting minimised at sign-in: no "still running" notice
            self.after(60, self.hide_to_tray)
        if self.settings.get("auto_reconnect") and not os.environ.get("MCC_NO_AUTOCONNECT"):
            self.after(1200, lambda: self.connect_all(quiet=True))

    # ---------- tray, background and closing ----------
    def _setup_tray(self):
        try:
            img = Image.open(resource_path(os.path.join("assets", "icon.ico"))).convert("RGBA").resize(
                (64, 64), Image.LANCZOS)
            self.tray = Tray(img, "Magic Caster Companion",
                             on_open=lambda: self.ui(self.show_window),
                             on_toggle_recognition=lambda: self.ui(self._toggle_recognition),
                             is_recognising=lambda: self._recognising,
                             on_connect=lambda: self.ui(self.connect_all),
                             on_quit=lambda: self.ui(self._close))
            self.tray.start()
            self._refresh_status()
        except Exception as e:                       # a missing tray must never stop the app from working
            self.tray = None
            self.log(f"System tray unavailable: {e}")

    def _recognising_changed(self):
        self._recognising = bool(self.cast_mode.get())
        if self.tray:
            self.tray.refresh_menu()

    def _toggle_recognition(self):
        self.cast_mode.set(not self.cast_mode.get())

    def show_window(self):
        self.hidden = False
        self.deiconify()
        self.state("normal")
        self.lift()
        self.attributes("-topmost", True)
        self.after(250, lambda: self.attributes("-topmost", False))
        self.focus_force()

    def hide_to_tray(self):
        if not self.tray:
            return
        self.hidden = True
        self.withdraw()
        if not self._tray_hinted:
            self._tray_hinted = True
            self.tray.notify("Still running in the tray, so your wand keeps working. Right-click the icon to quit.")

    def _on_close_request(self):
        """The window's X button: keep running in the tray, or quit, depending on the saved choice."""
        if not self.tray:
            self._close()
            return
        pref = self.settings.get("close_to_tray")
        if pref == "tray":
            self.hide_to_tray()
        elif pref == "quit":
            self._close()
        else:
            self._close_dialog()

    def _close_dialog(self):
        dlg = tk.Toplevel(self)
        dlg.title("Close Magic Caster Companion?")
        dlg.configure(bg=PARCH)
        dlg.resizable(False, False)
        dlg.transient(self)
        dlg.after(100, lambda: style_titlebar(dlg))
        tk.Label(dlg, text="Keep running in the tray?", bg=PARCH, fg=RED, font=(SERIF, 18, "bold italic")).pack(
            padx=22, pady=(16, 4), anchor="w")
        tk.Label(dlg, text="In the tray the wand stays connected and your spell actions keep working, even with "
                           "this window closed.", bg=PARCH, fg=INK, font=(SERIF, 11), wraplength=380,
                 justify="left").pack(padx=22, anchor="w")
        remember = tk.BooleanVar(value=False)
        ttk.Checkbutton(dlg, text="Remember my choice", variable=remember, style="Book.TCheckbutton").pack(
            padx=22, pady=(10, 0), anchor="w")
        row = tk.Frame(dlg, bg=PARCH)
        row.pack(padx=22, pady=(12, 16), anchor="e")

        def choose(v):
            if remember.get():
                self.settings.set("close_to_tray", v)
                self.bg_vars["tray"].set(v == "tray")
            dlg.destroy()
            if v == "tray":
                self.hide_to_tray()
            else:
                self._close()
        self.button("Keep running", lambda: choose("tray"), 0, 0, parent=row).pack(side="left", padx=3)
        self.button("Quit", lambda: choose("quit"), 0, 0, parent=row).pack(side="left", padx=3)
        self.button("Cancel", dlg.destroy, 0, 0, parent=row).pack(side="left", padx=3)
        dlg.update_idletasks()
        dlg.geometry("+%d+%d" % (self.winfo_rootx() + 270, self.winfo_rooty() + 230))
        dlg.grab_set()

    def _bg_changed(self, which):
        on = bool(self.bg_vars[which].get())
        if which == "tray":
            self.settings.set("close_to_tray", "tray" if on else "quit")
        elif which == "notify":
            self.settings.set("tray_notify", on)
        else:
            ok = set_autostart(on)
            if not ok:
                self.bg_vars["autostart"].set(not on)
                self.log("Could not change the start-with-Windows setting.")
            else:
                self.log("Will start with Windows, minimised to the tray." if on else
                         "No longer starts with Windows.")

    # ---------- plumbing ----------
    def run(self, coro, done=None, failed=None):
        fut = asyncio.run_coroutine_threadsafe(coro, self.loop)

        def cb(f):
            exc = f.exception()
            if exc:
                if failed:
                    self.ui(lambda: failed(exc))
                else:
                    self.ui(lambda: self.log(f"Error: {type(exc).__name__}: {exc}"))
            elif done:
                self.ui(lambda: done(f.result()))
        fut.add_done_callback(cb)

    def ui(self, fn):
        self.q.put(fn)

    def _poll(self):
        try:
            while True:
                self.q.get_nowait()()
        except queue.Empty:
            pass
        self.after(50, self._poll)

    def _tick(self):
        if self.meter is not None:
            try:
                self.meter.delete("bar")
                frac = min(1.0, self.spin / 10.0)
                self.meter.create_rectangle(0, 0, int(self.meter.winfo_width() * frac),
                                            self.meter.winfo_height(), fill=RED, width=0, tags="bar")
            except tk.TclError:
                self.meter = None
        if self.scope is not None:
            try:
                self._draw_scope()
            except tk.TclError:
                self.scope = None
        self.after(90, self._tick)

    def _draw_scope(self):
        """Live trace of how fast the wand is turning over the last few seconds."""
        c = self.scope
        c.delete("all")
        w, h = int(c["width"]), int(c["height"])
        top, base = 8, h - 8
        y_of = lambda v: base - min(v, 12.0) / 12.0 * (base - top)
        c.create_line(0, y_of(gestures.START_SPIN), w, y_of(gestures.START_SPIN), fill=GOLD, dash=(4, 3))
        now, win, pts = time.monotonic(), 3.5, []
        for t, v in list(self.spin_hist):
            if now - t <= win:
                pts += [(1 - (now - t) / win) * w, y_of(v)]
        if len(pts) >= 4:
            c.create_line(*pts, fill=RED, width=2, smooth=True)
        else:
            msg = "motion streaming is off" if not self.settings.get("streaming") else "waiting for the wand"
            c.create_text(w / 2, h / 2, text=msg, fill=MUTED, font=(SERIF, 11, "italic"))

    def _set_item(self, attr, text, page):
        item = getattr(self, attr)
        if item is not None and self.page == page:
            try:
                self.cv.itemconfig(item, text=text)
            except tk.TclError:
                setattr(self, attr, None)

    def _draw_footer(self):
        y = H - 24
        self.foot = {}
        for key, x in (("w", W // 2 - 250), ("b", W // 2 + 30)):
            dot = self.cv.create_oval(x, y - 6, x + 12, y + 6, fill="#8c7b62", outline="#1a0f08")
            txt = self.cv.create_text(x + 20, y, anchor="w", text="", fill="#d9c07a", font=(SERIF, 12, "italic"))
            self.foot[key] = (dot, txt)
        self.cv.create_text(W - 20, y, anchor="e", text=f"v{__version__}", fill="#8a7347", font=(SERIF, 10))

    def _refresh_status(self):
        """Footer, device-page dots and battery bars follow the status variables."""
        def short(s):
            return s if len(s) <= 30 else s[:28] + "..."
        for key, name, sv, bv in (("w", "Wand", "w_state", "w_batt"), ("b", "Base", "b_state", "b_batt")):
            state = self.vars[sv].get()
            batt = self.vars[bv].get() if state == "connected" else ""
            dot, txt = self.foot[key]
            self.cv.itemconfig(dot, fill=state_color(state))
            self.cv.itemconfig(txt, text=f"{name}: {short(state)}" + (f"  {batt}" if batt else ""))
            d = self.dev_dots.get(key)
            if d is not None:
                try:
                    self.cv.itemconfig(d, fill=state_color(state))
                except tk.TclError:
                    pass
            bar = self.batt_bars.get(key)
            if bar is not None:
                pct = battery_percent(self.vars[bv].get()) if state == "connected" else None
                x, y, w, h, fill_id = bar
                try:
                    self.cv.coords(fill_id, x + 1, y + 1, x + 1 + max(0, (w - 2) * (pct or 0) / 100), y + h - 1)
                    self.cv.itemconfig(fill_id, fill=battery_color(pct), state="normal" if pct else "hidden")
                except tk.TclError:
                    pass
        if getattr(self, "tray", None):
            self.tray.set_title("Magic Caster Companion\n" + "\n".join(
                self.cv.itemcget(self.foot[k][1], "text") for k in ("w", "b")))

    def log(self, msg):
        self.log_lines.append(msg)
        self.log_lines = self.log_lines[-200:]
        if self.logbox is not None:
            try:
                self.logbox.configure(state="normal")
                self.logbox.insert("end", msg + "\n")
                self.logbox.see("end")
                self.logbox.configure(state="disabled")
            except tk.TclError:
                self.logbox = None

    def cue(self, name):
        if self.settings.get("sounds"):
            if name == "page":
                play_cue("page", style=self.settings.get("page_sound"), volume=self.settings.get("page_volume"))
            else:
                play_cue(name)

    def _preview_page_sound(self):
        """Play the page-turn sound with the current choice, even if sound effects are switched off."""
        play_cue("page", style=self.settings.get("page_sound"), volume=self.settings.get("page_volume"))

    # ---------- book chrome ----------
    def _draw_tabs(self):
        self.tab_ids, self.tab_imgs = {}, {}
        for i, (key, label, col) in enumerate(TABS):
            y = BY0 + 24 + i * 88
            for st in ("normal", "hover", "active"):
                self.tab_imgs[(key, st)] = ImageTk.PhotoImage(tab_pil(label, col, st, h=78))
            self.tab_ids[key] = self.cv.create_image(BX1 - 2, y, image=self.tab_imgs[(key, "normal")], anchor="nw",
                                                     tags=("tab", f"tab_{key}"))
            self.cv.tag_bind(f"tab_{key}", "<Button-1>", lambda _e, k=key: self.show(k))
            self.cv.tag_bind(f"tab_{key}", "<Enter>", lambda _e, k=key: self._tab_hover(k, True))
            self.cv.tag_bind(f"tab_{key}", "<Leave>", lambda _e, k=key: self._tab_hover(k, False))

    def _tab_hover(self, key, on):
        self.cv.config(cursor="hand2" if on else "")
        if key != self.page:
            self.cv.itemconfig(self.tab_ids[key], image=self.tab_imgs[(key, "hover" if on else "normal")])

    def _mark_tab(self, active):
        for key, item in self.tab_ids.items():
            self.cv.itemconfig(item, image=self.tab_imgs[(key, "active" if key == active else "normal")])

    def clear(self):
        for w in self.widgets:
            try:
                w.destroy()
            except tk.TclError:
                pass
        self.widgets = []
        self.cv.delete("page")
        self.meter = self.scope = None
        self.logbox = self.status_item = self.note_item = self.pip_item = self.empty_item = None
        self.dev_dots, self.batt_bars = {}, {}

    def show(self, page, animate=True):
        if self.busy or (page == self.page and animate):
            return
        self.page = page
        self._mark_tab(page)
        self.clear()
        if animate:
            self.busy = True
            self.cue("page")
            self._flip(0, page)
        else:
            self._build(page)

    def _flip(self, step, page):
        n = 7
        self.cv.delete("flip")
        if step < n:
            x = BX1 - (BX1 - SPINE) * (step + 1) / n
            self.cv.create_rectangle(x, BY0, BX1, BY1, fill="#d9c79c", outline="", tags=("flip", "page"))
            self.cv.create_line(x, BY0, x, BY1, fill="#8a6b3a", width=3, tags=("flip", "page"))
            self.after(22, lambda: self._flip(step + 1, page))
        else:
            self.busy = False
            self._build(page)

    def _build(self, page):
        self.cv.delete("flip")
        getattr(self, f"_page_{page}")()
        self.cv.tag_raise("tab")
        self._refresh_status()

    # ---------- widget helpers ----------
    def put(self, widget, x, y, anchor="nw", **kw):
        self.widgets.append(widget)
        self.last_win = self.cv.create_window(x, y, window=widget, anchor=anchor, tags="page", **kw)
        return widget

    def text(self, x, y, s, size=11, bold=False, italic=False, color=INK, width=PAGE_W, anchor="nw", **kw):
        style = " ".join(p for p in ("bold" if bold else "", "italic" if italic else "") if p) or "normal"
        tags = kw.pop("tags", "page")
        return self.cv.create_text(x, y, text=s, fill=color, anchor=anchor, width=width,
                                   font=(SERIF, size, style), tags=tags, **kw)

    def button(self, label, cmd, x, y, parent=None, tip=None, bg=PARCH):
        b = RoundButton(parent or self, label, cmd, tip=tip, bg=bg)
        return self.put(b, x, y) if parent is None else b

    def check(self, label, var, x, y, cmd=None, style="Book.TCheckbutton"):
        cb = ttk.Checkbutton(self, text=label, variable=var, command=cmd, style=style)
        return self.put(cb, x, y)

    def label(self, var, x, y, size=12, bold=False, width=None, bg=PARCH):
        lb = tk.Label(self, textvariable=var, bg=bg, fg=INK, font=(SERIF, size, "bold" if bold else "normal"),
                      anchor="w", justify="left", wraplength=width or 0)
        return self.put(lb, x, y)

    def slider(self, x, y, title, value, lo, hi, step, length, fmt, on_change=None, on_release=None):
        """Titled ttk slider with a live value readout. Returns the Scale."""
        self.text(x, y, title, 10, italic=True)
        readout = tk.Label(self, text=fmt(value), bg=PARCH, fg=INK, font=(SERIF, 11, "bold"), width=6, anchor="e")
        self.put(readout, x + length + 8, y + 18)

        def moved(v):
            val = round(float(v) / step) * step
            readout.configure(text=fmt(val))
            if on_change:
                on_change(val)
        sc = ttk.Scale(self, from_=lo, to=hi, orient="horizontal", length=length, style="Book.Horizontal.TScale",
                       command=moved)
        sc.set(value)
        if on_release:
            sc.bind("<ButtonRelease-1>", lambda _e: on_release())
        self.put(sc, x, y + 20)
        return sc

    def rule(self, x, y, w=PAGE_W):
        self.cv.create_line(x, y, x + w, y, fill="#8a6b3a", width=1, tags="page")

    def ornament(self, x, y, w=PAGE_W):
        mid = x + w // 2
        self.cv.create_line(x, y, mid - 18, y, fill="#9a7b45", width=1, tags="page")
        self.cv.create_line(mid + 18, y, x + w, y, fill="#9a7b45", width=1, tags="page")
        self.cv.create_text(mid, y, text="✦", fill="#9a7b45", font=(SERIF, 12), tags="page")

    def card(self, x0, y0, x1, y1, r=14, fill=CARD, outline=CARD_EDGE, tags="page"):
        pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1, x0, y1,
               x0, y1 - r, x0, y0 + r, x0, y0]
        return self.cv.create_polygon(pts, smooth=True, fill=fill, outline=outline, width=1.5, tags=tags)

    # ---------- page: devices ----------
    def _device_card(self, key, x, y, w, h, title, subtitle, rows, on_connect, on_disconnect):
        """rows: (label, var name, kind) with kind 'text', 'status' (dot) or 'battery' (bar)."""
        self.card(x - 14, y, x + w + 14, y + h)
        self.text(x + 4, y + 12, title, 18, bold=True, width=w)
        top = y + 48
        if subtitle:
            self.text(x + 4, y + 40, subtitle, 11, italic=True, width=w)
            top = y + 74
        for i, (name, var, kind) in enumerate(rows):
            ry = top + i * 34
            self.text(x + 4, ry + 2, name, 12, italic=True, width=110)
            if kind == "status":
                self.dev_dots[key] = self.cv.create_oval(x + 118, ry + 6, x + 130, ry + 18, fill="#8c7b62",
                                                         outline="#5a4a30", tags="page")
                self.label(self.vars[var], x + 138, ry, 12, bg=CARD, width=w - 140)
            elif kind == "battery":
                self.label(self.vars[var], x + 118, ry, 12, bg=CARD, width=50)
                bx, by, bw, bh = x + 176, ry + 6, 110, 12
                self.cv.create_rectangle(bx, by, bx + bw, by + bh, outline="#8a6b3a", fill=FIELD, tags="page")
                fid = self.cv.create_rectangle(bx + 1, by + 1, bx + 1, by + bh - 1, fill="#3aa655", outline="",
                                               tags="page", state="hidden")
                self.batt_bars[key] = (bx, by, bw, bh, fid)
            else:
                self.label(self.vars[var], x + 118, ry, 12, bg=CARD, width=w - 120)
        by = top + len(rows) * 34 + 10
        self.button("Connect", on_connect, x + 4, by, bg=CARD, tip="Find and connect to this device")
        self.button("Disconnect", on_disconnect, x + 112, by, bg=CARD,
                    tip="Disconnect and stop reconnecting until you press Connect again")

    def _page_devices(self):
        self.text(LX, BY0 + 14, "Magic Caster\nCompanion", 28, bold=True, italic=True, color=RED)
        self.ornament(LX, BY0 + 118)
        self._device_card("w", LX, BY0 + 138, PAGE_W - 20, 224, "The Wand", None,
                          [("Status", "w_state", "status"), ("Model", "w_info", "text"),
                           ("Battery", "w_batt", "battery")],
                          lambda: self.connect("wand"), lambda: self.disconnect("wand"))
        self.button("Connect wand & base", self.connect_all, LX, BY0 + 382,
                    tip="Scan, then connect both devices. They reconnect automatically if the link drops.")
        self.button("Scan only", self.do_scan, LX + 226, BY0 + 382, tip="List nearby devices in the Notes page")
        self.card(LX - 14, BY0 + 438, LX + PAGE_W - 6, BY0 + 628)
        self.text(LX + 4, BY0 + 450, "Getting started", 14, bold=True, color=RED)
        steps = ("1   Wave the wand to wake it.\n2   Press Connect wand & base.\n"
                 "3   Open Spells to see how each spell is cast.\n"
                 "4   Open Teach to unlock spells, then Cast to use them.")
        self.text(LX + 4, BY0 + 480, steps, 11, width=PAGE_W - 20)

        self._device_card("b", RX, BY0 + 20, PAGE_W - 20, 372, "The Base", "Magic Caster Box",
                          [("Status", "b_state", "status"), ("Firmware", "b_info", "text"),
                           ("Battery", "b_batt", "battery"), ("Lid", "b_lid", "text"),
                           ("Wand in base", "b_wand", "text"), ("USB power", "b_usb", "text")],
                          lambda: self.connect("box"), lambda: self.disconnect("box"))
        try:
            crest = Image.open(resource_path(os.path.join("assets", "icon.ico"))).convert("RGBA").resize(
                (120, 120), Image.LANCZOS)
            self._crest = ImageTk.PhotoImage(crest)
            self.cv.create_image(RX + (PAGE_W - 20) // 2, BY0 + 412, image=self._crest, anchor="n", tags="page")
        except (OSError, ValueError):
            pass
        self.text(RX + (PAGE_W - 20) // 2, BY0 + 548, "An unofficial, community-made companion", 10, italic=True,
                  anchor="n", width=300)
        self.text(RX + (PAGE_W - 20) // 2, BY0 + 568, f"Version {__version__}", 10, italic=True, anchor="n",
                  color=MUTED)

    # ---------- page: spells ----------
    def _page_spells(self):
        self.text(LX, BY0 + 20, "Index of Spells", 24, bold=True, italic=True, color=RED)
        n_un = len(set(self.store.unlocked()) | set(self.settings.get("wand_known")))
        self.text(LX, BY0 + 60, f"✦ unlocked   ★ the wand knows it   ◇ learning      "
                  f"{n_un} of {len(SPELLS)}", 10, italic=True)
        self.spell_filter = tk.StringVar()
        ent = tk.Entry(self, textvariable=self.spell_filter, bg=FIELD, fg=INK, relief="flat",
                       font=(SERIF, 12), highlightthickness=1, highlightbackground=PARCH_DARK,
                       highlightcolor=GOLD, insertbackground=INK, width=34)
        self.put(ent, LX, BY0 + 90)
        Tip(ent, "Type to filter the list")
        self.spell_filter.trace_add("write", lambda *_: self._fill_spells())
        frame = tk.Frame(self, bg=PARCH)
        sb = ttk.Scrollbar(frame, orient="vertical", style="Book.Vertical.TScrollbar")
        self.spell_list = tk.Listbox(frame, bg=PARCH, fg=INK, font=(SERIF, 12), bd=0, highlightthickness=0,
                                     selectbackground="#c9a96a", selectforeground=INK, activestyle="none",
                                     height=21, width=33, yscrollcommand=sb.set, exportselection=False)
        sb.configure(command=self.spell_list.yview)
        self.spell_list.pack(side="left")
        sb.pack(side="right", fill="y")
        self.put(frame, LX, BY0 + 128)
        self.spell_list.bind("<<ListboxSelect>>", self._spell_selected)
        self._fill_spells()
        self.button("Play effect", self.play_selected, RX, BY0 + 530, tip="Show this spell's light and buzz on the wand")
        self.button("Teach this spell", lambda: self.show("teach"), RX + 124, BY0 + 530,
                    tip="Go to the Teach page to unlock this spell")
        self.button("Actions & colour...", self._action_dialog, RX, BY0 + 578,
                    tip="Choose this spell's light colour and what it does on your PC")
        self._draw_spell_detail()

    def _fill_spells(self):
        q = self.spell_filter.get().lower().replace(" ", "_")
        self.spell_view = [s for s in SPELLS if q in s]
        self.spell_list.delete(0, "end")
        for s in self.spell_view:
            self.spell_list.insert("end", self._mark(s) + pretty(s))
            if s == self.sel_spell:
                self.spell_list.selection_set("end")
                self.spell_list.see("end")

    def _spell_selected(self, _e):
        sel = self.spell_list.curselection()
        if sel:
            self.sel_spell = self.spell_view[sel[0]]
            self._draw_spell_detail()

    def _draw_spell_detail(self):
        self.cv.delete("detail")
        s = self.sel_spell
        x = RX
        tg = ("page", "detail")
        self.text(x, BY0 + 24, pretty(s), 22, bold=True, italic=True, color=RED, tags=tg)
        self.cv.create_line(x, BY0 + 88, x + PAGE_W, BY0 + 88, fill="#9a7b45", tags=tg)
        desc = DESCRIPTIONS.get(s, "A spell from the Magic Caster Wand's repertoire.")
        self.text(x, BY0 + 100, desc, 11, italic=True, tags=tg)
        paths = diagram_paths(s)
        if paths:
            iw = 190 if len(paths) == 1 else 120
            self._detail_imgs = [ink_image(p, iw) for p in paths]
            for i, im in enumerate(self._detail_imgs):
                self.cv.create_image(x + i * (iw + 10), BY0 + 150, image=im, anchor="nw", tags=tg)
            if len(paths) > 1:
                self.text(x, BY0 + 150 + self._detail_imgs[0].height() + 4, "Two ways to cast it", 9,
                          italic=True, tags=tg)
        else:
            self.text(x, BY0 + 160, "No diagram is available for this spell yet.\nInvent your own motion on the "
                      "Teach page.", 10, italic=True, tags=tg)
        one = bool(paths) and len(paths) == 1
        tx, ty, tw = (x + 210, BY0 + 150, PAGE_W - 210) if one else (x, BY0 + 340, PAGE_W)
        self.text(tx, ty, "How to cast", 13, bold=True, tags=tg, width=tw)
        self.text(tx, ty + 26, CAST_STEPS, 10, tags=tg, width=tw)
        st, n = self.store.state(s), self.store.casts(s)
        meaning = {"unlocked": "The book will recognise this spell when you cast it.",
                   "learning": f"Recognised, but needs {UNLOCK_AT - n} more cast(s) to unlock fully.",
                   "locked": "The book can't recognise it yet. Teach it on the Teach page."}[st]
        info = f"{STATE_TEXT[st]}  ({n} recorded casts)\n{meaning}"
        if s in self.settings.get("wand_known"):
            info += "\n★ The wand recognises this spell by itself."
        act = self.settings.action(s)
        if act:
            info += f"\nOn cast: {act['type']} {act['value']}"
        self.text(x, BY0 + 462, info, 10, italic=True, tags=tg)

    # ---------- page: teach ----------
    def _page_teach(self):
        self.text(LX, BY0 + 20, "Teach a Spell", 24, bold=True, italic=True, color=RED)
        self.card(LX - 14, BY0 + 62, LX + PAGE_W - 6, BY0 + 160)
        self.text(LX + 4, BY0 + 70, "The wand only reports its motion, so the book learns how you cast each "
                  "spell. Spells start locked. Cast one three times and it unlocks: from then on the book "
                  "recognises it.", 10, italic=True, width=PAGE_W - 24)
        self.text(LX, BY0 + 176, "1  Choose a spell", 12, bold=True)
        self.cast_combo = ttk.Combobox(self, style="Book.TCombobox", values=[pretty(s) for s in SPELLS],
                                       state="readonly", width=30, font=(SERIF, 11))
        self.cast_combo.set(pretty(self.sel_spell))
        self.cast_combo.bind("<<ComboboxSelected>>", self._teach_pick)
        self.put(self.cast_combo, LX, BY0 + 202)
        self.text(LX, BY0 + 244, "2  Cast it three times", 12, bold=True)
        self.button("Record 3 casts", lambda: self.arm_record(3), LX, BY0 + 270,
                    tip="Cast the spell three times. The book learns your motion and rejects stray ones.")
        self.button("Record 1 cast", lambda: self.arm_record(1), LX + 148, BY0 + 270,
                    tip="Add a single cast to this spell")
        self.pip_item = self.text(LX, BY0 + 316, "", 14, bold=True, color=RED)
        self.status_item = self.text(LX, BY0 + 342, self.t_status.get(), 11, italic=True, width=PAGE_W)
        self.ornament(LX, BY0 + 410)
        self.text(LX, BY0 + 420, "Spells you are teaching", 13, bold=True)
        self.g_list = tk.Listbox(self, bg=PARCH, fg=INK, font=(SERIF, 12), bd=0, highlightthickness=0,
                                 selectbackground="#c9a96a", selectforeground=INK, activestyle="none",
                                 height=5, width=33, exportselection=False)
        self.put(self.g_list, LX, BY0 + 450)
        self.g_win = self.last_win
        self.empty_item = self.text(LX + 4, BY0 + 456, "Nothing yet. Choose a spell above and\npress Record 3 casts.",
                                    11, italic=True, color=MUTED, width=PAGE_W - 10)
        self._fill_gestures()
        self.button("Forget", self.delete_gesture, LX, BY0 + 572, tip="Forget the selected spell's casts")
        self.button("Export", self.export_gestures, LX + 92, BY0 + 572, tip="Save your casts to a file to share")
        self.button("Import", self.import_gestures, LX + 184, BY0 + 572, tip="Add casts from a shared file")
        self.button("Check", self.check_casts, LX + 276, BY0 + 572,
                    tip="Self-test: how reliably are your recorded casts told apart?")

        self.text(RX, BY0 + 24, "Trace this", 20, bold=True)
        self.text(RX, BY0 + 58, "Start at the dot and follow the arrows.", 10, italic=True)
        self.text(RX, BY0 + 88, "Motion", 10, italic=True)
        self.meter = tk.Canvas(self, width=PAGE_W - 60, height=14, bg=FIELD, highlightthickness=1,
                               highlightbackground=PARCH_DARK)
        self.put(self.meter, RX + 60, BY0 + 88)
        self._teach_diagram()
        self.card(RX - 14, BY0 + 520, RX + PAGE_W + 6, BY0 + 640)
        self.text(RX + 4, BY0 + 528, "What the marks mean", 12, bold=True, color=RED)
        self.text(RX + 4, BY0 + 552, f"Locked: not taught yet, so the book can't tell when you cast it.\n"
                  f"◇ Learning: 1 or 2 casts recorded. It is recognised, but not reliably.\n"
                  f"✦ Unlocked: {UNLOCK_AT} or more casts. More casts make it more reliable.", 10,
                  width=PAGE_W - 20)
        self._update_pips()

    def _teach_pick(self, _e):
        name = self.cast_combo.get().lower().replace(" ", "_")
        if name in SPELLS:
            self.sel_spell = name
            self.cv.delete("cdiag")
            self._teach_diagram()
            self._update_pips()

    def _teach_diagram(self):
        paths = diagram_paths(self.sel_spell)
        self.text(RX, BY0 + 122, pretty(self.sel_spell), 15, bold=True, italic=True, color=RED,
                  tags=("page", "cdiag"))
        if paths:
            iw = 200 if len(paths) == 1 else 130
            self.cast_imgs = [ink_image(p, iw) for p in paths]
            for i, im in enumerate(self.cast_imgs):
                self.cv.create_image(RX + i * (iw + 10), BY0 + 150, image=im, anchor="nw", tags=("page", "cdiag"))
        else:
            self.text(RX, BY0 + 160, "No diagram for this spell; invent your own motion.", 10, italic=True,
                      tags=("page", "cdiag"))

    def _update_pips(self):
        if self.pip_item is None:
            return
        n = self.store.casts(self.sel_spell)
        filled = min(UNLOCK_AT, n)
        pips = "●" * filled + "○" * (UNLOCK_AT - filled)
        try:
            self.cv.itemconfig(self.pip_item, text=f"{pips}   {STATE_TEXT[self.store.state(self.sel_spell)]}"
                                                    f"  ({n} casts)")
        except tk.TclError:
            self.pip_item = None

    def _fill_gestures(self):
        self.g_list.delete(0, "end")
        for n, s in sorted(self.store.data.items()):
            self.g_list.insert("end", f"{MARK[self.store.state(n)]}{pretty(n)}  ({len(s)} casts)")
        try:  # the list is hidden while empty so the hint text underneath shows
            self.cv.itemconfig(self.g_win, state="normal" if self.store.data else "hidden")
            if self.empty_item is not None:
                self.cv.itemconfig(self.empty_item, state="hidden" if self.store.data else "normal")
        except (tk.TclError, AttributeError):
            pass
        self._update_pips()

    # ---------- page: practice ----------
    def _pbtn(self, label, cmd, x, y, tip=None):
        self.button(label, cmd, x, y, tip=tip)
        return self.last_win

    def _page_practice(self):
        self.text(LX, BY0 + 20, "Practice", 24, bold=True, italic=True, color=RED)
        self.card(LX - 14, BY0 + 62, LX + PAGE_W - 6, BY0 + 132)
        self.text(LX + 4, BY0 + 70, "Cast the spell shown. The book tells you how it went, and if it gets one wrong "
                  "you can teach it from the mistake.", 10, italic=True, width=PAGE_W - 24)
        self.p_wins = {
            "start": self._pbtn("Start practice", self._practice_start, LX, BY0 + 150,
                                "Practise the spells you have taught, one after another"),
            "stop": self._pbtn("Stop", self._practice_stop, LX, BY0 + 150),
            "skip": self._pbtn("Skip spell", self._practice_next, LX + 96, BY0 + 150, "Try a different spell"),
        }
        self.text(RX, BY0 + 24, "Cast this spell", 20, bold=True)
        self.p_wins["add"] = self._pbtn("Teach it this cast", self._practice_add, RX + 216, BY0 + 338,
                                        "Add that cast to the book as an example of this spell")
        self.p_wins["next"] = self._pbtn("Next spell", self._practice_next, RX + 216, BY0 + 386)
        self._draw_practice()

    def _practice_buttons(self):
        p = self.practice
        active, st, res = p["active"], p["state"], p["result"]
        ok = bool(res and res["ok"])
        want = {"start": not active, "stop": active, "skip": active and st == "waiting",
                "add": bool(active and st == "result" and not ok and p["gesture"] is not None
                            and not (res or {}).get("added")),
                "next": bool(active and st == "result" and not ok)}
        for k, wid in self.p_wins.items():
            try:
                self.cv.itemconfig(wid, state="normal" if want.get(k) else "hidden")
            except tk.TclError:
                pass

    def _draw_practice(self):
        self.cv.delete("plive")
        tg = ("page", "plive")
        p = self.practice
        sess = p["session"]
        hits = sum(1 for s in sess if s[1])
        th, tt = self.pstats.totals()
        self.card(LX - 14, BY0 + 206, LX + PAGE_W - 6, BY0 + 300, tags=tg)
        self.text(LX + 4, BY0 + 214, f"This session: {hits} of {len(sess)}"
                  + (f"  ({100 * hits // len(sess)}%)" if sess else ""), 13, bold=True, tags=tg, width=PAGE_W - 24)
        self.text(LX + 4, BY0 + 242, f"Streak {p['streak']}   ·   Best streak {self.pstats.best_streak}", 11,
                  tags=tg, width=PAGE_W - 24)
        self.text(LX + 4, BY0 + 266, f"All time: {th} of {tt}" + (f"  ({100 * th // tt}%)" if tt else ""), 11,
                  color=MUTED, tags=tg, width=PAGE_W - 24)
        self.text(LX, BY0 + 318, "Recent attempts", 13, bold=True, tags=tg)
        if not sess:
            self.text(LX, BY0 + 346, "Nothing yet.", 11, italic=True, color=MUTED, tags=tg)
        for i, (target, ok, got) in enumerate(reversed(sess[-9:])):
            line = f"{'✓' if ok else '✗'}  {pretty(target)}"
            if not ok:
                line += f"   → {pretty(got) if got else 'not recognised'}"
            self.text(LX, BY0 + 346 + i * 24, line, 12, bold=(i == 0), color=("#2f6b3a" if ok else "#7a4a2a"),
                      tags=tg, width=PAGE_W)
        self._practice_buttons()

        target = p["target"]
        if not p["active"] or not target:
            self.text(RX, BY0 + 70, p["msg"] or "Press Start practice. You will be asked to cast spells you have "
                      "taught, one after another, and the ones you find hard come up more often.", 12, italic=True,
                      color=MUTED, tags=tg)
        else:
            self.text(RX, BY0 + 58, pretty(target), 24, bold=True, italic=True, color=RED, tags=tg)
            self.text(RX, BY0 + 100, DESCRIPTIONS.get(target, ""), 11, italic=True, tags=tg)
            paths = diagram_paths(target)
            if paths:
                iw = 190 if len(paths) == 1 else 100
                self._practice_imgs = [ink_image(pa, iw) for pa in paths]
                for i, im in enumerate(self._practice_imgs):
                    self.cv.create_image(RX + i * (iw + 8), BY0 + 150, image=im, anchor="nw", tags=tg)
            col_x, w = RX + 216 if len(paths) <= 1 else RX, 178
            col_y = BY0 + 150 if len(paths) <= 1 else BY0 + 410
            res = p["result"]
            if p["state"] == "waiting":
                self.text(col_x, col_y, "Cast it now...", 18, italic=True, color=MUTED, tags=tg, width=w)
                self.text(col_x, col_y + 40, "Hold the wand in your normal grip, trace the shape, then hold still.",
                          10, italic=True, color=MUTED, tags=tg, width=w)
            elif res["ok"]:
                self.text(col_x, col_y, "✓ Yes!", 28, bold=True, color="#2f6b3a", tags=tg, width=w)
                detail = "The wand recognised it itself." if res["source"] == "wand" else \
                    f"Distance {res['dist']:.2f}"
                self.text(col_x, col_y + 50, detail + "\nNext spell in a moment...", 10, color=MUTED, tags=tg, width=w)
            else:
                self.text(col_x, col_y, "✗ Not quite", 22, bold=True, color="#7a4a2a", tags=tg, width=w)
                said = (f"The book thought that was {pretty(res['got'])}." if res["got"] else
                        "The book did not recognise that as any spell you have taught.")
                if res["tdist"] is not None:
                    said += f"\nDistance to {pretty(target)}: {res['tdist']:.2f}."
                if res.get("added"):
                    said += "\nAdded to the book. Try again!"
                self.text(col_x, col_y + 40, said, 10, tags=tg, width=w)
        weakest = self.pstats.weakest(3)
        self.card(RX - 14, BY0 + 520, RX + PAGE_W + 6, BY0 + 640, tags=tg)
        self.text(RX + 4, BY0 + 530, "Needs the most practice", 13, bold=True, color=RED, tags=tg)
        if not weakest:
            self.text(RX + 4, BY0 + 560, "Your weak spots will show up here as you practise.", 11, italic=True,
                      color=MUTED, tags=tg, width=PAGE_W - 24)
        for i, (name, rate, tries) in enumerate(weakest):
            h, t = self.pstats.accuracy(name)
            self.text(RX + 4, BY0 + 558 + i * 24, f"{pretty(name)}   {h} of {t}  ({int(rate * 100)}%)", 12, tags=tg,
                      width=PAGE_W - 24)

    def _practice_start(self):
        p = self.practice
        if not self.store.data:
            p["msg"] = "You have not taught any spells yet. Open Teach and cast a spell three times first."
        elif not (self.wand and self.wand.connected):
            p["msg"] = "Connect your wand first, on the Devices page."
        else:
            p.update(active=True, streak=0, session=[], msg="", last=None)
            self._practice_next()
            return
        self._draw_practice()

    def _practice_next(self):
        p = self.practice
        if not p["active"]:
            return
        p["token"] += 1
        p["target"] = pick_target(sorted(self.store.data), p["last"], self.pstats)
        p["last"] = p["target"]
        p.update(state="waiting", result=None, gesture=None)
        if self.page == "practice":
            self._draw_practice()

    def _practice_stop(self):
        p = self.practice
        p.update(active=False, state="idle", result=None, gesture=None, target=None)
        p["token"] += 1
        if self.page == "practice":
            self._draw_practice()

    def _practice_listening(self):
        p = self.practice
        return bool(p["active"] and self.page == "practice" and p["target"] and
                    (p["state"] == "waiting" or (p["state"] == "result" and not p["result"]["ok"])))

    def _practice_cast(self, g):
        p = self.practice
        r = evaluate(self.store, g, p["target"], float(self.settings.get("accept")))
        p["gesture"] = g
        self._practice_result(r["ok"], r["got"], r["dist"], r["target_dist"], "book")

    def _practice_native(self, key):
        self._practice_result(key == self.practice["target"], key, None, None, "wand")

    def _practice_result(self, ok, got, dist, tdist, source):
        p = self.practice
        target = p["target"]
        p["streak"] = p["streak"] + 1 if ok else 0
        self.pstats.record(target, ok, p["streak"])
        p["session"].append((target, ok, got))
        p["result"] = {"ok": ok, "got": got, "dist": dist, "tdist": tdist, "source": source, "added": False}
        p["state"] = "result"
        self.cue("success" if ok else "fail")
        if ok:
            self.wand_call("play", spell_effect(target, self.settings.color(target)))
            tok = p["token"]
            self.after(2200, lambda: self._practice_next() if (p["token"] == tok and p["active"]) else None)
        self._draw_practice()

    def _practice_add(self):
        p = self.practice
        if p["gesture"] is None or not p["target"] or not p["result"]:
            return
        self.store.add(p["target"], p["gesture"])
        p["result"]["added"] = True
        self.log(f"Added a cast to {pretty(p['target'])} from practice ({self.store.casts(p['target'])} casts)")
        self._draw_practice()

    # ---------- page: cast (free casting, a full two-page spread) ----------
    def _page_cast(self):
        self.cv.create_image(BX0, BY0, image=self.spread_img, anchor="nw", tags="page")
        self.text(SX0, BY0 + 14, "Free Casting", 26, bold=True, italic=True, color=RED)
        self.text(SX0, BY0 + 60, "Cast any spell you like. The book recognises the ones you have unlocked.", 11,
                  italic=True, width=560)
        usable = set(self.store.unlocked()) | set(self.settings.get("wand_known"))
        self.text(SX1, BY0 + 24, f"✦ {len(usable)} of {len(SPELLS)} spells unlocked", 14, bold=True,
                  anchor="ne", width=320)

        self.text(SX0, BY0 + 96, "Motion", 12, bold=True)
        self.scope = tk.Canvas(self, width=250, height=120, bg=FIELD, highlightthickness=1,
                               highlightbackground=PARCH_DARK)
        self.put(self.scope, SX0, BY0 + 122)
        self.text(SX0, BY0 + 252, "How fast the wand is turning, over the last few seconds. A cast starts when "
                  "the line rises above the gold mark.", 10, italic=True, width=250)
        stream = self.check("Stream motion (for my own spells)", self.stream_var, SX0, BY0 + 316,
                            self._streaming_changed)
        Tip(stream, "On: the book learns and recognises spells you teach it. Off: only the spells the wand "
                    "recognises by itself are reported.")
        ns = self.settings.get("native_stats")
        heard = int(ns.get("streaming_on", 0)) + int(ns.get("streaming_off", 0))
        self.text(SX0, BY0 + 338, (f"The wand has named {heard} spell(s) by itself (streaming on: "
                                   f"{int(ns.get('streaming_on', 0))}, off: {int(ns.get('streaming_off', 0))})."
                                   if heard else "The wand has not named a spell by itself yet."),
                  9, italic=True, color=MUTED, width=270)
        self.card(SX0 + 280, BY0 + 90, SX1, BY0 + 330)
        self._draw_cast_live()
        self.ornament(SX0, BY0 + 352, SX1 - SX0)

        self.text(SX0, BY0 + 368, "Recent casts", 14, bold=True)
        self._draw_history()
        x2 = SX0 + 440
        self.text(x2, BY0 + 368, "Your unlocked spells", 14, bold=True)
        self._draw_chips(x2, BY0 + 398, SX1 - x2)
        self.check("Recognise casts (works on every page)", self.cast_mode, x2, BY0 + 512)
        self.check("Test mode: recognise only, run no actions", self.test_mode, x2, BY0 + 538,
                   lambda: self.settings.set("test_mode", bool(self.test_mode.get())))
        self.slider(x2, BY0 + 568, "Sensitivity limit (lower is stricter)", float(self.accept_var.get()), 0.3, 2.0,
                    0.05, 170, lambda v: f"{v:.2f}", on_change=lambda v: self.accept_var.set(round(v, 2)),
                    on_release=lambda: self.settings.set("accept", round(float(self.accept_var.get()), 2)))
        self.button("Auto-tune", self.autotune, x2 + 262, BY0 + 576,
                    tip="Set the limit from a self-test of your own recorded casts")
        self.note_item = self.text(x2, BY0 + 622, self.c_note.get(), 10, italic=True, color=MUTED, width=SX1 - x2)

    def _draw_cast_live(self):
        """The big result card: the latest recognised (or missed) cast."""
        self.cv.delete("live")
        x0, y0, x1, y1 = SX0 + 280, BY0 + 90, SX1, BY0 + 330
        tg = ("page", "live")
        lc = self.last_cast
        mid = (x0 + x1) // 2
        if lc is None:
            self.text(mid, y0 + 78, "Cast a spell", 30, italic=True, color=MUTED, anchor="n", tags=tg)
            msg = ("Wave the wand to cast. Any spell you have unlocked is recognised here, and you can cast "
                   "with this page closed too." if (self.store.unlocked() or self.settings.get("wand_known")) else
                   "You have not unlocked any spells yet. Open Teach to unlock your first.")
            self.text(mid, y0 + 130, msg, 11, italic=True, color=MUTED, anchor="n", width=440, tags=tg)
            return
        near = ", ".join(f"{pretty(n)} {d:.2f}" for n, d in lc["near"][:3])
        native = bool(lc.get("native"))
        if native and not lc["name"]:
            self.text(mid, y0 + 50, str(lc["raw"]), 30, bold=True, italic=True, color=RED, anchor="n", width=480,
                      tags=tg)
            self.text(mid, y0 + 130, "Recognised by the wand itself. This book has no diagram for that spell.",
                      11, italic=True, color=MUTED, anchor="n", width=440, tags=tg)
            return
        if lc["name"]:
            n = lc["name"]
            self.text(x0 + 24, y0 + 22, pretty(n), 32, bold=True, italic=True, color=RED, width=330, tags=tg)
            self.text(x0 + 24, y0 + 108, DESCRIPTIONS.get(n, ""), 12, italic=True, width=330, tags=tg)
            if native:
                self.text(x0 + 24, y0 + 168, "✦ Recognised by the wand itself", 11, bold=True, color="#2f6b3a",
                          width=330, tags=tg)
            else:
                self.text(x0 + 24, y0 + 168, f"distance {lc['dist']:.2f}   ·   limit {lc['limit']:.2f}", 10,
                          color=MUTED, width=330, tags=tg)
                self.text(x0 + 24, y0 + 190, f"Closest: {near}", 10, color=MUTED, width=330, tags=tg)
            paths = diagram_paths(n)
            if paths:
                self._live_img = ink_image(paths[0], 118)
                self.cv.create_image(x1 - 24, y0 + 18, image=self._live_img, anchor="ne", tags=tg)
        else:
            self.text(mid, y0 + 40, "Nothing recognised", 26, italic=True, color="#7a4a2a", anchor="n", tags=tg)
            self.text(mid, y0 + 100, f"Closest: {near}\nLimit {lc['limit']:.2f}. Try again, teach more casts, or "
                      "raise the limit below.", 11, italic=True, color=MUTED, anchor="n", width=440, tags=tg)

    def _draw_history(self):
        self.cv.delete("hist")
        tg = ("page", "hist")
        if not self.cast_log:
            self.text(SX0, BY0 + 400, "Your casts will be listed here.", 11, italic=True, color=MUTED, tags=tg,
                      width=380)
            return
        for i, (clock, name, dist, src) in enumerate(reversed(self.cast_log[-8:])):
            y = BY0 + 400 + i * 24
            if name:
                self.text(SX0, y, f"{clock}   ✦ {pretty(name)}", 12, bold=(i == 0), tags=tg, width=300)
            else:
                self.text(SX0, y, f"{clock}   not recognised", 12, italic=True, color=MUTED, tags=tg, width=300)
            self.text(SX0 + 380, y + 2, src if src in ("wand", "both") else f"{dist:.2f}", 10, color=MUTED,
                      anchor="ne", tags=tg, width=60)

    def _draw_chips(self, x, y, w):
        taught = self.store.unlocked()
        names = [(n, "✦ ") for n in taught] + [(n, "★ ") for n in sorted(self.settings.get("wand_known"))
                                                   if n not in taught]
        if not names:
            self.text(x, y, "None yet. Open the Teach page and cast a spell three times to unlock it.", 11,
                      italic=True, color=MUTED, width=w)
            self.button("Go to Teach", lambda: self.show("teach"), x, y + 56)
            return
        h, gap, cx, cy, shown = 26, 8, x, y, 0
        for n, mark in names:
            label = mark + pretty(n)
            tw = self.chip_font.measure(label) + 22
            if cx + tw > x + w:
                cx, cy = x, cy + h + gap
            if cy > y + 2 * (h + gap):
                break
            self.card(cx, cy, cx + tw, cy + h, r=13)
            self.text(cx + tw // 2, cy + h // 2, label, 10, anchor="center", width=tw)
            cx += tw + gap
            shown += 1
        if shown < len(names):
            self.text(x + w, y + 3 * (h + gap) - 4, f"+{len(names) - shown} more", 10, italic=True, color=MUTED,
                      anchor="ne", width=120)

    # ---------- page: lights ----------
    def _page_lights(self):
        self.text(LX, BY0 + 20, "Light & Sound", 24, bold=True, italic=True, color=RED)
        self.text(LX, BY0 + 62, "Colour the lights along the wand and the base.", 10, italic=True)
        self.swatch = tk.Label(self, width=14, height=3, bg=hexcolor(self.color), relief="solid", bd=1)
        self.put(self.swatch, LX, BY0 + 110)
        self.button("Pick colour", self.pick_color, LX + 170, BY0 + 124)
        self.text(LX, BY0 + 200, "Wand light", 12, bold=True)
        self.group = ttk.Combobox(self, style="Book.TCombobox", values=list(LED_GROUPS) + ["All"],
                                  state="readonly", width=16, font=(SERIF, 11))
        self.group.set("Tip")
        self.put(self.group, LX, BY0 + 228)
        self.button("Set wand light", self.set_led, LX, BY0 + 270)
        self.text(LX, BY0 + 340, "Base light", 12, bold=True)
        self.button("Set base light", self.set_box_led, LX, BY0 + 368)
        self.button("All lights off", self.leds_off, LX, BY0 + 430)
        self.card(LX - 14, BY0 + 492, LX + PAGE_W - 6, BY0 + 642)
        self.text(LX + 4, BY0 + 502, "Background", 14, bold=True, color=RED)
        for i, (key, label) in enumerate([("tray", "Keep running in the tray when I close the window"),
                                          ("notify", "Notify me when a spell is recognised in the tray"),
                                          ("autostart", "Start with Windows, minimised to the tray")]):
            self.check(label, self.bg_vars[key], LX + 4, BY0 + 534 + i * 32, lambda k=key: self._bg_changed(k),
                       style="Card.TCheckbutton")

        self.text(RX, BY0 + 24, "Buzz", 20, bold=True)
        self.text(RX, BY0 + 62, "Make the wand vibrate for a moment.", 10, italic=True)
        self.buzz_ms = tk.IntVar(value=300)
        self.slider(RX, BY0 + 100, "Length", 300, 50, 2000, 50, 280, lambda v: f"{int(v)} ms",
                    on_change=lambda v: self.buzz_ms.set(int(v)))
        self.button("Buzz", lambda: self.wand_call("buzz", int(self.buzz_ms.get())), RX, BY0 + 170)
        self.ornament(RX, BY0 + 252)
        self.text(RX, BY0 + 268, "Preferences", 18, bold=True)
        for i, (key, label) in enumerate([("sounds", "Sound effects on this PC"),
                                          ("auto_reconnect", "Connect and reconnect automatically"),
                                          ("base_status_light", "Show wand status on the base's light")]):
            self.check(label, self.pref_vars[key], RX, BY0 + 312 + i * 32, lambda k=key: self._pref_changed(k))
        self.ornament(RX, BY0 + 424)
        self.text(RX, BY0 + 438, "Page-turn sound", 18, bold=True)
        labels = [STYLE_LABELS[s] for s in STYLES]
        combo = ttk.Combobox(self, style="Book.TCombobox", values=labels, state="readonly", width=16,
                             font=(SERIF, 11))
        combo.set(STYLE_LABELS.get(self.settings.get("page_sound"), labels[0]))

        def style_picked(_e):
            self.settings.set("page_sound", STYLES[labels.index(combo.get())])
            self._preview_page_sound()
        combo.bind("<<ComboboxSelected>>", style_picked)
        self.put(combo, RX, BY0 + 474)
        self.button("Play", self._preview_page_sound, RX + 190, BY0 + 468, tip="Hear the page-turn sound")
        self.slider(RX, BY0 + 516, "Volume", float(self.settings.get("page_volume")), 0.0, 1.0, 0.05, 240,
                    lambda v: f"{int(round(v * 100))}%",
                    on_change=lambda v: self.settings.data.__setitem__("page_volume", round(v, 2)),
                    on_release=lambda: (self.settings.save(), self._preview_page_sound()))

    def _pref_changed(self, key):
        self.settings.set(key, bool(self.pref_vars[key].get()))
        if key == "base_status_light":
            self._base_light()
        elif key == "auto_reconnect" and self.pref_vars[key].get():
            self.connect_all(quiet=True)

    # ---------- page: notes ----------
    def _page_notes(self):
        self.text(LX, BY0 + 20, "Notes", 24, bold=True, italic=True, color=RED)
        self.text(LX, BY0 + 62, "What the book has been up to.", 10, italic=True)
        self.logbox = tk.Text(self, width=40, height=26, bg=FIELD, fg=INK, font=(SERIF, 10), relief="flat",
                              wrap="word", state="disabled", padx=8, pady=6, highlightthickness=1,
                              highlightbackground=PARCH_DARK)
        self.put(self.logbox, LX, BY0 + 92)
        self.logbox.configure(state="normal")
        self.logbox.insert("end", "\n".join(self.log_lines) + ("\n" if self.log_lines else ""))
        self.logbox.configure(state="disabled")
        self.logbox.see("end")

        self.text(RX, BY0 + 24, "About", 20, bold=True)
        self.text(RX, BY0 + 56, f"Version {__version__}", 10, italic=True)
        self.ornament(RX, BY0 + 84)
        self.text(RX, BY0 + 100,
                  "Magic Caster Companion is an unofficial, community-made replacement for the discontinued "
                  "app. It is not affiliated with or endorsed by the makers of the Magic Caster Wand.\n\n"
                  "The protocol was learned by probing real devices and from the MIT-licensed "
                  "hass-magic-caster-wand project by eigger, whose spell diagrams are also used here.\n\n"
                  "Your recorded casts, colours and actions are kept in your user profile.\n\n"
                  "Shortcuts: Ctrl+1 to Ctrl+6 turn to each page.", 11)
        self.button("Open data folder", lambda: os.startfile(DATA_DIR) if os.path.isdir(DATA_DIR) else None,
                    RX, BY0 + 500, tip="Where your casts, colours and settings are stored")

    # ---------- connecting ----------
    def _fresh(self, kind):
        """Coroutine: scan result for kind, rescanning first if it is missing or older than 30 s."""
        async def go():
            if self.scan_lock is None:
                self.scan_lock = asyncio.Lock()
            async with self.scan_lock:
                info = self.found.get(kind)
                if not info or time.monotonic() - self.found_at > 30:
                    found = await scan(6)
                    self.found, self.found_at = found, time.monotonic()
                    self.ui(lambda: self.log("Found: " + (", ".join(
                        f"{v['name']} ({v['rssi']} dBm)" for v in found.values()) or "nothing")))
                    info = found.get(kind)
            if not info:
                raise RuntimeError(f"{'wand' if kind == 'wand' else 'base'} not found - wake it (wave it), and "
                                   "close any other window already connected to it")
            return info
        return go()

    def do_scan(self):
        self.log("Scanning (8s)...")

        async def go():
            found = await scan(8)
            self.found, self.found_at = found, time.monotonic()
            return found
        self.run(go(), lambda f: self.log("Found: " + (", ".join(
            f"{v['name']} ({v['rssi']} dBm)" for v in f.values()) or "nothing - wave the wand and scan again")))

    def connect_all(self, quiet=False):
        self.connect("wand", quiet)
        self.connect("box", quiet)

    def connect(self, kind, quiet=False):
        cur = self.wand if kind == "wand" else self.box
        if (cur is not None and cur.connected) or self.connecting[kind]:
            return
        self.connecting[kind] = True
        self.user_off[kind] = False
        st = self.vars["w_state" if kind == "wand" else "b_state"]
        name = "wand" if kind == "wand" else "base"
        st.set(f"looking for the {name}...")

        async def go():
            info = await self._fresh(kind)
            self.ui(lambda: st.set("connecting..."))
            dev = self._make(kind, info["address"])
            await dev.connect()
            if kind == "wand" and self.settings.get("streaming"):
                await dev.imu_start()
            return dev

        def ok(dev):
            self.connecting[kind] = False
            if kind == "wand":
                self.wand = dev
                self.vars["w_info"].set(f"{dev.model} (fw {dev.firmware})")
                self.vars["w_batt"].set(f"{dev.battery}%")
                self.vars["w_state"].set("connected")
                self.log("Wand connected, motion streaming.")
            else:
                self.box = dev
                self.vars["b_info"].set(dev.firmware or "-")
                self.vars["b_batt"].set(f"{dev.battery}%")
                self.vars["b_state"].set("connected")
                self.log("Base connected.")
            self.cue("connect")
            self._base_light()

        def fail(e):
            self.connecting[kind] = False
            reason = str(e) or type(e).__name__
            if self.settings.get("auto_reconnect") and not self.user_off[kind]:
                st.set(f"waiting for the {name} (wave it)...")
                if not quiet:
                    self.log(f"Could not connect to the {name}: {reason}. Retrying automatically.")
                self.after(RETRY_S * 1000, lambda: self.connect(kind, quiet=True))
            else:
                st.set(f"failed: {reason}")
        self.run(go(), ok, fail)

    def _make(self, kind, address):
        if kind == "wand":
            w = Wand(address)
            w.on_imu = self._on_imu
            w.on_touch = lambda m: self.ui(lambda: self.log(f"Wand touch sensors: {m:04b}"))
            w.on_spell = lambda n: self.ui(lambda: self._native_spell(n))
            w.on_disconnect = lambda: self.ui(lambda: self._lost("wand"))
            return w
        b = Box(address)
        b.on_lid = lambda x: self.ui(lambda: self.vars["b_lid"].set("removed" if x else "on"))
        b.on_wand = lambda x: self.ui(lambda: self.vars["b_wand"].set("yes" if x else "no"))
        b.on_charge = lambda x: self.ui(lambda: self.vars["b_usb"].set("plugged in" if x else "unplugged"))
        b.on_disconnect = lambda: self.ui(lambda: self._lost("box"))
        return b

    def _lost(self, kind):
        name = "Wand" if kind == "wand" else "Base"
        self.vars["w_state" if kind == "wand" else "b_state"].set("disconnected")
        if not self.user_off[kind]:
            self.log(f"{name} disconnected.")
        self._base_light()
        if self.settings.get("auto_reconnect") and not self.user_off[kind]:
            self.after(3000, lambda: self.connect(kind, quiet=True))

    def disconnect(self, kind):
        self.user_off[kind] = True
        dev = self.wand if kind == "wand" else self.box
        if dev:
            self.run(dev.disconnect())

    def _base_light(self):
        """Base light mirrors the wand: green when connected, amber when not."""
        if not (self.box and self.box.connected):
            return
        if not self.settings.get("base_status_light"):
            return
        wand_ok = bool(self.wand and self.wand.connected)
        r, g, b = (0, 110, 0) if wand_ok else (140, 60, 0)
        self.run(self.box.led(r, g, b))

    def wand_call(self, method, *args):
        if not (self.wand and self.wand.connected):
            self.log("Connect the wand first.")
            return
        self.run(getattr(self.wand, method)(*args))

    # ---------- lights ----------
    def pick_color(self):
        c = colorchooser.askcolor(color=hexcolor(self.color))
        if c and c[0]:
            self.color = tuple(int(x) for x in c[0])
            self.swatch.configure(bg=c[1])

    def set_led(self):
        g = self.group.get()
        if g == "All":
            self.wand_call("led_all", *self.color)
        else:
            self.wand_call("led", LED_GROUPS[g], *self.color)

    def set_box_led(self):
        if not (self.box and self.box.connected):
            self.log("Connect the base first.")
            return
        self.run(self.box.led(*self.color))

    def leds_off(self):
        if self.wand and self.wand.connected:
            self.run(self.wand.leds_off())
        if self.box and self.box.connected:
            self.run(self.box.leds_off())

    # ---------- spells ----------
    def play_selected(self):
        self.log(f"Playing {pretty(self.sel_spell)}")
        self.wand_call("play", spell_effect(self.sel_spell, self.settings.color(self.sel_spell)))

    def _action_dialog(self):
        spell = self.sel_spell
        if self._dlg is not None:
            try:
                self._dlg.destroy()
            except tk.TclError:
                pass
        dlg = self._dlg = tk.Toplevel(self)
        dlg.title(f"Actions & colour: {pretty(spell)}")
        dlg.configure(bg=PARCH)
        dlg.resizable(False, False)
        dlg.transient(self)
        dlg.after(100, lambda: style_titlebar(dlg))
        color = list(self.settings.color(spell) or spell_color(spell))
        act = self.settings.action(spell) or {"type": "None", "value": ""}
        lab = dict(bg=PARCH, fg=INK, font=(SERIF, 11), anchor="w")
        tk.Label(dlg, text=pretty(spell), bg=PARCH, fg=RED, font=(SERIF, 20, "bold italic")).grid(
            row=0, column=0, columnspan=3, sticky="w", padx=16, pady=(12, 4))
        tk.Label(dlg, text="Light colour", **lab).grid(row=1, column=0, sticky="w", padx=16, pady=6)
        sw = tk.Label(dlg, width=8, bg=hexcolor(color), relief="solid", bd=1)
        sw.grid(row=1, column=1, sticky="w")

        def pick():
            c = colorchooser.askcolor(color=hexcolor(color), parent=dlg)
            if c and c[0]:
                color[:] = [int(x) for x in c[0]]
                sw.configure(bg=c[1])

        def reset():
            color[:] = spell_color(spell)
            sw.configure(bg=hexcolor(color))
        fr = tk.Frame(dlg, bg=PARCH)
        fr.grid(row=1, column=2, sticky="w", padx=8)
        self.button("Pick...", pick, 0, 0, parent=fr).pack(side="left", padx=2)
        self.button("Reset", reset, 0, 0, parent=fr).pack(side="left", padx=2)

        tk.Label(dlg, text="When cast, also", **lab).grid(row=2, column=0, sticky="w", padx=16, pady=6)
        typ = ttk.Combobox(dlg, style="Book.TCombobox", values=ACTION_TYPES, state="readonly", width=26,
                           font=(SERIF, 11))
        typ.set(act["type"] if act["type"] in ACTION_TYPES else "None")
        typ.grid(row=2, column=1, columnspan=2, sticky="w")
        val = tk.StringVar(value=act["value"])
        ent = tk.Entry(dlg, textvariable=val, width=52, bg=FIELD, fg=INK, relief="flat", font=(SERIF, 11),
                       highlightthickness=1, highlightbackground=PARCH_DARK, highlightcolor=GOLD,
                       insertbackground=INK)
        ent.grid(row=3, column=0, columnspan=3, padx=16, pady=4, sticky="we")
        hint = tk.Label(dlg, text="", wraplength=470, justify="left", bg=PARCH, fg=INK, font=(SERIF, 10, "italic"))
        hint.grid(row=4, column=0, columnspan=3, padx=16, sticky="w")

        def on_type(_e=None):
            hint.configure(text=HINTS.get(typ.get(), "Nothing extra happens besides the light and buzz."))
        typ.bind("<<ComboboxSelected>>", on_type)
        on_type()

        def current():
            return {"type": typ.get(), "value": val.get().strip()}

        def browse():
            t = typ.get()
            ft = [("WAV sound", "*.wav")] if t == "Play sound file" else [("Programs", "*.exe"), ("All files", "*.*")]
            p = filedialog.askopenfilename(parent=dlg, filetypes=ft)
            if p:
                val.set(f'"{p}"' if (t == "Run program" and " " in p) else p)

        def test():
            a = current()
            try:
                validate(a)
                if a["type"] == "None":
                    messagebox.showinfo("Test", "No action selected.", parent=dlg)
                    return
                run_action(a, spell)
            except Exception as e:
                messagebox.showerror("Cannot run this action", str(e), parent=dlg)

        def save():
            a = current()
            try:
                validate(a)
            except ValueError as e:
                messagebox.showerror("Check the action", str(e), parent=dlg)
                return
            self.settings.set_action(spell, a)
            self.settings.set_color(spell, None if tuple(color) == tuple(spell_color(spell)) else color)
            dlg.destroy()
            self._dlg = None
            if self.page == "spells":
                self._draw_spell_detail()
            self.log(f"Saved actions for {pretty(spell)}")

        row = tk.Frame(dlg, bg=PARCH)
        row.grid(row=5, column=0, columnspan=3, sticky="e", padx=16, pady=(10, 14))
        self.button("Browse...", browse, 0, 0, parent=row).pack(side="left", padx=3)
        self.button("Test", test, 0, 0, parent=row).pack(side="left", padx=3)
        self.button("Save", save, 0, 0, parent=row).pack(side="left", padx=3)
        self.button("Cancel", dlg.destroy, 0, 0, parent=row).pack(side="left", padx=3)
        dlg.update_idletasks()
        dlg.geometry("+%d+%d" % (self.winfo_rootx() + 220, self.winfo_rooty() + 180))
        dlg.grab_set()

    # ---------- gestures ----------
    def arm_record(self, n):
        if not (self.wand and self.wand.connected):
            self.log("Connect the wand first.")
            self.t_status.set("Connect your wand on the Devices page first.")
            return
        self.rec = {"name": self.sel_spell, "need": n, "got": 0}
        self.t_status.set(f"{pretty(self.sel_spell)}: cast 1 of {n}. Make the motion now...")

    def _on_imu(self, samples):  # BLE thread
        self.spin = max(math.sqrt(sum(g * g for g in s.gyro)) for s in samples)
        self.spin_hist.append((time.monotonic(), self.spin))
        for smp in samples:
            g = self.seg.feed(smp)
            if g:
                self.ui(lambda g=g: self._gesture_done(g))

    def _gesture_done(self, g):
        if self.rec:
            self._record_step(g)
        elif self._practice_listening():
            self._practice_cast(g)
        elif self.cast_mode.get():
            self._cast(g)

    def _record_step(self, g):
        r = self.rec
        ok, msg, _ = self.store.check(r["name"], g)
        if not ok and r.get("rejects", 0) < 2:
            r["rejects"] = r.get("rejects", 0) + 1
            self.cue("fail")
            self.t_status.set(f"{msg} Try that cast again ({r['got'] + 1} of {r['need']}). "
                              "(If it keeps happening, the next one is kept anyway.)")
            return
        r["rejects"] = 0
        before = self.store.casts(r["name"])
        self.store.add(r["name"], g)
        r["got"] += 1
        self.cue("saved")
        self.log(f"Recorded {pretty(r['name'])} cast {self.store.casts(r['name'])} ({len(g)} samples)")
        just_unlocked = before < UNLOCK_AT <= self.store.casts(r["name"])
        if self.page == "teach":
            self._fill_gestures()
        if r["got"] < r["need"]:
            self.t_status.set(f"Saved {r['got']} of {r['need']}. Cast {pretty(r['name'])} again...")
            return
        self.rec = None
        total = self.store.casts(r["name"])
        msg = (f"{pretty(r['name'])} is unlocked! The book will now recognise it." if just_unlocked
               else f"Saved. {pretty(r['name'])} now has {total} casts.")
        if total < UNLOCK_AT:
            msg += f" {UNLOCK_AT - total} more to unlock it."
        chk = self.store.self_check()
        if chk:
            msg += f" Self-test: {chk['correct']} of {chk['total']} casts recognised."
        self.t_status.set(msg)
        if just_unlocked:
            self.log(f"Unlocked {pretty(r['name'])}")
            self.cue("success")
            self._flash(r["name"], self.settings.color(r["name"]) or spell_color(r["name"]),
                        f"{pretty(r['name'])} unlocked!")

    def _dedupe(self, name, source):
        """False if this recognition should not fire, because the other recogniser already handled the cast.

        - Same spell reported by both the wand and the book within a moment: it counts once, and the history
          entry is marked as seen by both.
        - The wand named a DIFFERENT spell for this cast first: trust the wand and ignore the book's answer.
        """
        now = time.monotonic()
        last, self._last_fire = self._last_fire, (now, name, source)
        if last and last[2] != source and now - last[0] < FIRE_WINDOW_S:
            if last[1] == name:
                for i in range(len(self.cast_log) - 1, -1, -1):
                    entry = self.cast_log[i]
                    if entry[1] == name:
                        self.cast_log[i] = entry[:3] + ("both",)
                        break
                if self.page == "cast":
                    self._draw_history()
                return False
            if source == "book":
                self.log(f"The wand named {pretty(last[1])} for this cast, so the book's "
                         f"{pretty(name)} was ignored.")
                return False
        return True

    def _note_native(self, key):
        """Remember which spells the wand recognises by itself, and count them by streaming state."""
        ns = dict(self.settings.get("native_stats"))
        field = "streaming_on" if self.settings.get("streaming") else "streaming_off"
        ns[field] = int(ns.get(field, 0)) + 1
        self.settings.set("native_stats", ns)
        known = list(self.settings.get("wand_known"))
        if key and key not in known:
            known.append(key)
            self.settings.set("wand_known", known)
            self.log(f"The wand knows {pretty(key)} by itself.")

    def _mark(self, s):
        """Index mark: unlocked (taught), the wand knows it, learning, or locked."""
        st = self.store.state(s)
        if st == "unlocked":
            return MARK["unlocked"]
        if s in self.settings.get("wand_known"):
            return "★ "
        return MARK[st]

    def _streaming_changed(self):
        on = bool(self.stream_var.get())
        self.settings.set("streaming", on)
        if not on:
            self.spin_hist.clear()
            self.spin = 0.0
        if self.wand and self.wand.connected:
            self.wand_call("imu_start" if on else "imu_stop")
        self.log("Motion streaming on: your taught spells are recognised." if on else
                 "Motion streaming off: only spells the wand recognises itself are reported.")

    def _native_spell(self, raw):
        """The wand itself recognised a spell and told us its name."""
        key = spell_key(raw)
        known = key in SPELLS
        self.log(f"Wand recognised: {raw}" + ("" if known else "  (not in this book's list)"))
        self._note_native(key if known else None)
        if known and self._practice_listening():
            self._practice_native(key)
            return
        if known and not self._dedupe(key, "wand"):
            return                       # the book already recognised this same cast: it counts once
        self.last_cast = {"name": key if known else None, "raw": raw, "native": True, "dist": 0.0,
                          "limit": 0.0, "near": []}
        self.cast_log.append((time.strftime("%H:%M:%S"), key if known else raw, 0.0, "wand"))
        self.cast_log = self.cast_log[-50:]
        if self.page == "cast":
            self._draw_cast_live()
            self._draw_history()
        if known:
            self._spell_cast(key)
        else:
            self.cue("success")

    def _cast(self, g):
        if not self.store.data:
            if self.page == "teach":
                self.t_status.set("The book knows no spells yet. Teach it one first.")
            return
        accept = float(self.settings.get("accept"))
        best, dist, scores = self.store.match(g, accept)
        near = sorted(scores.items(), key=lambda kv: kv[1])[:4]
        if best and not self._dedupe(best, "book"):
            self.log(f"Cast {pretty(best)} d={dist:.2f} (already handled via the wand)")
            return                       # the wand already reported this same cast: it counts once
        self.last_cast = {"name": best, "dist": dist, "limit": accept, "near": near}
        self.cast_log.append((time.strftime("%H:%M:%S"), best, dist, "book"))
        self.cast_log = self.cast_log[-50:]
        if self.page == "cast":
            self._draw_cast_live()
            self._draw_history()
        if not best:
            self.cue("fail")
            return
        self.log(f"Cast {pretty(best)} d={dist:.2f}")
        self._spell_cast(best)

    def _spell_cast(self, best):
        """A spell was recognised (by the book or by the wand): sound, glow, wand effect, then its action."""
        self.cue("success")
        col = self.settings.color(best) or spell_color(best)
        if self.hidden and self.tray and self.settings.get("tray_notify"):
            self.tray.notify(f"{pretty(best)} recognised")
        if self.page != "cast" and not self.hidden:          # the Cast page shows the result itself
            self._flash(best, col)
        self.wand_call("play", spell_effect(best, self.settings.color(best)))
        act = self.settings.action(best)
        if act:
            if self.test_mode.get():
                self.log(f"Test mode: would run {act['type']}: {act['value']}")
            else:
                try:
                    self.log("Ran " + run_action(act, best))
                except Exception as e:
                    self.log(f"Action failed: {e}")

    def _flash(self, name, rgb, text=None):
        """The spell name glows in the middle of the page, then fades into the parchment."""
        steps, pr = 16, (0xe8, 0xd9, 0xb5)
        cx = SPINE if self.page == "cast" else SPINE + (BX1 - SPINE) // 2
        cy = BY0 + 430

        def frame(i):
            self.cv.delete("flash")
            if i >= steps:
                return
            t = i / steps
            c = tuple(int(rgb[j] * 0.75 * (1 - t) + pr[j] * t) for j in range(3))
            self.cv.create_text(cx, cy, text=text or pretty(name), fill=hexcolor(c), width=380,
                                font=(SERIF, 28 + int(8 * (1 - t)), "bold italic"), tags="flash")
            self.after(50, lambda: frame(i + 1))
        frame(0)

    def autotune(self):
        chk = self.store.self_check()
        if not chk or chk["suggested_accept"] is None:
            self.c_note.set("Teach at least two casts of a spell first, then try again.")
            return
        s = chk["suggested_accept"]
        self.accept_var.set(s)
        self.settings.set("accept", s)
        self.c_note.set(f"Self-test: {chk['correct']} of {chk['total']} recognised. Limit set to {s}.")
        if self.page == "cast":  # redraw so the slider moves to the new value
            self.clear()
            self._build("cast")

    def check_casts(self):
        chk = self.store.self_check()
        if not chk:
            self.t_status.set("Record at least two casts of a spell first.")
            return
        msg = f"Self-test: {chk['correct']} of {chk['total']} of your casts are recognised."
        if chk["confused"]:
            pairs = sorted({f"{pretty(a)} looks like {pretty(b)}" for a, b in chk["confused"]})
            msg += " Mixed up: " + "; ".join(pairs[:3]) + "."
        self.t_status.set(msg)

    def delete_gesture(self):
        sel = self.g_list.curselection()
        if sel:
            name = sorted(self.store.data)[sel[0]]
            if messagebox.askyesno("Forget spell", f"Forget all casts of {pretty(name)}? It will be locked again."):
                self.store.remove(name)
                self._fill_gestures()

    def export_gestures(self):
        if not self.store.data:
            self.t_status.set("Nothing to export yet.")
            return
        p = filedialog.asksaveasfilename(defaultextension=".json", initialfile="my-spells.json",
                                         filetypes=[("Spell files", "*.json")])
        if p:
            self.store.export_to(p)
            self.log(f"Exported casts to {p}")

    def import_gestures(self):
        p = filedialog.askopenfilename(filetypes=[("Spell files", "*.json")])
        if not p:
            return
        try:
            n = self.store.import_from(p)
        except (ValueError, OSError) as e:
            messagebox.showerror("Import", f"Could not import that file: {e}")
            return
        self._fill_gestures()
        self.t_status.set(f"Imported {n} casts.")

    def _close(self):
        if self.tray:
            self.tray.stop()
        for d in (self.wand, self.box):
            if d and d.connected:
                try:
                    asyncio.run_coroutine_threadsafe(d.disconnect(), self.loop).result(3)
                except Exception:
                    pass
        self.destroy()


def _screenshots(app: App, outdir: str, demo: bool = True):
    """Developer helper: save a PNG of every page (and the actions dialog) for the README."""
    from PIL import ImageGrab
    os.makedirs(outdir, exist_ok=True)
    keys = [k for k, _, _ in TABS]
    app.attributes("-topmost", True)  # make sure no other window is in front when grabbing the screen
    app.lift()
    app.focus_force()

    def snap(name, widget=None):
        w = widget or app
        box = (w.winfo_rootx(), w.winfo_rooty(), w.winfo_rootx() + w.winfo_width(),
               w.winfo_rooty() + w.winfo_height())
        ImageGrab.grab(bbox=box).save(os.path.join(outdir, f"{name}.png"))

    if demo:  # realistic-looking sample state for the documentation
        for k, v in (("w_state", "connected"), ("w_info", "Heroic wand (fw 0.3)"), ("w_batt", "82%"),
                     ("b_state", "connected"), ("b_info", "32.1"), ("b_batt", "100%"), ("b_lid", "removed"),
                     ("b_wand", "no"), ("b_usb", "unplugged")):
            app.vars[k].set(v)
        blank = [[0.0] * 6 for _ in range(gestures.N_POINTS)]
        for name, n in (("lumos", 4), ("nox", 3), ("expelliarmus", 3), ("protego", 5), ("accio", 3),
                        ("stupefy", 3), ("incendio", 2), ("reparo", 1), ("aguamenti", 3), ("alohomora", 3),
                        ("wingardium_leviosa", 3), ("expecto_patronum", 3)):
            app.store.data[name] = [blank] * n
        app.last_cast = {"name": "expelliarmus", "dist": 0.41, "limit": 0.9,
                         "near": [("expelliarmus", 0.41), ("stupefy", 0.88), ("protego", 1.12)]}
        app.cast_log = [("14:02:11", "lumos", 0.33, "book"), ("14:02:19", "nox", 0.52, "book"),
                        ("14:02:40", None, 1.31, "book"), ("14:03:02", "protego", 0.0, "wand"),
                        ("14:03:20", "expelliarmus", 0.41, "book")]
        now = time.monotonic()
        for i in range(60):   # a believable motion trace: rest, one swish, rest
            t = i / 60 * 3.5
            app.spin_hist.append((now - 3.5 + t, 0.4 + (7 * math.sin((t - 1.2) / 1.0 * math.pi)
                                                         if 1.2 < t < 2.2 else 0.0)))
        app.t_status.set("Protego: cast 2 of 3. Make the motion now...")
        app.sel_spell = "protego"
        app.accept_var.set(0.9)       # documentation shows the default, not whatever this PC has saved
        app.settings.data["wand_known"] = ["protego", "wingardium_leviosa"]
        app.settings.data["native_stats"] = {"streaming_on": 1, "streaming_off": 2}
        app.pstats.spells = {"lumos": {"tries": 5, "hits": 2}, "nox": {"tries": 4, "hits": 4},
                             "accio": {"tries": 6, "hits": 3}, "stupefy": {"tries": 3, "hits": 1}}
        app.pstats.best_streak = 5
        app.practice.update(active=True, state="result", target="stupefy", last="stupefy", streak=0,
                            gesture=[[0.0] * 6] * 10, session=[("lumos", True, "lumos"), ("nox", True, "nox"),
                                                                ("accio", False, "stupefy"),
                                                                ("protego", True, "protego"),
                                                                ("stupefy", False, "nox")],
                            result={"ok": False, "got": "nox", "dist": 0.78, "tdist": 1.02, "source": "book",
                                    "added": False})

    def grab(i=0):
        if i >= len(keys):
            app.sel_spell = "expelliarmus"
            app._action_dialog()
            app.update()
            app.after(500, lambda: (snap("dialog", app._dlg), app.destroy()))
            return
        app.page = keys[i]
        app._mark_tab(keys[i])
        app.clear()
        if keys[i] == "spells":
            app.sel_spell = "expelliarmus"
        if keys[i] == "cast":          # fresh timestamps so the demo motion trace is inside the 3.5 s window
            now = time.monotonic()
            app.spin_hist.clear()
            for j in range(60):
                t = j / 60 * 3.5
                app.spin_hist.append((now - 3.5 + t, 0.4 + (7 * math.sin((t - 1.2) / 1.0 * math.pi)
                                                             if 1.2 < t < 2.2 else 0.0)))
        app._build(keys[i])
        app.update()
        app.after(500, lambda: (snap(keys[i]), grab(i + 1)))
    app.after(900, grab)


def _selftest(outfile):
    """Headless BLE check for the packaged EXE: scan, connect to the wand, write the result to a file."""
    import traceback

    async def go(f):
        found = await scan(8)
        f.write(f"scan: {found}\n")
        f.flush()
        if "wand" in found:
            async with Wand(found["wand"]["address"]) as w:
                f.write(f"connected: model={w.model} fw={w.firmware} battery={w.battery}\n")

    with open(outfile, "w", encoding="utf-8") as f:
        try:
            asyncio.run(go(f))
            f.write("OK\n")
        except Exception:
            f.write("FAILED\n" + traceback.format_exc())


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--selftest":
        _selftest(sys.argv[2])
        sys.exit(0)
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    shots = len(sys.argv) > 2 and sys.argv[1] == "--shots"
    if shots:  # never connect to devices or touch real user data when taking screenshots
        import tempfile
        os.environ["MCC_NO_AUTOCONNECT"] = "1"
        os.environ["MCC_NO_TRAY"] = "1"
        d = tempfile.mkdtemp()
    instance = None
    if not shots:                      # only one copy may talk to the wand: a second launch shows the first
        instance = SingleInstance()
        if instance.already_running:
            instance.ask_existing_to_show()
            sys.exit(0)
    a = App(start_hidden=("--minimized" in sys.argv and not shots))
    if instance:
        instance.watch(lambda: a.ui(a.show_window))
    if shots:
        a.settings = Settings(os.path.join(d, "s.json"))
        a.store = gestures.GestureStore(os.path.join(d, "g.json"))
        a.pstats = PracticeStats(os.path.join(d, "p.json"))
        _screenshots(a, sys.argv[2])
    a.mainloop()
