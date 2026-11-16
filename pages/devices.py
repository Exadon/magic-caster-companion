"""The Devices page."""
from common import (
    BY0, CARD, FIELD, Image, ImageTk, LX, MUTED, PAGE_W, RED, RX, __version__, os, resource_path,
)


class DevicesPage:
    """The Devices page."""

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
