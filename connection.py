"""Finding, connecting to and reconnecting the wand and base."""
from common import (
    Box, RETRY_S, Wand, asyncio, scan, time,
)


class ConnectionMixin:
    """Finding, connecting to and reconnecting the wand and base."""

    def _fresh(self, kind):
        """Coroutine: scan result for kind, rescanning first if it is missing or older than 30 s."""
        async def go():
            if self.scan_lock is None:
                self.scan_lock = asyncio.Lock()
            async with self.scan_lock:
                info = self.found.get(kind)
                if not info or time.monotonic() - self.found_at > 30:
                    found = await scan(6)
                    self.found, self.found_at = found, time.monotonic()
                    self.ui(lambda: self.log("Found: " + (", ".join(
                        f"{v['name']} ({v['rssi']} dBm)" for v in found.values()) or "nothing")))
                    info = found.get(kind)
            if not info:
                raise RuntimeError(f"{'wand' if kind == 'wand' else 'base'} not found - wake it (wave it), and "
                                   "close any other window already connected to it")
            return info
        return go()

    def do_scan(self):
        self.log("Scanning (8s)...")

        async def go():
            found = await scan(8)
            self.found, self.found_at = found, time.monotonic()
            return found
        self.run(go(), lambda f: self.log("Found: " + (", ".join(
            f"{v['name']} ({v['rssi']} dBm)" for v in f.values()) or "nothing - wave the wand and scan again")))

    def connect_all(self, quiet=False):
        self.connect("wand", quiet)
        self.connect("box", quiet)

    def connect(self, kind, quiet=False):
        cur = self.wand if kind == "wand" else self.box
        if (cur is not None and cur.connected) or self.connecting[kind]:
            return
        self.connecting[kind] = True
        self.user_off[kind] = False
        st = self.vars["w_state" if kind == "wand" else "b_state"]
        name = "wand" if kind == "wand" else "base"
        st.set(f"looking for the {name}...")

        async def go():
            info = await self._fresh(kind)
            self.ui(lambda: st.set("connecting..."))
            dev = self._make(kind, info["address"])
            await dev.connect()
            if kind == "wand" and self.settings.get("streaming"):
                await dev.imu_start()
            return dev

        def ok(dev):
            self.connecting[kind] = False
            if kind == "wand":
                self.wand = dev
                self.vars["w_info"].set(f"{dev.model} (fw {dev.firmware})")
                self.vars["w_batt"].set(f"{dev.battery}%")
                self.vars["w_state"].set("connected")
                self.log("Wand connected, motion streaming.")
            else:
                self.box = dev
                self.vars["b_info"].set(dev.firmware or "-")
                self.vars["b_batt"].set(f"{dev.battery}%")
                self.vars["b_state"].set("connected")
                self.log("Base connected.")
            self.cue("connect")
            self._base_light()

        def fail(e):
            self.connecting[kind] = False
            reason = str(e) or type(e).__name__
            if self.settings.get("auto_reconnect") and not self.user_off[kind]:
                st.set(f"waiting for the {name} (wave it)...")
                if not quiet:
                    self.log(f"Could not connect to the {name}: {reason}. Retrying automatically.")
                self.after(RETRY_S * 1000, lambda: self.connect(kind, quiet=True))
            else:
                st.set(f"failed: {reason}")
        self.run(go(), ok, fail)

    def _make(self, kind, address):
        if kind == "wand":
            w = Wand(address)
            w.on_imu = self._on_imu
            w.on_touch = lambda m: self.ui(lambda: self.log(f"Wand touch sensors: {m:04b}"))
            w.on_spell = lambda n: self.ui(lambda: self._native_spell(n))
            w.on_disconnect = lambda: self.ui(lambda: self._lost("wand"))
            return w
        b = Box(address)
        b.on_lid = lambda x: self.ui(lambda: self.vars["b_lid"].set("removed" if x else "on"))
        b.on_wand = lambda x: self.ui(lambda: self.vars["b_wand"].set("yes" if x else "no"))
        b.on_charge = lambda x: self.ui(lambda: self.vars["b_usb"].set("plugged in" if x else "unplugged"))
        b.on_disconnect = lambda: self.ui(lambda: self._lost("box"))
        return b

    def _lost(self, kind):
        name = "Wand" if kind == "wand" else "Base"
        self.vars["w_state" if kind == "wand" else "b_state"].set("disconnected")
        if not self.user_off[kind]:
            self.log(f"{name} disconnected.")
        self._base_light()
        if self.settings.get("auto_reconnect") and not self.user_off[kind]:
            self.after(3000, lambda: self.connect(kind, quiet=True))

    def disconnect(self, kind):
        self.user_off[kind] = True
        dev = self.wand if kind == "wand" else self.box
        if dev:
            self.run(dev.disconnect())

    def _base_light(self):
        """Base light mirrors the wand: green when connected, amber when not."""
        if not (self.box and self.box.connected):
            return
        if not self.settings.get("base_status_light"):
            return
        wand_ok = bool(self.wand and self.wand.connected)
        r, g, b = (0, 110, 0) if wand_ok else (140, 60, 0)
        self.run(self.box.led(r, g, b))

    def wand_call(self, method, *args):
        if not (self.wand and self.wand.connected):
            self.log("Connect the wand first.")
            return
        self.run(getattr(self.wand, method)(*args))
