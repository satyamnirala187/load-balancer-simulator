import contextlib
import io
import unittest

from lbsim.__main__ import main
from lbsim.algorithms import ALGORITHMS, LeastConnections
from lbsim.health import HealthChecker
from lbsim.servers import Server
from lbsim.simulator import failover, simulate
from lbsim.traffic import PATTERNS, Fault, make_scenario

KILL, REVIVE = 5200, 8200  # ms; with 500 ms checks the server is noticed at 5500 and back at 8500
DETECT, RECOVER = 5500, 8500


def killed_run(alg, interval_ms=500):
    scenario = make_scenario("normal", seed=3, duration_s=12)
    scenario.faults = [Fault(KILL, "app-3", False), Fault(REVIVE, "app-3", True)]
    return simulate(alg, scenario, interval_ms)


class HealthCheckerTest(unittest.TestCase):
    def test_marks_down_and_up_only_when_state_changes(self):
        s1, s2, s3 = (Server(f"s{i}", 1, 50) for i in (1, 2, 3))
        lb = LeastConnections([s1, s2, s3])
        hc = HealthChecker(lb, 500)

        hc.check(500)
        self.assertEqual(hc.log, [])  # everyone alive: nothing to do

        s2.alive = False
        self.assertTrue(s2.healthy)  # balancer is blind until the next check
        hc.check(1000)
        self.assertEqual(hc.log, [(1000, "s2", False)])
        self.assertFalse(s2.healthy)
        picks = [lb.acquire().id for _ in range(30)]
        self.assertNotIn("s2", picks)

        hc.check(1500)
        self.assertEqual(len(hc.log), 1)  # still down: no repeat

        s2.alive = True
        hc.check(2000)
        self.assertEqual(hc.log[-1], (2000, "s2", True))
        self.assertIs(lb.acquire(), s2)  # back in the heap, and it is the least loaded

    def test_interval_must_be_positive(self):
        with self.assertRaises(ValueError):
            HealthChecker(LeastConnections([Server("s1", 1, 50)]), 0)


class FailoverTest(unittest.TestCase):
    def test_traffic_keeps_succeeding_and_nothing_reaches_the_dead_server(self):
        for alg in ALGORITHMS:
            with self.subTest(alg.name):
                r = killed_run(alg)
                log = [(t, up) for t, i, up in r.health_log if i == "app-3"]
                self.assertEqual(log, [(DETECT, False), (RECOVER, True)])
                down = [q for q in r.records if DETECT <= q.arrival_ms < RECOVER]
                self.assertGreater(len(down), 100)
                self.assertEqual([q for q in down if q.server_id == "app-3"], [])
                self.assertGreaterEqual(sum(q.ok for q in down) / len(down), 0.99)
                self.assertEqual(failover(r, "app-3").while_down, 0)
                self.assertTrue(all(s.connections == 0 for s in r.servers))

    def test_in_flight_requests_finish_and_failures_are_explained(self):
        for alg in ALGORITHMS:
            with self.subTest(alg.name):
                r = killed_run(alg)
                # the policy is exercised: some request accepted before the kill was still running at the kill
                self.assertTrue(any(q.server_id == "app-3" and q.ok and q.arrival_ms < KILL < q.arrival_ms + q.latency_ms
                                    for q in r.records))
                failures = [q for q in r.records if not q.ok]
                self.assertTrue(all(q.arrival_ms >= KILL for q in failures))  # nothing accepted before the kill is lost
                window = [q for q in failures if q.arrival_ms < DETECT]
                self.assertGreater(len(window), 0)  # the blind window is visible, not silently hidden
                self.assertTrue(all(q.error == "refused" and q.server_id == "app-3" for q in window))
                # after detection a request can only fail because the survivors ran out of capacity, never by
                # being sent to the dead server (round robin ignores capacity, so it can do this)
                self.assertTrue(all(q.error == "overloaded" for q in failures if q.arrival_ms >= DETECT))

    def test_recovery_returns_traffic_to_the_revived_server(self):
        for alg in ALGORITHMS:
            with self.subTest(alg.name):
                r = killed_run(alg)
                back = [q for q in r.records if q.server_id == "app-3" and q.ok and q.arrival_ms >= RECOVER]
                self.assertGreater(len(back), 20)
                self.assertLess(back[0].arrival_ms, RECOVER + 1000)  # promptly, not eventually

    def test_total_outage_fails_cleanly(self):
        scenario = make_scenario("normal", seed=3, duration_s=6)
        scenario.faults = [Fault(2000, sid, False) for sid in ("app-1", "app-2", "app-3", "app-4", "app-5")]
        for alg in ALGORITHMS:
            with self.subTest(alg.name):
                r = simulate(alg, scenario, 500)
                late = [q for q in r.records if q.arrival_ms >= 2500]
                self.assertTrue(late and all(q.error == "no healthy server" for q in late))
                self.assertTrue(all(s.connections == 0 for s in r.servers))


def run_cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        main(list(args))
    return out.getvalue()


class CliTest(unittest.TestCase):
    def tables(self, out):
        return [block for block in out.split("\n\n") if "---" in block]

    def test_every_table_lists_all_three_algorithms(self):
        kill = ("--kill-server", "app-3", "--at", "4s", "--revive-at", "7s")
        for args, tables_each in [(kill, 3), ((), 2)]:  # per pattern: comparison, load[, failover]
            expected = tables_each * len(PATTERNS)
            out = run_cli("--pattern", "all", "--duration", "10", *args)
            tables = self.tables(out)
            self.assertEqual(len(tables), expected)
            for t in tables:
                for alg in ALGORITHMS:
                    self.assertIn(alg.name, t)
            self.assertEqual("Failover:" in out, bool(args))

    def test_a_kill_without_a_revive_says_not_revived(self):
        out = run_cli("--pattern", "spike", "--kill-server", "app-3", "--at", "9s")
        self.assertIn("Failover: app-3 killed at 9s, marked down at 9.5s (health check every 500 ms). Not revived.\n", out)
        self.assertNotIn("never", out)
        out = run_cli("--pattern", "spike", "--kill-server", "app-3", "--at", "9s", "--revive-at", "14.5s")
        self.assertIn(", revived at 14.5s, back in rotation at 15s\n", out)  # with a revive the line is unchanged

    def test_bad_flags_are_rejected(self):
        for args in (["--kill-server", "app-9", "--at", "5s"], ["--kill-server", "app-3"], ["--at", "5s"],
                     ["--kill-server", "app-3", "--at", "30s"], ["--kill-server", "app-3", "--at", "8s", "--revive-at", "5s"],
                     ["--check-interval", "0"]):
            with self.subTest(args), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main(args)


if __name__ == "__main__":
    unittest.main()
