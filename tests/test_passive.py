import contextlib
import io
import unittest

from lbsim.__main__ import main
from lbsim.algorithms import ALGORITHMS, LeastConnections
from lbsim.health import HealthChecker
from lbsim.servers import Server
from lbsim.simulator import failover, routed_while_marked_down, simulate
from lbsim.traffic import Fault, make_scenario

KILL, REVIVE = 5200, 8200


def killed_run(alg, interval_ms, passive_after):
    scenario = make_scenario("normal", seed=3, duration_s=12)
    scenario.faults = [Fault(KILL, "app-3", False), Fault(REVIVE, "app-3", True)]
    return simulate(alg, scenario, interval_ms, passive_after)


class PassiveUnitTest(unittest.TestCase):
    def setUp(self):
        self.s1, self.s2, self.s3 = (Server(f"s{i}", 1, 50) for i in (1, 2, 3))
        self.lb = LeastConnections([self.s1, self.s2, self.s3])

    def test_off_by_default(self):
        hc = HealthChecker(self.lb)
        for t in range(10):
            hc.note_refused(self.s2, t)
        self.assertTrue(self.s2.healthy)
        self.assertEqual(hc.log, [])

    def test_marks_down_after_n_refusals_in_a_row(self):
        hc = HealthChecker(self.lb, passive_after=3)
        hc.note_refused(self.s2, 1)
        hc.note_refused(self.s2, 2)
        self.assertTrue(self.s2.healthy)
        hc.note_refused(self.s2, 3)
        self.assertFalse(self.s2.healthy)
        self.assertEqual(hc.log, [(3, "s2", False)])
        self.assertNotIn("s2", [self.lb.acquire().id for _ in range(30)])

    def test_a_success_ends_the_streak(self):
        hc = HealthChecker(self.lb, passive_after=3)
        for event in ("r", "r", "ok", "r", "r"):
            hc.note_refused(self.s2, 0) if event == "r" else hc.note_ok(self.s2)
        self.assertTrue(self.s2.healthy)  # never 3 in a row
        hc.note_refused(self.s2, 9)
        self.assertFalse(self.s2.healthy)

    def test_the_active_probe_does_not_log_a_passive_mark_twice_and_still_brings_it_back(self):
        hc = HealthChecker(self.lb, passive_after=1)
        self.s2.alive = False
        hc.note_refused(self.s2, 10)
        hc.check(500)  # probe sees alive=False, healthy=False: nothing to do
        self.assertEqual(hc.log, [(10, "s2", False)])
        self.s2.alive = True
        hc.check(1000)  # passive never brings a server back; the probe does
        self.assertEqual(hc.log[-1], (1000, "s2", True))
        self.assertTrue(self.s2.healthy)

    def test_negative_count_rejected(self):
        with self.assertRaises(ValueError):
            HealthChecker(self.lb, passive_after=-1)


class PassiveRunTest(unittest.TestCase):
    def test_blind_window_is_n_refusals_however_slow_the_probe_is(self):
        for alg in ALGORITHMS:
            for interval in (2000, 500, 100):
                r = killed_run(alg, interval, passive_after=3)
                with self.subTest(f"{alg.name}/{interval} ms"):
                    f = failover(r, "app-3")
                    self.assertLessEqual(f.refused, 3)
                    self.assertEqual(routed_while_marked_down(r), 0)
                    self.assertGreater(f.after, 20)  # the active probe still brings it back and traffic returns
        for alg in ALGORITHMS:  # and with a 2 s probe it is exactly the 3 that trigger the mark
            self.assertEqual(failover(killed_run(alg, 2000, 3), "app-3").refused, 3, alg.name)
            # off: the window is the time to the next probe (5.2 s -> 6.0 s here), far more than 3 requests
            self.assertGreater(failover(killed_run(alg, 2000, 0), "app-3").refused, 10, alg.name)

    def test_marks_down_before_the_probe_would_have(self):
        for alg in ALGORITHMS:
            passive = failover(killed_run(alg, 500, 3), "app-3")
            active = failover(killed_run(alg, 500, 0), "app-3")
            self.assertEqual(active.detect_ms, 5500)
            self.assertLess(passive.detect_ms, active.detect_ms, alg.name)
            self.assertEqual(passive.recover_ms, active.recover_ms)  # coming back is still the probe's job

    def test_overload_alone_never_marks_a_server_down(self):
        # the safety property: a burst far beyond capacity makes servers reject requests ("overloaded"),
        # but only a dead server's "refused" counts, so even passive_after=1 marks nothing down
        scenario = make_scenario("burst", seed=1, duration_s=10)
        for alg in ALGORITHMS:
            r = simulate(alg, scenario, passive_after=1)
            with self.subTest(alg.name):
                self.assertGreater(sum(x.error == "overloaded" for x in r.records), 100)  # it really was overloaded
                self.assertEqual(r.health_log, [])

    def test_total_outage_still_fails_cleanly(self):
        scenario = make_scenario("normal", seed=3, duration_s=6)
        scenario.faults = [Fault(2000, f"app-{i}", False) for i in range(1, 6)]
        for alg in ALGORITHMS:
            r = simulate(alg, scenario, 2000, passive_after=3)
            late = [q for q in r.records if q.arrival_ms >= 2200]
            with self.subTest(alg.name):
                self.assertTrue(all(q.error in ("refused", "no healthy server") for q in late))
                self.assertTrue(any(q.error == "no healthy server" for q in late))  # all five marked down passively
                self.assertTrue(all(s.connections == 0 for s in r.servers))


class PassiveCliTest(unittest.TestCase):
    def run_cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main(list(args))
        return out.getvalue()

    def test_flag_changes_the_failover_table_and_names_itself(self):
        base = ("--kill-server", "app-3", "--at", "10s", "--revive-at", "15s", "--check-interval", "2")
        off, on = self.run_cli(*base), self.run_cli(*base, "--passive-after", "3")
        self.assertNotIn("refused requests", off)
        self.assertIn("or after 3 refused requests", on)
        self.assertNotEqual(off, on)

    def test_bad_value_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(["--passive-after", "-1"])


if __name__ == "__main__":
    unittest.main()
