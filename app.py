"""Magic Caster Companion: a spell-book desktop app for the Magic Caster Wand and Box."""
import asyncio
import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import colorchooser, messagebox, ttk

from PIL import Image, ImageChops, ImageFilter, ImageTk

import gestures
from mcwand import Box, LED_GROUPS, Wand, scan
from spells_data import (CAST_STEPS, DESCRIPTIONS, SPELLS, diagram_paths, pretty,
                         spell_effect)

SERIF = "Palatino Linotype"
PARCH, PARCH_DARK = "#e8d9b5", "#b89a62"
INK, INK_RGB = "#3a2412", (58, 36, 18)
RED, GOLD, LEATHER = "#7a1f1f", "#c9a227", "#2b1a10"
W, H = 1000, 700
BX0, BX1, BY0, BY1 = 30, 930, 25, 675
SPINE = (BX0 + BX1) // 2
LX, RX = BX0 + 28, SPINE + 28          # left/right page content origins
PAGE_W = SPINE - BX0 - 56              # usable content width of a page

TABS = [("devices", "Devices", "#8a2323"), ("spells", "Spells", "#2f6b3a"),
        ("cast", "Cast", "#243f73"), ("lights", "Lights", "#b8862b"),
        ("notes", "Notes", "#5a2f6b")]


