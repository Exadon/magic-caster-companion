"""The Lights page."""
from common import (
    BY0, LED_GROUPS, LX, PAGE_W, RED, RX, SERIF, STYLES, STYLE_LABELS, colorchooser, hexcolor, tk,
    ttk,
)


class LightsPage:
    """The Lights page."""

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
