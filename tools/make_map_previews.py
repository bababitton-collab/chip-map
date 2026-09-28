"""One preview PNG per map, for the cards on the front door.

    python tools/make_map_previews.py            # every map in site/
    python tools/make_map_previews.py --domain energy

WHY THIS IS NOT A BUILD STEP
----------------------------
The map is a <canvas>: the picture does not exist until a browser has run the
page's JavaScript and laid the stations out. Turning that into a PNG needs a
browser, and the build does not have one -- build.yml installs python and node
and nothing else, and chains/ imports no browser driver. Adding one would put
a headless Chrome on the critical path of every publish, so that a picture
nobody had looked at could fail a deploy.

So the previews are made here, by hand, against a local build, and committed.
chains/publish_site.py copies them into site/assets/ exactly as it already
copies the hero preview -- which is the same arrangement, and the reason that
one is a checked-in file too.

REQUIREMENTS
------------
Chrome, and the ``websockets`` package. Neither is in requirements.txt,
because neither is needed to build or serve the site. Run it after a normal
build, with site/ populated.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:      # run as a script, from anywhere
    sys.path.insert(0, str(REPO))
SITE = REPO / "site"
OUT = REPO / "tools" / "map-previews"
PORT = 8951
CDP_PORT = 9455

# The card is a wide strip, so the shot is the map at a wide viewport and the
# canvas band only -- header, rail and board cropped out by clipping to the
# canvas itself.
DESKTOP = (1400, 900)
MOBILE = (760, 900)

CHROME = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/usr/bin/google-chrome", "/usr/bin/chromium",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)

FREEZE = """(() => {
  const s = document.createElement('style');
  s.textContent = '*{transition:none!important;animation:none!important}';
  document.head.appendChild(s);
  // The rail and the board are not in the picture: the card is the map.
  ['#srail', '.railbtnwrap', '.board', '.ledger', '.qcards', '.maphint',
   '.legend', '.cta2'].forEach(sel => {
    document.querySelectorAll(sel).forEach(e => e.style.display = 'none');
  });
  return 1;
})()"""


def chrome_binary() -> str:
    for p in CHROME:
        if Path(p).is_file():
            return p
    got = shutil.which("chrome") or shutil.which("google-chrome") \
        or shutil.which("chromium")
    if got:
        return got
    raise SystemExit("chrome not found -- this tool needs one to draw the map")


class Browser:
    def __init__(self):
        self.profile = tempfile.mkdtemp(prefix="map-preview-")
        self.proc = subprocess.Popen(
            [chrome_binary(), f"--remote-debugging-port={CDP_PORT}",
             f"--user-data-dir={self.profile}", "--headless=new",
             "--no-first-run", "--no-default-browser-check",
             "--disable-extensions", "--hide-scrollbars",
             "--force-device-scale-factor=1", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.ws = self._page()

    @staticmethod
    def _page(timeout: float = 30.0) -> str:
        end = time.time() + timeout
        while time.time() < end:
            try:
                raw = urllib.request.urlopen(
                    f"http://127.0.0.1:{CDP_PORT}/json/list", timeout=2).read()
                for t in json.loads(raw):
                    if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                        return t["webSocketDebuggerUrl"]
            except Exception:
                time.sleep(0.3)
        raise SystemExit("chrome did not expose a page target")

    def close(self):
        try:
            self.proc.terminate()
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()
        shutil.rmtree(self.profile, ignore_errors=True)


async def shoot(ws_url, url, size, dest):
    import websockets
    async with websockets.connect(ws_url, max_size=80 * 1024 * 1024) as ws:
        n = 0

        async def send(method, **params):
            nonlocal n
            n += 1
            await ws.send(json.dumps({"id": n, "method": method, "params": params}))
            while True:
                msg = json.loads(await ws.recv())
                if msg.get("id") == n:
                    if "error" in msg:
                        raise RuntimeError(f"{method}: {msg['error']}")
                    return msg.get("result", {})

        # Device scale 1. The card shows the image at roughly 600 CSS px, so a
        # 1400px-wide capture is already more than twice what it needs; at 2
        # the five previews came to six megabytes of PNG for no visible gain.
        await send("Emulation.setDeviceMetricsOverride", width=size[0],
                   height=size[1], deviceScaleFactor=1, mobile=False)
        await send("Page.enable")
        await send("Page.navigate", url=url)
        await asyncio.sleep(3.2)
        await send("Runtime.evaluate", expression=FREEZE, returnByValue=True)
        await asyncio.sleep(0.5)
        box = await send("Runtime.evaluate", returnByValue=True, expression="""
            (() => { const c = document.getElementById('map');
              if (!c) return null;
              const r = c.getBoundingClientRect();
              return JSON.stringify({x: r.left, y: r.top + scrollY,
                                     w: r.width, h: r.height}); })()""")
        raw = box.get("result", {}).get("value")
        if not raw:
            raise SystemExit(f"no canvas on {url}")
        b = json.loads(raw)
        clip = {"x": max(0, b["x"]), "y": max(0, b["y"]),
                "width": b["w"], "height": b["h"], "scale": 1}
        shot = await send("Page.captureScreenshot", format="png",
                          captureBeyondViewport=True, clip=clip)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(base64.b64decode(shot["data"]))
        return dest


class Served:
    def __init__(self, root: Path, port: int):
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
            cwd=str(root), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        end = time.time() + 20
        while time.time() < end:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1)
                return
            except Exception:
                time.sleep(0.3)
        raise SystemExit("the local server did not come up")

    def close(self):
        try:
            self.proc.terminate()
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", default=None, help="one map, instead of all")
    args = ap.parse_args(argv)

    from chains import domains as registry
    names = [args.domain] if args.domain else registry.discover()
    missing = [n for n in names if not (SITE / n / "index.html").is_file()]
    if missing:
        raise SystemExit(f"no build in site/ for: {', '.join(missing)} -- "
                         f"run the build and publish first")

    served = Served(SITE, PORT)
    browser = Browser()
    try:
        for name in names:
            url = f"http://127.0.0.1:{PORT}/{name}/"
            for size, suffix in ((DESKTOP, ""), (MOBILE, "-mobile")):
                dest = OUT / f"{name}{suffix}.png"
                asyncio.run(shoot(browser.ws, url, size, dest))
                print(f"  {dest.relative_to(REPO)}  {dest.stat().st_size:,} bytes")
    finally:
        browser.close()
        served.close()
    print(f"\nwrote {len(names) * 2} files to {OUT.relative_to(REPO)}")
    print("Add them to data/site.json under map_previews, then publish.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
