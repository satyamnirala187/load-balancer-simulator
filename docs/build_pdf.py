"""Render docs/COMPLEXITY.md to docs/COMPLEXITY.pdf.

    .venv/bin/pip install -r docs/requirements.txt
    .venv/bin/python docs/build_pdf.py

markdown -> HTML with print CSS -> a headless Chromium-based browser (Chrome, Brave or Chromium), driven over the DevTools
protocol, prints it to A4 -> pypdf stamps the SHA-256 of the markdown into the PDF's Keywords. tests/test_docs.py compares that
hash with the current markdown, so a PDF that was not rebuilt after an edit fails the tests.
"""
import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile

import markdown
from pypdf import PdfReader, PdfWriter
from websockets.sync.client import connect

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from take_screenshots import BROWSERS, Page, find_browser, wait_http  # noqa: E402  (the same small DevTools client)

CDP_PORT = 9334
HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE, TARGET = os.path.join(HERE, "COMPLEXITY.md"), os.path.join(HERE, "COMPLEXITY.pdf")

CSS = """
@page { size: A4; margin: 14mm 15mm 16mm 15mm; }
body { font: 9.2pt/1.36 "Helvetica Neue", Helvetica, Arial, sans-serif; color: #14213d; margin: 0; }
h1 { font: 700 17pt Georgia, "Times New Roman", serif; margin: 0 0 6pt; }
h2 { font: 700 11.2pt Georgia, "Times New Roman", serif; margin: 11pt 0 4pt; break-after: avoid; }
h2:nth-of-type(6) { break-before: page; }  /* section 6 (measurements) starts page 3 so its table stays with its heading */
p { margin: 4pt 0; }
pre { font: 7.5pt/1.3 Menlo, "SF Mono", Consolas, "Courier New", monospace; background: #f1f4f9; padding: 5pt 8pt; margin: 5pt 0;
      border-radius: 3pt; white-space: pre; overflow: hidden; break-inside: avoid; -webkit-print-color-adjust: exact; }
code { font: 8.1pt Menlo, "SF Mono", Consolas, "Courier New", monospace; background: #eef1f6; padding: 0 2pt; border-radius: 2pt;
       -webkit-print-color-adjust: exact; }
pre code { background: none; padding: 0; font-size: inherit; }
table { border-collapse: collapse; width: 100%; font-size: 8.2pt; margin: 5pt 0; break-inside: avoid; }
th, td { border: 0.5pt solid #c9d1e0; padding: 2pt 5pt; vertical-align: top; text-align: left; }
th { background: #eef1f6; -webkit-print-color-adjust: exact; }
ul, ol { margin: 4pt 0; padding-left: 15pt; } li { margin: 1.5pt 0; }
"""


def main():
    raw = open(SOURCE, "rb").read()
    body = markdown.markdown(raw.decode("utf-8"), extensions=["tables", "fenced_code"])
    html = f"<!doctype html><html><head><meta charset='utf-8'><title>Load Balancer Simulator: complexity analysis</title><style>{CSS}</style></head><body>{body}</body></html>"
    with tempfile.TemporaryDirectory() as tmp:
        page, raw_pdf = os.path.join(tmp, "doc.html"), os.path.join(tmp, "raw.pdf")
        open(page, "w", encoding="utf-8").write(html)
        browser = subprocess.Popen([find_browser(), "--headless=new", f"--remote-debugging-port={CDP_PORT}", f"--user-data-dir={tmp}/profile",
                                    "--no-first-run", "--no-default-browser-check", "about:blank"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            wait_http(f"http://127.0.0.1:{CDP_PORT}/json/version", "browser")
            target = next(t for t in json.loads(wait_http(f"http://127.0.0.1:{CDP_PORT}/json", "page target")) if t["type"] == "page")
            with connect(target["webSocketDebuggerUrl"], max_size=None) as ws:
                p = Page(ws)
                p.call("Page.navigate", url="file://" + page)
                p.wait("document.readyState === 'complete'", "page to load")
                footer = ("<div style='width:100%;font:8pt Helvetica,Arial,sans-serif;color:#6b7a99;text-align:center'>"
                          "<span class='pageNumber'></span> / <span class='totalPages'></span></div>")
                pdf = p.call("Page.printToPDF", printBackground=True, preferCSSPageSize=True, displayHeaderFooter=True,
                             headerTemplate="<span></span>", footerTemplate=footer)["data"]
            open(raw_pdf, "wb").write(base64.b64decode(pdf))
        finally:
            browser.terminate()
        writer = PdfWriter(clone_from=PdfReader(raw_pdf))
        writer.add_metadata({"/Title": "Load Balancer Simulator: complexity analysis", "/Author": "Satyam Nirala and Raghav Sihag",
                             "/Keywords": "source-sha256:" + hashlib.sha256(raw).hexdigest()})
        with open(TARGET, "wb") as f:
            writer.write(f)
    print(f"wrote docs/COMPLEXITY.pdf ({len(PdfReader(TARGET).pages)} pages)")


if __name__ == "__main__":
    main()
