"""CLI: run the same synthetic traffic through every algorithm and print a comparison.

    python3 -m lbsim [--pattern normal|spike|slow_server|burst|all] [--seed N] [--duration S] [--rate R]
                     [--kill-server ID --at S [--revive-at S]] [--check-interval S] [--passive-after N]
"""
import argparse

from .algorithms import ALGORITHMS
from .health import DEFAULT_INTERVAL_MS
from .report import comparison_table, failover_table, failover_title, load_table, print_table
from .servers import FLEET
from .simulator import simulate
from .traffic import PATTERNS, Fault, make_scenario


def seconds(text):
    """'10s' or '10' -> 10.0"""
    return float(text.rstrip("s"))


def print_comparison(scenario, results, rate, duration, kill=None, interval_ms=DEFAULT_INTERVAL_MS, passive_after=0):
    print(f"\nRailDhaara Tatkal rush [simulated] | pattern: {scenario.name} | "
          f"base {rate:g} req/s x {duration:g}s | {len(scenario.requests)} requests")
    if scenario.slow:
        print("slow servers: " + ", ".join(f"{k} x{v:g}" for k, v in scenario.slow.items()))
    print_table(*comparison_table(results))
    print_table(*load_table(results))
    if kill:
        print("\n" + failover_title(results[0], kill, interval_ms, passive_after=passive_after))
        print_table(*failover_table(results, kill))


def main(argv=None):
    p = argparse.ArgumentParser(prog="python3 -m lbsim", description=__doc__.split("\n")[0])
    p.add_argument("--pattern", choices=(*PATTERNS, "all"), default="normal")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--duration", type=float, default=20, help="seconds of simulated traffic")
    p.add_argument("--rate", type=float, default=100, help="base arrival rate, requests/sec")
    p.add_argument("--kill-server", choices=[f[0] for f in FLEET], metavar="ID",
                   help="stop this server mid-run: it stops accepting new requests; ones already in flight finish")
    p.add_argument("--at", type=seconds, metavar="S", help="when to kill it, e.g. 10s (needs --kill-server)")
    p.add_argument("--revive-at", type=seconds, metavar="S", help="when to bring it back, e.g. 15s")
    p.add_argument("--check-interval", type=seconds, default=DEFAULT_INTERVAL_MS / 1000, metavar="S",
                   help="seconds between health checks (default 0.5s)")
    p.add_argument("--passive-after", type=int, default=0, metavar="N",
                   help="also mark a server down after N refused requests in a row (default 0 = off)")
    a = p.parse_args(argv)
    if a.duration <= 0 or a.rate <= 0 or a.check_interval <= 0:
        p.error("--duration, --rate and --check-interval must be positive")
    if a.passive_after < 0:
        p.error("--passive-after must be 0 (off) or a positive count")
    if a.kill_server:
        if a.at is None:
            p.error("--kill-server needs --at")
        if not 0 <= a.at < a.duration:
            p.error("--at must be inside the run (0 <= at < duration)")
        if a.revive_at is not None and not a.at < a.revive_at < a.duration:
            p.error("--revive-at must be after --at and inside the run")
    elif a.at is not None or a.revive_at is not None:
        p.error("--at / --revive-at need --kill-server")
    for pattern in PATTERNS if a.pattern == "all" else (a.pattern,):
        scenario = make_scenario(pattern, a.seed, a.duration, a.rate)  # built once: same traffic for every algorithm
        if a.kill_server:
            scenario.faults = [Fault(a.at * 1000, a.kill_server, False)]
            if a.revive_at is not None:
                scenario.faults.append(Fault(a.revive_at * 1000, a.kill_server, True))
        interval_ms = a.check_interval * 1000
        results = [simulate(alg, scenario, interval_ms, a.passive_after) for alg in ALGORITHMS]
        print_comparison(scenario, results, a.rate, a.duration, a.kill_server, interval_ms, a.passive_after)


if __name__ == "__main__":
    main()
