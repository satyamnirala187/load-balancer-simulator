"""Build the 10-slide deck: slides/RailDhaara_LoadBalancer.pptx

    .venv/bin/pip install -r slides/requirements.txt
    .venv/bin/python slides/build_deck.py

Every figure on a slide comes from lbsim.facts (computed from the simulator), docs/bench_results.json, or the
short list of structural constants in STRUCTURAL below. tests/test_docs.py rebuilds the numbers and fails if the
saved deck disagrees, so after changing code or docs: rebuild the deck.
"""
import io
import os
import re
import sys
import unittest

from lxml import etree
from PIL import Image
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_MARKER_STYLE, XL_TICK_LABEL_POSITION
from pptx.enum.dml import MSO_THEME_COLOR as T
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

from lbsim import facts  # noqa: E402
from lbsim.servers import FLEET  # noqa: E402
from lbsim.traffic import make_scenario  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "RailDhaara_LoadBalancer.pptx")
SHOT = os.path.join(ROOT, "docs", "screenshots", "01_live_view_after_kill.png")
# The capture ends mid-way through the two line charts, and a plain crop above them still slices the sidebar's help text.
# Row 1108 is blank in BOTH columns: below the Kill/Revive buttons and above their help text (sidebar), and below the bar
# charts and above their legends (main area). The file in docs/ stays the full capture.
SHOT_KEEP_PX = 1108
REPO = "github.com/satyamnirala187/load-balancer-simulator"
PARTNER = "Raghav Sihag"

W, H = 13.333, 7.5
LEFT = 0.7
CW = W - 2 * LEFT

THEME = {"dk1": "14213D", "lt1": "FFFFFF", "dk2": "5B6B8C", "lt2": "EEF1F6", "accent1": "4C78A8", "accent2": "D97706",
         "accent3": "2F9E44", "accent4": "E45756", "accent5": "F2A900", "accent6": "7B8DB0", "hlink": "4C78A8", "folHlink": "7B8DB0"}
RGB = {k: RGBColor.from_string(v) for k, v in THEME.items()}
ALGO_COLOR = {"Round Robin": "accent2", "Least Connections": "accent1", "Weighted Least Conn.": "accent3"}

# Numbers on the slides that are not measurements: design constants and the illustrative heap example.
STRUCTURAL = {"1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "27", "390", "9.6", "0.20", "0.25", "0.33", "0.67", "17",
              "100", "400", "1,000", "100,000", "50,000", "0.5", "2026", "42"}  # 42 = the seed


# --------------------------------------------------------------------------------------------------------- numbers
def test_count():
    suite = unittest.defaultTestLoader.discover(os.path.join(ROOT, "tests"), top_level_dir=ROOT)
    return suite.countTestCases()


def numbers():
    """Every formatted figure the slides quote. The test uses the same dict to check the saved deck."""
    cap, bench, sk = facts.capacity(), facts.bench(), facts.spike_kill()
    bw, lat = facts.blind_window(), facts.spike_latency()
    heap_rows = {r["servers"]: r for r in bench["heap_vs_linear"]}
    cell = lambda pat, alg: facts.load_cell(pat, 10000, alg)
    N = {"full": str(cap["full"]), "survivors": str(cap["survivors"]), "ceiling": f"{cap['ceiling_pct']}%",
         "heap5": f"{heap_rows[5]['heap_us']:.2f}", "scan5": f"{heap_rows[5]['linear_us']:.2f}",
         "ratio50k": f"{heap_rows[50000]['linear_over_heap']:.0f}×",
         "bw_lc_2s": str(bw[2000, 0]["Least Connections"]), "bw_lc_pass": str(bw[2000, 3]["Least Connections"]),
         "spike_wlc": cell("spike", "Weighted Least Conn.")["failed_pct"], "spike_lc": cell("spike", "Least Connections")["failed_pct"],
         "spike_rr": cell("spike", "Round Robin")["failed_pct"], "lat_lc": lat["avg_ms"]["Least Connections"],
         "lat_wlc": lat["avg_ms"]["Weighted Least Conn."], "burst_rr": cell("burst", "Round Robin")["failed_pct"],
         "burst_wlc": cell("burst", "Weighted Least Conn.")["failed_pct"], "tests": str(test_count()), "floor": f"{facts.burst()['floor_pct']}%",
         "kill_ok": " / ".join(sk[0][n][1] for n in facts.NAMES),
         "spread1k": f"{facts.stability()[1000]['req_s']:.1f}%",
         "steady400": " / ".join(f"{float(facts.capacity()['sweep'][400]['survivors'][i]):.1f}%" for i in range(3))}
    return N


