"""Dashboard tests, run through Streamlit's AppTest (the real script, real widgets, no browser).

They need Streamlit (pip install -r requirements.txt) and are skipped without it.
The run uses a fake clock so a 20 s simulation takes milliseconds and is deterministic.
"""
import json
import shlex
import unittest
from pathlib import Path

from lbsim.algorithms import ALGORITHMS
from lbsim.live import LiveRun
from lbsim.traffic import make_scenario

from .test_live import Clock, cli_rows

try:
    import pyarrow as pa
    from streamlit.testing.v1 import AppTest
except ImportError:
    AppTest = None

DASHBOARD = str(Path(__file__).resolve().parent.parent / "dashboard.py")
CFG = ("normal", 42, 20, 100)
NAMES = [a.name for a in ALGORITHMS]


def open_app():
    """-> (AppTest, LiveRun, Clock): the dashboard on a run driven by a fake clock, speed 1x."""
    clock = Clock()
    run = LiveRun(make_scenario(*CFG), speed=1, clock=clock)
    at = AppTest.from_file(DASHBOARD, default_timeout=60)
    at.session_state["cfg"], at.session_state["run"] = CFG, run
    at.run()
    at.select_slider[0].set_value(1).run()  # the sidebar's speed (default 2x) would otherwise override the run's
    return at, run, clock


def bar_frames(at):
    """The data behind each bar chart on the page: DataFrames with server / count / state columns."""
    frames = []
    for el in at.main:
        if getattr(el, "type", None) == "vega_lite_chart":
            for d in el.proto.datasets:
                df = pa.ipc.open_stream(d.data.data).read_all().to_pandas()
                if "server" in df.columns:
                    frames.append(df.set_index("server"))
    return frames


def metric(at, label):
    return next(m.value for m in at.metric if m.label == label)


