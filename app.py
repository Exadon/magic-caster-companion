"""Magic Caster Companion: a spell-book desktop app for the Magic Caster Wand and Box."""
import asyncio
import math
import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk

from PIL import Image, ImageChops, ImageFilter, ImageTk

import gestures
from actions import ACTION_TYPES, HINTS, play_cue, run_action, validate
from mcwand import Box, LED_GROUPS, Wand, scan
from settings import DATA_DIR, Settings
from spells_data import (CAST_STEPS, DESCRIPTIONS, SPELLS, diagram_paths, pretty, resource_path,
                         spell_color, spell_effect)
from version import __version__

SERIF = "Palatino Linotype"
PARCH, PARCH_DARK = "#e8d9b5", "#b89a62"
FIELD = "#f3e8c8"
INK, INK_RGB = "#3a2412", (58, 36, 18)
RED, GOLD, LEATHER = "#7a1f1f", "#c9a227", "#2b1a10"
W, H = 1000, 730
BX0, BX1, BY0, BY1 = 30, 930, 25, 675
SPINE = (BX0 + BX1) // 2
LX, RX = BX0 + 28, SPINE + 28          # left/right page content origins
PAGE_W = SPINE - BX0 - 56              # usable content width of a page
RETRY_S = 6                            # seconds between automatic reconnect attempts

TABS = [("devices", "Devices", "#8a2323"), ("spells", "Spells", "#2f6b3a"),
        ("cast", "Cast", "#243f73"), ("lights", "Lights", "#b8862b"),
        ("notes", "Notes", "#5a2f6b")]


def hexcolor(rgb):
    return "#%02x%02x%02x" % tuple(int(x) for x in rgb)


def make_page(w, h, spine_on_right):
    """Procedural parchment: flat centre, darker edges, shadow toward the spine."""
    base = Image.new("RGB", (w, h), PARCH)
    edge = Image.new("RGB", (w, h), PARCH_DARK)
    rad = Image.radial_gradient("L").resize((w, h)).point(lambda v: max(0, v - 175) * 3)
    page = Image.composite(edge, base, rad)
    grad = Image.linear_gradient("L").rotate(90 if spine_on_right else -90).resize((w, h))
    shadow = grad.point(lambda v: max(0, v - 235) * 4)
    return Image.composite(Image.new("RGB", (w, h), (90, 60, 30)), page, shadow)


def make_leather(w, h):
    base = Image.new("RGB", (w, h), (46, 28, 17))
    noise = Image.effect_noise((w, h), 22).convert("RGB")
    return Image.blend(base, noise, 0.10)


_ink_cache = {}


def ink_image(path, width):
    key = (path, width)
    if key not in _ink_cache:
        im = Image.open(path).convert("RGBA")
        mask = ImageChops.multiply(im.getchannel("A"), im.convert("L"))
        mask = mask.filter(ImageFilter.MaxFilter(3))
        ink = Image.new("RGBA", im.size, INK_RGB + (255,))
        ink.putalpha(mask)
        h = int(im.height * width / im.width)
        _ink_cache[key] = ImageTk.PhotoImage(ink.resize((width, h), Image.LANCZOS))
    return _ink_cache[key]