def chart_data():
    """The series behind the three charts: slide -> list of series values."""
    bw, sk = facts.blind_window(), facts.spike_kill()
    per_second = [0] * 20
    for r in make_scenario("spike", facts.SEED, 20, facts.RATE).requests:
        per_second[min(int(r.arrival_ms // 1000), 19)] += 1
    ivs = (2000, 500, 100)
    return {2: [per_second, [facts.capacity()["full"]] * 20],
            5: [[bw[iv, 0]["Round Robin"] for iv in ivs], [bw[iv, 0]["Least Connections"] for iv in ivs],
                [bw[iv, 3]["Least Connections"] for iv in ivs]],
            8: [[float(sk[0][n][1].rstrip("%"))] for n in facts.NAMES]}


def required_by_slide():
    """slide number -> strings that must appear on it (used by the drift test)."""
    N = numbers()
    return {2: [N["full"]],
            4: [N["heap5"], N["scan5"], N["ratio50k"]],
            7: [f"{facts.load_cell(p, 10000, a)['failed_pct']} · {facts.load_cell(p, 10000, a)['avg_ms']} ms"
                for p in ("normal", "spike", "slow_server", "burst") for a in facts.NAMES],
            8: [N["survivors"], N["ceiling"], N["steady400"]],
            9: [N["spread1k"], N["survivors"]],
            10: [N["spike_wlc"], N["spike_lc"], N["spike_rr"], N["bw_lc_2s"], N["bw_lc_pass"], N["survivors"], N["tests"]]}


# ------------------------------------------------------------------------------------------------------ primitives
def patch_theme(prs):
    """Colours and fonts live in the theme, so the whole deck restyles from one place."""
    part = prs.slide_master.part.part_related_by(RT.THEME)
    root = etree.fromstring(part.blob)
    a = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
    scheme = root.find(f".//{a}clrScheme")
    scheme.set("name", "RailDhaara")
    for child in scheme:
        key = etree.QName(child).localname
        for old in list(child):
            child.remove(old)
        etree.SubElement(child, f"{a}srgbClr").set("val", THEME[key])
    fonts = root.find(f".//{a}fontScheme")
    fonts.set("name", "RailDhaara")
    fonts.find(f"{a}majorFont/{a}latin").set("typeface", "Cambria")
    fonts.find(f"{a}minorFont/{a}latin").set("typeface", "Arial")
    part._blob = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def patch_master_and_layout(prs):
    """Title style (Cambria 36 bold, left) on the master; title position on the 'Title Only' layout."""
    lvl1 = prs.slide_master._element.find(".//" + qn("p:titleStyle")).find(qn("a:lvl1pPr"))
    lvl1.set("algn", "l")
    rpr = lvl1.find(qn("a:defRPr"))
    rpr.set("sz", "3600")
    rpr.set("b", "1")
    layout = prs.slide_layouts[5]
    title = layout.placeholders[0]
    title.left, title.top, title.width, title.height = Inches(LEFT), Inches(0.45), Inches(CW), Inches(0.95)
    title.text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
    title.text_frame.margin_left = 0  # line up with the body text
    return layout


def plain(shape):
    """Drop the theme style reference so no inherited shadow or outline sneaks in."""
    style = shape._element.find(qn("p:style"))
    if style is not None:
        shape._element.remove(style)
    return shape


def set_color(color_format, value):
    if isinstance(value, str):  # theme key like "accent2"
        color_format.theme_color = {"dk1": T.TEXT_1, "dk2": T.TEXT_2, "lt1": T.BACKGROUND_1, "lt2": T.BACKGROUND_2,
                                    "accent1": T.ACCENT_1, "accent2": T.ACCENT_2, "accent3": T.ACCENT_3,
                                    "accent4": T.ACCENT_4, "accent5": T.ACCENT_5, "accent6": T.ACCENT_6}[value]
    else:
        color_format.rgb = value


def box(slide, x, y, w, h, fill="lt2", shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.08, line=None, name=None):
    s = plain(slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h)))
    if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        s.adjustments[0] = radius
    if fill:
        s.fill.solid()
        set_color(s.fill.fore_color, fill)
    else:
        s.fill.background()
    if line:
        set_color(s.line.color, line)
        s.line.width = Pt(1)
    else:
        s.line.fill.background()
    if name:
        s.name = name
    return s


def nb(t):
    """Keep a number and its unit on one line."""
    return re.sub(r"(\d) (ms|req/s|µs|s|px)\b", "\\1\u00a0\\2", t)


def text(slide, x, y, w, h, paras, size=16, color="dk1", bold=False, font=None, align=None, anchor=MSO_ANCHOR.TOP,
         space_after=0, shape=None, name=None, spacing=None, wrap=True):
    """paras: a string, or a list of paragraphs; a paragraph is a string or a list of runs; a run is a string or
    (string, {size, bold, color, font, italic})."""
    s = shape or slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = s.text_frame
    tf.word_wrap = wrap
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    if name:
        s.name = name
    paras = [paras] if isinstance(paras, str) else paras
    for i, para in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        if align:
            p.alignment = align
        p.space_after = Pt(space_after)
        if spacing:
            p.line_spacing = spacing
        for run in ([para] if isinstance(para, (str, tuple)) else para):
            t, o = (run, {}) if isinstance(run, str) else run
            r = p.add_run()
            r.text = nb(t)
            r.font.size = Pt(o.get("size", size))
            r.font.bold = o.get("bold", bold)
            r.font.italic = o.get("italic", False)
            set_color(r.font.color, o.get("color", color))
            fn = o.get("font", font)
            if fn:
                r.font.name = fn
    return s


def line(slide, x1, y1, x2, y2, color="dk2", width=1.5):
    c = plain(slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2)))
    set_color(c.line.color, color)
    c.line.width = Pt(width)
    return c


def new_slide(prs, layout, title, dark=False, notes=""):
    s = prs.slides.add_slide(layout)
    s.shapes.title.text = title
    if dark:
        s.background.fill.solid()
        set_color(s.background.fill.fore_color, "dk1")
        for r in s.shapes.title.text_frame.paragraphs[0].runs:
            set_color(r.font.color, "lt1")
    else:
        number(s, len(prs.slides))
    if notes:
        s.notes_slide.notes_text_frame.text = notes
    return s


