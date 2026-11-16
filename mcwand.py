"""Minimal Magic Caster Wand + Box BLE library (own implementation).

Protocol facts were learned from probing real devices and from the MIT-licensed
eigger/hass-magic-caster-wand project. Deliberately omits calibration, factory
unlock and the Nordic DFU service, which can alter or damage the devices.
"""
import asyncio
import struct
from dataclasses import dataclass
from typing import Callable, Dict, Optional

from bleak import BleakClient, BleakScanner
from bleak.exc import BleakError

WAND_SERVICE_TAIL = "587e-48a0-974c-544d6163c577"
BOX_SERVICE_TAIL = "587e-48a0-974c-54686f72c577"
BATTERY_UUID = "00002a19-0000-1000-8000-00805f9b34fb"

TIP, MID_UPPER, MID_LOWER, POMMEL = 0, 1, 2, 3
LED_GROUPS = {"Tip": TIP, "Upper middle": MID_UPPER, "Lower middle": MID_LOWER, "Pommel": POMMEL}
ACCEL_G = 0.00048828125   # raw -> g
GYRO_RADS = 0.0010908308  # raw -> rad/s


@dataclass
class ImuSample:
    gyro: tuple   # rad/s (x, y, z)
    accel: tuple  # g (x, y, z)


async def scan(timeout: float = 8.0) -> Dict[str, Dict[str, str]]:
    """Scan once; return {'wand': {...}, 'box': {...}} for the strongest of each."""
    found = await BleakScanner.discover(timeout=timeout, return_adv=True)
    best: Dict[str, tuple] = {}
    for addr, (dev, adv) in found.items():
        name = dev.name or adv.local_name or ""
        kind = "wand" if name.startswith("MCW-") else "box" if name.startswith("MCB-") else None
        if kind and (kind not in best or adv.rssi > best[kind][2]):
            best[kind] = (addr, name, adv.rssi)
    return {k: {"address": a, "name": n, "rssi": r} for k, (a, n, r) in best.items()}


class _Device:
    SERVICE_TAIL = WAND_SERVICE_TAIL

    def __init__(self, address: str):
        self.address = address
        self.cmd_uuid = f"57420002-{self.SERVICE_TAIL}"
        self.notify_uuid = f"57420003-{self.SERVICE_TAIL}"
        self._c = BleakClient(address, timeout=12, disconnected_callback=self._lost)
        self.on_disconnect: Optional[Callable[[], None]] = None
        self.firmware: Optional[str] = None
        self.battery: Optional[int] = None

    def _lost(self, _client):
        if self.on_disconnect:
            self.on_disconnect()

    @property
    def connected(self) -> bool:
        return self._c.is_connected

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *exc):
        await self.disconnect()

    async def connect(self):
        last = None
        for _ in range(3):
            try:
                await self._c.connect()
                break
            except (BleakError, asyncio.TimeoutError) as e:
                last = e
                # Re-find the device (it may have stopped advertising) and retry.
                dev = await BleakScanner.find_device_by_address(self.address, timeout=6)
                self._c = BleakClient(dev or self.address, timeout=12, disconnected_callback=self._lost)
        else:
            raise last or BleakError("connect failed")
        # Subscribe first: devices drop idle links that never subscribe.
        await self._c.start_notify(self.notify_uuid, self._handle)
        await asyncio.sleep(0.5)
        self.battery = (await self._c.read_gatt_char(BATTERY_UUID))[0]
        await self._after_connect()

    async def _after_connect(self):
        await self._send(b"\x00", 0.4)

    async def disconnect(self):
        if self._c.is_connected:
            try:
                await self._before_disconnect()
            except Exception:
                pass
            await self._c.disconnect()

    async def _before_disconnect(self):
        pass

    async def _send(self, data: bytes, wait: float = 0.05):
        await self._c.write_gatt_char(self.cmd_uuid, data, response=False)
        await asyncio.sleep(wait)

    async def leds_off(self):
        await self._send(b"\x40")

    def _handle(self, _, d: bytearray):
        if d and d[0] == 0x00 and len(d) >= 2:
            self.firmware = ".".join(str(b) for b in d[1:])
        self._handle_specific(d)

    def _handle_specific(self, d: bytearray):
        pass


