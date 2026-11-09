"""The documents must agree with the simulator: README, REPORT, demo script, viva sheet, the saved CLI fallbacks and the deck.

Every figure in them comes from lbsim.facts. These tests recompute it and fail when a document is stale, so a change to the
code that moves a number cannot slip past the slides. After such a change: python3 -m lbsim.facts, then regenerate the
documents and rebuild the deck (slides/build_deck.py).

The deck checks need python-pptx (pip install -r slides/requirements.txt) and are skipped without it.
"""
import contextlib
import importlib.util
import io
import json
import re
import shlex
import unittest
from pathlib import Path

from lbsim import facts, loadtest
from lbsim.__main__ import main

ROOT = Path(__file__).resolve().parent.parent
RR, LC, WLC = facts.NAMES

try:
    from pptx import Presentation
except ImportError:
    Presentation = None


def read(*parts):
    return ROOT.joinpath(*parts).read_text()


def number_tokens(text):
    """Every number in a text as a float ('1,000' -> 1000.0, '0.50' -> 0.5)."""
    return {float(t.replace(",", "")) for t in re.findall(r"\d[\d,]*(?:\.\d+)?", text)}


class TablesInDocsTest(unittest.TestCase):
    def test_readme_and_report_carry_the_computed_tables(self):
        for name in ("README.md", "REPORT.md"):
            text = read(name)
            for table in (facts.load_text(), facts.blind_window_md(), facts.spike_kill_md()):
                self.assertIn(table, text, f"{name} is out of date: run python3 -m lbsim.facts and update the table")
        self.assertIn(facts.capacity_md(), read("REPORT.md"))

    def test_report_quotes_the_benchmark_file_and_the_headline_estimates(self):
        report = read("REPORT.md")
        bench, cap = facts.bench(), facts.capacity()
        for r in bench["heap_vs_linear"]:
            self.assertIn(f"| {r['servers']:,} | {r['heap_us']:.2f} | {r['linear_us']:.2f} | {r['linear_over_heap']:.2f} |", report)
        for r in bench["per_request"]:
            self.assertIn(f"| {r['requests']:,} | " + " | ".join(f"{r[n]:.2f}" for n in facts.NAMES) + " |", report)
        self.assertIn(f"about {cap['survivors']} req/s for the four survivors", report)
        self.assertIn(f"about {cap['ceiling_pct']}% of it", report)

    def test_stability_and_detection_claims_are_true(self):
        st, fd = facts.stability(), facts.fast_detection()
        for n in (1000, 10000):
            for key in ("req_s", "avg_ms"):
                self.assertIn(f"{st[n][key]:.1f}%", read("REPORT.md"))
        self.assertIn(f"{st[10000]['req_s']:.1f}%", read("README.md"))
        self.assertLess(fd["max_diff"], 2.0)  # the claim "under 2 points" in the docs
        self.assertIn(f"{fd['max_diff']:.1f} points", read("REPORT.md"))
        self.assertLess(st[10000]["req_s"], 2.0)
        self.assertLess(st[10000]["avg_ms"], 2.0)

    def test_viva_and_demo_script_quote_the_right_numbers(self):
        viva, demo_text, d = read("docs", "VIVA.md"), read("docs", "DEMO_SCRIPT.md"), facts.demo()
        cap, bw, lat = facts.capacity(), facts.blind_window(), facts.spike_latency()
        c10 = lambda pat, alg, key: facts.load_cell(pat, 10000, alg)[key]
        for needle in (c10("spike", WLC, "failed_pct"), c10("spike", LC, "failed_pct"), c10("spike", RR, "failed_pct"),
                       str(bw[2000, 0][LC]), str(bw[2000, 0][RR]), str(cap["survivors"]), str(cap["full"]),
                       f"{cap['ceiling_pct']}%", lat["avg_ms"][WLC], lat["avg_ms"][LC], f"{lat['shared']:,}", lat["shared_wlc_ms"]):
            self.assertIn(needle, viva)
        hv = {r["servers"]: r for r in facts.bench()["heap_vs_linear"]}
        steady = cap["sweep"][400]["survivors"]
        sk = facts.spike_kill()
        for needle in (f"{hv[5]['linear_us']:.2f}", f"{hv[5]['heap_us']:.2f}", f"{hv[50000]['linear_over_heap']:.0f} times faster",
                       f"{steady[0]} / {steady[1]} / {steady[2]}%", " / ".join(sk[0][n][1] for n in facts.NAMES),
                       f"{bw[2000, 0][LC]} refused each", f"at most {bw[2000, 3][LC]} requests", f"{cap['app-1']} of that"):
            self.assertIn(needle, viva)
        for needle in (f"{d['requests']['normal']:,} requests", " / ".join(d["rush_failed"]), " / ".join(d["kill_failed"]),
                       " / ".join(d["kill_refused"]), " / ".join(d["kill_success"]), " / ".join(d["normal_avg_ms"]),
                       f"{hv[5]['linear_us']:.2f} against {hv[5]['heap_us']:.2f}", f"{hv[50000]['linear_over_heap']:.0f} times faster",
                       f"{bw[2000, 0][LC]} requests", f"{cap['sweep'][400]['survivors'][0]}, {cap['sweep'][400]['survivors'][1]} and "
                       f"{cap['sweep'][400]['survivors'][2]} percent", f"about {cap['ceiling_pct']} percent"):
            self.assertIn(needle, demo_text)

    def test_documents_name_the_browser_that_was_actually_used(self):
        # the dashboard checks ran in Brave (Chromium 156); an earlier draft said Chrome, which was not installed
        for name in ("README.md", "REPORT.md"):
            text = read(name)
            self.assertIn("Brave", text, name)
            self.assertNotRegex(text, r"(?i)(checked|driven|tested) in (google )?chrome", name)

    def test_viva_answers_all_six_questions(self):
        viva = read("docs", "VIVA.md")
        for q in ("Is this what IRCTC actually runs?", "Where did the traffic numbers come from?", "Why a heap?",
                  "Why does Weighted Least Connections win?", "Why does Least Connections lose most in the blind window?",
                  "Why does killing the biggest server still fail a third of the requests?"):
            self.assertIn(q, viva)

    def test_demo_script_fits_twelve_minutes(self):
        text = read("docs", "DEMO_SCRIPT.md")
        rows = re.findall(r"^\| (\d+):(\d\d) \| .* \| (\d+):(\d\d) \|$", text, flags=re.M)
        self.assertEqual(len(rows), 6)
        end = 0
        for m1, s1, m2, s2 in rows:
            start = int(m1) * 60 + int(s1)
            self.assertEqual(start, end)  # contiguous
            end = start + int(m2) * 60 + int(s2)
        self.assertEqual(end, 12 * 60)


