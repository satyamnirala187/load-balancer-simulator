import contextlib
import io
import unittest

from lbsim import loadtest
from lbsim.algorithms import ALGORITHMS
from lbsim.traffic import PATTERNS, SURGES, make_scenario, rate_factor

from .test_live import cli_rows

SIZES = (1000, 10000)
NAMES = [a.name for a in ALGORITHMS]


class LoadRunTest(unittest.TestCase):
    def test_scenarios_are_sized_to_about_n_requests(self):
        for pattern in PATTERNS:
            for n in SIZES:
                scenario, _ = loadtest.run(pattern, n, seed=42, rate=100)
                with self.subTest(f"{pattern}/{n}"):
                    self.assertAlmostEqual(len(scenario.requests) / n, 1, delta=0.10)

    def test_every_run_completes_with_exact_accounting(self):
        for pattern in PATTERNS:
            for n in SIZES:
                scenario, results = loadtest.run(pattern, n, seed=42, rate=100)
                for r in results:
                    with self.subTest(f"{pattern}/{n}/{r.algorithm}"):
                        self.assertEqual([x.request_id for x in r.records], [q.id for q in scenario.requests])
                        self.assertEqual(sum(r.load.values()) + r.failed, r.total)  # served + failed = sent
                        self.assertTrue(all(s.connections == 0 for s in r.servers))  # nothing leaked
                        self.assertEqual(routed_while_down(r), 0)

    def test_same_seed_same_numbers(self):
        for pattern in PATTERNS:
            a, b = loadtest.run(pattern, 1000, 7, 100)[1], loadtest.run(pattern, 1000, 7, 100)[1]
            self.assertEqual(a, b, pattern)

    def test_10k_numbers_are_stable_across_seeds(self):
        # where nothing saturates, 10k-request runs agree to within 5% whichever seed makes the traffic
        for pattern in ("normal", "slow_server"):
            per_seed = [loadtest.run(pattern, 10000, seed, 100)[1] for seed in range(42, 47)]
            for j, alg in enumerate(NAMES):
                for metric in ("requests_per_sec", "avg_latency_ms"):
                    values = [getattr(runs[j], metric) for runs in per_seed]
                    with self.subTest(f"{pattern}/{alg}/{metric}"):
                        self.assertLess((max(values) - min(values)) / min(values), 0.05)

    def test_loadtest_numbers_match_the_cli(self):
        scenario, results = loadtest.run("spike", 1000, seed=42, rate=100)
        cli = cli_rows("--pattern", "spike", "--seed", "42", "--rate", "100",
                       "--duration", repr(loadtest.duration_s("spike", 1000, 100)))
        for r in results:
            comparison_row = cli[r.algorithm][0]
            self.assertEqual(comparison_row[1:], [f"{r.requests_per_sec:.1f}", f"{r.avg_latency_ms:.1f}",
                                                   f"{r.max_latency_ms:.1f}", str(r.failed)])

    def test_burst_is_a_sudden_ten_times_surge(self):
        for pattern, want in {"normal": 1.0, "spike": 1.6, "slow_server": 1.0, "burst": 1.9}.items():
            self.assertAlmostEqual(rate_factor(pattern), want, places=9, msg=pattern)
        factor, (lo, hi) = SURGES["burst"]
        self.assertEqual(factor, 10)
        scenario = make_scenario("burst", seed=1, duration_s=100, rate=100)
        window = [q for q in scenario.requests if lo * 100_000 <= q.arrival_ms < hi * 100_000]
        outside = len(scenario.requests) - len(window)
        in_window_rate = len(window) / ((hi - lo) * 100)
        outside_rate = outside / ((1 - (hi - lo)) * 100)
        self.assertAlmostEqual(in_window_rate / outside_rate, 10, delta=0.5)

    def test_loadtest_cli_prints_both_tables_with_all_three_algorithms(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            loadtest.main(["--sizes", "200", "400", "--seeds", "2"])
        for name in NAMES:
            self.assertEqual(out.getvalue().count(name), 2 * len(PATTERNS) * 2)  # 2 tables x patterns x sizes
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            loadtest.main(["--sizes", "0"])


def routed_while_down(result):
    from lbsim.simulator import routed_while_marked_down
    return routed_while_marked_down(result)


if __name__ == "__main__":
    unittest.main()
