"""Visual building blocks for the spell-book UI: colours, rendered buttons, tooltips, ttk styles."""
import re
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageTk

SERIF = "Palatino Linotype"
PARCH, PARCH_DARK = "#e8d9b5", "#b89a62"
FIELD = "#f3e8c8"
CARD, CARD_EDGE = "#efe3c1", "#c9b07a"
INK, INK_RGB = "#3a2412", (58, 36, 18)
RED, GOLD, LEATHER = "#7a1f1f", "#c9a227", "#2b1a10"
TEXT_ON_DARK = "#f3e6c4"

# ---------------------------------------------------------------- status colours


def state_color(state: str) -> str:
    """Dot colour for a connection status string."""
    s = (state or "").lower()
    if s == "connected":
        return "#3aa655"
    if s.startswith(("looking", "connecting", "waiting")):
        return "#e0a526"
    if s.startswith("failed"):
        return "#c0392b"
    return "#8c7b62"


def battery_percent(text: str):
    m = re.match(r"\s*(\d+)", text or "")
    return max(0, min(100, int(m.group(1)))) if m else None


def battery_color(pct) -> str:
    if pct is None:
        return "#8c7b62"
    return "#3aa655" if pct >= 40 else "#e0a526" if pct >= 15 else "#c0392b"


# ---------------------------------------------------------------- fonts and buttons
_font_cache = {}


def pil_font(size: int, bold: bool = False):
    key = (size, bold)
    if key not in _font_cache:
        for name in (("palab.ttf" if bold else "pala.ttf"), ("georgiab.ttf" if bold else "georgia.ttf")):
            try:
                _font_cache[key] = ImageFont.truetype(name, size)
                break
            except OSError:
                continue
        else:
            _font_cache[key] = ImageFont.load_default()
    return _font_cache[key]


_BTN = {"normal": ((112, 76, 50), (74, 47, 29)), "hover": ((136, 94, 62), (96, 62, 40)),
        "down": ((62, 39, 23), (90, 59, 38))}


