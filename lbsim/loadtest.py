"""Load runs: about 1k and 10k requests through every algorithm on every traffic pattern.

    python3 -m lbsim.loadtest [--sizes 1000 10000] [--rate 100] [--seed 42] [--seeds 5]

Each scenario is sized to roughly N requests at the base rate (surge patterns need less time), so the
`requests` column shows the real count. Table 1 is seed --seed and matches the CLI exactly:
python3 -m lbsim --pattern P --seed S --duration D --rate R. Table 2 shows how far the numbers move
across --seeds consecutive seeds, which is the "are these numbers stable" check.
"""
import argparse
import time

from .algorithms import ALGORITHMS
from .report import comparison_table, print_table
from .simulator import simulate
from .traffic import PATTERNS, make_scenario, rate_factor


def duration_s(pattern, n, rate):
    return n / (rate * rate_factor(pattern))


def run(pattern, n, seed, rate):
    """-> (Scenario, [RunResult per algorithm]) for a run of about n requests."""
    scenario = make_scenario(pattern, seed, duration_s(pattern, n, rate), rate)
    return scenario, [simulate(a, scenario) for a in ALGORITHMS]


def span(values, fmt):
    return f"{fmt(min(values))} - {fmt(max(values))}"


def main(argv=None):
    p = argparse.ArgumentParser(prog="python3 -m lbsim.loadtest", description=__doc__.split("\n")[0])
    p.add_argument("--sizes", type=int, nargs="+", default=[1000, 10000], metavar="N", help="requests per run")
    p.add_argument("--rate", type=float, default=100, help="base arrival rate, requests/sec")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--seeds", type=int, default=5, help="seeds for the stability table (1 skips it)")
    a = p.parse_args(argv)
    if min(a.sizes) <= 0 or a.rate <= 0 or a.seeds < 1:
        p.error("--sizes and --rate must be positive and --seeds at least 1")

    started = time.perf_counter()
    load, stable, runs = [], [], 0
    for pattern in PATTERNS:
        for n in a.sizes:
            per_seed = [run(pattern, n, a.seed + i, a.rate)[1] for i in range(a.seeds)]
            runs += a.seeds * len(ALGORITHMS)
            for j, alg in enumerate(ALGORITHMS):
                r = per_seed[0][j]
                _, (row,) = comparison_table([r])
                load.append([pattern, f"{n:,}", r.algorithm, f"{r.total:,}"] + row[1:] +
                            [f"{100 * r.failed / r.total:.1f}%" if r.total else "-"])
                seeds = [res[j] for res in per_seed]
                stable.append([pattern, f"{n:,}", r.algorithm,
                               span([s.requests_per_sec for s in seeds], lambda v: f"{v:.1f}"),
                               span([s.avg_latency_ms for s in seeds], lambda v: f"{v:.1f}"),
                               span([100 * s.failed / s.total for s in seeds], lambda v: f"{v:.1f}%")])
    print(f"Load runs: base {a.rate:g} req/s, sizes {', '.join(f'{n:,}' for n in a.sizes)}, seed {a.seed}")
    print_table(["Pattern", "Size", "Algorithm", "requests", "req/s", "avg ms", "max ms", "failed", "failed %"],
                load, left=3)
    if a.seeds > 1:
        print(f"\nStability: min - max across {a.seeds} seeds ({a.seed} to {a.seed + a.seeds - 1})")
        print_table(["Pattern", "Size", "Algorithm", "req/s", "avg ms", "failed %"], stable, left=3)
    print(f"\n{runs} simulations in {time.perf_counter() - started:.1f} s")


if __name__ == "__main__":
    main()
