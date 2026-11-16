"""The Practice page."""
from common import (
    BY0, DESCRIPTIONS, LX, MUTED, PAGE_W, RED, RX, diagram_paths, evaluate, ink_image, pick_target,
    pretty, spell_effect, tk,
)


class PracticePage:
    """The Practice page."""

    def _pbtn(self, label, cmd, x, y, tip=None):
        self.button(label, cmd, x, y, tip=tip)
        return self.last_win

    def _page_practice(self):
        self.text(LX, BY0 + 20, "Practice", 24, bold=True, italic=True, color=RED)
        self.card(LX - 14, BY0 + 62, LX + PAGE_W - 6, BY0 + 132)
        self.text(LX + 4, BY0 + 70, "Cast the spell shown. The book tells you how it went, and if it gets one wrong "
                  "you can teach it from the mistake.", 10, italic=True, width=PAGE_W - 24)
        self.p_wins = {
            "start": self._pbtn("Start practice", self._practice_start, LX, BY0 + 150,
                                "Practise the spells you have taught, one after another"),
            "stop": self._pbtn("Stop", self._practice_stop, LX, BY0 + 150),
            "skip": self._pbtn("Skip spell", self._practice_next, LX + 96, BY0 + 150, "Try a different spell"),
        }
        self.text(RX, BY0 + 24, "Cast this spell", 20, bold=True)
        self.p_wins["add"] = self._pbtn("Teach it this cast", self._practice_add, RX + 216, BY0 + 338,
                                        "Add that cast to the book as an example of this spell")
        self.p_wins["next"] = self._pbtn("Next spell", self._practice_next, RX + 216, BY0 + 386)
        self._draw_practice()

    def _practice_buttons(self):
        p = self.practice
        active, st, res = p["active"], p["state"], p["result"]
        ok = bool(res and res["ok"])
        want = {"start": not active, "stop": active, "skip": active and st == "waiting",
                "add": bool(active and st == "result" and not ok and p["gesture"] is not None
                            and not (res or {}).get("added")),
                "next": bool(active and st == "result" and not ok)}
        for k, wid in self.p_wins.items():
            try:
                self.cv.itemconfig(wid, state="normal" if want.get(k) else "hidden")
            except tk.TclError:
                pass

    def _draw_practice(self):
        self.cv.delete("plive")
        tg = ("page", "plive")
        p = self.practice
        sess = p["session"]
        hits = sum(1 for s in sess if s[1])
        th, tt = self.pstats.totals()
        self.card(LX - 14, BY0 + 206, LX + PAGE_W - 6, BY0 + 300, tags=tg)
        self.text(LX + 4, BY0 + 214, f"This session: {hits} of {len(sess)}"
                  + (f"  ({100 * hits // len(sess)}%)" if sess else ""), 13, bold=True, tags=tg, width=PAGE_W - 24)
        self.text(LX + 4, BY0 + 242, f"Streak {p['streak']}   ·   Best streak {self.pstats.best_streak}", 11,
                  tags=tg, width=PAGE_W - 24)
        self.text(LX + 4, BY0 + 266, f"All time: {th} of {tt}" + (f"  ({100 * th // tt}%)" if tt else ""), 11,
                  color=MUTED, tags=tg, width=PAGE_W - 24)
        self.text(LX, BY0 + 318, "Recent attempts", 13, bold=True, tags=tg)
        if not sess:
            self.text(LX, BY0 + 346, "Nothing yet.", 11, italic=True, color=MUTED, tags=tg)
        for i, (target, ok, got) in enumerate(reversed(sess[-9:])):
            line = f"{'✓' if ok else '✗'}  {pretty(target)}"
            if not ok:
                line += f"   → {pretty(got) if got else 'not recognised'}"
            self.text(LX, BY0 + 346 + i * 24, line, 12, bold=(i == 0), color=("#2f6b3a" if ok else "#7a4a2a"),
                      tags=tg, width=PAGE_W)
        self._practice_buttons()

        target = p["target"]
        if not p["active"] or not target:
            self.text(RX, BY0 + 70, p["msg"] or "Press Start practice. You will be asked to cast spells you have "
                      "taught, one after another, and the ones you find hard come up more often.", 12, italic=True,
                      color=MUTED, tags=tg)
        else:
            self.text(RX, BY0 + 58, pretty(target), 24, bold=True, italic=True, color=RED, tags=tg)
            self.text(RX, BY0 + 100, DESCRIPTIONS.get(target, ""), 11, italic=True, tags=tg)
            paths = diagram_paths(target)
            if paths:
                iw = 190 if len(paths) == 1 else 100
                self._practice_imgs = [ink_image(pa, iw) for pa in paths]
                for i, im in enumerate(self._practice_imgs):
                    self.cv.create_image(RX + i * (iw + 8), BY0 + 150, image=im, anchor="nw", tags=tg)
            col_x, w = RX + 216 if len(paths) <= 1 else RX, 178
            col_y = BY0 + 150 if len(paths) <= 1 else BY0 + 410
            res = p["result"]
            if p["state"] == "waiting":
                self.text(col_x, col_y, "Cast it now...", 18, italic=True, color=MUTED, tags=tg, width=w)
                self.text(col_x, col_y + 40, "Hold the wand in your normal grip, trace the shape, then hold still.",
                          10, italic=True, color=MUTED, tags=tg, width=w)
            elif res["ok"]:
                self.text(col_x, col_y, "✓ Yes!", 28, bold=True, color="#2f6b3a", tags=tg, width=w)
                detail = "The wand recognised it itself." if res["source"] == "wand" else \
                    f"Distance {res['dist']:.2f}"
                self.text(col_x, col_y + 50, detail + "\nNext spell in a moment...", 10, color=MUTED, tags=tg, width=w)
            else:
                self.text(col_x, col_y, "✗ Not quite", 22, bold=True, color="#7a4a2a", tags=tg, width=w)
                said = (f"The book thought that was {pretty(res['got'])}." if res["got"] else
                        "The book did not recognise that as any spell you have taught.")
                if res["tdist"] is not None:
                    said += f"\nDistance to {pretty(target)}: {res['tdist']:.2f}."
                if res.get("added"):
                    said += "\nAdded to the book. Try again!"
                self.text(col_x, col_y + 40, said, 10, tags=tg, width=w)
        weakest = self.pstats.weakest(3)
        self.card(RX - 14, BY0 + 520, RX + PAGE_W + 6, BY0 + 640, tags=tg)
        self.text(RX + 4, BY0 + 530, "Needs the most practice", 13, bold=True, color=RED, tags=tg)
        if not weakest:
            self.text(RX + 4, BY0 + 560, "Your weak spots will show up here as you practise.", 11, italic=True,
                      color=MUTED, tags=tg, width=PAGE_W - 24)
        for i, (name, rate, tries) in enumerate(weakest):
            h, t = self.pstats.accuracy(name)
            self.text(RX + 4, BY0 + 558 + i * 24, f"{pretty(name)}   {h} of {t}  ({int(rate * 100)}%)", 12, tags=tg,
                      width=PAGE_W - 24)

    def _practice_start(self):
        p = self.practice
        if not self.store.data:
            p["msg"] = "You have not taught any spells yet. Open Teach and cast a spell three times first."
        elif not (self.wand and self.wand.connected):
            p["msg"] = "Connect your wand first, on the Devices page."
        else:
            p.update(active=True, streak=0, session=[], msg="", last=None)
            self._practice_next()
            return
        self._draw_practice()

    def _practice_next(self):
        p = self.practice
        if not p["active"]:
            return
        p["token"] += 1
        p["target"] = pick_target(sorted(self.store.data), p["last"], self.pstats)
        p["last"] = p["target"]
        p.update(state="waiting", result=None, gesture=None)
        if self.page == "practice":
            self._draw_practice()

    def _practice_stop(self):
        p = self.practice
        p.update(active=False, state="idle", result=None, gesture=None, target=None)
        p["token"] += 1
        if self.page == "practice":
            self._draw_practice()

    def _practice_listening(self):
        p = self.practice
        return bool(p["active"] and self.page == "practice" and p["target"] and
                    (p["state"] == "waiting" or (p["state"] == "result" and not p["result"]["ok"])))

    def _practice_cast(self, g):
        p = self.practice
        r = evaluate(self.store, g, p["target"], float(self.settings.get("accept")))
        p["gesture"] = g
        self._practice_result(r["ok"], r["got"], r["dist"], r["target_dist"], "book")

    def _practice_native(self, key):
        self._practice_result(key == self.practice["target"], key, None, None, "wand")

    def _practice_result(self, ok, got, dist, tdist, source):
        p = self.practice
        target = p["target"]
        p["streak"] = p["streak"] + 1 if ok else 0
        self.pstats.record(target, ok, p["streak"])
        p["session"].append((target, ok, got))
        p["result"] = {"ok": ok, "got": got, "dist": dist, "tdist": tdist, "source": source, "added": False}
        p["state"] = "result"
        self.cue("success" if ok else "fail")
        if ok:
            self.wand_call("play", spell_effect(target, self.settings.color(target)))
            tok = p["token"]
            self.after(2200, lambda: self._practice_next() if (p["token"] == tok and p["active"]) else None)
        self._draw_practice()

    def _practice_add(self):
        p = self.practice
        if p["gesture"] is None or not p["target"] or not p["result"]:
            return
        self.store.add(p["target"], p["gesture"])
        p["result"]["added"] = True
        self.log(f"Added a cast to {pretty(p['target'])} from practice ({self.store.casts(p['target'])} casts)")
        self._draw_practice()
