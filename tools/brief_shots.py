"""Before/after screenshots of every surface the copy brief touches.

    python tools/brief_shots.py --out tools/brief-shots/after
    python tools/brief_shots.py --site ../before/site --out tools/brief-shots/before

Four pages at four viewports, plus the states a reader has to activate to see
the parts that only exist after a click: the station browser open, its filters
set, a station selected, and the relationship diagram opened on a phone.

It is not a build step and not a test. Like tools/make_map_previews.py it
needs Chrome and ``websockets``, neither of which is in requirements.txt,
because neither is needed to build or serve the site. It also reports, per
shot, whether the page scrolled sideways, what the console said, and which
font families actually resolved -- the three things the brief asks to be
checked at each width and the three that a picture alone will not show.
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
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

PORT = 8952
CDP_PORT = 9456

# 1920 is in the brief and is captured; the three below it are the ones that
# change the layout, so every state is taken at those and the widest is taken
# of the page as a whole.
VIEWPORTS = {"390x844": (390, 844), "768x1024": (768, 1024),
             "1440x1000": (1440, 1000), "1920x1080": (1920, 1080)}

CHROME = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/usr/bin/google-chrome", "/usr/bin/chromium",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)

# Each entry is (slug, path, viewports, steps). A step is JavaScript run after
# the page settles; it returns when the state it asks for is on screen.
OPEN_RAIL = """
  (() => { const b = document.getElementById('railbtn');
           if (b && b.getAttribute('aria-expanded') !== 'true') b.click();
           return !!b; })()
"""
SET_FILTERS = OPEN_RAIL + """;
  (() => {
    const cp = document.getElementById('rf-cp'), pu = document.getElementById('rf-pulse');
    if (cp) { cp.value = 'yes'; cp.dispatchEvent(new Event('change', {bubbles:true})); }
    if (pu) { pu.value = 'tightening'; pu.dispatchEvent(new Event('change', {bubbles:true})); }
    return [cp && cp.value, pu && pu.value];
  })()
"""
SELECT_STATION = OPEN_RAIL + """;
  (() => { const r = document.querySelector('#srail .rstn');
           if (r) r.click(); return !!r; })()
"""
OPEN_RELATIONS = """
  (() => { const b = document.querySelector('[data-rel]');
           if (b) { b.scrollIntoView({block:'center'}); b.click(); }
           return !!b; })()