def btn_pil(text: str, state: str = "normal", height: int = 34, size: int = 16, pad: int = 18) -> Image.Image:
    """A rounded, gradient, gold-rimmed button with centred text (RGBA)."""
    f = pil_font(size, True)
    bb = f.getbbox(text)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    w, h, s = tw + 2 * pad, height, 3
    top, bot = _BTN[state]
    grad = Image.linear_gradient("L").resize((w * s, h * s))
    fill = Image.composite(Image.new("RGB", (w * s, h * s), bot), Image.new("RGB", (w * s, h * s), top), grad)
    mask = Image.new("L", (w * s, h * s), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w * s - 1, h * s - 1), radius=9 * s, fill=255)
    im = Image.new("RGBA", (w * s, h * s), (0, 0, 0, 0))
    im.paste(fill, (0, 0), mask)
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, w * s - 1, h * s - 1), radius=9 * s, outline=(201, 162, 39, 255), width=s)
    im = im.resize((w, h), Image.LANCZOS)
    ImageDraw.Draw(im).text(((w - tw) // 2 - bb[0], (h - th) // 2 - bb[1] + (1 if state == "down" else 0)),
                            text, font=f, fill=(243, 230, 196, 255))
    return im


_btn_cache = {}


def btn_image(text: str, state: str = "normal"):
    key = (text, state)
    if key not in _btn_cache:
        _btn_cache[key] = ImageTk.PhotoImage(btn_pil(text, state))
    return _btn_cache[key]


def _shade(hexcolor: str, f: float):
    """Lighten (f>0) or darken (f<0) a #rrggbb colour; returns an (r, g, b) tuple."""
    c = [int(hexcolor[i:i + 2], 16) for i in (1, 3, 5)]
    return tuple(int(x + (255 - x) * f) if f >= 0 else int(x * (1 + f)) for x in c)


def tab_pil(label: str, color: str, state: str = "normal", w: int = 58, h: int = 92) -> Image.Image:
    """A bookmark tab: flush with the page on the left, rounded on the right, text running downward.

    state: 'normal', 'hover' or 'active' (active is brighter, wider, with a lighter gold rim).
    """
    s, r = 3, 14
    if state == "active":
        w += 10
    top, bot = {"normal": (_shade(color, .10), _shade(color, -.12)),
                "hover": (_shade(color, .22), color and _shade(color, 0)),
                "active": (_shade(color, .30), _shade(color, .06))}[state]
    grad = Image.linear_gradient("L").resize((w * s, h * s))
    fill = Image.composite(Image.new("RGB", (w * s, h * s), bot), Image.new("RGB", (w * s, h * s), top), grad)
    shape = (-r * s - 4, 0, w * s - 1, h * s - 1)      # left corners sit off-canvas, so the left edge is square
    mask = Image.new("L", (w * s, h * s), 0)
    ImageDraw.Draw(mask).rounded_rectangle(shape, radius=r * s, fill=255)
    im = Image.new("RGBA", (w * s, h * s), (0, 0, 0, 0))
    im.paste(fill, (0, 0), mask)
    rim = (240, 216, 120, 255) if state == "active" else (201, 162, 39, 255)
    ImageDraw.Draw(im).rounded_rectangle(shape, radius=r * s, outline=rim, width=(3 if state == "active" else 2) * s)
    im = im.resize((w, h), Image.LANCZOS)
    f = pil_font(15, True)
    bb = f.getbbox(label)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    t = Image.new("RGBA", (tw + 4, th + 6), (0, 0, 0, 0))
    ImageDraw.Draw(t).text((2 - bb[0], 3 - bb[1]), label, font=f, fill=(243, 230, 196, 255))
    t = t.rotate(270, expand=True)
    im.alpha_composite(t, ((w + 4 - t.width) // 2, (h - t.height) // 2))
    return im


class Tip:
    """Small hover tooltip."""

    def __init__(self, widget, text: str):
        self.w, self.text, self.tw, self.job = widget, text, None, None
        widget.bind("<Enter>", self._enter, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _enter(self, _e):
        self._hide()
        self.job = self.w.after(550, self._show)

    def _show(self):
        try:
            x, y = self.w.winfo_pointerx() + 14, self.w.winfo_pointery() + 18
            self.tw = tk.Toplevel(self.w)
            self.tw.overrideredirect(True)
            self.tw.attributes("-topmost", True)
            self.tw.geometry(f"+{x}+{y}")
            tk.Label(self.tw, text=self.text, bg="#2b1a10", fg=TEXT_ON_DARK, font=(SERIF, 10), padx=9, pady=5,
                     wraplength=260, justify="left", bd=1, relief="solid").pack()
        except tk.TclError:
            self.tw = None

    def _hide(self, _e=None):
        if self.job:
            try:
                self.w.after_cancel(self.job)
            except tk.TclError:
                pass
            self.job = None
        if self.tw is not None:
            try:
                self.tw.destroy()
            except tk.TclError:
                pass
            self.tw = None


class RoundButton(tk.Label):
    """Rendered rounded button with hover and pressed states."""

    def __init__(self, master, text, command, tip=None, bg=PARCH):
        self.cmd = command
        self.imgs = {s: btn_image(text, s) for s in ("normal", "hover", "down")}
        super().__init__(master, image=self.imgs["normal"], bg=bg, bd=0, cursor="hand2", takefocus=1)
        self.bind("<Enter>", lambda _e: self._set("hover"))
        self.bind("<Leave>", lambda _e: self._set("normal"))
        self.bind("<ButtonPress-1>", lambda _e: self._set("down"))
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Return>", lambda _e: self.cmd())
        self.bind("<space>", lambda _e: self.cmd())
        if tip:
            Tip(self, tip)

    def _set(self, state):
        try:
            self.configure(image=self.imgs[state])
        except tk.TclError:
            pass

    def _release(self, e):
        inside = 0 <= e.x < self.winfo_width() and 0 <= e.y < self.winfo_height()
        self._set("hover" if inside else "normal")
        if inside:
            self.cmd()


# ---------------------------------------------------------------- page, cover and ink art


def make_page(w, h, spine_on_right):
    """Procedural parchment: flat centre, darker edges, a narrow shadow toward the spine."""
    base = Image.new("RGB", (w, h), PARCH)
    edge = Image.new("RGB", (w, h), PARCH_DARK)
    rad = Image.radial_gradient("L").resize((w, h)).point(lambda v: max(0, v - 175) * 3)
    page = Image.composite(edge, base, rad)
    if spine_on_right is None:      # one wide open spread with no spine
        return page
    grad = Image.linear_gradient("L").rotate(90 if spine_on_right else -90).resize((w, h))
    shadow = grad.point(lambda v: max(0, v - 235) * 4)
    return Image.composite(Image.new("RGB", (w, h), (90, 60, 30)), page, shadow)


def make_leather(w, h, book):
    """Leather desk with a soft shadow under the book. book = (x0, y0, x1, y1)."""
    base = Image.new("RGB", (w, h), (46, 28, 17))
    im = Image.blend(base, Image.effect_noise((w, h), 22).convert("RGB"), 0.10)
    x0, y0, x1, y1 = book
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rounded_rectangle((x0 - 2, y0 + 8, x1 + 26, y1 + 24), radius=20, fill=190)
    m = m.filter(ImageFilter.GaussianBlur(16))
    return Image.composite(Image.new("RGB", (w, h), (8, 4, 2)), im, m)


_ink_cache = {}


def ink_image(path, width):
    key = (path, width)
    if key not in _ink_cache:
        im = Image.open(path).convert("RGBA")
        mask = ImageChops.multiply(im.getchannel("A"), im.convert("L")).filter(ImageFilter.MaxFilter(3))
        ink = Image.new("RGBA", im.size, INK_RGB + (255,))
        ink.putalpha(mask)
        h = int(im.height * width / im.width)
        _ink_cache[key] = ImageTk.PhotoImage(ink.resize((width, h), Image.LANCZOS))
    return _ink_cache[key]


# ---------------------------------------------------------------- window chrome and ttk styles


def style_titlebar(win):
    """Windows 11: dark title bar in the leather colour. Silently does nothing elsewhere."""
    try:
        import ctypes
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())

        def attr(a, v):
            c = ctypes.c_int(v)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, a, ctypes.byref(c), ctypes.sizeof(c))
        attr(20, 1)                                   # dark mode
        attr(35, (16 << 16) | (26 << 8) | 43)         # caption colour (BGR)
        attr(36, (181 << 16) | (217 << 8) | 232)      # caption text
        attr(34, (39 << 16) | (162 << 8) | 201)       # border
    except Exception:
        pass


def apply_styles(root):
    st = ttk.Style(root)
    st.theme_use("clam")
    st.configure("Book.TCombobox", fieldbackground=FIELD, background=PARCH_DARK, foreground=INK,
                 arrowcolor=INK, bordercolor=PARCH_DARK, selectbackground=FIELD, selectforeground=INK)
    st.map("Book.TCombobox", fieldbackground=[("readonly", FIELD)], foreground=[("readonly", INK)],
           selectbackground=[("readonly", FIELD)], selectforeground=[("readonly", INK)])
    st.configure("Book.Vertical.TScrollbar", background=PARCH_DARK, troughcolor=PARCH, bordercolor=PARCH,
                 lightcolor=PARCH_DARK, darkcolor=PARCH_DARK, arrowcolor=INK, relief="flat")
    st.map("Book.Vertical.TScrollbar", background=[("active", "#a3844c")])
    st.configure("Book.Horizontal.TScale", background=PARCH_DARK, troughcolor="#d8c79a", bordercolor=PARCH_DARK,
                 lightcolor=PARCH_DARK, darkcolor=PARCH_DARK)
    st.configure("Book.TCheckbutton", background=PARCH, foreground=INK, font=(SERIF, 11), focuscolor=PARCH,
                 indicatorbackground=FIELD, indicatorforeground=RED, upperbordercolor=PARCH_DARK,
                 lowerbordercolor=PARCH_DARK)
    st.map("Book.TCheckbutton", background=[("active", PARCH)], indicatorbackground=[("pressed", "#e6d6aa")])
    st.configure("Card.TCheckbutton", background=CARD, foreground=INK, font=(SERIF, 11), focuscolor=CARD,
                 indicatorbackground=FIELD, indicatorforeground=RED, upperbordercolor=PARCH_DARK,
                 lowerbordercolor=PARCH_DARK)
    st.map("Card.TCheckbutton", background=[("active", CARD)], indicatorbackground=[("pressed", "#e6d6aa")])
    root.option_add("*TCombobox*Listbox.background", FIELD)
    root.option_add("*TCombobox*Listbox.foreground", INK)
    root.option_add("*TCombobox*Listbox.font", (SERIF, 11))