def make_page(w, h, spine_on_right):
    """Procedural parchment: flat centre, darker edges, shadow toward the spine."""
    base = Image.new("RGB", (w, h), PARCH)
    edge = Image.new("RGB", (w, h), PARCH_DARK)
    rad = Image.radial_gradient("L").resize((w, h)).point(lambda v: max(0, v - 175) * 3)
    page = Image.composite(edge, base, rad)
    grad = Image.linear_gradient("L").rotate(90 if spine_on_right else -90).resize((w, h))
    shadow = grad.point(lambda v: max(0, v - 190) * 3 // 2)
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
        self.title("Magic Caster Companion - Spell Book")
        self.geometry(f"{W}x{H}")
        self.resizable(False, False)
        self.configure(bg=LEATHER)
        self.q: "queue.Queue" = queue.Queue()
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()

        self.wand: Wand | None = None
        self.box: Box | None = None
        self.found = {}
        self.color = (255, 200, 80)
        self.sel_spell = "lumos" if "lumos" in SPELLS else SPELLS[0]
        self.spin = 0.0
        self.meter = None
        self.log_lines: list[str] = []
        self.logbox: tk.Text | None = None
        self.store = gestures.GestureStore(
            os.path.join(os.environ.get("APPDATA", "."), "MagicCasterCompanion", "gestures.json"))
        self.seg = gestures.Segmenter()
        self.recording: str | None = None
        self.page = None
        self.busy = False
        self.widgets: list[tk.Widget] = []
        self.vars = {k: tk.StringVar(value="-") for k in
                     ("w_state", "w_info", "w_batt", "b_state", "b_info", "b_batt", "b_lid", "b_wand", "b_usb")}
        self.vars["w_state"].set("not connected")
        self.vars["b_state"].set("not connected")
        self.g_status = tk.StringVar(value="Connect your wand, then record or cast.")
        self.cast_mode = tk.BooleanVar(value=True)
        self.status_item = None
        self.g_status.trace_add("write", self._status_changed)

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Book.TCombobox", fieldbackground="#f3e8c8", background=PARCH_DARK,
                        foreground=INK, arrowcolor=INK, bordercolor=PARCH_DARK, selectbackground="#f3e8c8",
                        selectforeground=INK)
        style.map("Book.TCombobox", fieldbackground=[("readonly", "#f3e8c8")],
                  foreground=[("readonly", INK)], selectbackground=[("readonly", "#f3e8c8")],
                  selectforeground=[("readonly", INK)])
        self.option_add("*TCombobox*Listbox.background", "#f3e8c8")
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
        self._draw_tabs()

        self.after(50, self._poll)
        self.after(90, self._tick)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.show("devices", animate=False)

    # ---------- plumbing ----------
    def run(self, coro, done=None, failed=None):
        fut = asyncio.run_coroutine_threadsafe(coro, self.loop)

        def cb(f):
            exc = f.exception()
            if exc:
                self.ui(lambda: self.log(f"Error: {type(exc).__name__}: {exc}"))
                if failed:
                    self.ui(failed)
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

    def button(self, label, cmd, x, y, width=None):
        b = tk.Button(self, text=label, command=cmd, bg="#5b3a24", fg="#f3e6c4", relief="flat",
                      activebackground="#7a5236", activeforeground="#fff7dc", cursor="hand2",
                      font=(SERIF, 11, "bold"), padx=12, pady=5, bd=0, width=width or 0)
        return self.put(b, x, y)

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
        self.button("Connect wand", self.connect_wand, LX, BY0 + 300)
        self.button("Disconnect", self.disconnect_wand, LX + 160, BY0 + 300)
        self.rule(LX, BY0 + 370)
        self.button("Scan for wand and base", self.do_scan, LX, BY0 + 390)
        self.text(LX, BY0 + 440, "Wake the wand first: lift it from the base or give it a wave. Scanning takes "
                  "eight seconds.", 10, italic=True)

        self.text(RX, BY0 + 30, "The Base", 20, bold=True)
        self.text(RX, BY0 + 62, "Magic Caster Box", 11, italic=True)
        rows = [("b_state", "Status"), ("b_info", "Firmware"), ("b_batt", "Battery"), ("b_lid", "Lid"),
                ("b_wand", "Wand in base"), ("b_usb", "USB power")]
        for i, (k, name) in enumerate(rows):
            self.text(RX, BY0 + 110 + i * 32, name, 12, italic=True, width=130)
            self.label(self.vars[k], RX + 140, BY0 + 108 + i * 32, 12, width=240)
        self.button("Connect base", self.connect_box, RX, BY0 + 330)
        self.button("Disconnect", self.disconnect_box, RX + 160, BY0 + 330)

    # ---------- page: spells ----------
    def _page_spells(self):
        self.text(LX, BY0 + 20, "Index of Spells", 24, bold=True, italic=True, color=RED)
        self.text(LX, BY0 + 62, "Choose a spell to see how it is cast.", 10, italic=True)
        self.spell_filter = tk.StringVar()
        ent = tk.Entry(self, textvariable=self.spell_filter, bg="#f3e8c8", fg=INK, relief="flat",
                       font=(SERIF, 12), highlightthickness=1, highlightbackground=PARCH_DARK, width=34)
        self.put(ent, LX, BY0 + 90)
        self.spell_filter.trace_add("write", lambda *_: self._fill_spells())
        frame = tk.Frame(self, bg=PARCH)
        sb = tk.Scrollbar(frame)
        self.spell_list = tk.Listbox(frame, bg=PARCH, fg=INK, font=(SERIF, 12), bd=0, highlightthickness=0,
                                     selectbackground="#c9a96a", selectforeground=INK, activestyle="none",
                                     height=21, width=33, yscrollcommand=sb.set)
        sb.config(command=self.spell_list.yview)
        self.spell_list.pack(side="left")
        sb.pack(side="right", fill="y")
        self.put(frame, LX, BY0 + 128)
        self.spell_list.bind("<<ListboxSelect>>", self._spell_selected)
        self._fill_spells()
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
        self.text(x, BY0 + 24, pretty(s), 22, bold=True, italic=True, color=RED, width=PAGE_W, tags=("page", "detail"))
        desc = DESCRIPTIONS.get(s, "A spell from the Magic Caster Wand's repertoire.")
        self.text(x, BY0 + 100, desc, 11, italic=True, width=PAGE_W, tags=("page", "detail"))
        paths = diagram_paths(s)
        if paths:
            iw = 190 if len(paths) == 1 else 120
            self._detail_imgs = [ink_image(p, iw) for p in paths]
            for i, im in enumerate(self._detail_imgs):
                self.cv.create_image(x + i * (iw + 10), BY0 + 150, image=im, anchor="nw", tags=("page", "detail"))
            if len(paths) > 1:
                self.text(x, BY0 + 150 + self._detail_imgs[0].height() + 4, "Two ways to cast it", 9, italic=True,
                          tags=("page", "detail"))
        else:
            self.text(x, BY0 + 160, "No diagram is available for this spell yet.\nRecord your own motion on the "
                      "Cast page.", 10, italic=True, tags=("page", "detail"))
        tx = x + 210 if paths and len(paths) == 1 else x
        ty = BY0 + 150 if paths and len(paths) == 1 else BY0 + 340
        tw = PAGE_W - 210 if paths and len(paths) == 1 else PAGE_W
        self.text(tx, ty, "How to cast", 13, bold=True, tags=("page", "detail"), width=tw)
        self.text(tx, ty + 26, CAST_STEPS, 10, tags=("page", "detail"), width=tw)
        n = len(self.store.data.get(s, []))
        self.text(x, BY0 + 480, f"Your recorded casts of this spell: {n}", 10, italic=True, tags=("page", "detail"))
        if not hasattr(self, "_spell_btns") or not self._spell_btns_alive():
            self._spell_btns = [self.button("Play effect", self.play_selected, x, BY0 + 515),
                                self.button("Teach this spell", lambda: self.show("cast"), x + 150, BY0 + 515)]

    def _spell_btns_alive(self):
        try:
            return all(b.winfo_exists() for b in self._spell_btns)
        except tk.TclError:
            return False

    # ---------- page: cast ----------
    def _page_cast(self):
        self.text(LX, BY0 + 20, "Teach & Cast", 24, bold=True, italic=True, color=RED)
        self.text(LX, BY0 + 62, "The wand reports its motion, and the book compares each swish with the casts "
                  "you have recorded. Record three or more casts of a spell, then turn on casting.", 10, italic=True)
        self.text(LX, BY0 + 140, "Spell to teach", 12, bold=True)
        self.cast_combo = ttk.Combobox(self, style="Book.TCombobox", values=[pretty(s) for s in SPELLS],
                                       state="readonly", width=30, font=(SERIF, 11))
        self.cast_combo.set(pretty(self.sel_spell))
        self.cast_combo.bind("<<ComboboxSelected>>", self._cast_pick)
        self.put(self.cast_combo, LX, BY0 + 168)
        self.button("Record a cast", self.arm_record, LX, BY0 + 208)
        cb = tk.Checkbutton(self, text="Recognise my casts and play the effect", variable=self.cast_mode,
                            bg=PARCH, fg=INK, activebackground=PARCH, selectcolor="#f3e8c8",
                            font=(SERIF, 11), anchor="w")
        self.put(cb, LX, BY0 + 258)
        self.rule(LX, BY0 + 300)
        self.text(LX, BY0 + 312, "Spells you have taught", 13, bold=True)
        self.g_list = tk.Listbox(self, bg=PARCH, fg=INK, font=(SERIF, 12), bd=0, highlightthickness=0,
                                 selectbackground="#c9a96a", selectforeground=INK, activestyle="none",
                                 height=9, width=33)
        self.put(self.g_list, LX, BY0 + 342)
        self._fill_gestures()
        self.button("Forget selected", self.delete_gesture, LX, BY0 + 520)

        self.text(RX, BY0 + 24, "The Last Cast", 20, bold=True)
        self.status_item = self.text(RX, BY0 + 64, self.g_status.get(), 15, bold=True, italic=True, color=RED,
                                     width=PAGE_W - 20)
        self.text(RX, BY0 + 150, "Motion", 10, italic=True)
        self.meter = tk.Canvas(self, width=PAGE_W - 60, height=14, bg="#f3e8c8", highlightthickness=1,
                               highlightbackground=PARCH_DARK)
        self.put(self.meter, RX + 60, BY0 + 150)
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
        self.text(RX, BY0 + 190, f"Trace: {pretty(self.sel_spell)}", 13, bold=True, tags=("page", "cdiag"))
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
        self.swatch = tk.Label(self, width=14, height=3, bg="#%02x%02x%02x" % self.color, relief="sunken")
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
                      bg=PARCH, fg=INK, troughcolor="#f3e8c8", highlightthickness=0, font=(SERIF, 10),
                      label="Length (milliseconds)")
        self.put(sc, RX, BY0 + 100)
        self.button("Buzz", lambda: self.wand_call("buzz", int(self.buzz_ms.get())), RX, BY0 + 190)

    # ---------- page: notes ----------
    def _page_notes(self):
        self.text(LX, BY0 + 20, "Notes", 24, bold=True, italic=True, color=RED)
        self.text(LX, BY0 + 62, "What the book has been up to.", 10, italic=True)
        self.logbox = tk.Text(self, width=40, height=26, bg="#f3e8c8", fg=INK, font=(SERIF, 10), relief="flat",
                              wrap="word", state="disabled")
        self.put(self.logbox, LX, BY0 + 92)
        self.logbox.configure(state="normal")
        self.logbox.insert("end", "\n".join(self.log_lines) + ("\n" if self.log_lines else ""))
        self.logbox.configure(state="disabled")
        self.logbox.see("end")

        self.text(RX, BY0 + 24, "About", 20, bold=True)
        self.text(RX, BY0 + 64,
                  "Magic Caster Companion is an unofficial, community-made replacement for the discontinued "
                  "app. It is not affiliated with or endorsed by the makers of the Magic Caster Wand.\n\n"
                  "The protocol was learned by probing real devices and from the MIT-licensed "
                  "hass-magic-caster-wand project by eigger, whose spell diagrams are also used here.\n\n"
                  "Your recorded casts are kept in your user profile, in the MagicCasterCompanion folder.",
                  11)

    # ---------- device actions ----------
    def do_scan(self):
        self.log("Scanning (8s)...")
        self.run(scan(8), self._scanned)

    def _scanned(self, found):
        self.found = found
        self.log("Found: " + (", ".join(f"{v['name']} ({v['rssi']} dBm)" for v in found.values()) or "nothing"))
        if not found:
            self.log("Wake the wand or base (lift the wand from the base, give it a wave) and scan again.")

    def _need_found(self, kind):
        if kind not in self.found:
            self.log(f"No {kind} found yet - press Scan first.")
            return None
        return self.found[kind]["address"]

    def connect_wand(self):
        addr = self._need_found("wand")
        if not addr or (self.wand and self.wand.connected):
            return
        self.vars["w_state"].set("connecting...")
        w = Wand(addr)
        w.on_imu = self._on_imu
        w.on_touch = lambda m: self.ui(lambda: self.log(f"Wand touch sensors: {m:04b}"))
        w.on_spell = lambda n: self.ui(lambda: self.log(f"Wand reported spell: {n}"))
        w.on_disconnect = lambda: self.ui(self._wand_lost)

        async def go():
            await w.connect()
            await w.imu_start()
            return w

        def ok(w):
            self.wand = w
            self.vars["w_state"].set("connected")
            self.vars["w_info"].set(f"{w.model} (fw {w.firmware})")
            self.vars["w_batt"].set(f"{w.battery}%")
            self.log("Wand connected, motion streaming.")
        self.run(go(), ok, lambda: self.vars["w_state"].set("failed - wake the wand and retry"))

    def _wand_lost(self):
        self.vars["w_state"].set("disconnected")
        self.log("Wand disconnected.")

    def disconnect_wand(self):
        if self.wand:
            self.run(self.wand.disconnect())

    def connect_box(self):
        addr = self._need_found("box")
        if not addr or (self.box and self.box.connected):
            return
        self.vars["b_state"].set("connecting...")
        b = Box(addr)
        b.on_lid = lambda x: self.ui(lambda: self.vars["b_lid"].set("removed" if x else "on"))
        b.on_wand = lambda x: self.ui(lambda: self.vars["b_wand"].set("yes" if x else "no"))
        b.on_charge = lambda x: self.ui(lambda: self.vars["b_usb"].set("plugged in" if x else "unplugged"))
        b.on_disconnect = lambda: self.ui(lambda: (self.vars["b_state"].set("disconnected"),
                                                   self.log("Base disconnected.")))

        def ok(_):
            self.box = b
            self.vars["b_state"].set("connected")
            self.vars["b_info"].set(b.firmware or "-")
            self.vars["b_batt"].set(f"{b.battery}%")
            self.log("Base connected.")
        self.run(b.connect(), ok, lambda: self.vars["b_state"].set("failed - retry"))

    def disconnect_box(self):
        if self.box:
            self.run(self.box.disconnect())

    def wand_call(self, method, *args):
        if not (self.wand and self.wand.connected):
            self.log("Connect the wand first.")
            return
        self.run(getattr(self.wand, method)(*args))

    # ---------- lights ----------
    def pick_color(self):
        c = colorchooser.askcolor(color="#%02x%02x%02x" % self.color)
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
        self.wand_call("play", spell_effect(self.sel_spell))

    # ---------- gestures ----------
    def arm_record(self):
        if not (self.wand and self.wand.connected):
            self.log("Connect the wand first.")
            self.g_status.set("Connect your wand on the Devices page first.")
            return
        self.recording = self.sel_spell
        self.g_status.set(f"Recording {pretty(self.recording)}: make the motion now...")

    def _on_imu(self, samples):  # BLE thread
        import math
        s = samples[-1]
        self.spin = math.sqrt(sum(g * g for g in s.gyro))
        for smp in samples:
            g = self.seg.feed(smp)
            if g:
                self.ui(lambda g=g: self._gesture_done(g))

    def _gesture_done(self, g):
        if self.recording:
            name, self.recording = self.recording, None
            self.store.add(name, g)
            n = len(self.store.data[name])
            self.g_status.set(f"Saved cast {n} of {pretty(name)}. Record more, or just cast it.")
            self.log(f"Recorded {pretty(name)} cast {n} ({len(g)} samples)")
            if self.page == "cast":
                self._fill_gestures()
        elif self.cast_mode.get():
            if not self.store.data:
                self.g_status.set("The book knows no spells yet. Teach it one first.")
                return
            best, dist, _ = self.store.match(g)
            if best:
                self.g_status.set(f"{pretty(best)}!   (distance {dist:.2f})")
                self.log(f"Cast {pretty(best)} d={dist:.2f}")
                self.wand_call("play", spell_effect(best))
            else:
                self.g_status.set(f"Nothing recognised (closest {dist:.2f}). Try again, or teach more casts.")

    def delete_gesture(self):
        sel = self.g_list.curselection()
        if sel:
            name = sorted(self.store.data)[sel[0]]
            if messagebox.askyesno("Forget spell", f"Forget all casts of {pretty(name)}?"):
                self.store.remove(name)
                self._fill_gestures()

    def _close(self):
        for d in (self.wand, self.box):
            if d and d.connected:
                try:
                    asyncio.run_coroutine_threadsafe(d.disconnect(), self.loop).result(3)
                except Exception:
                    pass
        self.destroy()


def _screenshots(app: App, outdir: str):
    from PIL import ImageGrab
    os.makedirs(outdir, exist_ok=True)
    keys = [k for k, _, _ in TABS]

    def grab(i=0):
        if i >= len(keys):
            app.destroy()
            return
        app.page = keys[i]
        app._mark_tab(keys[i])
        app.clear()
        app._build(keys[i])
        if keys[i] == "spells":
            app.sel_spell = "expelliarmus"
            app._fill_spells()
            app._draw_spell_detail()
        app.update()
        app.after(400, lambda: (ImageGrab.grab(bbox=(app.winfo_rootx(), app.winfo_rooty(),
                                                     app.winfo_rootx() + W, app.winfo_rooty() + H)
                                               ).save(os.path.join(outdir, f"{keys[i]}.png")), grab(i + 1)))
    app.after(800, grab)


if __name__ == "__main__":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    a = App()
    if len(sys.argv) > 2 and sys.argv[1] == "--shots":
        _screenshots(a, sys.argv[2])
    a.mainloop()
