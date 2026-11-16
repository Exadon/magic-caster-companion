"""Command-line demo: find the wand, flash its lights, buzz, then print motion events for 20 s."""
import asyncio
import math
import sys

from mcwand import Wand, scan, TIP, MID_UPPER, MID_LOWER, POMMEL


async def main():
    addr = sys.argv[1] if len(sys.argv) > 1 else None
    if not addr:
        print("Scanning for a wand (8 s)...")
        found = await scan(8)
        if "wand" not in found:
            sys.exit("No wand found. Wake it (lift it from the base or wave it) and retry.")
        addr = found["wand"]["address"]
    async with Wand(addr) as w:
        print(f"connected: model={w.model} firmware={w.firmware} battery={w.battery}%")
        for grp, rgb in [(TIP, (255, 0, 0)), (MID_UPPER, (255, 140, 0)),
                         (MID_LOWER, (0, 255, 0)), (POMMEL, (0, 0, 255))]:
            await w.led(grp, *rgb)
            await asyncio.sleep(0.4)
        await w.buzz(500)
        await asyncio.sleep(1.2)
        await w.leds_off()

        def imu(samples):
            s = samples[-1]
            spin = math.sqrt(sum(x * x for x in s.gyro))
            if spin > 4.0:
                print(f"fast swish: {spin:.1f} rad/s")

        w.on_imu = imu
        w.on_touch = lambda m: print(f"touch sensors: {m:04b}")
        await w.imu_start()
        print("Listening for 20 s - swish the wand...")
        await asyncio.sleep(20)


asyncio.run(main())