def number(slide, n):
    """Slide number as a real field (renumbers itself when slides move)."""
    tb = text(slide, W - LEFT - 0.6, H - 0.55, 0.6, 0.3, "", size=11, color="dk2", align=PP_ALIGN.RIGHT, name="Slide number")
    p = tb.text_frame.paragraphs[0]._p
    for r in p.findall(qn("a:r")):
        p.remove(r)
    fld = etree.SubElement(p, qn("a:fld"), id="{B6F15528-21DE-4FAA-801E-634DDDAF4B2B}", type="slidenum")
    rpr = etree.SubElement(fld, qn("a:rPr"), lang="en-US", sz="1100")
    fill = etree.SubElement(rpr, qn("a:solidFill"))
    etree.SubElement(fill, qn("a:schemeClr"), val="tx2")
    etree.SubElement(fld, qn("a:t")).text = str(n)


def alt(shape, description):
    shape._element.xpath(".//p:cNvPr")[0].set("descr", description)


def legend(slide, x, y, items, size=12):
    """A legend we lay out ourselves (chart legends overlap in some renderers): coloured dot + label per item."""
    for label, color in items:
        box(slide, x, y + 0.06, 0.16, 0.16, fill=color, shape=MSO_SHAPE.OVAL, name=f"Key {label}")
        w = len(label) * 0.082 * size / 12
        text(slide, x + 0.24, y, w, 0.3, label, size=size, color="dk1", wrap=False)
        x += 0.24 + w + 0.18


def skip_labels(chart, n):
    cat = chart.category_axis._element
    el = etree.Element(qn("c:tickLblSkip"))
    el.set("val", str(n))
    nm = cat.find(qn("c:noMultiLvlLbl"))
    nm.addprevious(el) if nm is not None else cat.append(el)


def style_chart(chart, size=12):
    chart.font.size = Pt(size)
    chart.font.color.rgb = RGB["dk1"]
    chart.has_title = False


def style_axes(chart, vmax=None, vmin=0, unit=None, fmt=None, cat_title=None):
    va, ca = chart.value_axis, chart.category_axis
    va.minimum_scale = vmin
    if vmax is not None:
        va.maximum_scale = vmax
    if unit:
        va.major_unit = unit
    va.has_major_gridlines = True
    va.major_gridlines.format.line.color.rgb = RGBColor(0xDD, 0xE2, 0xEB)
    va.format.line.fill.background()
    va.tick_labels.font.size = Pt(12)
    if fmt:
        va.tick_labels.number_format, va.tick_labels.number_format_is_linked = fmt, False
    ca.tick_labels.font.size = Pt(12)
    ca.format.line.color.rgb = RGBColor(0xB8, 0xC1, 0xD1)
    ca.has_major_gridlines = False
    if cat_title:
        ca.has_title = True
        ca.axis_title.text_frame.text = cat_title
        ca.axis_title.text_frame.paragraphs[0].runs[0].font.size = Pt(12)
        ca.axis_title.text_frame.paragraphs[0].runs[0].font.bold = False


# ------------------------------------------------------------------------------------------------------------ slides
def slide_title(prs, layout):
    s = new_slide(prs, layout, "Load Balancer\vSimulator", dark=True, notes=(
        "About 0:20. Say the name, the course, and that the demo scenario is a fictional booking site."))
    t = s.shapes.title
    t.left, t.top, t.width, t.height = Inches(0.9), Inches(2.3), Inches(7.4), Inches(2.1)
    t.text_frame.vertical_anchor = MSO_ANCHOR.BOTTOM
    for r in t.text_frame.paragraphs[0].runs:
        r.font.size = Pt(54)
    text(s, 0.9, 1.75, 7.2, 0.35, "ALGORITHMS  ·  PROJECT 27  ·  GREEDY + HEAP", size=13, color="accent5", bold=True)
    text(s, 0.9, 4.65, 6.6, 0.9, "Demo scenario: the 10 AM Tatkal rush on RailDhaara, a fictional booking site", size=22, color="lt2", spacing=1.1)
    text(s, 0.9, 6.35, 7.4, 0.35, f"Satyam Nirala and {PARTNER}", size=16, color="lt1")
    x0, base, unit = 8.75, 5.75, 0.42  # the fleet: five servers, bar height = weight
    text(s, x0, 1.75, 3.9, 0.3, "FIVE SERVERS, BAR HEIGHT = WEIGHT", size=12, color="lt2", bold=True)
    for i, (sid, weight, _ms) in enumerate(FLEET):
        x, h = x0 + i * 0.8, weight * unit
        box(s, x, base - h, 0.55, h, fill="accent1", radius=0.2, name=f"Bar {sid}")
        text(s, x, base - h - 0.4, 0.55, 0.3, str(weight), size=16, color="lt1", bold=True, align=PP_ALIGN.CENTER)
        text(s, x - 0.1, base + 0.1, 0.75, 0.3, sid, size=12, color="lt2", align=PP_ALIGN.CENTER)
    return s


