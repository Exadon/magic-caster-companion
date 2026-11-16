"""Voice incantations in the app: opt-in listening for spell names, with or without a swish of the wand."""
from common import (
    H, PARCH, RED, SERIF, SPELLS, VOICE_MODES, VOICE_WINDOW_S, VoiceListener, messagebox, os, phrase_map, pretty,
    style_titlebar, time, tk, voice_available,
)


class VoiceMixin:
    """Listens through Windows' offline speech recognition. Nothing is recorded or sent anywhere."""

    def _voice_init(self):
        self.voice = None
        self.voice_state = "off"            # off / starting / listening / error / stopped
        self.voice_detail = ""
        self.voice_last = None              # (phrase, confidence) most recently heard
        self.voice_combo = None
        self.voice_note_item = None
        self._voice_pending = None          # (key, phrase, confidence, time) heard but waiting for a swish
        self._last_swish = 0.0
        self._voice_restarts = 0
        self._voice_n = 0                   # how many spells the recogniser is listening for
        y = H - 24
        self.voice_light = (self.cv.create_oval(36, y - 6, 48, y + 6, fill="#d23a3a", outline="#1a0f08",
                                                state="hidden"),
                            self.cv.create_text(56, y, anchor="w", text="Listening", fill="#e8a0a0",
                                                font=(SERIF, 12, "italic"), state="hidden"))
        if self.settings.get("voice_mode") != "off" and not os.environ.get("MCC_NO_VOICE"):
            self.after(2500, self._voice_start)

    # ---------- what to listen for ----------
    def _voice_keys(self):
        """Spells the recogniser is told about. Fewer words means more accurate recognition."""
        if self.settings.get("voice_scope") == "all":
            return list(SPELLS)
        used = set(self.store.data) | set(self.settings.get("wand_known")) | set(self.settings.data["actions"])
        keys = [s for s in SPELLS if s in used]
        return keys if len(keys) >= 3 else list(SPELLS)       # too few to be accurate: listen for all of them

    # ---------- start / stop ----------
    def _voice_start(self):
        self._voice_stop()
        phrases = phrase_map(self._voice_keys())
        holder = {}
        listener = VoiceListener(
            phrases,
            on_heard=lambda k, p, c: self.ui(lambda: self._voice_heard(k, p, c)),
            on_state=lambda s, d: self.ui(lambda: self._voice_state_changed(holder.get("l"), s, d)))
        holder["l"] = listener
        self.voice = listener
        self._voice_n = len({k for k in phrases.values()})
        listener.start()

    def _voice_stop(self):
        v, self.voice = self.voice, None
        self._voice_pending = None
        if v:
            v.stop()
        self.voice_state = "off"
        self._voice_refresh()

    def _voice_state_changed(self, listener, state, detail):
        if listener is not self.voice or listener is None:
            return                                           # an old listener: ignore
        self.voice_state, self.voice_detail = state, detail
        if state == "error":
            self.log(f"Voice listening problem: {detail}")
            self.voice = None
        elif state == "listening":
            self._voice_restarts = 0
            self.log(f"Listening for {self._voice_n} spells by voice.")
        elif state == "stopped" and self.settings.get("voice_mode") != "off":
            if self._voice_restarts < 3:                     # the recogniser process ended unexpectedly: try again
                self._voice_restarts += 1
                self.after(3000, lambda: self._voice_start() if self.settings.get("voice_mode") != "off" else None)
        self._voice_refresh()

    def _voice_refresh(self):
        listening = self.voice_state == "listening"
        for item in self.voice_light:
            try:
                self.cv.itemconfig(item, state="normal" if listening else "hidden")
            except tk.TclError:
                pass
        if self.voice_note_item is not None and self.page == "cast":
            try:
                self.cv.itemconfig(self.voice_note_item, text=self._voice_note())
            except tk.TclError:
                self.voice_note_item = None

    def _voice_note(self):
        mode = self.settings.get("voice_mode")
        if mode == "off":
            return "Off. Turn it on to cast by saying a spell's name."
        if self.voice_state == "error":
            return self.voice_detail
        if self.voice_state == "starting":
            return "Starting speech recognition..."
        how = "Say a spell, then swish the wand." if mode == "motion" else "Just say a spell."
        note = f"Listening for {getattr(self, '_voice_n', 0)} spells. {how}"
        if self._voice_pending:
            note = f"Heard {pretty(self._voice_pending[0])}. Now swish the wand!"
        elif self.voice_last:
            note += f"  Last heard: {self.voice_last[0]} ({self.voice_last[1]:.2f})"
        return note

    # ---------- turning it on ----------
    def _voice_set_mode(self, mode):
        if mode == self.settings.get("voice_mode"):
            return
        if mode == "off":
            self.settings.set("voice_mode", "off")
            self._voice_stop()
            self.log("Voice listening turned off.")
            return
        if not voice_available():
            messagebox.showinfo("Voice incantations", "Windows speech recognition (English) is not installed on "
                                "this PC, so voice casting isn't available.")
            self._voice_sync_combo()
            return
        if not self.settings.get("voice_consented") and not self._voice_consent():
            self._voice_sync_combo()
            return
        self.settings.set("voice_mode", mode)
        self._voice_start()

    def _voice_sync_combo(self):
        if self.voice_combo is not None:
            try:
                labels = dict(VOICE_MODES)
                self.voice_combo.set(labels[self.settings.get("voice_mode")])
            except tk.TclError:
                self.voice_combo = None

    def _voice_consent(self) -> bool:
        """Ask once before the microphone is used. Returns True if the user agrees."""
        dlg = tk.Toplevel(self)
        dlg.title("Use the microphone?")
        dlg.configure(bg=PARCH)
        dlg.resizable(False, False)
        dlg.transient(self)
        dlg.after(100, lambda: style_titlebar(dlg))
        tk.Label(dlg, text="Listen for spell names?", bg=PARCH, fg=RED, font=(SERIF, 18, "bold italic")).pack(
            padx=22, pady=(16, 4), anchor="w")
        tk.Label(dlg, justify="left", wraplength=400, bg=PARCH, fg="#3a2412", font=(SERIF, 11),
                 text="This turns on your microphone so you can cast by saying a spell's name. Listening happens "
                      "on this PC with Windows' built-in speech recognition. Nothing is recorded, saved or sent "
                      "anywhere.\n\nA red \"Listening\" light shows at the bottom of the window whenever the "
                      "microphone is in use, and you can turn it off at any time.").pack(padx=22, anchor="w")
        answer = {"ok": False}
        row = tk.Frame(dlg, bg=PARCH)
        row.pack(padx=22, pady=(14, 16), anchor="e")

        def choose(ok):
            answer["ok"] = ok
            dlg.destroy()
        self.button("Turn it on", lambda: choose(True), 0, 0, parent=row).pack(side="left", padx=3)
        self.button("Cancel", lambda: choose(False), 0, 0, parent=row).pack(side="left", padx=3)
        dlg.update_idletasks()
        dlg.geometry("+%d+%d" % (self.winfo_rootx() + 250, self.winfo_rooty() + 220))
        dlg.grab_set()
        self.wait_window(dlg)
        if answer["ok"]:
            self.settings.set("voice_consented", True)
        return answer["ok"]

    # ---------- what happens when a spell is heard ----------
    def _voice_heard(self, key, phrase, confidence):
        self.voice_last = (phrase, confidence)
        mode = self.settings.get("voice_mode")
        if mode == "off":
            return
        if confidence < float(self.settings.get("voice_confidence")):
            self.log(f"Heard \"{phrase}\" but wasn't sure enough ({confidence:.2f}).")
            self._voice_refresh()
            return
        if self.rec or self._practice_listening():          # teaching or practising: voice stays out of the way
            self.log(f"Heard \"{phrase}\" (ignored while teaching or practising).")
            return
        if mode == "voice":
            self._voice_fire(key, phrase, confidence)
        elif time.monotonic() - self._last_swish < VOICE_WINDOW_S:    # the swish came first
            self._voice_fire(key, phrase, confidence)
            self._last_swish = 0.0
        else:                                                # wait for the swish
            self._voice_pending = (key, phrase, confidence, time.monotonic())
            self.after(int(VOICE_WINDOW_S * 1000) + 100, self._voice_expire)
        self._voice_refresh()

    def _voice_expire(self):
        p = self._voice_pending
        if p and time.monotonic() - p[3] >= VOICE_WINDOW_S:
            self._voice_pending = None
            self.log(f"Heard {pretty(p[0])} but no swish of the wand followed.")
            self._voice_refresh()

    def _voice_consume_swish(self):
        """A swish just ended. If a spoken spell is waiting for one, cast it. Returns True if it was used."""
        p = self._voice_pending
        if p and time.monotonic() - p[3] < VOICE_WINDOW_S:
            self._voice_pending = None
            self._voice_fire(p[0], p[1], p[2])
            self._voice_refresh()
            return True
        return False

    def _voice_fire(self, key, phrase, confidence):
        fresh = self._dedupe(key, "voice")                   # the same cast already seen by the wand or book: once
        self.log(f"Heard you say {pretty(key)} ({confidence:.2f})" + ("" if fresh else " (already handled)"))
        if not fresh:
            return
        self.last_cast = {"name": key, "via": "voice", "heard": phrase, "conf": confidence, "dist": 0.0,
                          "limit": 0.0, "near": []}
        self.cast_log.append((time.strftime("%H:%M:%S"), key, 0.0, "voice"))
        self.cast_log = self.cast_log[-50:]
        if self.page == "cast":
            self._draw_cast_live()
            self._draw_history()
        self._spell_cast(key)
