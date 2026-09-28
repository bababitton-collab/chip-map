"""A throwaway Chrome, driven over CDP, at an exact CSS viewport.

Some rules can only be checked against a real layout. "No layer label wraps
inside a word at 1200, 1280 and 1440" is one: it depends on the browser's line
breaker, the loaded font and the column arithmetic at that width, and none of
those exist in a string comparison.

Everything here skips rather than fails when the machine has no Chrome or no
websockets, the same way the node harnesses skip: CI runs the suite before the
build and has neither, so this is a local guarantee, and the source-level
checks beside it are the ones that run everywhere.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

import pytest

CHROME_PATHS = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)


def chrome_binary():
    for p in CHROME_PATHS:
        if Path(p).is_file():
            return p
    return shutil.which("chrome") or shutil.which("google-chrome") \
        or shutil.which("chromium")


def require():
    """Skip unless this machine can actually run the check."""
    if chrome_binary() is None:
        pytest.skip("chrome is not installed")
    try:
        import websockets  # noqa: F401
    except ImportError:
        pytest.skip("websockets is not installed")


class Browser:
    """One headless Chrome and one page, for the length of a test module."""

    def __init__(self, port: int = 9444):
        self.port = port
        self.profile = tempfile.mkdtemp(prefix="chip-map-test-")
        self.proc = subprocess.Popen(
            [chrome_binary(), f"--remote-debugging-port={port}",
             f"--user-data-dir={self.profile}", "--headless=new",
             "--no-first-run", "--no-default-browser-check",
             "--disable-extensions", "--hide-scrollbars",
             "--force-device-scale-factor=1", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.ws_url = self._page(port)

    @staticmethod
    def _page(port, timeout=30.0):
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
        raise RuntimeError("chrome did not expose a page target")

    def close(self):
        try:
            self.proc.terminate()
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()
        shutil.rmtree(self.profile, ignore_errors=True)

    def measure(self, url, width, height, script, settle=2.2):
        """Load url at an exact viewport and return the script's value."""
        return asyncio.run(self._measure(url, width, height, script, settle))

    async def _measure(self, url, width, height, script, settle):
        import websockets
        async with websockets.connect(self.ws_url,
                                      max_size=64 * 1024 * 1024) as ws:
            n = 0

            async def send(method, **params):
                nonlocal n
                n += 1
                await ws.send(json.dumps({"id": n, "method": method,
                                          "params": params}))
                while True:
                    msg = json.loads(await ws.recv())
                    if msg.get("id") == n:
                        if "error" in msg:
                            raise RuntimeError(f"{method}: {msg['error']}")
                        return msg.get("result", {})

            await send("Emulation.setDeviceMetricsOverride", width=width,
                       height=height, deviceScaleFactor=1, mobile=False)
            await send("Page.enable")
            await send("Page.navigate", url=url)
            await asyncio.sleep(settle)
            r = await send("Runtime.evaluate", expression=script,
                           returnByValue=True, awaitPromise=True)
            if r.get("exceptionDetails"):
                raise RuntimeError(json.dumps(r["exceptionDetails"])[:400])
            return r.get("result", {}).get("value")


class Served:
    """A directory on a local port, for the length of a test module."""

    def __init__(self, root: Path, port: int = 8933):
        self.port = port
        self.proc = subprocess.Popen(
            ["python", "-m", "http.server", str(port), "--bind", "127.0.0.1"],
            cwd=str(root), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        end = time.time() + 20
        while time.time() < end:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1)
                return
            except Exception:
                time.sleep(0.3)
        raise RuntimeError("the test server did not come up")

    def url(self, path=""):
        return f"http://127.0.0.1:{self.port}/{path.lstrip('/')}"

    def close(self):
        try:
            self.proc.terminate()
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()