@unittest.skipIf(AppTest is None, "streamlit not installed (pip install -r requirements.txt)")
class DashboardTest(unittest.TestCase):
    def test_loads_without_errors_with_every_control(self):
        at, run, clock = open_app()
        self.assertEqual(list(at.exception), [])
        self.assertEqual([s.label for s in at.selectbox], ["Pattern", "Algorithm (live view)", "Server"])
        self.assertEqual(at.selectbox[0].options, ["Normal load", "Sudden spike (Tatkal rush)", "One slow server",
                                                   "Sudden 10x burst"])
        self.assertEqual(at.selectbox[1].options, NAMES)
        self.assertEqual(at.radio[0].options, ["Live view", "Compare all 3"])
        self.assertEqual({b.key: b.disabled for b in at.button},
                         {"start": False, "reset": False, "kill": True, "revive": True})  # nothing to kill yet
        self.assertEqual(metric(at, "Sent to a marked-down server"), "0")
        self.assertEqual(len(bar_frames(at)), 2)  # recent load + open connections

    def test_every_pattern_algorithm_and_view_renders(self):
        at, run, clock = open_app()
        for view in ("Live view", "Compare all 3"):
            at.radio[0].set_value(view)
            for pattern in ("normal", "spike", "slow_server", "burst"):
                at.selectbox[0].set_value(pattern)  # AppTest takes the raw value, the page shows the label
                for name in NAMES:
                    at.selectbox[1].set_value(name).run()
                    with self.subTest(f"{view}/{pattern}/{name}"):
                        self.assertEqual(list(at.exception), [])
                        self.assertEqual(at.session_state["run"].scenario.name, pattern)  # new pattern = new run

    def test_kill_and_revive_buttons_reroute_traffic_while_the_run_is_live(self):
        at, run, clock = open_app()
        at.button(key="start").click().run()
        self.assertTrue(run.running)
        self.assertFalse(at.button(key="kill").disabled)

        clock.t = 10.2
        at.run()
        before = bar_frames(at)[0]["count"]  # "handled in the last 5 s"
        self.assertTrue((before > 0).all(), before.to_dict())  # every server is taking traffic

        at.selectbox[2].set_value("app-3")
        at.button(key="kill").click().run()
        clock.t = 17.0  # health check noticed at 10.5; the 5 s window now holds only post-detection traffic
        at.run()
        self.assertEqual(list(at.exception), [])
        recent, open_now = bar_frames(at)
        self.assertEqual(recent.loc["app-3", "count"], 0)
        self.assertEqual(recent.loc["app-3", "state"], "marked down")
        self.assertTrue((recent.drop("app-3")["count"] > 0).all())  # the others absorbed its share
        for sim in run.sims.values():
            self.assertFalse(sim.by_id["app-3"].alive)
            self.assertEqual([x for x in sim.checker.log if x[1] == "app-3"], [(10500, "app-3", False)])
        self.assertEqual(metric(at, "Sent to a marked-down server"), "0")

        at.button(key="revive").click().run()
        clock.t = 19.0
        at.run()
        recent, open_now = bar_frames(at)
        self.assertEqual(recent.loc["app-3", "state"], "up")
        self.assertGreater(recent.loc["app-3", "count"], 0)  # traffic came back
        self.assertEqual(metric(at, "Sent to a marked-down server"), "0")

    def test_narrow_screen_and_light_theme_fixes_stay_in_place(self):
        # found in the browser at 390 px / light theme: no hint that the controls hide in the sidebar, line-chart
        # legends clipped at the right edge, a pale-blue line that vanished on white. (Layout itself needs a browser.)
        at, run, clock = open_app()
        at.button(key="start").click().run()
        clock.t = 40.0
        at.run()
        at.radio[0].set_value("Compare all 3").run()
        hint = [m.value for m in at.markdown if "mobile-hint" in m.value]
        self.assertEqual(len(hint), 1)
        self.assertIn("@media (max-width:640px)", hint[0])  # shown only on narrow screens
        self.assertIn("sidebar", hint[0])

        lines = 0
        for el in at.main:
            if getattr(el, "type", None) != "vega_lite_chart":
                continue
            spec = json.loads(el.proto.spec)
            mark = spec["mark"]["type"] if isinstance(spec["mark"], dict) else spec["mark"]
            if mark != "line":
                continue
            lines += 1
            color = spec["encoding"]["color"]
            self.assertEqual(color["legend"]["columns"], 1)  # one entry per row: three names do not fit in a row at 390 px
            self.assertEqual(len(color["scale"]["domain"]), len(color["scale"]["range"]))  # explicit, theme-safe colours
        self.assertEqual(lines, 2)  # latency and throughput

    def test_no_stray_values_are_printed_on_the_page(self):
        # Streamlit "magic" prints bare expressions, so a stray `a() if c else b()` shows a literal `None`
        at, run, clock = open_app()
        for step in (lambda: None, lambda: at.button(key="start").click().run(),
                     lambda: at.button(key="start").click().run(), lambda: at.radio[0].set_value("Compare all 3").run()):
            step()
            for el in list(at.sidebar) + list(at.main):
                value = getattr(el, "value", None)  # dataframes have a DataFrame here; only text matters
                if isinstance(value, str):
                    self.assertNotIn(value, ("`None`", "None", "`True`", "`False`"))

    def test_pause_stops_simulated_time(self):
        at, run, clock = open_app()
        at.button(key="start").click().run()
        clock.t = 4.0
        at.button(key="start").click().run()  # now labelled Pause
        self.assertFalse(run.running)
        self.assertEqual(metric(at, "Simulated time"), "4.0 s / 20 s")
        clock.t = 9.0
        at.run()
        self.assertEqual(metric(at, "Simulated time"), "4.0 s / 20 s")

    def test_comparison_view_shows_all_three_and_matches_the_cli(self):
        at, run, clock = open_app()
        at.button(key="start").click().run()
        clock.t = 10.2
        at.run()
        at.selectbox[2].set_value("app-3")
        at.button(key="kill").click().run()
        clock.t = 15.0
        at.button(key="revive").click().run()
        clock.t = 40.0  # far past the end
        at.run()
        self.assertTrue(run.finished)
        self.assertEqual(metric(at, "Run"), "Finished")

        at.radio[0].set_value("Compare all 3").run()
        self.assertEqual(list(at.exception), [])
        panels = [m.value for m in at.markdown if m.value.startswith("#### ")]
        self.assertEqual(panels, [f"#### {n}" for n in NAMES])  # all three side by side
        self.assertEqual(len(bar_frames(at)), 3)

        tables = [df.values.tolist() for df in (d.value for d in at.dataframe)]  # comparison, load, failover
        self.assertEqual(len(tables), 3)
        for t in tables:
            self.assertEqual([row[0] for row in t], NAMES)

        # the page prints the CLI command for this very run; the CLI's numbers must equal the page's
        cmd = at.code[0].value
        self.assertIn("--kill-server app-3 --at 10.2", cmd)
        cli = cli_rows(*shlex.split(cmd)[3:])
        for i, name in enumerate(NAMES):
            self.assertEqual(cli[name], [t[i] for t in tables], name)

    def test_comparison_numbers_match_the_plain_cli_run(self):
        at, run, clock = open_app()
        at.button(key="start").click().run()
        clock.t = 40.0
        at.run()
        at.radio[0].set_value("Compare all 3").run()
        tables = [d.value.values.tolist() for d in at.dataframe]
        cli = cli_rows("--pattern", "normal", "--seed", "42", "--duration", "20", "--rate", "100")
        self.assertEqual(len(tables), 2)  # no kill, so no failover table
        for i, name in enumerate(NAMES):
            self.assertEqual(cli[name], [t[i] for t in tables], name)


if __name__ == "__main__":
    unittest.main()
