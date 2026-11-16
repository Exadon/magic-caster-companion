"""System tray, running in the background, and closing the window."""
from common import (
    INK, Image, PARCH, RED, SERIF, Tray, asyncio, os, resource_path, set_autostart, style_titlebar,
    tk, ttk,
)


class ShellMixin:
    """System tray, running in the background, and closing the window."""

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
