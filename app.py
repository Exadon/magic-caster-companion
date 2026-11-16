"""Magic Caster Companion: a spell-book desktop app for the Magic Caster Wand and Box (entry point)."""
from common import (
    BX0, BX1, BY0, BY1, Box, CARD, CARD_EDGE, DATA_DIR, GOLD, H, INK, ImageTk, LEATHER, MUTED,
    PAGE_W, PARCH, PracticeStats, RED, RoundButton, SERIF, SPELLS, SPINE, Settings, SingleInstance,
    TABS, Tray, W, Wand, __version__, apply_styles, asyncio, autostart_enabled, battery_color,
    battery_percent, collections, gestures, make_leather, make_page, math, os, play_cue, queue,
    resource_path, scan, state_color, style_titlebar, sys, tab_pil, threading, time, tk, tkfont,
    ttk,
)
from casting import CastingMixin
from connection import ConnectionMixin
from pages.cast import CastPage
from pages.devices import DevicesPage
from pages.lights import LightsPage
from pages.notes import NotesPage
from pages.practice import PracticePage
from pages.spells import SpellsPage
from pages.teach import TeachPage
from shell import ShellMixin


class App(ShellMixin, ConnectionMixin, CastingMixin, DevicesPage, SpellsPage, TeachPage, PracticePage, CastPage, LightsPage, NotesPage, tk.Tk):
    """The main window: owns the state and drawing surface; the pages and behaviours live in the mixins."""

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
        instance = SingleInstance(os.environ.get("MCC_INSTANCE_NAME", "MagicCasterCompanion"))   # env: for tests
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