class App(tk.Tk):
    def __init__(self):
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
        self.meter = None
        self.status_item = None
        self.scores_item = None
        self.log_lines: list[str] = []
        self.logbox: tk.Text | None = None
        self.store = gestures.GestureStore(os.path.join(DATA_DIR, "gestures.json"))
        self.seg = gestures.Segmenter()
        self.rec: dict | None = None
        self.page = None
        self.busy = False
        self.widgets: list[tk.Widget] = []
        self._dlg = None
        self.vars = {k: tk.StringVar(value="-") for k in
                     ("w_state", "w_info", "w_batt", "b_state", "b_info", "b_batt", "b_lid", "b_wand", "b_usb")}
        self.vars["w_state"].set("not connected")
        self.vars["b_state"].set("not connected")
        self.g_status = tk.StringVar(value="Connect your wand, then record or cast.")
        self.g_status.trace_add("write", self._status_changed)
        self.cast_mode = tk.BooleanVar(value=True)
        self.test_mode = tk.BooleanVar(value=self.settings.get("test_mode"))
        self.accept_var = tk.DoubleVar(value=self.settings.get("accept"))
        self.pref_vars = {k: tk.BooleanVar(value=self.settings.get(k))
                          for k in ("sounds", "auto_reconnect", "base_status_light")}

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Book.TCombobox", fieldbackground=FIELD, background=PARCH_DARK, foreground=INK,
                        arrowcolor=INK, bordercolor=PARCH_DARK, selectbackground=FIELD, selectforeground=INK)
        style.map("Book.TCombobox", fieldbackground=[("readonly", FIELD)], foreground=[("readonly", INK)],
                  selectbackground=[("readonly", FIELD)], selectforeground=[("readonly", INK)])
        self.option_add("*TCombobox*Listbox.background", FIELD)
        self.option_add("*TCombobox*Listbox.foreground", INK)
        self.option_add("*TCombobox*Listbox.font", (SERIF, 11))

        self.cv = tk.Canvas(self, width=W, height=H, highlightthickness=0, bg=LEATHER)
        self.cv.pack()
        self.leather = ImageTk.PhotoImage(make_leather(W, H))
        self.cv.create_image(0, 0, image=self.leather, anchor="nw")
        self.cv.create_rectangle(BX0 - 10, BY0 - 10, BX1 + 10, BY1 + 10, outline=GOLD, width=3)
        self.cv.create_rectangle(BX0 - 5, BY0 - 5, BX1 + 5, BY1 + 5, outline="#6b4a1e", width=6)
        ph = BY1 - BY0
        self.left_img = ImageTk.PhotoImage(make_page(SPINE - BX0, ph, True))
        self.right_img = ImageTk.PhotoImage(make_page(BX1 - SPINE, ph, False))
        self.cv.create_image(BX0, BY0, image=self.left_img, anchor="nw")
        self.cv.create_image(SPINE, BY0, image=self.right_img, anchor="nw")
        self.cv.create_line(SPINE, BY0, SPINE, BY1, fill="#5a3c1c", width=2)
        self.ribbon = self.cv.create_text(W // 2, H - 24, text="", fill="#d9c07a", font=(SERIF, 12, "italic"))
        for k in ("w_state", "w_batt", "b_state", "b_batt"):
            self.vars[k].trace_add("write", lambda *_: self._ribbon())
        self._ribbon()
        self._draw_tabs()

        self.after(50, self._poll)
        self.after(90, self._tick)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.show("devices", animate=False)
        if self.settings.get("auto_reconnect") and not os.environ.get("MCC_NO_AUTOCONNECT"):
            self.after(1200, lambda: self.connect_all(quiet=True))

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
        self.after(90, self._tick)

    def _status_changed(self, *_):
        if self.status_item is not None and self.page == "cast":
            try:
                self.cv.itemconfig(self.status_item, text=self.g_status.get())
            except tk.TclError:
                self.status_item = None

    def _ribbon(self):
        def short(s):
            return s if len(s) <= 38 else s[:36] + "..."
        wb = f" ({self.vars['w_batt'].get()})" if self.vars["w_state"].get() == "connected" else ""
        bb = f" ({self.vars['b_batt'].get()})" if self.vars["b_state"].get() == "connected" else ""
        self.cv.itemconfig(self.ribbon, text=f"Wand: {short(self.vars['w_state'].get())}{wb}     ✦     "
                                             f"Base: {short(self.vars['b_state'].get())}{bb}")

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
            play_cue(name)

    # ---------- book chrome ----------
    def _draw_tabs(self):
        self.tab_ids = {}
        for i, (key, label, col) in enumerate(TABS):
            y = BY0 + 40 + i * 104
            r = self.cv.create_rectangle(BX1 - 2, y, BX1 + 56, y + 92, fill=col, outline=GOLD, width=2,
                                         tags=("tab", f"tab_{key}"))
            t = self.cv.create_text(BX1 + 27, y + 46, text=label, fill="#f3e6c4", angle=270,
                                    font=(SERIF, 13, "bold"), tags=("tab", f"tab_{key}"))
            self.tab_ids[key] = (r, t, y, col)
            self.cv.tag_bind(f"tab_{key}", "<Button-1>", lambda _e, k=key: self.show(k))
            self.cv.tag_bind(f"tab_{key}", "<Enter>", lambda _e: self.cv.config(cursor="hand2"))
            self.cv.tag_bind(f"tab_{key}", "<Leave>", lambda _e: self.cv.config(cursor=""))

    def _mark_tab(self, active):
        for key, (r, _t, y, col) in self.tab_ids.items():
            on = key == active
            self.cv.coords(r, BX1 - 2, y, BX1 + (66 if on else 56), y + 92)
            self.cv.itemconfig(r, outline="#fff2b0" if on else GOLD, width=3 if on else 2)

    def clear(self):
        for w in self.widgets:
            try:
                w.destroy()
            except tk.TclError:
                pass
        self.widgets = []
        self.cv.delete("page")
        self.meter = None
        self.logbox = None
        self.status_item = None
        self.scores_item = None

    def show(self, page, animate=True):
        if self.busy or (page == self.page and animate):
            return
        self.page = page
        self._mark_tab(page)
        self.clear()
        if animate:
            self.busy = True
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

    # widget helpers
    def put(self, widget, x, y, anchor="nw", **kw):
        self.widgets.append(widget)
        self.cv.create_window(x, y, window=widget, anchor=anchor, tags="page", **kw)
        return widget

    def text(self, x, y, s, size=11, bold=False, italic=False, color=INK, width=PAGE_W, anchor="nw", **kw):
        style = " ".join(p for p in ("bold" if bold else "", "italic" if italic else "") if p) or "normal"
        tags = kw.pop("tags", "page")
        return self.cv.create_text(x, y, text=s, fill=color, anchor=anchor, width=width,
                                   font=(SERIF, size, style), tags=tags, **kw)

    def button(self, label, cmd, x, y, width=None, parent=None):
        b = tk.Button(parent or self, text=label, command=cmd, bg="#5b3a24", fg="#f3e6c4", relief="flat",
                      activebackground="#7a5236", activeforeground="#fff7dc", cursor="hand2",
                      font=(SERIF, 11, "bold"), padx=12, pady=5, bd=0, width=width or 0)
        return self.put(b, x, y) if parent is None else b

    def check(self, label, var, x, y, cmd=None):
        cb = tk.Checkbutton(self, text=label, variable=var, command=cmd, bg=PARCH, fg=INK,
                            activebackground=PARCH, selectcolor=FIELD, font=(SERIF, 11), anchor="w")
        return self.put(cb, x, y)

    def label(self, var, x, y, size=12, bold=False, width=None):
        lb = tk.Label(self, textvariable=var, bg=PARCH, fg=INK, font=(SERIF, size, "bold" if bold else "normal"),
                      anchor="w", justify="left", wraplength=width or 0)
        return self.put(lb, x, y)

    def rule(self, x, y, w=PAGE_W):
        self.cv.create_line(x, y, x + w, y, fill="#8a6b3a", width=1, tags="page")

    # ---------- page: devices ----------
    def _page_devices(self):
        self.text(LX, BY0 + 30, "Magic Caster\nCompanion", 28, bold=True, italic=True, color=RED)
        self.rule(LX, BY0 + 125)
        self.text(LX, BY0 + 140, "The Wand", 20, bold=True)
        for i, (k, name) in enumerate([("w_state", "Status"), ("w_info", "Model"), ("w_batt", "Battery")]):
            self.text(LX, BY0 + 190 + i * 32, name, 12, italic=True, width=100)
            self.label(self.vars[k], LX + 110, BY0 + 188 + i * 32, 12, width=280)
        self.button("Connect wand", lambda: self.connect("wand"), LX, BY0 + 300)
        self.button("Disconnect", lambda: self.disconnect("wand"), LX + 160, BY0 + 300)
        self.rule(LX, BY0 + 370)
        self.button("Connect wand & base", self.connect_all, LX, BY0 + 390)
        self.button("Scan only", self.do_scan, LX + 230, BY0 + 390)
        self.text(LX, BY0 + 440, "Wake the wand first by giving it a wave. Connect scans for you, and reconnects "
                  "automatically if the link drops (change this on the Lights page).", 10, italic=True)

        self.text(RX, BY0 + 30, "The Base", 20, bold=True)
        self.text(RX, BY0 + 62, "Magic Caster Box", 11, italic=True)
        rows = [("b_state", "Status"), ("b_info", "Firmware"), ("b_batt", "Battery"), ("b_lid", "Lid"),
                ("b_wand", "Wand in base"), ("b_usb", "USB power")]
        for i, (k, name) in enumerate(rows):
            self.text(RX, BY0 + 110 + i * 32, name, 12, italic=True, width=130)
            self.label(self.vars[k], RX + 140, BY0 + 108 + i * 32, 12, width=240)
        self.button("Connect base", lambda: self.connect("box"), RX, BY0 + 330)
        self.button("Disconnect", lambda: self.disconnect("box"), RX + 160, BY0 + 330)

    # ---------- page: spells ----------
    def _page_spells(self):
        self.text(LX, BY0 + 20, "Index of Spells", 24, bold=True, italic=True, color=RED)
        self.text(LX, BY0 + 62, "Choose a spell to see how it is cast. ✦ marks spells you have taught.", 10,
                  italic=True)
        self.spell_filter = tk.StringVar()
        ent = tk.Entry(self, textvariable=self.spell_filter, bg=FIELD, fg=INK, relief="flat",
                       font=(SERIF, 12), highlightthickness=1, highlightbackground=PARCH_DARK, width=34)
        self.put(ent, LX, BY0 + 90)
        self.spell_filter.trace_add("write", lambda *_: self._fill_spells())
        frame = tk.Frame(self, bg=PARCH)
        sb = tk.Scrollbar(frame)
        self.spell_list = tk.Listbox(frame, bg=PARCH, fg=INK, font=(SERIF, 12), bd=0, highlightthickness=0,
                                     selectbackground="#c9a96a", selectforeground=INK, activestyle="none",
                                     height=21, width=33, yscrollcommand=sb.set, exportselection=False)
        sb.config(command=self.spell_list.yview)
        self.spell_list.pack(side="left")
        sb.pack(side="right", fill="y")
        self.put(frame, LX, BY0 + 128)
        self.spell_list.bind("<<ListboxSelect>>", self._spell_selected)
        self._fill_spells()
        self.button("Play effect", self.play_selected, RX, BY0 + 530)
        self.button("Teach this spell", lambda: self.show("cast"), RX + 130, BY0 + 530)
        self.button("Actions & colour...", self._action_dialog, RX, BY0 + 575)
        self._draw_spell_detail()

    def _fill_spells(self):
        q = self.spell_filter.get().lower().replace(" ", "_")
        self.spell_view = [s for s in SPELLS if q in s]
        self.spell_list.delete(0, "end")
        for s in self.spell_view:
            mark = "✦ " if s in self.store.data else "   "
            self.spell_list.insert("end", mark + pretty(s))
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
            self.text(x, BY0 + 160, "No diagram is available for this spell yet.\nRecord your own motion on the "
                      "Cast page.", 10, italic=True, tags=tg)
        one = bool(paths) and len(paths) == 1
        tx, ty, tw = (x + 210, BY0 + 150, PAGE_W - 210) if one else (x, BY0 + 340, PAGE_W)
        self.text(tx, ty, "How to cast", 13, bold=True, tags=tg, width=tw)
        self.text(tx, ty + 26, CAST_STEPS, 10, tags=tg, width=tw)
        n = len(self.store.data.get(s, []))
        act = self.settings.action(s)
        info = f"Your recorded casts: {n}"
        info += f"\nOn cast: {act['type']} {act['value']}" if act else ""
        self.text(x, BY0 + 475, info, 10, italic=True, tags=tg)

    # ---------- page: cast ----------
    def _page_cast(self):
        self.text(LX, BY0 + 20, "Teach & Cast", 24, bold=True, italic=True, color=RED)
        self.text(LX, BY0 + 62, "Teach the book your own motion for a spell: record three casts, then cast it.",
                  10, italic=True)
        self.text(LX, BY0 + 100, "Spell to teach", 12, bold=True)
        self.cast_combo = ttk.Combobox(self, style="Book.TCombobox", values=[pretty(s) for s in SPELLS],
                                       state="readonly", width=30, font=(SERIF, 11))
        self.cast_combo.set(pretty(self.sel_spell))
        self.cast_combo.bind("<<ComboboxSelected>>", self._cast_pick)
        self.put(self.cast_combo, LX, BY0 + 126)
        self.button("Record 3 casts", lambda: self.arm_record(3), LX, BY0 + 166)
        self.button("Record 1 cast", lambda: self.arm_record(1), LX + 150, BY0 + 166)
        self.check("Recognise my casts and play the effect", self.cast_mode, LX, BY0 + 214)
        self.check("Test mode (recognise only, run no actions)", self.test_mode, LX, BY0 + 238,
                   lambda: self.settings.set("test_mode", bool(self.test_mode.get())))
        sc = tk.Scale(self, from_=0.3, to=2.0, resolution=0.05, orient="horizontal", variable=self.accept_var,
                      length=250, bg=PARCH, fg=INK, troughcolor=FIELD, highlightthickness=0, font=(SERIF, 10),
                      label="Sensitivity limit (lower is stricter)")
        sc.bind("<ButtonRelease-1>", lambda _e: self.settings.set("accept", round(float(self.accept_var.get()), 2)))
        self.put(sc, LX, BY0 + 272)
        self.button("Auto-tune", self.autotune, LX + 270, BY0 + 292)
        self.rule(LX, BY0 + 345)
        self.text(LX, BY0 + 352, "Spells you have taught", 13, bold=True)
        self.g_list = tk.Listbox(self, bg=PARCH, fg=INK, font=(SERIF, 12), bd=0, highlightthickness=0,
                                 selectbackground="#c9a96a", selectforeground=INK, activestyle="none",
                                 height=7, width=33, exportselection=False)
        self.put(self.g_list, LX, BY0 + 382)
        self._fill_gestures()
        self.button("Forget", self.delete_gesture, LX, BY0 + 566)
        self.button("Export", self.export_gestures, LX + 88, BY0 + 566)
        self.button("Import", self.import_gestures, LX + 176, BY0 + 566)
        self.button("Check", self.check_casts, LX + 264, BY0 + 566)

        self.text(RX, BY0 + 24, "The Last Cast", 20, bold=True)
        self.status_item = self.text(RX, BY0 + 64, self.g_status.get(), 15, bold=True, italic=True, color=RED,
                                     width=PAGE_W - 20)
        self.text(RX, BY0 + 150, "Motion", 10, italic=True)
        self.meter = tk.Canvas(self, width=PAGE_W - 60, height=14, bg=FIELD, highlightthickness=1,
                               highlightbackground=PARCH_DARK)
        self.put(self.meter, RX + 60, BY0 + 150)
        self.scores_item = self.text(RX + 215, BY0 + 222, "Cast to see how close each of your spells is.", 11,
                                     italic=True, width=170)
        self.cast_imgs = []
        self._cast_diagram()

    def _cast_pick(self, _e):
        name = self.cast_combo.get().lower().replace(" ", "_")
        if name in SPELLS:
            self.sel_spell = name
            self.cv.delete("cdiag")
            self._cast_diagram()

    def _cast_diagram(self):
        paths = diagram_paths(self.sel_spell)
        self.text(RX, BY0 + 190, f"Trace: {pretty(self.sel_spell)}", 13, bold=True, tags=("page", "cdiag"),
                  width=PAGE_W)
        if paths:
            iw = 200 if len(paths) == 1 else 130
            self.cast_imgs = [ink_image(p, iw) for p in paths]
            for i, im in enumerate(self.cast_imgs):
                self.cv.create_image(RX + i * (iw + 10), BY0 + 222, image=im, anchor="nw", tags=("page", "cdiag"))
        else:
            self.text(RX, BY0 + 230, "No diagram for this spell; invent your own motion.", 10, italic=True,
                      tags=("page", "cdiag"))

    def _fill_gestures(self):
        self.g_list.delete(0, "end")
        for n, s in sorted(self.store.data.items()):
            self.g_list.insert("end", f"{pretty(n)}  ({len(s)} casts)")

    # ---------- page: lights ----------
    def _page_lights(self):
        self.text(LX, BY0 + 20, "Light & Sound", 24, bold=True, italic=True, color=RED)
        self.text(LX, BY0 + 62, "Colour the lights along the wand and the base.", 10, italic=True)
        self.swatch = tk.Label(self, width=14, height=3, bg=hexcolor(self.color), relief="sunken")
        self.put(self.swatch, LX, BY0 + 110)
        self.button("Pick colour", self.pick_color, LX + 170, BY0 + 120)
        self.text(LX, BY0 + 200, "Wand light", 12, bold=True)
        self.group = ttk.Combobox(self, style="Book.TCombobox", values=list(LED_GROUPS) + ["All"],
                                  state="readonly", width=16, font=(SERIF, 11))
        self.group.set("Tip")
        self.put(self.group, LX, BY0 + 228)
        self.button("Set wand light", self.set_led, LX, BY0 + 270)
        self.text(LX, BY0 + 340, "Base light", 12, bold=True)
        self.button("Set base light", self.set_box_led, LX, BY0 + 368)
        self.button("All lights off", self.leds_off, LX, BY0 + 430)

        self.text(RX, BY0 + 24, "Buzz", 20, bold=True)
        self.text(RX, BY0 + 62, "Make the wand vibrate for a moment.", 10, italic=True)
        self.buzz_ms = tk.IntVar(value=300)
        sc = tk.Scale(self, from_=50, to=2000, orient="horizontal", variable=self.buzz_ms, length=300,
                      bg=PARCH, fg=INK, troughcolor=FIELD, highlightthickness=0, font=(SERIF, 10),
                      label="Length (milliseconds)")
        self.put(sc, RX, BY0 + 100)
        self.button("Buzz", lambda: self.wand_call("buzz", int(self.buzz_ms.get())), RX, BY0 + 190)
        self.rule(RX, BY0 + 260)
        self.text(RX, BY0 + 275, "Preferences", 18, bold=True)
        for i, (key, label) in enumerate([("sounds", "Sound effects on this PC"),
                                          ("auto_reconnect", "Connect and reconnect automatically"),
                                          ("base_status_light", "Show wand status on the base's light")]):
            self.check(label, self.pref_vars[key], RX, BY0 + 315 + i * 32,
                       lambda k=key: self._pref_changed(k))

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
                              wrap="word", state="disabled")
        self.put(self.logbox, LX, BY0 + 92)
        self.logbox.configure(state="normal")
        self.logbox.insert("end", "\n".join(self.log_lines) + ("\n" if self.log_lines else ""))
        self.logbox.configure(state="disabled")
        self.logbox.see("end")

        self.text(RX, BY0 + 24, "About", 20, bold=True)
        self.text(RX, BY0 + 56, f"Version {__version__}", 10, italic=True)
        self.text(RX, BY0 + 84,
                  "Magic Caster Companion is an unofficial, community-made replacement for the discontinued "
                  "app. It is not affiliated with or endorsed by the makers of the Magic Caster Wand.\n\n"
                  "The protocol was learned by probing real devices and from the MIT-licensed "
                  "hass-magic-caster-wand project by eigger, whose spell diagrams are also used here.\n\n"
                  "Your recorded casts, colours and actions are kept in your user profile.", 11)
        self.button("Open data folder", lambda: os.startfile(DATA_DIR) if os.path.isdir(DATA_DIR) else None,
                    RX, BY0 + 470)

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
            if kind == "wand":
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
            w.on_spell = lambda n: self.ui(lambda: self.log(f"Wand reported spell: {n}"))
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
        color = list(self.settings.color(spell) or spell_color(spell))
        act = self.settings.action(spell) or {"type": "None", "value": ""}
        lab = dict(bg=PARCH, fg=INK, font=(SERIF, 11), anchor="w")
        tk.Label(dlg, text=pretty(spell), bg=PARCH, fg=RED, font=(SERIF, 20, "bold italic")).grid(
            row=0, column=0, columnspan=3, sticky="w", padx=16, pady=(12, 4))
        tk.Label(dlg, text="Light colour", **lab).grid(row=1, column=0, sticky="w", padx=16, pady=6)
        sw = tk.Label(dlg, width=8, bg=hexcolor(color), relief="sunken")
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
                       highlightthickness=1, highlightbackground=PARCH_DARK)
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
            self.g_status.set("Connect your wand on the Devices page first.")
            return
        self.rec = {"name": self.sel_spell, "need": n, "got": 0}
        self.g_status.set(f"{pretty(self.sel_spell)}: cast 1 of {n}. Make the motion now...")

    def _on_imu(self, samples):  # BLE thread
        self.spin = math.sqrt(sum(g * g for g in samples[-1].gyro))
        for smp in samples:
            g = self.seg.feed(smp)
            if g:
                self.ui(lambda g=g: self._gesture_done(g))

    def _gesture_done(self, g):
        if self.rec:
            self._record_step(g)
        elif self.cast_mode.get():
            self._cast(g)

    def _record_step(self, g):
        r = self.rec
        ok, msg, _ = self.store.check(r["name"], g)
        if not ok and r.get("rejects", 0) < 2:
            r["rejects"] = r.get("rejects", 0) + 1
            self.cue("fail")
            self.g_status.set(f"{msg} Try that cast again ({r['got'] + 1} of {r['need']}). "
                              "(If it keeps happening, the next one is kept anyway.)")
            return
        r["rejects"] = 0
        self.store.add(r["name"], g)
        r["got"] += 1
        self.cue("saved")
        self.log(f"Recorded {pretty(r['name'])} cast {len(self.store.data[r['name']])} ({len(g)} samples)")
        if self.page == "cast":
            self._fill_gestures()
        if r["got"] < r["need"]:
            self.g_status.set(f"Saved {r['got']} of {r['need']}. Cast {pretty(r['name'])} again...")
            return
        self.rec = None
        total = len(self.store.data[r["name"]])
        msg = f"All saved: {pretty(r['name'])} now has {total} casts."
        if total < 3:
            msg += " Record a few more for better results."
        chk = self.store.self_check()
        if chk:
            msg += f" Self-test: {chk['correct']} of {chk['total']} casts recognised."
        self.g_status.set(msg)

    def _cast(self, g):
        if not self.store.data:
            self.g_status.set("The book knows no spells yet. Teach it one first.")
            return
        accept = float(self.settings.get("accept"))
        best, dist, scores = self.store.match(g, accept)
        top = sorted(scores.items(), key=lambda kv: kv[1])[:4]
        if self.scores_item is not None:
            lines = [f"{pretty(n)}  {d:.2f}" for n, d in top] + [f"limit {accept:.2f}"]
            try:
                self.cv.itemconfig(self.scores_item, text="Closest:\n" + "\n".join(lines))
            except tk.TclError:
                self.scores_item = None
        if not best:
            self.cue("fail")
            self.g_status.set(f"Nothing recognised (closest {dist:.2f}, limit {accept:.2f}). Try again, or teach more "
                              "casts.")
            return
        self.g_status.set(f"{pretty(best)}!   (distance {dist:.2f})")
        self.log(f"Cast {pretty(best)} d={dist:.2f}")
        self.cue("success")
        col = self.settings.color(best) or spell_color(best)
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

    def _flash(self, name, rgb):
        """Spell name glows on the right-hand page, then fades into the parchment."""
        steps, pr = 16, (0xe8, 0xd9, 0xb5)
        cx, cy = SPINE + (BX1 - SPINE) // 2, BY0 + 420

        def frame(i):
            self.cv.delete("flash")
            if i >= steps:
                return
            t = i / steps
            c = tuple(int(rgb[j] * 0.75 * (1 - t) + pr[j] * t) for j in range(3))
            self.cv.create_text(cx, cy, text=pretty(name), fill=hexcolor(c), width=380,
                                font=(SERIF, 30 + int(8 * (1 - t)), "bold italic"), tags="flash")
            self.after(50, lambda: frame(i + 1))
        frame(0)

    def autotune(self):
        chk = self.store.self_check()
        if not chk or chk["suggested_accept"] is None:
            self.g_status.set("Record at least two casts of a spell first, then try again.")
            return
        s = chk["suggested_accept"]
        self.accept_var.set(s)
        self.settings.set("accept", s)
        self.g_status.set(f"Self-test: {chk['correct']} of {chk['total']} recognised. Sensitivity limit set to {s}.")

    def check_casts(self):
        chk = self.store.self_check()
        if not chk:
            self.g_status.set("Record at least two casts of a spell first.")
            return
        msg = f"Self-test: {chk['correct']} of {chk['total']} of your casts are recognised."
        if chk["confused"]:
            pairs = sorted({f"{pretty(a)} looks like {pretty(b)}" for a, b in chk["confused"]})
            msg += " Mixed up: " + "; ".join(pairs[:3]) + "."
        self.g_status.set(msg)

    def delete_gesture(self):
        sel = self.g_list.curselection()
        if sel:
            name = sorted(self.store.data)[sel[0]]
            if messagebox.askyesno("Forget spell", f"Forget all casts of {pretty(name)}?"):
                self.store.remove(name)
                self._fill_gestures()

    def export_gestures(self):
        if not self.store.data:
            self.g_status.set("Nothing to export yet.")
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
        self.g_status.set(f"Imported {n} casts.")

    def _close(self):
        for d in (self.wand, self.box):
            if d and d.connected:
                try:
                    asyncio.run_coroutine_threadsafe(d.disconnect(), self.loop).result(3)
                except Exception:
                    pass
        self.destroy()


