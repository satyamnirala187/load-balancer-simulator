import unittest

from lbsim.algorithms import ALGORITHMS
from lbsim.simulator import simulate
from lbsim.traffic import PATTERNS, make_scenario


class TrafficTest(unittest.TestCase):
    def test_same_seed_same_traffic_and_spike_is_busier(self):
        a, b = make_scenario("normal", seed=3), make_scenario("normal", seed=3)
        self.assertEqual(a.requests, b.requests)
        self.assertGreater(len(make_scenario("spike", seed=3).requests), len(a.requests))
        self.assertEqual(make_scenario("slow_server", seed=3).slow, {"app-2": 5.0})

    def test_unknown_pattern_rejected(self):
        with self.assertRaises(ValueError):
            make_scenario("bogus")


class SimulateTest(unittest.TestCase):
    def test_every_request_accounted_and_connections_drain(self):
        for pattern in PATTERNS:
            scenario = make_scenario(pattern, seed=5, duration_s=5)
            for alg in ALGORITHMS:
                r = simulate(alg, scenario)
                self.assertEqual([x.request_id for x in r.records], [q.id for q in scenario.requests])
                self.assertEqual(sum(r.load.values()) + r.failed, r.total)
                self.assertTrue(all(s.connections == 0 for s in r.servers))
                self.assertTrue(all(x.latency_ms > 0 for x in r.records if x.ok))
                self.assertTrue(all(x.latency_ms is None for x in r.records if not x.ok))

    def test_round_robin_fails_more_than_weighted_under_spike(self):
        s = make_scenario("spike", seed=5, duration_s=10)
        rr, wlc = (simulate(a, s) for a in (ALGORITHMS[0], ALGORITHMS[2]))
        self.assertGreater(rr.failed, wlc.failed)


if __name__ == "__main__":
    unittest.main()
