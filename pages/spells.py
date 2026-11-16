"""The Spells page and its actions dialog."""
from common import (
    ACTION_TYPES, BY0, CAST_STEPS, DESCRIPTIONS, FIELD, GOLD, HINTS, INK, LX, PAGE_W, PARCH,
    PARCH_DARK, RED, RX, SERIF, SPELLS, STATE_TEXT, Tip, UNLOCK_AT, colorchooser, diagram_paths,
    filedialog, hexcolor, ink_image, messagebox, pretty, run_action, spell_color, spell_effect,
    style_titlebar, tk, ttk, validate,
)


class SpellsPage:
    """The Spells page and its actions dialog."""

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
