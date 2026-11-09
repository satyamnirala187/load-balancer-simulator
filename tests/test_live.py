import contextlib
import io
import random
import re
import shlex
import unittest

from lbsim.__main__ import main
from lbsim.algorithms import ALGORITHMS
from lbsim.live import LiveRun
from lbsim.report import cli_command, comparison_table, failover_table, load_table, recent_load, timeseries
from lbsim.simulator import Record, RunResult, Simulation, routed_while_marked_down, simulate
from lbsim.traffic import PATTERNS, Fault, make_scenario


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


def cli_rows(*args):
    """Run the CLI. -> {algorithm: its table rows in print order (comparison, load[, failover])}, as lists of cells."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        main(list(args))
    rows = {}
    for line in out.getvalue().splitlines():  # a row looks like "Round Robin   96.8   82.7 ..."
        cells = re.split(r"\s{2,}", line.strip())
        if cells[0] in [a.name for a in ALGORITHMS]:
            rows.setdefault(cells[0], []).append(cells)
    return rows


def drive(run, clock, until_s=None, step=(0.05, 2.0), seed=0):
    """Advance the fake clock in irregular steps, ticking the run each time."""
    rng = random.Random(seed)
    while not run.finished and (until_s is None or clock.t < until_s):
        clock.t += rng.uniform(*step)
        run.tick()


class LiveRunTest(unittest.TestCase):
    def new(self, pattern="normal", speed=1.0, **kw):
        clock = Clock()
        return LiveRun(make_scenario(pattern, seed=42, duration_s=20, rate=100), speed=speed, clock=clock, **kw), clock

    def test_stepped_run_gives_exactly_the_batch_result(self):
        for pattern in PATTERNS:
            run, clock = self.new(pattern, speed=3)
            run.start()
            drive(run, clock)
            self.assertTrue(run.finished and not run.running)
            for alg, result in zip(ALGORITHMS, run.results()):
                with self.subTest(f"{pattern}/{alg.name}"):
                    self.assertEqual(result, simulate(alg, run.scenario))

    def test_live_kill_and_revive_match_the_cli_for_the_same_run(self):
        run, clock = self.new()
        run.start()
        clock.t = 10.2
        self.assertTrue(run.kill("app-3"))
        clock.t = 15.0
        self.assertTrue(run.revive("app-3"))
        drive(run, clock)
        cmd = cli_command("normal", 42, 20, 100, run.sims["Round Robin"].faults)
        self.assertIn("--kill-server app-3 --at 10.2", cmd)

        cli = cli_rows(*shlex.split(cmd)[3:])
        results = run.results()
        want = comparison_table(results)[1], load_table(results)[1], failover_table(results, "app-3")[1]
        for i, name in enumerate(run.sims):
            # per algorithm the CLI prints 3 rows: comparison, load, failover
            self.assertEqual(cli[name], [want[0][i], want[1][i], want[2][i]])

    def test_nothing_routed_to_a_dead_server_after_detection(self):
        run, clock = self.new()
        run.start()
        clock.t = 8.0
        run.kill("app-3")
        drive(run, clock)
        for r in run.results():
            with self.subTest(r.algorithm):
                detect = next(t for t, i, up in r.health_log if i == "app-3" and not up)
                self.assertEqual(detect, 8500)
                self.assertEqual([q for q in r.records if q.server_id == "app-3" and q.arrival_ms >= detect], [])
                self.assertEqual(routed_while_marked_down(r), 0)

    def test_buttons_are_guarded(self):
        run, clock = self.new()
        self.assertFalse(run.kill("app-1"))  # not started
        run.start()
        clock.t = 5
        self.assertTrue(run.kill("app-1"))
        self.assertFalse(run.kill("app-1"))  # already dead
        self.assertFalse(run.revive("app-2"))  # already alive
        self.assertTrue(run.revive("app-1"))
        drive(run, clock)
        self.assertFalse(run.kill("app-1"))  # run is over
        with self.assertRaises(KeyError):
            run.kill("app-9")

    def test_revive_while_paused_waits_for_the_next_check_then_resumes(self):
        # the demo's flow: kill, pause to talk, revive on the frozen screen, resume
        run, clock = self.new("spike")
        run.start()
        clock.t = 9.0
        self.assertTrue(run.kill("app-3"))
        clock.t = 14.5
        run.pause()
        server = run.sims["Weighted Least Conn."].by_id["app-3"]
        self.assertEqual((server.alive, server.healthy), (False, False))  # dead and already marked down
        self.assertTrue(run.revive("app-3"))  # allowed while paused
        self.assertEqual((server.alive, server.healthy), (True, False))  # alive, not back in rotation yet
        self.assertEqual(run.now_ms, 14500)  # the clock did not move
        run.start()
        clock.t += 0.6
        run.tick()
        self.assertEqual((server.alive, server.healthy), (True, True))  # the next check put it back
        drive(run, clock)
        for r in run.results():
            self.assertEqual(routed_while_marked_down(r), 0, r.algorithm)

    def test_pause_freezes_the_clock_and_speed_scales_it(self):
        run, clock = self.new(speed=4)
        run.start()
        clock.t = 2
        run.pause()
        self.assertEqual(run.now_ms, 8000)
        clock.t = 50
        run.tick()
        self.assertEqual(run.now_ms, 8000)
        run.start()
        clock.t = 51
        run.speed = 1
        run.tick()
        self.assertEqual(run.now_ms, 9000)


class ReportTest(unittest.TestCase):
    def test_routed_while_marked_down_can_actually_detect_a_violation(self):
        rec = lambda i, t, sid: Record(i, t, sid, 10.0, True)
        log = [(100, "s1", False), (200, "s1", True), (300, "s1", False)]
        ok = RunResult("x", [rec(0, 50, "s1"), rec(1, 150, "s2"), rec(2, 250, "s1")], [], 0, log, [])
        self.assertEqual(routed_while_marked_down(ok), 0)
        bad = RunResult("x", [rec(0, 150, "s1"), rec(1, 350, "s1"), rec(2, 350, "s2")], [], 0, log, [])
        self.assertEqual(routed_while_marked_down(bad), 2)  # one in each down period, s2 is fine

    def test_timeseries_and_recent_load(self):
        recs = [Record(0, 100, "a", 10.0, True), Record(1, 900, "b", 30.0, True), Record(2, 1500, None, None, False, "x"),
                Record(3, 2200, "a", 20.0, True)]
        ts = timeseries(recs)
        self.assertEqual((ts["t"], ts["ok"], ts["failed"], ts["avg_ms"]), ([0, 1, 2], [2, 0, 1], [0, 1, 0], [20.0, None, 20.0]))
        self.assertEqual(timeseries(recs, upto_ms=2100)["t"], [0, 1])  # bucket 2 has not finished yet
        self.assertEqual(timeseries([])["t"], [])
        self.assertEqual(recent_load(recs, ["a", "b", "c"], now_ms=2300, window_ms=1500), {"a": 1, "b": 1, "c": 0})
        self.assertEqual(recent_load(recs, ["a", "b", "c"], now_ms=2300, window_ms=1000), {"a": 1, "b": 0, "c": 0})
        # records only exist up to now: at now=1000 these are the first two; 100 is exactly on the edge: out
        self.assertEqual(recent_load(recs[:2], ["a", "b"], now_ms=1000, window_ms=900), {"a": 0, "b": 1})

    def test_cli_command(self):
        k, v = Fault(10200.5, "app-3", False), Fault(15000, "app-3", True)
        self.assertEqual(cli_command("spike", 7, 30, 150, []), "python3 -m lbsim --pattern spike --seed 7 --duration 30 --rate 150")
        self.assertTrue(cli_command("spike", 7, 30, 150, [k, v]).endswith("--kill-server app-3 --at 10.2005s --revive-at 15.0s"))
        for faults in ([k, Fault(11000, "app-1", False)], [v], [k, Fault(16000, "app-1", True)], [Fault(9000, "app-3", True), k]):
            self.assertIsNone(cli_command("spike", 7, 30, 150, faults))  # CLI can't express these

    def test_simulation_rejects_faults_in_the_past(self):
        sim = Simulation(ALGORITHMS[0], make_scenario("normal", seed=1, duration_s=5))
        sim.advance(2000)
        with self.assertRaises(ValueError):
            sim.inject(Fault(1000, "app-1", False))


if __name__ == "__main__":
    unittest.main()