def slide_rush(prs, layout, N, charts):
    s = new_slide(prs, layout, "10 AM: everyone arrives at once", notes=(
        "About 0:45. Booking opens at a fixed time and the whole queue arrives together. That is the shape of load we model: "
        "100 requests a second on a normal morning, four times that in the rush, ten times in a burst. The dashed line is what the "
        "five servers can sustain, an estimate. The rush brushes it. That is why the algorithms only separate under the spike.\n"
        "Say it is synthetic: no IRCTC data."))
    stats = [("100", "req/s, a normal morning", "dk2"), ("400", "req/s, the Tatkal rush (×4)", "accent2"),
             ("1,000", "req/s, a sudden burst (×10)", "accent4")]
    for i, (big, label, col) in enumerate(stats):
        y = 1.85 + i * 1.2
        text(s, LEFT, y, 2.5, 0.9, big, size=44, color=col, bold=True, anchor=MSO_ANCHOR.MIDDLE)
        text(s, LEFT + 2.6, y, 3.0, 0.9, label, size=16, color="dk1", anchor=MSO_ANCHOR.MIDDLE)
    text(s, LEFT, 5.55, 5.5, 0.9, [[("Five servers sustain about ", {}), (N["full"], {"bold": True}),
                                    (" req/s in total. That figure is an estimate from our latency model.", {})]],
         size=14, color="dk1", spacing=1.1)
    text(s, 6.9, 1.7, 5.7, 0.35, "Requests arriving per second in one simulated rush", size=14, bold=True)
    cd = CategoryChartData()
    cd.categories = [str(i) for i in range(20)]
    cd.add_series("Arriving", charts[2][0])
    cd.add_series("Fleet capacity (estimate)", charts[2][1])
    gf = s.shapes.add_chart(XL_CHART_TYPE.LINE, Inches(6.9), Inches(2.1), Inches(5.73), Inches(3.55), cd)
    alt(gf, "Line chart: arrivals per second jump from about 100 to about 400 between seconds 8 and 12, close to the estimated fleet capacity.")
    chart = gf.chart
    style_chart(chart)
    style_axes(chart, vmax=500, unit=100, cat_title="seconds into the run")
    skip_labels(chart, 2)
    chart.has_legend = False
    for ser, col, dash in ((chart.plots[0].series[0], "accent2", False), (chart.plots[0].series[1], "dk2", True)):
        ser.smooth = False
        ser.marker.style = XL_MARKER_STYLE.NONE
        ser.format.line.width = Pt(2.75)
        ser.format.line.color.rgb = RGB[col]
        if dash:
            ser.format.line.dash_style = 4  # MSO_LINE.DASH
    legend(s, 6.95, 5.75, [("Arriving per second", "accent2"), ("Fleet capacity (estimate)", "dk2")])
    text(s, LEFT, 6.55, 8, 0.3, "Synthetic traffic and invented servers. No IRCTC data.", size=12, color="dk2")
    return s


def slide_algorithms(prs, layout):
    s = new_slide(prs, layout, "Three ways to pick a server", notes=(
        "About 0:40. Round Robin takes turns. Least Connections picks the server with the fewest open connections. "
        "Weighted Least Connections divides by the server's weight, so a big server is allowed more. "
        "The last two are greedy: each request goes to the best server at that moment, no look-ahead."))
    cards = [("Round Robin", "Next healthy server, in a fixed order", "Load and server size", "O(1), more when servers are down"),
             ("Least Connections", "Fewest open connections", "Server size", "O(log n), with a heap"),
             ("Weighted Least Conn.", "Lowest connections ÷ weight", "Response time", "O(log n), with a heap")]
    cw, gap = 3.75, 0.34
    for i, (name, rule, ignores, cost) in enumerate(cards):
        x = LEFT + i * (cw + gap)
        box(s, x, 1.75, cw, 4.5, fill="lt2", name=f"Card {name}")
        box(s, x + 0.3, 2.2, 0.3, 0.3, fill=ALGO_COLOR[name], shape=MSO_SHAPE.OVAL, name=f"Colour {name}")
        text(s, x + 0.75, 1.9, cw - 1.0, 1.0, name, size=20, bold=True, font="+mj-lt", anchor=MSO_ANCHOR.MIDDLE)
        for j, (label, value) in enumerate((("Picks", rule), ("Ignores", ignores), ("Cost per pick", cost))):
            y = 3.0 + j * 1.07
            text(s, x + 0.3, y, cw - 0.6, 0.3, label.upper(), size=11, bold=True, color="dk2")
            text(s, x + 0.3, y + 0.3, cw - 0.6, 0.6, value, size=16, color="dk1")
    text(s, LEFT, 6.5, CW, 0.5, [[("Least Connections and Weighted Least Connections are greedy: ", {"bold": True}),
                                  ("each request goes to the best server now.", {})]], size=16)
    return s


