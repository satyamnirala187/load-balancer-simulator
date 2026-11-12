"""Take the dashboard screenshots used in the slide deck and the demo fallback.

    .venv/bin/python docs/take_screenshots.py

Starts the dashboard (light theme) and a headless Chromium-based browser (Chrome, Brave or Chromium), drives the
page over the DevTools protocol the way the demo does (Tatkal rush, kill app-3 live, Compare view) and writes
docs/screenshots/*.png. Needs the venv from requirements.txt (Streamlit brings the websockets package).
"""
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

from websockets.sync.client import connect

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(ROOT, "docs", "screenshots")
APP_PORT, CDP_PORT = 8767, 9333
BROWSERS = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            "/Applications/Chromium.app/Contents/MacOS/Chromium", "google-chrome", "chromium", "brave-browser"]


class Page:
    def __init__(self, ws):
        self.ws, self.n = ws, 0

    def call(self, method, **params):
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    def js(self, expr):
        return self.call("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)["result"].get("value")

    def wait(self, expr, what, timeout=30):
        end = time.time() + timeout
        while time.time() < end:
            if self.js(expr):
                return
            time.sleep(0.1)
        raise TimeoutError(what)

    def click(self, element_expr, what):
        """Real mouse click at the centre of the element that `element_expr` evaluates to."""
        self.wait(f"!!({element_expr})", what)
        x, y = self.js(f"(() => {{ const r = ({element_expr}).getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; }})()")
        for kind in ("mouseMoved", "mousePressed", "mouseReleased"):
            self.call("Input.dispatchMouseEvent", type=kind, x=x, y=y, button="left", clickCount=1)

    def button(self, text):
        self.click(f"[...document.querySelectorAll('button')].find(b => b.innerText.trim() === {json.dumps(text)})", text)

    def pick(self, select_index, option):
        self.click(f"document.querySelectorAll('[data-testid=\"stSelectbox\"] input[role=\"combobox\"]')[{select_index}]", f"select {select_index}")
        self.click(f"[...document.querySelectorAll('[role=\"option\"]')].find(o => o.innerText.trim() === {json.dumps(option)})", option)
        time.sleep(0.8)

    def sim_seconds(self):
        text = self.js("document.querySelector('.status')?.innerText || ''")  # e.g. "Running · 9.0 s / 20 s · ..."
        m = re.search(r"([\d.]+) s /", text)
        return float(m.group(1)) if m else 0.0

    def shot(self, name):
        os.makedirs(OUT, exist_ok=True)
        data = self.call("Page.captureScreenshot", format="png")["data"]
        with open(os.path.join(OUT, name), "wb") as f:
            f.write(base64.b64decode(data))
        print("wrote", os.path.join("docs", "screenshots", name))


def find_browser():
    for b in BROWSERS:
        if os.path.exists(b) or shutil.which(b):
            return b
    sys.exit("No Chrome, Brave or Chromium found; set BROWSERS in this script.")


def wait_http(url, what, timeout=40):
    end = time.time() + timeout
    while time.time() < end:
        try:
            return urllib.request.urlopen(url, timeout=2).read()
        except OSError:
            time.sleep(0.3)
    raise TimeoutError(what)


def main():
    profile = tempfile.mkdtemp()
    app = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "dashboard.py", "--server.headless", "true",
                            "--server.port", str(APP_PORT), "--theme.base", "light", "--browser.gatherUsageStats", "false"],
                           cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    browser = subprocess.Popen([find_browser(), "--headless=new", f"--remote-debugging-port={CDP_PORT}", f"--user-data-dir={profile}",
                                "--no-first-run", "--no-default-browser-check", "--hide-scrollbars", "about:blank"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_http(f"http://localhost:{APP_PORT}/_stcore/health", "dashboard")
        wait_http(f"http://127.0.0.1:{CDP_PORT}/json/version", "browser")
        target = next(t for t in json.loads(wait_http(f"http://127.0.0.1:{CDP_PORT}/json", "page target")) if t["type"] == "page")
        with connect(target["webSocketDebuggerUrl"], max_size=None) as ws:
            p = Page(ws)
            p.call("Emulation.setDeviceMetricsOverride", width=1440, height=900, deviceScaleFactor=1.5, mobile=False)
            # config.toml defines a light and a dark theme, so Streamlit follows the browser's colour scheme: ask for light
            p.call("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "light"}])
            p.call("Page.navigate", url=f"http://localhost:{APP_PORT}/")
            p.wait("document.body.innerText.includes('Ready')", "dashboard to load")
            p.pick(0, "Sudden spike (Tatkal rush)")
            p.pick(1, "Weighted Least Conn.")
            p.pick(2, "app-3")
            p.button("Start")
            p.wait("true", "start")
            while p.sim_seconds() < 9.0:  # the rush runs from 8 s to 12 s of the 20 s run
                time.sleep(0.05)
            p.button("Kill")
            while p.sim_seconds() < 14.6:  # past detection (0.5 s) and past the rush: app-3's bar has drained
                time.sleep(0.05)
            p.js("document.querySelectorAll('[data-testid=\"stToast\"]').forEach(t => t.remove())")  # it covers the disclaimer
            p.shot("01_live_view_after_kill.png")
            p.wait("document.body.innerText.includes('Finished')", "run to finish", 30)
            p.click("[...document.querySelectorAll('label')].find(l => l.innerText.trim() === 'Compare all 3')", "compare view")
            time.sleep(2)
            p.shot("02_compare_view.png")
            p.js("(() => { const m = document.querySelector('[data-testid=\"stMain\"]'); const c = [...document.querySelectorAll('.gloss')].find(e => e.innerText.startsWith('Failover')); m.scrollTo(0, c.getBoundingClientRect().top + m.scrollTop - 60); })()")
            time.sleep(1)
            p.shot("03_compare_tables.png")
    finally:
        browser.terminate()
        app.terminate()
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    main()
