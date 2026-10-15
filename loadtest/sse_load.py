#!/usr/bin/env python3
"""Load test for the public caption stream.

Opens N concurrent SSE viewers (spread across languages) against a running
deployment and reports connection success, captions received per viewer and
delivery delay (server `ts` -> receipt; run from a machine with NTP-synced clock).

    pip install httpx==0.28.1
    python loadtest/sse_load.py --base https://captions.example.com --campus east-hartford \
        --viewers 300 --langs en,es,pt,ht --duration 120

Run it during a live (or simulated) service: start one with the admin
dashboard's "Start service now" and the simulated sender (tools/simulate_sender.py).
Expectations on a 2 vCPU / 4 GB VPS: 1000+ viewers with p95 delivery < 250 ms.
Note: run from several client machines/IPs for > 400 viewers, because the
per-IP stream limit (PUBLIC_MAX_STREAMS_PER_IP) defaults to 400.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time

import httpx


async def viewer(client: httpx.AsyncClient, url: str, lang: str, stop_at: float, stats: dict) -> None:
    try:
        async with client.stream("GET", url, params={"lang": lang}) as resp:
            if resp.status_code != 200:
                stats["rejected"][resp.status_code] = stats["rejected"].get(resp.status_code, 0) + 1
                return
            stats["connected"] += 1
            event = None
            async for line in resp.aiter_lines():
                if time.time() > stop_at:
                    break
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:") and event == "caption":
                    msg = json.loads(line[5:])
                    if msg.get("t") == "caption":
                        stats["captions"] += 1
                        stats["delays"].append((time.time() - msg["ts"]) * 1000)
    except Exception as e:
        stats["errors"][type(e).__name__] = stats["errors"].get(type(e).__name__, 0) + 1


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--base", required=True)
    p.add_argument("--campus", required=True)
    p.add_argument("--viewers", type=int, default=200)
    p.add_argument("--langs", default="en,es")
    p.add_argument("--duration", type=int, default=60)
    p.add_argument("--ramp", type=float, default=10.0, help="seconds over which to open connections")
    a = p.parse_args()

    langs = a.langs.split(",")
    url = f"{a.base.rstrip('/')}/api/public/campus/{a.campus}/stream"
    stats = {"connected": 0, "captions": 0, "delays": [], "rejected": {}, "errors": {}}
    stop_at = time.time() + a.ramp + a.duration
    limits = httpx.Limits(max_connections=a.viewers + 10, max_keepalive_connections=0)
    async with httpx.AsyncClient(timeout=httpx.Timeout(30, read=60), limits=limits, http2=False) as client:
        tasks = []
        for i in range(a.viewers):
            tasks.append(asyncio.create_task(viewer(client, url, langs[i % len(langs)], stop_at, stats)))
            await asyncio.sleep(a.ramp / a.viewers)
        print(f"opened {a.viewers} viewers; running {a.duration}s ...")
        await asyncio.gather(*tasks)

    d = sorted(stats["delays"])
    print(f"connected: {stats['connected']}/{a.viewers}  rejected: {stats['rejected']}  errors: {stats['errors']}")
    print(f"captions received: {stats['captions']} ({stats['captions'] / max(1, stats['connected']):.1f} per viewer)")
    if d:
        print(f"delivery delay ms: p50={statistics.median(d):.0f} p95={d[int(len(d) * 0.95) - 1]:.0f} max={d[-1]:.0f}")


if __name__ == "__main__":
    asyncio.run(main())