def slide_heap(prs, layout, N):
    s = new_slide(prs, layout, "One heap, O(log n) per request", notes=(
        "About 1:15. The servers sit in a min-heap keyed by connections over weight, so the least loaded one is always the root. "
        "A pick reads the root, counts the connection and sifts down. A finished request lowers a key and sifts up. "
        "A server going down is removed, coming back is pushed. All logarithmic. The lock covers pick and count together, "
        "so two requests can never choose from the same stale count.\n"
        "Be honest about the numbers: at our five servers a plain scan is actually faster. The heap wins above roughly twenty servers."))
    text(s, LEFT, 1.65, 5.8, 0.3, "EXAMPLE: CONNECTIONS ÷ WEIGHT, LOWEST AT THE ROOT", size=11, bold=True, color="dk2")
    nodes = {"app-3": (3.85, 2.5, "1 ÷ 5 = 0.20"), "app-1": (2.5, 3.65, "2 ÷ 8 = 0.25"), "app-4": (5.2, 3.65, "1 ÷ 4 = 0.25"),
             "app-2": (1.55, 4.8, "2 ÷ 6 = 0.33"), "app-5": (3.45, 4.8, "2 ÷ 3 = 0.67")}
    for parent, child in (("app-3", "app-1"), ("app-3", "app-4"), ("app-1", "app-2"), ("app-1", "app-5")):
        (px, py, _), (cx, cy, _) = nodes[parent], nodes[child]
        line(s, px, py + 0.38, cx, cy - 0.38, color="dk2", width=1.5)
    for sid, (cx, cy, label) in nodes.items():
        root = sid == "app-3"
        n = box(s, cx - 0.8, cy - 0.38, 1.6, 0.76, fill="accent5" if root else "lt2", line=None if root else "accent6", name=f"Node {sid}")
        text(s, 0, 0, 0, 0, [[(sid, {"bold": True, "size": 14})], [(label, {"size": 12})]], shape=n, align=PP_ALIGN.CENTER,
             anchor=MSO_ANCHOR.MIDDLE)
    text(s, 4.8, 2.25, 1.9, 0.5, "← next pick", size=14, bold=True, color="dk1")
    ops = [("Pick", "read the root, count it, sift down"),
           ("Request finishes", "lower that server's key, sift up"),
           ("Server dies or returns", "remove it from the heap, or push it back")]
    text(s, 7.0, 1.65, 5.6, 0.3, "EVERY OPERATION", size=11, bold=True, color="dk2")
    for i, (op, what) in enumerate(ops):
        y = 2.05 + i * 1.05
        text(s, 7.0, y, 4.0, 0.9, [[(op, {"bold": True, "size": 18})], [(what, {"size": 14, "color": "dk2"})]], space_after=2)
        pill = box(s, 11.15, y + 0.05, 1.48, 0.5, fill="accent5", radius=0.5, name=f"Cost {op}")
        text(s, 0, 0, 0, 0, "O(log n)", shape=pill, size=15, bold=True, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    text(s, 7.0, 5.2, 5.6, 0.5, "A lock covers pick and count together, so two requests never choose from the same stale count.",
         size=14, color="dk1", spacing=1.05)
    box(s, LEFT, 5.95, 5.8, 0.95, fill="lt2", name="Callout five servers")
    text(s, LEFT + 0.25, 6.0, 5.4, 0.85,
         [[(f"{N['scan5']} vs {N['heap5']} µs", {"bold": True, "size": 20})],
          [("per operation at our 5 servers: the plain scan is faster", {"size": 13, "color": "dk2"})]], anchor=MSO_ANCHOR.MIDDLE)
    box(s, 6.83, 5.95, 5.8, 0.95, fill="lt2", name="Callout fifty thousand")
    text(s, 7.08, 6.0, 5.4, 0.85,
         [[(f"{N['ratio50k']} faster", {"bold": True, "size": 20})],
          [("than a scan at 50,000 servers (measured, Python)", {"size": 13, "color": "dk2"})]], anchor=MSO_ANCHOR.MIDDLE)
    return s


def slide_failover(prs, layout, N, charts):
    s = new_slide(prs, layout, "Failover: noticing is the hard part", notes=(
        "About 1:10. The server really dies at one moment, but the balancer only finds out at the next health check. "
        "In between it keeps sending traffic to a dead server and those requests are refused. That is the blind window. "
        "Least Connections is hit hardest because a dead server shows zero connections, so it looks like the least loaded one. "
        "A passive check fixes it: three refusals in a row and the server is marked down at once.\n"
        "Decision: requests already in flight on the dying server finish. Bookings are not safe to retry."))
    y = 3.7
    line(s, 0.9, y, 6.9, y, color="dk2", width=2.5)
    events = [(1.0, "Server dies", "above", "accent4"), (2.4, "Blind window: requests are refused", "below", "accent5"),
              (3.8, "Marked down: nothing is routed after this", "above", "accent1"), (5.2, "Server revived", "below", "accent3"),
              (6.6, "Next probe puts it back: traffic returns", "above", "accent1")]
    box(s, 1.0, y + 0.18, 2.8, 0.14, fill="accent5", radius=0.5, name="Blind window")
    for x, label, where, col in events:
        box(s, x - 0.14, y - 0.14, 0.28, 0.28, fill=col, shape=MSO_SHAPE.OVAL, name=f"Marker {label}")
        if where == "above":
            text(s, x - 0.7, 2.3, 1.4, 1.2, label, size=13, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.BOTTOM)
        else:
            text(s, x - 0.7, y + 0.55, 1.4, 1.1, label, size=13, align=PP_ALIGN.CENTER)
    text(s, LEFT, 1.65, 6.3, 0.3, "THE BALANCER ONLY KNOWS WHAT A CHECK TELLS IT", size=11, bold=True, color="dk2")
    text(s, 7.5, 1.65, 5.1, 0.35, "Refused requests after a kill, by check interval", size=14, bold=True)
    cd = CategoryChartData()
    cd.categories = ["2 s", "0.5 s", "0.1 s"]
    for name, values in zip(("Round Robin", "Least / Weighted LC", "With passive check"), charts[5]):
        cd.add_series(name, values)
    gf = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(7.5), Inches(2.05), Inches(5.13), Inches(3.1), cd)
    alt(gf, "Column chart of refused requests at check intervals of 2, 0.5 and 0.1 seconds for three setups.")
    chart = gf.chart
    style_chart(chart)
    style_axes(chart, vmax=175, unit=50, cat_title="time between health checks")
    chart.has_legend = False
    plot = chart.plots[0]
    plot.gap_width, plot.overlap = 55, -5
    plot.has_data_labels = True
    plot.data_labels.font.size = Pt(12)
    plot.data_labels.position = XL_LABEL_POSITION.OUTSIDE_END
    for ser, col in zip(plot.series, ("accent2", "accent1", "dk2")):
        ser.format.fill.solid()
        ser.format.fill.fore_color.rgb = RGB[col]
    legend(s, 7.55, 5.2, [("Round Robin", "accent2"), ("Least / Weighted LC", "accent1"), ("+ passive check", "dk2")])
    text(s, LEFT, 5.75, 5.7, 1.1, [[("Drain, not retry", {"bold": True, "size": 16})],
                                   [("Requests already in flight on a dying server finish. Bookings are not safe to replay.",
                                     {"size": 14})]], space_after=3, spacing=1.05)
    text(s, 6.95, 5.75, 5.68, 1.1, [[("Passive check, opt-in", {"bold": True, "size": 16})],
                                    [("After 3 refused requests in a row, mark the server down at once. Overload never counts.",
                                      {"size": 14})]], space_after=3, spacing=1.05)
    return s