def _screenshots(app: App, outdir: str):
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

    def grab(i=0):
        if i >= len(keys):
            app.sel_spell = "expelliarmus"
            app._action_dialog()
            app.update()
            app.after(400, lambda: (snap("dialog", app._dlg), app.destroy()))
            return
        app.page = keys[i]
        app._mark_tab(keys[i])
        app.clear()
        app._build(keys[i])
        if keys[i] == "spells":
            app.sel_spell = "expelliarmus"
            app._fill_spells()
            app._draw_spell_detail()
        if keys[i] == "cast":
            app.sel_spell = "expelliarmus"
            app._cast_pick(None)
            app.cast_combo.set(pretty(app.sel_spell))
            app.g_status.set("Expelliarmus!   (distance 0.41)")
            app.cv.itemconfig(app.scores_item,
                              text="Closest:\nExpelliarmus  0.41\nStupefy  0.88\nProtego  1.12\nlimit 0.90")
        app.update()
        app.after(400, lambda: (snap(keys[i]), grab(i + 1)))
    app.after(800, grab)


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
        d = tempfile.mkdtemp()
    a = App()
    if shots:
        a.settings = Settings(os.path.join(d, "s.json"))
        a.store = gestures.GestureStore(os.path.join(d, "g.json"))
        _screenshots(a, sys.argv[2])
    a.mainloop()
