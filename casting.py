"""Turning wand motion and wand reports into recognised casts, and the effects and actions that follow."""
from common import (
    BX1, BY0, FIRE_WINDOW_S, MARK, SERIF, SPELLS, SPINE, UNLOCK_AT, filedialog, hexcolor, math,
    messagebox, pretty, run_action, spell_color, spell_effect, spell_key, time,
)


class CastingMixin:
    """Turning wand motion and wand reports into recognised casts, and the effects and actions that follow."""

    def arm_record(self, n):
        if not (self.wand and self.wand.connected):
            self.log("Connect the wand first.")
            self.t_status.set("Connect your wand on the Devices page first.")
            return
        self.rec = {"name": self.sel_spell, "need": n, "got": 0}
        self.t_status.set(f"{pretty(self.sel_spell)}: cast 1 of {n}. Make the motion now...")

    def _on_imu(self, samples):  # BLE thread
        self.spin = max(math.sqrt(sum(g * g for g in s.gyro)) for s in samples)
        self.spin_hist.append((time.monotonic(), self.spin))
        for smp in samples:
            g = self.seg.feed(smp)
            if g:
                self.ui(lambda g=g: self._gesture_done(g))

    def _gesture_done(self, g):
        if self.rec:
            self._record_step(g)
        elif self._practice_listening():
            self._practice_cast(g)
        elif self.cast_mode.get():
            self._cast(g)

    def _record_step(self, g):
        r = self.rec
        ok, msg, _ = self.store.check(r["name"], g)
        if not ok and r.get("rejects", 0) < 2:
            r["rejects"] = r.get("rejects", 0) + 1
            self.cue("fail")
            self.t_status.set(f"{msg} Try that cast again ({r['got'] + 1} of {r['need']}). "
                              "(If it keeps happening, the next one is kept anyway.)")
            return
        r["rejects"] = 0
        before = self.store.casts(r["name"])
        self.store.add(r["name"], g)
        r["got"] += 1
        self.cue("saved")
        self.log(f"Recorded {pretty(r['name'])} cast {self.store.casts(r['name'])} ({len(g)} samples)")
        just_unlocked = before < UNLOCK_AT <= self.store.casts(r["name"])
        if self.page == "teach":
            self._fill_gestures()
        if r["got"] < r["need"]:
            self.t_status.set(f"Saved {r['got']} of {r['need']}. Cast {pretty(r['name'])} again...")
            return
        self.rec = None
        total = self.store.casts(r["name"])
        msg = (f"{pretty(r['name'])} is unlocked! The book will now recognise it." if just_unlocked
               else f"Saved. {pretty(r['name'])} now has {total} casts.")
        if total < UNLOCK_AT:
            msg += f" {UNLOCK_AT - total} more to unlock it."
        chk = self.store.self_check()
        if chk:
            msg += f" Self-test: {chk['correct']} of {chk['total']} casts recognised."
        self.t_status.set(msg)
        if just_unlocked:
            self.log(f"Unlocked {pretty(r['name'])}")
            self.cue("success")
            self._flash(r["name"], self.settings.color(r["name"]) or spell_color(r["name"]),
                        f"{pretty(r['name'])} unlocked!")

    def _dedupe(self, name, source):
        """False if this recognition should not fire, because the other recogniser already handled the cast.

        - Same spell reported by both the wand and the book within a moment: it counts once, and the history
          entry is marked as seen by both.
        - The wand named a DIFFERENT spell for this cast first: trust the wand and ignore the book's answer.
        """
        now = time.monotonic()
        last, self._last_fire = self._last_fire, (now, name, source)
        if last and last[2] != source and now - last[0] < FIRE_WINDOW_S:
            if last[1] == name:
                for i in range(len(self.cast_log) - 1, -1, -1):
                    entry = self.cast_log[i]
                    if entry[1] == name:
                        self.cast_log[i] = entry[:3] + ("both",)
                        break
                if self.page == "cast":
                    self._draw_history()
                return False
            if source == "book":
                self.log(f"The wand named {pretty(last[1])} for this cast, so the book's "
                         f"{pretty(name)} was ignored.")
                return False
        return True

    def _note_native(self, key):
        """Remember which spells the wand recognises by itself, and count them by streaming state."""
        ns = dict(self.settings.get("native_stats"))
        field = "streaming_on" if self.settings.get("streaming") else "streaming_off"
        ns[field] = int(ns.get(field, 0)) + 1
        self.settings.set("native_stats", ns)
        known = list(self.settings.get("wand_known"))
        if key and key not in known:
            known.append(key)
            self.settings.set("wand_known", known)
            self.log(f"The wand knows {pretty(key)} by itself.")

    def _mark(self, s):
        """Index mark: unlocked (taught), the wand knows it, learning, or locked."""
        st = self.store.state(s)
        if st == "unlocked":
            return MARK["unlocked"]
        if s in self.settings.get("wand_known"):
            return "★ "
        return MARK[st]

    def _streaming_changed(self):
        on = bool(self.stream_var.get())
        self.settings.set("streaming", on)
        if not on:
            self.spin_hist.clear()
            self.spin = 0.0
        if self.wand and self.wand.connected:
            self.wand_call("imu_start" if on else "imu_stop")
        self.log("Motion streaming on: your taught spells are recognised." if on else
                 "Motion streaming off: only spells the wand recognises itself are reported.")

    def _native_spell(self, raw):
        """The wand itself recognised a spell and told us its name."""
        key = spell_key(raw)
        known = key in SPELLS
        self.log(f"Wand recognised: {raw}" + ("" if known else "  (not in this book's list)"))
        self._note_native(key if known else None)
        if known and self._practice_listening():
            self._practice_native(key)
            return
        if known and not self._dedupe(key, "wand"):
            return                       # the book already recognised this same cast: it counts once
        self.last_cast = {"name": key if known else None, "raw": raw, "native": True, "dist": 0.0,
                          "limit": 0.0, "near": []}
        self.cast_log.append((time.strftime("%H:%M:%S"), key if known else raw, 0.0, "wand"))
        self.cast_log = self.cast_log[-50:]
        if self.page == "cast":
            self._draw_cast_live()
            self._draw_history()
        if known:
            self._spell_cast(key)
        else:
            self.cue("success")

    def _cast(self, g):
        if not self.store.data:
            if self.page == "teach":
                self.t_status.set("The book knows no spells yet. Teach it one first.")
            return
        accept = float(self.settings.get("accept"))
        best, dist, scores = self.store.match(g, accept)
        near = sorted(scores.items(), key=lambda kv: kv[1])[:4]
        if best and not self._dedupe(best, "book"):
            self.log(f"Cast {pretty(best)} d={dist:.2f} (already handled via the wand)")
            return                       # the wand already reported this same cast: it counts once
        self.last_cast = {"name": best, "dist": dist, "limit": accept, "near": near}
        self.cast_log.append((time.strftime("%H:%M:%S"), best, dist, "book"))
        self.cast_log = self.cast_log[-50:]
        if self.page == "cast":
            self._draw_cast_live()
            self._draw_history()
        if not best:
            self.cue("fail")
            return
        self.log(f"Cast {pretty(best)} d={dist:.2f}")
        self._spell_cast(best)

    def _spell_cast(self, best):
        """A spell was recognised (by the book or by the wand): sound, glow, wand effect, then its action."""
        self.cue("success")
        col = self.settings.color(best) or spell_color(best)
        if self.hidden and self.tray and self.settings.get("tray_notify"):
            self.tray.notify(f"{pretty(best)} recognised")
        if self.page != "cast" and not self.hidden:          # the Cast page shows the result itself
            self._flash(best, col)
        self.wand_call("play", spell_effect(best, self.settings.color(best)))
        act = self.settings.action(best)
        if act:
            if self.test_mode.get():
                self.log(f"Test mode: would run {act['type']}: {act['value']}")
            else:
                try:
                    self.log("Ran " + run_action(act, best))
                except Exception as e:
                    self.log(f"Action failed: {e}")

    def _flash(self, name, rgb, text=None):
        """The spell name glows in the middle of the page, then fades into the parchment."""
        steps, pr = 16, (0xe8, 0xd9, 0xb5)
        cx = SPINE if self.page == "cast" else SPINE + (BX1 - SPINE) // 2
        cy = BY0 + 430

        def frame(i):
            self.cv.delete("flash")
            if i >= steps:
                return
            t = i / steps
            c = tuple(int(rgb[j] * 0.75 * (1 - t) + pr[j] * t) for j in range(3))
            self.cv.create_text(cx, cy, text=text or pretty(name), fill=hexcolor(c), width=380,
                                font=(SERIF, 28 + int(8 * (1 - t)), "bold italic"), tags="flash")
            self.after(50, lambda: frame(i + 1))
        frame(0)

    def autotune(self):
        chk = self.store.self_check()
        if not chk or chk["suggested_accept"] is None:
            self.c_note.set("Teach at least two casts of a spell first, then try again.")
            return
        s = chk["suggested_accept"]
        self.accept_var.set(s)
        self.settings.set("accept", s)
        self.c_note.set(f"Self-test: {chk['correct']} of {chk['total']} recognised. Limit set to {s}.")
        if self.page == "cast":  # redraw so the slider moves to the new value
            self.clear()
            self._build("cast")

    def check_casts(self):
        chk = self.store.self_check()
        if not chk:
            self.t_status.set("Record at least two casts of a spell first.")
            return
        msg = f"Self-test: {chk['correct']} of {chk['total']} of your casts are recognised."
        if chk["confused"]:
            pairs = sorted({f"{pretty(a)} looks like {pretty(b)}" for a, b in chk["confused"]})
            msg += " Mixed up: " + "; ".join(pairs[:3]) + "."
        self.t_status.set(msg)

    def delete_gesture(self):
        sel = self.g_list.curselection()
        if sel:
            name = sorted(self.store.data)[sel[0]]
            if messagebox.askyesno("Forget spell", f"Forget all casts of {pretty(name)}? It will be locked again."):
                self.store.remove(name)
                self._fill_gestures()

    def export_gestures(self):
        if not self.store.data:
            self.t_status.set("Nothing to export yet.")
            return
        p = filedialog.asksaveasfilename(defaultextension=".json", initialfile="my-spells.json",
                                         filetypes=[("Spell files", "*.json")])
        if p:
            self.store.export_to(p)
            self.log(f"Exported casts to {p}")

    def import_gestures(self):
        p = filedialog.askopenfilename(filetypes=[("Spell files", "*.json")])
        if not p:
            return
        try:
            n = self.store.import_from(p)
        except (ValueError, OSError) as e:
            messagebox.showerror("Import", f"Could not import that file: {e}")
            return
        self._fill_gestures()
        self.t_status.set(f"Imported {n} casts.")
