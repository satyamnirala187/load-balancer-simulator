import random
import sys
import threading
import time
import unittest

from lbsim.algorithms import LeastConnections, MinHeap, RoundRobin, WeightedLeastConnections
from lbsim.servers import Server


def fleet(*weights, connections=0):
    return [Server(f"s{i}", w, 50, connections=connections) for i, w in enumerate(weights, 1)]


class MinHeapTest(unittest.TestCase):
    def test_random_ops_match_brute_force(self):
        rng, heap, model = random.Random(1), MinHeap(), {}
        for _ in range(3000):
            sid = f"s{rng.randrange(40)}"
            op = rng.choice(["set", "set", "remove"])
            if op == "remove" and sid in model:
                heap.remove(sid)
                del model[sid]
            elif op == "set":
                key = rng.randrange(100)
                (heap.update if sid in model else heap.push)(sid, key)
                model[sid] = key
            self.assertEqual(heap.peek(), min(((k, i) for i, k in model.items()), default=None))
            for i in range(1, len(heap._a)):  # heap property + position map
                self.assertLessEqual(heap._a[(i - 1) // 2], heap._a[i])
            self.assertTrue(all(heap._a[i][1] == sid for sid, i in heap._pos.items()))


class PickTest(unittest.TestCase):
    def test_heap_pick_returns_least_loaded(self):
        a, b, c = fleet(1, 1, 1, connections=0)
        a.connections, b.connections, c.connections = 5, 2, 9
        self.assertIs(LeastConnections([a, b, c]).acquire(), b)

    def test_heap_updates_after_request_finishes(self):
        lb = LeastConnections(fleet(1, 1, 1))
        a, b, c = lb.servers
        for _ in range(4):  # 1 each, then a again -> a=2, b=1, c=1
            lb.acquire()
        self.assertEqual([s.connections for s in lb.servers], [2, 1, 1])
        lb.release(b)
        self.assertEqual(b.connections, 0)
        self.assertIs(lb.acquire(), b)  # b became the unique minimum after finishing its request

    def test_round_robin_cycles_evenly(self):
        lb = RoundRobin(fleet(5, 1, 1))  # weights must not matter
        picks = [lb.acquire().id for _ in range(9)]
        self.assertEqual(picks, ["s1", "s2", "s3"] * 3)
        self.assertEqual([s.connections for s in lb.servers], [3, 3, 3])

    def test_weighted_favours_higher_weight_under_equal_load(self):
        # equal load (3 connections each): s1 has the lowest connections/weight
        self.assertEqual(WeightedLeastConnections(fleet(4, 2, 1, connections=3)).acquire().id, "s1")
        # from empty, picks split in proportion to weight (plain least-connections would give 3/2/2)
        lb = WeightedLeastConnections(fleet(4, 2, 1))
        for _ in range(7):
            lb.acquire()
        self.assertEqual([s.connections for s in lb.servers], [4, 2, 1])

    def test_down_servers_are_skipped_and_rejoin(self):
        for cls in (RoundRobin, LeastConnections, WeightedLeastConnections):
            lb = cls(fleet(1, 1, 1))
            lb.set_healthy(lb.servers[0], False)
            self.assertNotIn("s1", {lb.acquire().id for _ in range(6)}, cls.name)
            lb.set_healthy(lb.servers[0], True)
            self.assertIn("s1", {lb.acquire().id for _ in range(6)}, cls.name)

    def test_all_down_returns_none(self):
        lb = LeastConnections(fleet(1, 1))
        for s in lb.servers:
            lb.set_healthy(s, False)
        self.assertIsNone(lb.acquire())

    def test_random_walk_always_picks_a_minimum(self):
        rng = random.Random(7)
        for cls, score in [(LeastConnections, lambda s: s.connections),
                           (WeightedLeastConnections, lambda s: s.connections / s.weight)]:
            lb, held = cls(fleet(5, 3, 3, 2, 1)), []
            for _ in range(2000):
                if held and rng.random() < 0.45:
                    lb.release(held.pop(rng.randrange(len(held))))
                else:
                    before = {s.id: score(s) for s in lb.servers}
                    s = lb.acquire()
                    self.assertEqual(before[s.id], min(before.values()))
                    held.append(s)
            for s in held:
                lb.release(s)
            self.assertTrue(all(s.connections == 0 for s in lb.servers))


class YieldingLC(LeastConnections):
    def _pick(self):
        s = super()._pick()
        time.sleep(0)  # invite a thread switch between choosing and counting
        return s


class ConcurrencyTest(unittest.TestCase):
    def run_threads(self, fn, n=8):
        threads = [threading.Thread(target=fn) for _ in range(n)]
        [t.start() for t in threads]
        [t.join() for t in threads]

    def test_concurrent_requests_never_double_count(self):
        lb = YieldingLC(fleet(1, 1, 1, 1, 1))
        old = sys.getswitchinterval()
        sys.setswitchinterval(1e-6)
        try:
            self.run_threads(lambda: [lb.acquire() for _ in range(300)])
        finally:
            sys.setswitchinterval(old)
        counts = [s.connections for s in lb.servers]
        self.assertEqual(sum(counts), 8 * 300)  # no lost or double increments
        # picks on stale counts would pile onto one server; exact counts stay within 1 of each other
        self.assertLessEqual(max(counts) - min(counts), 1)

    def test_concurrent_acquire_release_drains_to_zero(self):
        lb = WeightedLeastConnections(fleet(4, 3, 2, 1))

        def churn():
            for _ in range(500):
                lb.release(lb.acquire())

        self.run_threads(churn)
        self.assertEqual([s.connections for s in lb.servers], [0, 0, 0, 0])


if __name__ == "__main__":
    unittest.main()
