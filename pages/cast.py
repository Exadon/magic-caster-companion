"""The Cast page: free casting on a full two-page spread."""
from common import (
    BX0, BY0, DESCRIPTIONS, FIELD, MUTED, PARCH_DARK, RED, SERIF, SPELLS, SX0, SX1, Tip, VOICE_MODES,
    diagram_paths, ink_image, pretty, tk, ttk,
)


class CastPage:
    """The Cast page: free casting on a full two-page spread."""

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
        self.text(SX0, BY0 + 338, (f"Named by the wand: {heard}  (streaming on {int(ns.get('streaming_on', 0))}, "
                                   f"off {int(ns.get('streaming_off', 0))})"
                                   if heard else "The wand has not named a spell yet."),
                  9, italic=True, color=MUTED, width=270)
        self.card(SX0 + 280, BY0 + 90, SX1, BY0 + 330)
        self._draw_cast_live()
        self.ornament(SX0, BY0 + 352, SX1 - SX0)

        self.text(SX0, BY0 + 368, "Recent casts", 14, bold=True)
        self._draw_history()
        self.rule(SX0, BY0 + 478, 400)
        self._voice_section(SX0, BY0 + 490)
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

    def _voice_section(self, x, y):
        """Opt-in voice incantations: say a spell's name (optionally with a swish of the wand) to cast it."""
        self.text(x, y, "Voice incantations", 14, bold=True)
        labels = [lab for _, lab in VOICE_MODES]
        combo = ttk.Combobox(self, style="Book.TCombobox", values=labels, state="readonly", width=28,
                             font=(SERIF, 11))
        combo.set(dict(VOICE_MODES).get(self.settings.get("voice_mode"), labels[0]))
        combo.bind("<<ComboboxSelected>>",
                   lambda _e: self._voice_set_mode(VOICE_MODES[labels.index(combo.get())][0]))
        self.put(combo, x, y + 28)
        self.voice_combo = combo
        Tip(combo, "Cast by saying a spell's name. With a swish, any movement of the wand also has to happen, which "
                   "stops accidental casts. This uses your microphone, and only after you turn it on.")
        self.slider(x, y + 60, "Confidence needed", float(self.settings.get("voice_confidence")), 0.4, 0.95, 0.05,
                    200, lambda v: f"{v:.2f}",
                    on_change=lambda v: self.settings.data.__setitem__("voice_confidence", round(v, 2)),
                    on_release=self.settings.save)
        self.voice_note_item = self.text(x, y + 112, self._voice_note(), 10, italic=True, color=MUTED, width=410)

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
            elif lc.get("via") == "voice":
                self.text(x0 + 24, y0 + 168, f"✦ Heard you say \"{lc['heard']}\"  ({lc['conf']:.2f})", 11, bold=True,
                          color="#2f6b3a", width=330, tags=tg)
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
        for i, (clock, name, dist, src) in enumerate(reversed(self.cast_log[-3:])):
            y = BY0 + 400 + i * 24
            if name:
                self.text(SX0, y, f"{clock}   ✦ {pretty(name)}", 12, bold=(i == 0), tags=tg, width=300)
            else:
                self.text(SX0, y, f"{clock}   not recognised", 12, italic=True, color=MUTED, tags=tg, width=300)
            self.text(SX0 + 380, y + 2, src if src in ("wand", "both", "voice") else f"{dist:.2f}", 10, color=MUTED,
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
