"""The Teach page."""
from common import (
    BY0, FIELD, INK, LX, MARK, MUTED, PAGE_W, PARCH, PARCH_DARK, RED, RX, SERIF, SPELLS,
    STATE_TEXT, UNLOCK_AT, diagram_paths, ink_image, pretty, tk, ttk,
)


class TeachPage:
    """The Teach page."""

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