def cropped_shot():
    """-> (PNG stream, width / height) of the live-view screenshot without its cut-off bottom edge."""
    img = Image.open(SHOT)
    img = img.crop((0, 0, img.width, SHOT_KEEP_PX))
    stream = io.BytesIO()
    img.save(stream, "PNG")
    stream.seek(0)
    return stream, img.width / img.height


def slide_dashboard(prs, layout):
    s = new_slide(prs, layout, "Watch the failover live", notes=(
        "About 0:10, then switch to the browser. The dashboard runs the same engine as the command line, so the same seed gives the same "
        "numbers; there is a test for that. Kill and Revive take effect at the simulated moment you click.\n"
        "Fallback: docs/fallback/ has the command-line tables and docs/screenshots/ has these screenshots."))
    pic_w = 7.45
    stream, aspect = cropped_shot()
    pic = s.shapes.add_picture(stream, Inches(W - LEFT - pic_w), Inches(1.65), width=Inches(pic_w))
    pic.line.color.rgb = RGBColor(0xC9, 0xD1, 0xE0)
    pic.line.width = Pt(1)
    alt(pic, "Dashboard Live view during a Tatkal-rush run: app-3 is marked down, its bar has dropped to zero and the others carry its load.")
    text(s, W - LEFT - pic_w, 1.65 + pic_w / aspect + 0.1, pic_w, 0.3,
         "One live run: Tatkal rush, app-3 killed at 9.6 s. Counts differ from the tables, which use fixed scenarios.",
         size=11, color="dk2")
    items = [("Live view", "Per-server status, load in the last 5 s, open connections, latency and throughput."),
             ("Compare view", "All three algorithms on the same traffic, side by side."),
             ("Kill and Revive", "Act at the simulated moment you click, on all three algorithms at once."),
             ("Same engine as the CLI", "Same seed, same numbers. A test checks it.")]
    for i, (head, body) in enumerate(items):
        text(s, LEFT, 1.7 + i * 1.2, 4.5, 1.1, [[(head, {"bold": True, "size": 18})], [(body, {"size": 14, "color": "dk2"})]],
             space_after=3, spacing=1.05)
    return s


