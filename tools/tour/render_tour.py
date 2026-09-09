"""Render the live map's tour mode to video.

    python tools/tour/render_tour.py                  # both orientations
    python tools/tour/render_tour.py --only portrait
    python tools/tour/render_tour.py --frames 2,10,21,27
    python tools/tour/render_tour.py --page site/index.html

The page is the source of truth for what the tour looks like. This script does
not know the script, the timings or the layout -- it reads ``window.tourDuration``
off the page and steps ``window.tourSeek(t)`` frame by frame, so a change to the
tour needs no change here.

Seeking rather than recording is the point. ``tourSeek(t)`` renders frame t as a
pure function of t, so the output is identical on a fast machine and a slow one,
and a dropped frame is impossible. Wall-clock screen recording gives neither.

Output goes to ``out/``, never into the repository:

    out/tour_1080x1920.mp4     the vertical cut (reels, stories)
    out/tour_1920x1080.mp4     the landscape cut (Facebook feed)

NOT PART OF CI, AND THE PAGE IT USES IS FROZEN
----------------------------------------------
This is a tool, run by hand, when a video is wanted. It needs Chrome and an
ffmpeg with libx264, neither of which the build assumes.

It also needs a page that HAS a tour: ``window.tourDuration`` and
``window.tourSeek(t)``. The site output does not have one. The tour overlay was
built into a one-off page and was never carried into
chains/templates/live-map.html, so ``live_map.html`` beside this script is that
page, frozen, with the data it was built with. ``--page site/index.html`` is
wired up and will work the day the template grows a tour mode; until then it
exits with that explanation rather than a stack trace from a missing function.

``--ffmpeg`` overrides the search and CHIP_MAP_FFMPEG is honoured, because a
system ffmpeg is not something this repo can assume.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from chains.paths import out_dir                                  # noqa: E402

try:
    import websockets
except ImportError:                                               # pragma: no cover
    sys.exit("render_tour needs the `websockets` package")

# The frozen page with the tour overlay. --page points elsewhere.
PAGE = Path(__file__).resolve().parent / "live_map.html"
VIEWPORTS = {"portrait": (1080, 1920), "landscape": (1920, 1080)}

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/usr/bin/google-chrome",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


def find_chrome() -> str:
    for c in CHROME_CANDIDATES:
        if Path(c).exists():
            return c
    found = shutil.which("chrome") or shutil.which("google-chrome")
    if found:
        return found
    sys.exit("no Chrome found; pass one on PATH or edit CHROME_CANDIDATES")


def find_ffmpeg(override: str | None) -> str:
    for c in (override, os.environ.get("CHIP_MAP_FFMPEG")):
        if c and Path(c).exists():
            return c
    found = shutil.which("ffmpeg")
    if found:
        return found
    sys.exit("no ffmpeg with libx264 found; pass --ffmpeg or set CHIP_MAP_FFMPEG")


def kill_tree(proc: subprocess.Popen) -> None:
    """Kill Chrome and its renderers.

    proc.kill() reaches only the launcher; Chrome's renderer, GPU and utility
    children survive it. A few hundred frames later that is dozens of orphaned
    processes, and the next run's websocket dies on the way up.
    """
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       check=False)
    else:
        proc.kill()
    try:
        proc.wait(timeout=10)
    except Exception:
        pass


class CDP:
    """The smallest CDP client that can seek a page and screenshot it."""

    def __init__(self, ws):
        self.ws = ws
        self.n = 0

    async def send(self, method: str, **params):
        self.n += 1
        await self.ws.send(json.dumps({"id": self.n, "method": method,
                                       "params": params}))
        while True:
            msg = json.loads(await self.ws.recv())
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']['message']}")
                return msg.get("result", {})

    async def js(self, expr: str):
        r = await self.send("Runtime.evaluate", expression=expr,
                            returnByValue=True, awaitPromise=True)
        if "exceptionDetails" in r:
            raise RuntimeError(f"page threw: {r['exceptionDetails'].get('text')}")
        return r["result"].get("value")

    async def shot(self) -> bytes:
        r = await self.send("Page.captureScreenshot", format="png",
                            captureBeyondViewport=False)
        return base64.b64decode(r["data"])


async def open_page(chrome: str, w: int, h: int, profile: Path):
    port = 9400 + (w % 97)
    proc = subprocess.Popen(
        [chrome, "--headless=new", f"--remote-debugging-port={port}",
         f"--user-data-dir={profile}", f"--window-size={w},{h}",
         "--force-device-scale-factor=1", "--hide-scrollbars", "--disable-gpu",
         "--no-first-run", "--no-default-browser-check", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    import urllib.request
    target = None
    for _ in range(80):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list") as r:
                for t in json.load(r):
                    if t["type"] == "page":
                        target = t
                        break
            if target:
                break
        except Exception:
            pass
        await asyncio.sleep(0.25)
    if not target:
        kill_tree(proc)
        sys.exit("Chrome never opened a debugging port")

    ws = await websockets.connect(target["webSocketDebuggerUrl"],
                                  max_size=None, ping_interval=None)
    cdp = CDP(ws)
    await cdp.send("Runtime.enable")
    await cdp.send("Page.enable")
    await cdp.send("Emulation.setDeviceMetricsOverride",
                   width=w, height=h, deviceScaleFactor=1, mobile=False)
    return proc, ws, cdp


def page_or_exit(override: str | None) -> Path:
    """The page to drive, checked for a tour before Chrome is started.

    Without the check the failure is a timeout waiting for a function that is
    never going to exist, which says nothing about why.
    """
    p = Path(override).resolve() if override else PAGE
    if not p.exists():
        sys.exit(f"{p} does not exist")
    if "tourSeek" not in p.read_text(encoding="utf-8", errors="ignore"):
        sys.exit(f"{p} has no tour: window.tourSeek is not defined in it. "
                 f"The tour overlay lives only in the frozen page beside this "
                 f"script; chains/templates/live-map.html has never carried "
                 f"one, so the built site has none either.")
    return p


async def render(name: str, w: int, h: int, fps: int, ffmpeg: str,
                 page: Path, chrome: str, dest: Path, save_frames: list[float]) -> dict:
    profile = Path(tempfile.mkdtemp(prefix=f"tour-{name}-"))
    proc, ws, cdp = await open_page(chrome, w, h, profile)
    try:
        url = page.resolve().as_uri() + "?tour=1"
        await cdp.send("Page.navigate", url=url)

        total = None
        for _ in range(80):                       # wait for the tour to boot
            await asyncio.sleep(0.25)
            total = await cdp.js("window.tourDuration || null")
            if total:
                break
        if not total:
            raise RuntimeError("page never defined window.tourDuration -- "
                               "is the ?tour=1 gate still there?")
        await cdp.js("document.fonts.ready.then(()=>1)")
        missing = await cdp.js("JSON.stringify(window.tourMissing||[])")

        n = int(round(total * fps))
        ff = subprocess.Popen(
            [ffmpeg, "-y", "-f", "image2pipe", "-framerate", str(fps), "-i", "-",
             "-c:v", "libx264", "-preset", "medium", "-crf", "18",
             "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dest)],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)

        saved = {}
        want = sorted(save_frames)
        for f in range(n):
            t = f / fps
            await cdp.js(f"window.tourSeek({t:.4f})")
            png = await cdp.shot()
            ff.stdin.write(png)
            while want and t >= want[0]:
                out = dest.parent / f"tour_{w}x{h}_t{want[0]:g}.png"
                out.write_bytes(png)
                saved[want.pop(0)] = out
            if f % (fps * 5) == 0:
                print(f"  {name}: {t:5.1f}s / {total}s", flush=True)

        ff.stdin.close()
        ff.wait()
        return {"total": total, "frames": n, "missing": json.loads(missing or "[]"),
                "saved": saved}
    finally:
        await ws.close()
        kill_tree(proc)
        shutil.rmtree(profile, ignore_errors=True)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--only", choices=sorted(VIEWPORTS))
    ap.add_argument("--ffmpeg")
    ap.add_argument("--page", help="a page carrying window.tourSeek; "
                                   "defaults to the frozen one beside this script")
    ap.add_argument("--frames", default="",
                    help="comma-separated seconds to also save as PNG "
                         "(from the portrait render)")
    args = ap.parse_args()

    page = page_or_exit(args.page)
    chrome = find_chrome()
    ffmpeg = find_ffmpeg(args.ffmpeg)
    dest_dir = out_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    frames = [float(x) for x in args.frames.split(",") if x.strip()]

    names = [args.only] if args.only else ["portrait", "landscape"]
    for name in names:
        w, h = VIEWPORTS[name]
        dest = dest_dir / f"tour_{w}x{h}.mp4"
        print(f"{name} {w}x{h} -> {dest}")
        r = await render(name, w, h, args.fps, ffmpeg, page, chrome, dest,
                         frames if name == "portrait" else [])
        size = dest.stat().st_size
        print(f"  done: {size:,} bytes, {r['frames']} frames, {r['total']}s")
        if r["missing"]:
            print(f"  WARNING nodes not in data: {r['missing']}")
        for t, p in r["saved"].items():
            print(f"  frame t={t:g}s -> {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
