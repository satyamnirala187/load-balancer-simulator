"""CLI: run the same synthetic traffic through every algorithm and print a comparison.

    python3 -m lbsim [--pattern normal|spike|slow_server|all] [--seed N] [--duration S] [--rate R]
"""
import argparse

from .algorithms import ALGORITHMS
from .simulator import simulate
from .traffic import PATTERNS, make_scenario


def print_comparison(scenario, results, rate, duration):
    print(f"\nRailDhaara Tatkal rush [simulated] | pattern: {scenario.name} | "
          f"base {rate:g} req/s x {duration:g}s | {len(scenario.requests)} requests")
    if scenario.slow:
        print("slow servers: " + ", ".join(f"{k} x{v:g}" for k, v in scenario.slow.items()))
    head = f"{'Algorithm':<22}{'req/s':>9}{'avg ms':>9}{'max ms':>9}{'failed':>9}"
    print("\n" + head + "\n" + "-" * len(head))
    for r in results:
        print(f"{r.algorithm:<22}{r.requests_per_sec:>9.1f}{r.avg_latency_ms:>9.1f}"
              f"{r.max_latency_ms:>9.1f}{r.failed:>9d}")
    cols = [f"{s.id} (w{s.weight})" for s in results[0].servers]
    head = f"{'Load: requests handled':<22}" + "".join(f"{c:>12}" for c in cols)
    print("\n" + head + "\n" + "-" * len(head))
    for r in results:
        print(f"{r.algorithm:<22}" + "".join(f"{n:>12d}" for n in r.load.values()))


def main(argv=None):
    p = argparse.ArgumentParser(prog="python3 -m lbsim", description=__doc__.split("\n")[0])
    p.add_argument("--pattern", choices=(*PATTERNS, "all"), default="normal")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--duration", type=float, default=20, help="seconds of simulated traffic")
    p.add_argument("--rate", type=float, default=100, help="base arrival rate, requests/sec")
    a = p.parse_args(argv)
    if a.duration <= 0 or a.rate <= 0:
        p.error("--duration and --rate must be positive")
    for pattern in PATTERNS if a.pattern == "all" else (a.pattern,):
        scenario = make_scenario(pattern, a.seed, a.duration, a.rate)  # built once: same traffic for every algorithm
        print_comparison(scenario, [simulate(alg, scenario) for alg in ALGORITHMS], a.rate, a.duration)


if __name__ == "__main__":
    main()