def slide_load(prs, layout, N):
    s = new_slide(prs, layout, "Near capacity, weighting wins", notes=(
        "About 0:45. Ten thousand requests per run. Each cell is the percentage of requests that failed and the average latency of the ones "
        "that were served. On a normal morning nothing fails. In the spike Weighted Least Connections fails 1.5 percent, Least Connections 8.8, "
        "Round Robin 10.8. In the burst nobody can win: it is more than twice what the fleet can sustain.\n"
        "Say the cost out loud: in the spike Weighted Least Connections averages higher latency, because it serves more of the traffic."))
    cols = [("normal", "Normal"), ("spike", "Spike ×4"), ("slow_server", "Slow server"), ("burst", "Burst ×10")]
    rows, cols_n = len(facts.NAMES) + 1, len(cols) + 1
    gf = s.shapes.add_table(rows, cols_n, Inches(LEFT), Inches(1.75), Inches(CW), Inches(3.1))
    alt(gf, "Table of failed percentage and average latency for each algorithm and traffic pattern at 10,000 requests.")
    tbl = gf.table
    tblPr = tbl._tbl.tblPr
    for attr in ("bandRow", "firstRow"):
        tblPr.set(attr, "0")
    style = tblPr.find(qn("a:tableStyleId"))
    if style is None:
        style = etree.SubElement(tblPr, qn("a:tableStyleId"))
    style.text = "{2D5ABB26-0587-4C30-8999-92F81FD0307C}"  # No Style, No Grid: all fills are explicit
    tbl.columns[0].width = Inches(3.0)
    for c in range(1, cols_n):
        tbl.columns[c].width = Inches((CW - 3.0) / len(cols))
    for r in range(rows):
        tbl.rows[r].height = Inches(0.7 if r == 0 else 0.8)

    def put(r, c, runs, fill, color="dk1", align=PP_ALIGN.CENTER):
        cell = tbl.cell(r, c)
        cell.fill.solid()
        set_color(cell.fill.fore_color, fill)
        cell.vertical_anchor = MSO_ANCHOR.MIDDLE
        cell.margin_left = cell.margin_right = Inches(0.12)
        tf = cell.text_frame
        tf.paragraphs[0].alignment = align
        for t, o in runs:
            run = tf.paragraphs[0].add_run()
            run.text = nb(t)
            run.font.size = Pt(o.get("size", 16))
            run.font.bold = o.get("bold", False)
            set_color(run.font.color, o.get("color", color))

    put(0, 0, [("", {})], "dk1")
    for c, (_, label) in enumerate(cols, 1):
        put(0, c, [(label, {"bold": True, "size": 15})], "dk1", color="lt1")
    for r, name in enumerate(facts.NAMES, 1):
        put(r, 0, [("●  ", {"color": ALGO_COLOR[name], "size": 14}), (name, {"bold": True})], "lt2" if r % 2 else "lt1",
            align=PP_ALIGN.LEFT)
        for c, (pat, _) in enumerate(cols, 1):
            cells = {a: facts.load_cell(pat, 10000, a) for a in facts.NAMES}
            pcts = {a: float(cells[a]["failed_pct"].rstrip("%")) for a in facts.NAMES}
            best = min(pcts.values()) == pcts[name] and max(pcts.values()) != min(pcts.values())
            cell = cells[name]
            put(r, c, [(cell["failed_pct"], {"bold": True, "size": 18}), (f" · {cell['avg_ms']} ms", {"size": 14, "color": "dk2"})],
                "lt2" if r % 2 else "lt1")
            if best:
                tbl.cell(r, c).fill.fore_color.rgb = RGBColor.from_string("DDF1E1")
    text(s, LEFT, 4.95, CW, 0.3, "Each cell: failed requests, then average latency of the requests that were served. 10,000 requests, seed 42. Lowest failure rate shaded.",
         size=12, color="dk2")
    leads = [("Spike", f"Weighted LC fails {N['spike_wlc']}. Least Connections fails {N['spike_lc']}, Round Robin {N['spike_rr']}."),
             ("Burst", f"About {N['floor']} failing is the floor for any balancer: the burst is more than twice the fleet's capacity. Round Robin {N['burst_rr']}, Weighted LC {N['burst_wlc']}."),
             ("The cost", f"In the spike Weighted LC averages {N['lat_wlc']} ms against {N['lat_lc']} ms for Least Connections: it serves more of the load.")]
    cw = (CW - 0.6) / 3
    for i, (head, body) in enumerate(leads):
        x = LEFT + i * (cw + 0.3)
        text(s, x, 5.5, cw, 1.5, [[(head, {"bold": True, "size": 16})], [(body, {"size": 14})]], space_after=3, spacing=1.05)
    return s


def slide_capacity(prs, layout, N, charts):
    s = new_slide(prs, layout, "The survivors run out of capacity", notes=(
        "About 0:50. We kill the biggest server, app-1, in the middle of the rush. Failover works: nothing is routed to the dead server. "
        "But a third of the requests still fail. The four survivors can sustain about 262 requests a second, an estimate from our latency model, "
        "and the rush offers 400. So no balancer can serve more than about 66 percent.\n"
        "Control: with app-1 dead from the start and no failover at all, a steady 400 gives the same kind of numbers. It is capacity, not failover."))
    text(s, LEFT, 1.65, 6.2, 0.35, "Success while app-1 is marked down, mid-spike", size=14, bold=True)
    cd = CategoryChartData()
    cd.categories = ["mid-spike"]
    for name, values in zip(facts.NAMES, charts[8]):
        cd.add_series(name, values)
    gf = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(LEFT), Inches(2.05), Inches(6.2), Inches(3.55), cd)
    alt(gf, "Column chart: success while app-1 is marked down is about 66 percent for Round Robin, 61 for Least Connections and 69 for Weighted Least Connections.")
    chart = gf.chart
    style_chart(chart)
    style_axes(chart, vmax=100, unit=25, fmt='0"%"')
    chart.category_axis.tick_label_position = XL_TICK_LABEL_POSITION.NONE
    chart.has_legend = False
    plot = chart.plots[0]
    plot.gap_width, plot.overlap = 80, -8
    plot.has_data_labels = True
    plot.data_labels.number_format, plot.data_labels.number_format_is_linked = '0.0"%"', False
    plot.data_labels.font.size = Pt(14)
    plot.data_labels.font.bold = True
    plot.data_labels.position = XL_LABEL_POSITION.OUTSIDE_END
    for ser, name in zip(plot.series, facts.NAMES):
        ser.format.fill.solid()
        ser.format.fill.fore_color.rgb = RGB[ALGO_COLOR[name]]
    legend(s, LEFT + 0.1, 5.7, [(n, ALGO_COLOR[n]) for n in facts.NAMES], size=13)
    text(s, LEFT, 6.2, 6.2, 0.5, "Probe-only detection. With the passive check the figures move by under 2 points.", size=12, color="dk2")
    x = 7.45
    for i, (big, label) in enumerate(((N["survivors"], "req/s the four survivors can sustain (estimate)"),
                                      ("400", "req/s the spike offers"))):
        text(s, x, 1.75 + i * 1.35, 2.5, 1.0, big, size=48, bold=True, color="accent2" if i else "dk1", anchor=MSO_ANCHOR.MIDDLE)
        text(s, x + 2.6, 1.75 + i * 1.35, 2.55, 1.0, label, size=15, anchor=MSO_ANCHOR.MIDDLE, spacing=1.05)
    text(s, x, 4.55, 5.18, 0.9, [[("So at most about ", {}), (N["ceiling"], {"bold": True}),
                                  (" can be served, whatever the balancer does.", {})]], size=18, spacing=1.05)
    box(s, x, 5.45, 5.18, 1.3, fill="lt2", name="Control experiment")
    text(s, x + 0.25, 5.5, 4.7, 1.2, [[("Control", {"bold": True, "size": 14})],
                                      [(f"app-1 dead from the first millisecond, no failover at all, steady 400 req/s: {N['steady400']}",
                                        {"size": 14})]], anchor=MSO_ANCHOR.MIDDLE, space_after=2, spacing=1.05)
    return s