class Wand(_Device):
    SERVICE_TAIL = WAND_SERVICE_TAIL

    def __init__(self, address: str):
        super().__init__(address)
        self.on_touch: Optional[Callable[[int], None]] = None  # 4-bit touch/gesture-sensor mask
        self.on_imu: Optional[Callable[[list], None]] = None
        self.on_spell: Optional[Callable[[str], None]] = None  # wand-reported, if any
        self.model: Optional[str] = None
        self.sku: Optional[str] = None

    async def _after_connect(self):
        await self._send(b"\x00")
        await self._send(bytes([0x0E, 0x04]))
        await self._send(bytes([0x0E, 0x02]))
        await asyncio.sleep(0.8)

    async def _before_disconnect(self):
        await self.imu_stop()

    # ---- outputs ----
    async def led(self, group: int, r: int, g: int, b: int):
        await self._send(bytes([0x42, group, r & 255, g & 255, b & 255]))

    async def led_all(self, r: int, g: int, b: int):
        for grp in (TIP, MID_UPPER, MID_LOWER, POMMEL):
            await self.led(grp, r, g, b)

    async def buzz(self, ms: int = 200):
        await self._send(bytes([0x68, 0x50]) + struct.pack("<H", ms))

    async def play(self, steps):
        """Play a macro. steps: list of ('led', group, r, g, b, ms) | ('buzz', ms) | ('delay', ms) | ('clear',)."""
        out = bytearray([0x68])
        for s in steps:
            if s[0] == "led":
                out += bytes([0x22, s[1], s[2] & 255, s[3] & 255, s[4] & 255]) + struct.pack("<H", s[5])
            elif s[0] == "buzz":
                out += bytes([0x50]) + struct.pack("<H", s[1])
            elif s[0] == "delay":
                out += bytes([0x10]) + struct.pack("<H", s[1])
            elif s[0] == "clear":
                out += bytes([0x20])
        await self._send(bytes(out))

    # ---- motion ----
    async def imu_start(self):
        await self._send(b"\x31", 0.1)
        await self._send(bytes([0x30, 0x00, 0x80]))

    async def imu_stop(self):
        await self._send(b"\x31")

    def _handle_specific(self, d: bytearray):
        op = d[0] if d else None
        if op == 0x10 and len(d) >= 2 and self.on_touch:
            self.on_touch(d[1] & 0x0F)
        elif op == 0x2C and len(d) >= 4 and self.on_imu:
            n = d[3]
            out = []
            for i in range(min(n, (len(d) - 4) // 12)):
                v = struct.unpack_from("<6h", d, 4 + 12 * i)
                out.append(ImuSample(tuple(x * GYRO_RADS for x in v[:3]),
                                     tuple(x * ACCEL_G for x in v[3:])))
            if out:
                self.on_imu(out)
        elif op == 0x24 and len(d) >= 5 and self.on_spell:
            name = bytes(d[4:4 + d[3]]).decode("utf-8", "ignore").replace("\x00", "").replace("_", " ").strip()
            if name:
                self.on_spell(name)
        elif op == 0x0E and len(d) >= 3:
            if d[1] == 0x04:
                self.model = bytes(d[2:]).decode("ascii", "ignore").strip("\x00")
            elif d[1] == 0x02:
                self.sku = bytes(d[2:]).decode("ascii", "ignore").strip("\x00")


class Box(_Device):
    SERVICE_TAIL = BOX_SERVICE_TAIL

    def __init__(self, address: str):
        super().__init__(address)
        self.on_lid: Optional[Callable[[bool], None]] = None      # True = lid removed
        self.on_wand: Optional[Callable[[bool], None]] = None     # True = wand present
        self.on_charge: Optional[Callable[[bool], None]] = None   # True = USB power plugged

    async def _after_connect(self):
        await self._send(b"\x00", 0.3)
        for req in (b"\x12", b"\x13", b"\x11", b"\x10"):  # wand, charge, lid notifications, status
            await self._send(req, 0.3)

    async def led(self, r: int, g: int, b: int):
        await self._send(bytes([0x42, 0, r & 255, g & 255, b & 255]))

    def _handle_specific(self, d: bytearray):
        if len(d) < 2:
            return
        op, v = d[0], d[1]
        if op == 0x10:  # combined status: bit0 = lid removed, bit1 = wand present
            if self.on_lid:
                self.on_lid(bool(v & 1))
            if self.on_wand:
                self.on_wand(bool(v & 2))
        elif op == 0x11 and self.on_lid:
            self.on_lid(v != 0)
        elif op == 0x12 and self.on_wand:
            self.on_wand(v != 0)
        elif op == 0x13 and self.on_charge:
            self.on_charge(v != 0)