class FallbackTest(unittest.TestCase):
    def test_saved_command_line_outputs_match_a_fresh_run(self):
        files = sorted((ROOT / "docs" / "fallback").glob("*.txt"))
        self.assertEqual(len(files), 4)
        for f in files:
            first, _, saved = f.read_text().partition("\n")
            argv = shlex.split(first.removeprefix("$ python3 -m "))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                (loadtest.main if argv[0] == "lbsim.loadtest" else main)(argv[1:] if argv[0] == "lbsim.loadtest" else argv[1:])
            fresh = "\n".join(l for l in out.getvalue().splitlines() if "simulations in" not in l)
            self.assertEqual(saved.rstrip("\n"), fresh.rstrip("\n"), f"{f.name} is stale: regenerate it")

    def test_screenshots_exist(self):
        for name in ("01_live_view_after_kill.png", "02_compare_view.png", "03_compare_tables.png"):
            self.assertGreater((ROOT / "docs" / "screenshots" / name).stat().st_size, 10_000)


@unittest.skipIf(Presentation is None, "python-pptx not installed (pip install -r slides/requirements.txt)")
class DeckTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("build_deck", ROOT / "slides" / "build_deck.py")
        cls.build = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.build)
        cls.deck = Presentation(str(ROOT / "slides" / "RailDhaara_LoadBalancer.pptx"))

    def slide_text(self, slide):
        parts = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                parts.append(shape.text_frame.text)
            if shape.has_table:
                parts += [c.text for row in shape.table.rows for c in row.cells]
        return re.sub(r"\s+", " ", " ".join(parts).replace(" ", " "))

    def test_ten_slides_each_with_a_title(self):
        self.assertEqual(len(self.deck.slides), 10)
        for i, slide in enumerate(self.deck.slides, 1):
            self.assertTrue(slide.shapes.title.text_frame.text.strip(), f"slide {i} has no title")
            self.assertTrue(slide.notes_slide.notes_text_frame.text.strip(), f"slide {i} has no speaker notes")

    def test_every_quoted_figure_is_on_its_slide(self):
        for number, needles in self.build.required_by_slide().items():
            text = self.slide_text(self.deck.slides[number - 1])
            for needle in needles:
                self.assertIn(needle, text, f"slide {number} should show {needle!r} (rebuild the deck?)")

    def test_chart_data_matches_the_simulator(self):
        for number, expected in self.build.chart_data().items():
            charts = [s.chart for s in self.deck.slides[number - 1].shapes if s.has_chart]
            self.assertEqual(len(charts), 1, number)
            actual = [list(series.values) for series in charts[0].plots[0].series]
            self.assertEqual(actual, [[float(v) for v in series] for series in expected], f"slide {number} chart is stale")

    def test_every_number_on_a_slide_is_a_measured_figure_or_a_listed_constant(self):
        allowed_text = " ".join([
            facts.load_text(), facts.blind_window_md(), facts.spike_kill_md(), facts.capacity_md(), json.dumps(facts.bench()),
            json.dumps(facts.spike_latency()), json.dumps({k: v for k, v in facts.capacity().items() if k != "sweep"}),
            json.dumps(facts.stability()), json.dumps(facts.demo()), json.dumps(self.build.numbers())])
        allowed = number_tokens(allowed_text) | number_tokens(" ".join(self.build.STRUCTURAL))
        unexplained = {}
        for i, slide in enumerate(self.deck.slides, 1):
            for token in number_tokens(self.slide_text(slide).replace(self.build.REPO, "")):  # the URL's digits are not data
                if not any(abs(token - a) < 1e-9 for a in allowed):
                    unexplained.setdefault(i, []).append(token)
        self.assertEqual(unexplained, {}, "numbers on slides that are neither measured nor in STRUCTURAL")

    def test_deck_names_the_browser_that_was_actually_used(self):
        text = self.slide_text(self.deck.slides[8])
        self.assertIn("Brave", text)
        self.assertNotRegex(text, r"(?i)checked in (google )?chrome")

    def test_test_count_on_the_closing_slide_is_current(self):
        suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
        self.assertIn(f"{suite.countTestCases()} tests pass", self.slide_text(self.deck.slides[9]))


if __name__ == "__main__":
    unittest.main()