def slide_limits(prs, layout, N):
    s = new_slide(prs, layout, "What this does not show", notes=(
        "About 0:30. Say these before they are asked. The traffic and the servers are invented. Time is simulated. A kill here means the server stops "
        "accepting new requests, not a power cut. The capacity figure is an estimate. Small runs are noisy. And the dashboard was checked in one desktop browser."))
    cards = [("Synthetic", "Traffic is Poisson arrivals, the servers are invented, latency is a formula. No IRCTC data, no real network."),
             ("Simulated time", "A virtual clock: no garbage collection, kernel queues or packet loss. Real threads are tested on the balancer, not on a network."),
             ("A kill is not a crash", "The server stops taking new requests; accepted ones finish. A power cut that drops them is not modelled."),
             ("An estimate", f"About {N['survivors']} req/s for the survivors comes from the latency model and is good to a few points."),
             ("Small samples", f"1,000-request runs differ by up to {N['spread1k']} in req/s between seeds. One fleet, one set of seeds."),
             ("Browser coverage", "Checked in Brave (Chromium), light and dark, and at 390 px in an iframe. Not on a phone, Safari or Firefox.")]
    cw, ch, gap = (CW - 0.7) / 3, 2.3, 0.35
    for i, (head, body) in enumerate(cards):
        x, y = LEFT + (i % 3) * (cw + gap), 1.7 + (i // 3) * (ch + gap)
        box(s, x, y, cw, ch, fill="lt2", name=f"Card {head}")
        text(s, x + 0.28, y + 0.25, cw - 0.56, 0.4, head, size=18, bold=True, font="+mj-lt")
        text(s, x + 0.28, y + 0.8, cw - 0.56, ch - 0.95, body, size=14, spacing=1.1)
    return s


def slide_close(prs, layout, N):
    s = new_slide(prs, layout, "What to take away", dark=True, notes=(
        "About 0:35. Three results, each with its number. Then the repository and questions."))
    rows = [(f"{N['spike_wlc']}", f"of requests failed with Weighted Least Connections in the spike, against {N['spike_lc']} for Least Connections and {N['spike_rr']} for Round Robin. Weigh the load by capacity."),
            (f"{N['bw_lc_2s']} → {N['bw_lc_pass']}", "requests lost in a 2 s blind window, cut to 3 by a passive check. How fast you notice a failure matters as much as how you route."),
            (f"{N['survivors']} of 400", "req/s the four survivors can sustain against what the spike offers, an estimate. No balancer fixes missing capacity.")]
    for i, (big, body) in enumerate(rows):
        y = 1.75 + i * 1.55
        text(s, LEFT, y, 3.8, 1.2, big, size=40, bold=True, color="accent5", anchor=MSO_ANCHOR.MIDDLE)
        text(s, 4.7, y, 7.93, 1.2, body, size=18, color="lt1", anchor=MSO_ANCHOR.MIDDLE, spacing=1.1)
    text(s, LEFT, 6.5, CW, 0.35, f"{REPO}   ·   {N['tests']} tests pass   ·   Questions?", size=15, color="lt2")
    return s


# --------------------------------------------------------------------------------------------------------- build
def build(path=OUT):
    N = numbers()
    charts = chart_data()
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(W), Inches(H)
    patch_theme(prs)
    layout = patch_master_and_layout(prs)
    slide_title(prs, layout)
    slide_rush(prs, layout, N, charts)
    slide_algorithms(prs, layout)
    slide_heap(prs, layout, N)
    slide_failover(prs, layout, N, charts)
    slide_dashboard(prs, layout)
    slide_load(prs, layout, N)
    slide_capacity(prs, layout, N, charts)
    slide_limits(prs, layout, N)
    slide_close(prs, layout, N)
    prs.core_properties.title = "Load Balancer Simulator"
    prs.core_properties.author = "Satyam Nirala"
    prs.core_properties.subject = "Algorithms course, project 27: Cloud Server Load Balancer (Greedy + Heap)"
    prs.save(path)
    return path


if __name__ == "__main__":
    print("wrote", os.path.relpath(build(), os.getcwd()))
