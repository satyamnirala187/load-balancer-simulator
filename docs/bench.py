"""Micro-benchmarks behind the complexity section of REPORT.md. Writes docs/bench_results.json.

    python3 docs/bench.py

1. Heap vs linear scan: one balancer operation (acquire or release) on a fleet of n servers.
   The linear version is what Least Connections would be without the heap: min() over every healthy server.
2. Whole simulation: wall time per request as the run grows (1k, 10k, 100k requests).

Timings are for one machine and one Python build; read the shape (how cost grows), not the absolute microseconds.
"""
import json
import os
import platform
import random
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from lbsim.algorithms import ALGORITHMS, Balancer, LeastConnections  # noqa: E402
from lbsim.servers import Server  # noqa: E402
from lbsim.simulator import simulate  # noqa: E402
from lbsim.traffic import make_scenario  # noqa: E402


class LinearLeastConnections(Balancer):
    """Least Connections by scanning every server: O(n) per pick. The baseline the heap replaces."""

    def _pick(self):
        return min((s for s in self.servers if s.healthy), key=lambda s: (s.connections, s.id), default=None)


def per_op_us(cls, n, ops, repeats=3):
    """Microseconds per balancer operation: n connections open, then `ops` times release one and acquire one."""
    best = float("inf")
    for _ in range(repeats):
        held = [Server(f"s{i:05d}", 1 + i % 8, 50, connections=1) for i in range(n)]  # n connections already open
        lb = cls(held)  # (the heap reads those counts when it is built, so no O(n^2) warm-up)
        rng = random.Random(1)
        t = time.perf_counter()
        for _ in range(ops):
            lb.release(held.pop(rng.randrange(len(held))))
            held.append(lb.acquire())
        best = min(best, (time.perf_counter() - t) / (2 * ops) * 1e6)
    return best


def main():
    results = {"machine": {"python": platform.python_version(), "platform": platform.platform(),
                           "processor": platform.processor() or platform.machine()},
               "heap_vs_linear": [], "per_request": []}
    for n, ops in ((5, 20000), (15, 20000), (20, 20000), (50, 20000), (500, 10000), (5000, 2000), (50000, 300)):
        heap, linear = per_op_us(LeastConnections, n, ops), per_op_us(LinearLeastConnections, n, ops)
        results["heap_vs_linear"].append({"servers": n, "heap_us": round(heap, 2), "linear_us": round(linear, 2),
                                          "linear_over_heap": round(linear / heap, 2)})
        print(f"n={n:>6}: heap {heap:8.2f} us/op   linear scan {linear:10.2f} us/op   linear/heap = {linear / heap:7.2f}")
    for requests in (1_000, 10_000, 100_000):
        scenario = make_scenario("normal", 42, requests / 100, 100)
        row = {"requests": len(scenario.requests)}
        for alg in ALGORITHMS:
            best = min(_time(lambda: simulate(alg, scenario)) for _ in range(3))
            row[alg.name] = round(best / len(scenario.requests) * 1e6, 2)
        results["per_request"].append(row)
        print(f"{row['requests']:>7,} requests: " + "   ".join(f"{k} {v} us/request" for k, v in row.items() if k != "requests"))
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bench_results.json")
    with open(path, "w") as f:
        json.dump(results, f, indent=2)
    print("wrote", path)


def _time(fn):
    t = time.perf_counter()
    fn()
    return time.perf_counter() - t


if __name__ == "__main__":
    main()
