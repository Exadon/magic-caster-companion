"""The Notes page."""
from common import (
    BY0, DATA_DIR, FIELD, INK, LX, PARCH_DARK, RED, RX, SERIF, __version__, os, tk,
)


class NotesPage:
    """The Notes page."""

    def _page_notes(self):
        self.text(LX, BY0 + 20, "Notes", 24, bold=True, italic=True, color=RED)
        self.text(LX, BY0 + 62, "What the book has been up to.", 10, italic=True)
        self.logbox = tk.Text(self, width=40, height=26, bg=FIELD, fg=INK, font=(SERIF, 10), relief="flat",
                              wrap="word", state="disabled", padx=8, pady=6, highlightthickness=1,
                              highlightbackground=PARCH_DARK)
        self.put(self.logbox, LX, BY0 + 92)
        self.logbox.configure(state="normal")
        self.logbox.insert("end", "\n".join(self.log_lines) + ("\n" if self.log_lines else ""))
        self.logbox.configure(state="disabled")
        self.logbox.see("end")

        self.text(RX, BY0 + 24, "About", 20, bold=True)
        self.text(RX, BY0 + 56, f"Version {__version__}", 10, italic=True)
        self.ornament(RX, BY0 + 84)
        self.text(RX, BY0 + 100,
                  "Magic Caster Companion is an unofficial, community-made replacement for the discontinued "
                  "app. It is not affiliated with or endorsed by the makers of the Magic Caster Wand.\n\n"
                  "The protocol was learned by probing real devices and from the MIT-licensed "
                  "hass-magic-caster-wand project by eigger, whose spell diagrams are also used here.\n\n"
                  "Your recorded casts, colours and actions are kept in your user profile.\n\n"
                  "Shortcuts: Ctrl+1 to Ctrl+6 turn to each page.", 11)
        self.button("Open data folder", lambda: os.startfile(DATA_DIR) if os.path.isdir(DATA_DIR) else None,
                    RX, BY0 + 500, tip="Where your casts, colours and settings are stored")
