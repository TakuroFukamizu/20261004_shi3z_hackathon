#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["bleak>=0.21"]
# ///
"""Checks whether this Mac can hold N toio cubes at once.

  uv run client/toio_spike.py --names a1B,c2D                connect to these cubes, soak for 10 minutes
  uv run client/toio_spike.py --names a1B,c2D --minutes 1    shorter soak
  uv run client/toio_spike.py --names a1B,c2D --move         also send one cube to the mat centre (250, 250)

Only the named cubes are touched (find the names with `uv run client/toio_hub.py --scan`).
Turn them on and put them on the mat first. PASS means: every named cube connected,
no disconnects, median config round trip under 100 ms.
"""
import argparse
import asyncio
import statistics
import sys
import time

from bleak import BleakClient

import toio_protocol as P
from toio_hub import choose, print_scan, scan

COLORS = [(255, 0, 0), (0, 255, 0), (0, 0, 255)]


async def connect(dev, name):
    c = {"name": name, "drops": 0, "ids": 0, "pos": None, "rt": [], "version": None, "pong": None, "moved": None}

    def lost(_client):
        c["drops"] += 1
        print("  LOST %s" % name)

    def on_id(_sender, data):
        c["ids"] += 1
        info = P.parse_id(bytes(data))
        if info and info["on_mat"]:
            c["pos"] = (info["x"], info["y"], info["angle"])

    def on_config(_sender, data):
        version = P.parse_version(bytes(data))
        if version:
            c["version"] = version
            if c["pong"]:
                c["pong"].set()

    def on_motor(_sender, data):
        result = P.parse_move_result(bytes(data))
        if result and c["moved"] and not c["moved"].done():
            c["moved"].set_result(result[1])

    client = BleakClient(dev, disconnected_callback=lost)
    t0 = time.monotonic()
    await client.connect()
    c["client"] = client
    await client.start_notify(P.ID_INFO, on_id)
    await client.start_notify(P.CONFIG, on_config)
    await client.start_notify(P.MOTOR, on_motor)
    on_id(None, await client.read_gatt_char(P.ID_INFO))
    c["battery"] = (await client.read_gatt_char(P.BATTERY))[0]
    print("  %s connected in %.1f s, battery %d%%" % (name, time.monotonic() - t0, c["battery"]))
    return c


async def ping(c):
    """Config round trip: write a version request, wait for its notification."""
    c["pong"] = asyncio.Event()
    t0 = time.monotonic()
    await c["client"].write_gatt_char(P.CONFIG, P.REQUEST_VERSION)
    try:
        await asyncio.wait_for(c["pong"].wait(), 2)
        c["rt"].append((time.monotonic() - t0) * 1000)
    except asyncio.TimeoutError:
        c["rt"].append(2000.0)


async def run(a):
    print("scanning 6 s ...")
    found = await scan()
    print_scan(found)
    names = [n for n in a.names.split(",") if n]
    named = [(name, dev) for name, _, dev in choose(found, names)]
    expect = len(names)
    cubes = []
    for name, dev in named:
        try:
            cubes.append(await connect(dev, name))
        except Exception as e:
            print("  %s: connect failed: %s" % (name, e))

    try:
        if a.move:
            on_mat = [c for c in cubes if c["pos"]]
            if on_mat:
                c = on_mat[0]
                c["moved"] = asyncio.get_running_loop().create_future()
                await c["client"].write_gatt_char(P.MOTOR, P.move_to(1, 250, 250))
                try:
                    print("move %s -> (250, 250): %s" % (c["name"], await asyncio.wait_for(c["moved"], 12)))
                except asyncio.TimeoutError:
                    print("move %s: no answer (firmware may not support target moves)" % c["name"])
            else:
                print("move: no cube is on the mat")

        deadline = time.monotonic() + a.minutes * 60
        tick = 0
        print("soaking for %g minutes ..." % a.minutes)
        while time.monotonic() < deadline:
            for c in cubes:
                if not c["client"].is_connected:
                    continue
                try:
                    await c["client"].write_gatt_char(P.LIGHT, P.led(*COLORS[tick % 3]))
                    await ping(c)
                except Exception as e:
                    print("  %s: %s" % (c["name"], e))
            tick += 1
            await asyncio.sleep(1)
    finally:
        print("\n%-10s %-8s %-6s %-9s %-16s %s" % ("name", "version", "drops", "id-notif", "position", "round trip ms (median / max)"))
        medians = []
        for c in cubes:
            med = statistics.median(c["rt"]) if c["rt"] else float("nan")
            medians.append(med)
            print("%-10s %-8s %-6d %-9d %-16s %.0f / %.0f" % (
                c["name"], c["version"], c["drops"], c["ids"], c["pos"], med, max(c["rt"], default=float("nan"))))
            try:
                if c["client"].is_connected:
                    await c["client"].write_gatt_char(P.LIGHT, P.LED_OFF)
                    await c["client"].disconnect()
            except Exception:
                pass
        ok = (len(cubes) >= expect and all(c["drops"] == 0 for c in cubes)
              and bool(medians) and all(m < 100 for m in medians))
        print("\n%s: %d of %d cubes connected" % ("PASS" if ok else "FAIL", len(cubes), expect))
    return 0 if ok else 1


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--minutes", type=float, default=10)
    p.add_argument("--names", required=True, help="comma-separated ids of your own cubes, e.g. a1B,c2D")
    p.add_argument("--move", action="store_true", help="send the first cube on the mat to (250, 250)")
    try:
        return asyncio.run(run(p.parse_args(argv)))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