"""


def shots(dom: str):
    map_url = f"/{dom}/"
    return [
        ("landing", "/", tuple(VIEWPORTS), None),
        (f"map-{dom}", map_url, tuple(VIEWPORTS), None),
        (f"map-{dom}-rail", map_url, ("1024x900", "1200x900"), OPEN_RAIL),
        (f"map-{dom}-filters", map_url, ("1440x1000",), SET_FILTERS),
        (f"map-{dom}-station", map_url, ("1440x1000",), SELECT_STATION),
        (f"map-{dom}-relations", map_url, ("390x844",), OPEN_RELATIONS),
        ("track-site", "/track/", tuple(VIEWPORTS), None),
        (f"track-{dom}", f"/{dom}/track/", tuple(VIEWPORTS), None),
    ]


EXTRA = {"1024x900": (1024, 900), "1200x900": (1200, 900)}


def size(name):
    return dict(VIEWPORTS, **EXTRA)[name]


# What a picture will not show: a sideways scroll of two pixels, a console
# warning, and a font that silently fell back to the system sans.
PROBE = """
(() => {
  const de = document.documentElement;
  const fonts = [...new Set([...document.querySelectorAll(
      'h1,h2,h3,p,span,b,button,input,li,td,th,summary')]
    .map(e => getComputedStyle(e).fontFamily.split(',')[0].replace(/["']/g,''))
    )];
  return {
    hscroll: de.scrollWidth - de.clientWidth,
    width: de.clientWidth,
    height: de.scrollHeight,
    fonts: fonts,
    loaded: [...document.fonts].filter(f => f.status === 'loaded')
              .map(f => f.family + ' ' + f.weight),
  };
})()
"""


def chrome_binary():
    for p in CHROME:
        if Path(p).is_file():
            return p
    return (shutil.which("chrome") or shutil.which("google-chrome")
            or shutil.which("chromium"))


def page_target(port, timeout=30.0):
    end = time.time() + timeout
    while time.time() < end:
        try:
            raw = urllib.request.urlopen(
                f"http://127.0.0.1:{port}/json/list", timeout=2).read()
            for t in json.loads(raw):
                if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                    return t["webSocketDebuggerUrl"]
        except Exception:
            time.sleep(0.3)
    raise SystemExit("chrome did not expose a page target")


async def run(ws_url, base, out: Path, jobs, settle):
    import websockets
    report = []
    async with websockets.connect(ws_url, max_size=256 * 1024 * 1024) as ws:
        n = 0
        console = []

        async def send(method, **params):
            nonlocal n
            n += 1
            await ws.send(json.dumps({"id": n, "method": method,
                                      "params": params}))
            while True:
                msg = json.loads(await ws.recv())
                if msg.get("method") in ("Runtime.consoleAPICalled",
                                         "Log.entryAdded"):
                    console.append(msg["params"])
                if msg.get("id") == n:
                    if "error" in msg:
                        raise RuntimeError(f"{method}: {msg['error']}")
                    return msg.get("result", {})

        await send("Page.enable")
        await send("Runtime.enable")
        await send("Log.enable")
        for slug, path, widths, step in jobs:
            for w in widths:
                px, py = size(w)
                console.clear()
                await send("Emulation.setDeviceMetricsOverride",
                           width=px, height=py, deviceScaleFactor=1,
                           mobile=px < 500)
                await send("Page.navigate", url=base + path.lstrip("/"))
                await asyncio.sleep(settle)
                if step:
                    r = await send("Runtime.evaluate", expression=step,
                                   returnByValue=True, awaitPromise=True)
                    if r.get("exceptionDetails"):
                        print(f"  ! {slug} {w}: "
                              f"{json.dumps(r['exceptionDetails'])[:200]}")
                    await asyncio.sleep(1.0)
                probe = (await send("Runtime.evaluate", expression=PROBE,
                                    returnByValue=True)
                         ).get("result", {}).get("value", {})
                shot = await send("Page.captureScreenshot", format="png",
                                  captureBeyondViewport=True)
                name = f"{slug}@{w}.png"
                (out / name).write_bytes(base64.b64decode(shot["data"]))
                bad = [c for c in console
                       if (c.get("type") in ("error", "warning")
                           or c.get("level") in ("error", "warning"))]
                report.append({"shot": name, "hscroll": probe.get("hscroll"),
                               "page": [probe.get("width"),
                                        probe.get("height")],
                               "fonts": probe.get("fonts"),
                               "loaded": probe.get("loaded"),
                               "console": [str(c)[:300] for c in bad]})
                flag = "" if not probe.get("hscroll") else \
                    f"  HORIZONTAL SCROLL +{probe['hscroll']}px"
                warn = f"  {len(bad)} console" if bad else ""
                print(f"  {name:<44} {probe.get('height'):>5}px{flag}{warn}")
    return report


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default=str(REPO / "site"))
    ap.add_argument("--out", default=str(REPO / "tools" / "brief-shots"))
    ap.add_argument("--domain", default="semi")
    ap.add_argument("--settle", type=float, default=3.0)
    a = ap.parse_args(argv)

    site = Path(a.site).resolve()
    if not (site / "index.html").exists():
        raise SystemExit(f"{site} has no index.html -- publish the site first")
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    if chrome_binary() is None:
        raise SystemExit("chrome is not installed")
    try:
        import websockets  # noqa: F401
    except ImportError:
        raise SystemExit("pip install websockets")

    srv = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(PORT), "--bind", "127.0.0.1"],
        cwd=str(site), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    profile = tempfile.mkdtemp(prefix="brief-shots-")
    chrome = subprocess.Popen(
        [chrome_binary(), f"--remote-debugging-port={CDP_PORT}",
         f"--user-data-dir={profile}", "--headless=new", "--no-first-run",
         "--no-default-browser-check", "--disable-extensions",
         "--hide-scrollbars", "--force-device-scale-factor=1", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        end = time.time() + 20
        while time.time() < end:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{PORT}/", timeout=1)
                break
            except Exception:
                time.sleep(0.3)
        ws = page_target(CDP_PORT)
        print(f"{site} -> {out}")
        report = asyncio.run(run(ws, f"http://127.0.0.1:{PORT}/", out,
                                 shots(a.domain), a.settle))
    finally:
        for p in (chrome, srv):
            try:
                p.terminate()
                p.wait(timeout=10)
            except Exception:
                p.kill()
        shutil.rmtree(profile, ignore_errors=True)

    (out / "report.json").write_text(json.dumps(report, indent=1),
                                     encoding="utf-8")
    scroll = [r["shot"] for r in report if r["hscroll"]]
    noisy = [r["shot"] for r in report if r["console"]]
    print(f"\n{len(report)} shots")
    print(f"  horizontal scroll: {scroll or 'none'}")
    print(f"  console errors/warnings: {noisy or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
