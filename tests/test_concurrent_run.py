"""Thread safety under load: a FULL run with real threads, not just the balancer on its own.

16 worker threads push requests through a balancer while a prober thread runs the health checks and a
chaos thread kills and revives servers underneath them (with and without the passive check). The balancer
is wrapped so that, inside its own lock, it audits every single pick. Afterwards every count must be exact.
"""
import random
import sys
import threading
import time
import unittest
from collections import Counter

from lbsim.algorithms import LeastConnections, RoundRobin, WeightedLeastConnections
from lbsim.health import HealthChecker
from lbsim.servers import make_servers

WORKERS = 16
MIN_REQUESTS = 12_000
CHAOS_VICTIMS = ("app-1", "app-3", "app-5")
SCORES = {RoundRobin: None,
          LeastConnections: lambda s: s.connections,
          WeightedLeastConnections: lambda s: s.connections / s.weight}


def audited(cls, score):
    """`cls` plus an audit that runs inside the balancer's lock, where reading every count is atomic."""

    class Audited(cls):
        def __init__(self, servers):
            super().__init__(servers)
            self.picks = 0
            self.violations = []
            self.max_open = 0
            self.uncounted = False  # a pick has been made but its connection is not counted yet

        def _changed(self, s):
            self.uncounted = False
            super()._changed(s)

        def _pick(self):
            s = super()._pick()
            if s is not None:
                self.picks += 1
                if self.uncounted:  # pick and count must be one atomic step, or counts go stale
                    self.violations.append("picked while the previous pick was still uncounted")
                self.uncounted = True
                if not s.healthy:
                    self.violations.append(f"picked marked-down {s.id}")
                healthy = [x for x in self.servers if x.healthy]
                if score and score(s) != min(score(x) for x in healthy):
                    self.violations.append(f"stale pick of {s.id}: {score(s)} vs min {min(score(x) for x in healthy)}")
                self.max_open = max(self.max_open, sum(x.connections for x in self.servers) + 1)  # +1: this pick
            return s

    return Audited


class FullRun:
    """Run it, then read the results off the attributes."""

    def __init__(self, base_cls, passive_after):
        self.base_cls = base_cls
        self.score = SCORES[base_cls]
        self.servers = make_servers()
        self.lb = audited(base_cls, self.score)(self.servers)
        self.checker = HealthChecker(self.lb, interval_ms=1, passive_after=passive_after)
        self.by_id = {s.id: s for s in self.servers}
        self.stop = threading.Event()
        self.problems = []  # exceptions and timeouts from any thread
        self.tallies = []  # one (outcomes, per-server ok) pair per worker: merged after, so nothing to race on
        self.t0 = time.monotonic()

    def now_ms(self):
        return (time.monotonic() - self.t0) * 1000

    def guarded(self, fn):
        def run(*a):
            try:
                fn(*a)
            except BaseException as e:  # noqa: BLE001  a crash in any thread must fail the test
                self.problems.append(repr(e))
        return run

    def wait_for(self, cond, what, timeout=10):
        end = time.monotonic() + timeout
        while not cond():
            if time.monotonic() > end:
                raise TimeoutError(what)
            time.sleep(0.0005)

    def worker(self, k):
        rng, outcomes, per_server, n = random.Random(k), Counter(), Counter(), 0
        self.tallies.append((outcomes, per_server))
        while not (self.stop.is_set() and n >= MIN_REQUESTS // WORKERS):
            n += 1
            s = self.lb.acquire()
            if s is None:
                outcomes["no healthy server"] += 1
                continue
            try:
                if not s.alive:
                    outcomes["refused"] += 1
                    self.checker.note_refused(s, self.now_ms())
                elif s.connections > s.max_connections:
                    outcomes["overloaded"] += 1
                else:
                    outcomes["ok"] += 1
                    per_server[s.id] += 1
                    self.checker.note_ok(s)
                    time.sleep(rng.choice((0, 0, 0, 0.0001)))  # hold the connection across a thread switch
            finally:
                self.lb.release(s)

    def prober(self):
        while not self.stop.is_set():
            self.checker.check(self.now_ms())
            time.sleep(0.001)

    def chaos(self):
        try:
            for sid in CHAOS_VICTIMS:
                s = self.by_id[sid]
                s.alive = False
                self.wait_for(lambda: not s.healthy, f"{sid} never marked down")
                time.sleep(0.005)  # traffic flows around the hole
                s.alive = True
                self.wait_for(lambda: s.healthy, f"{sid} never marked back up")
                time.sleep(0.005)
        finally:
            self.stop.set()  # always release the workers, even if chaos failed

    def run(self):
        old = sys.getswitchinterval()
        sys.setswitchinterval(1e-6)  # switch threads as often as possible
        try:
            threads = [threading.Thread(target=self.guarded(self.worker), args=(k,)) for k in range(WORKERS)]
            threads += [threading.Thread(target=self.guarded(self.prober)), threading.Thread(target=self.guarded(self.chaos))]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=60)
            if any(t.is_alive() for t in threads):
                self.problems.append("a thread is still running after 60 s (deadlock?)")
        finally:
            sys.setswitchinterval(old)
        self.checker.check(self.now_ms())  # settle: anything still dead-but-trusted gets noticed
        self.outcomes = sum((o for o, _ in self.tallies), Counter())
        self.ok_by_server = sum((p for _, p in self.tallies), Counter())
        return self


class ConcurrentFullRunTest(unittest.TestCase):
    def check_exact(self, r):
        total = sum(r.outcomes.values())
        self.assertEqual(r.problems, [])
        self.assertGreaterEqual(total, MIN_REQUESTS)
        self.assertGreater(r.outcomes["refused"], 0)  # servers really did die under the workers
        self.assertGreaterEqual(r.lb.max_open, 4)  # and the workers really did overlap
        # every request is accounted for exactly once
        self.assertEqual(r.lb.picks, total - r.outcomes["no healthy server"])  # one pick per successful acquire
        self.assertEqual(sum(r.ok_by_server.values()), r.outcomes["ok"])
        # no connection leaked or double counted
        self.assertEqual([s.connections for s in r.servers], [0] * len(r.servers))
        self.assertLessEqual(r.lb.max_open, WORKERS)  # never more open than there are workers
        # every pick was exact, and never a server marked down at that instant
        self.assertEqual(r.lb.violations, [])
        # the heap's keys are exactly the servers' real loads (a stale key = a lost update)
        if r.score:
            heap = r.lb._heap
            self.assertEqual(sorted(heap._a), sorted((r.score(s), s.id) for s in r.servers if s.healthy))
            self.assertTrue(all(heap._pos[sid] == i for i, (_, sid) in enumerate(heap._a)))
        # health transitions are logged once each: strictly down, up, down, up ...
        for sid in CHAOS_VICTIMS:
            states = [up for _, i, up in r.checker.log if i == sid]
            self.assertGreaterEqual(len(states), 2, sid)
            self.assertEqual(states[0], False, sid)
            self.assertTrue(all(a != b for a, b in zip(states, states[1:])), (sid, states))
        self.assertTrue(all(s.healthy == s.alive for s in r.servers))

    def test_full_run_counts_stay_exact(self):
        for base_cls in SCORES:
            for passive_after in (0, 3):
                with self.subTest(f"{base_cls.name}, passive_after={passive_after}"):
                    self.check_exact(FullRun(base_cls, passive_after).run())


if __name__ == "__main__":
    unittest.main()
