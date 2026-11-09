"""CLI: run the same synthetic traffic through every algorithm and print a comparison.

    python3 -m lbsim [--pattern normal|spike|slow_server|all] [--seed N] [--duration S] [--rate R]
                     [--kill-server ID --at S [--revive-at S]] [--check-interval S]
"""
import argparse
import math

from .algorithms import ALGORITHMS
from .health import DEFAULT_INTERVAL_MS
from .servers import FLEET
from .simulator import failover, simulate
from .traffic import PATTERNS, Fault, make_scenario


def seconds(text):
    """'10s' or '10' -> 10.0"""
    return float(text.rstrip("s"))


def secs(ms):
    return "never" if math.isinf(ms) else f"{ms / 1000:g}s"


def print_table(headers, rows):
    """First column left-aligned, the rest right-aligned."""
    cells = [headers] + rows
    w = [max(len(r[i]) for r in cells) + 2 for i in range(len(headers))]
    fmt = lambda r: r[0].ljust(w[0]) + "".join(c.rjust(n) for c, n in zip(r[1:], w[1:]))
    print("\n" + fmt(headers) + "\n" + "-" * len(fmt(headers)))
    for r in rows:
        print(fmt(r))


def print_comparison(scenario, results, rate, duration, kill=None, interval_ms=DEFAULT_INTERVAL_MS):
    print(f"\nRailDhaara Tatkal rush [simulated] | pattern: {scenario.name} | "
          f"base {rate:g} req/s x {duration:g}s | {len(scenario.requests)} requests")
    if scenario.slow:
        print("slow servers: " + ", ".join(f"{k} x{v:g}" for k, v in scenario.slow.items()))
    print_table(["Algorithm", "req/s", "avg ms", "max ms", "failed"],
                [[r.algorithm, f"{r.requests_per_sec:.1f}", f"{r.avg_latency_ms:.1f}",
                  f"{r.max_latency_ms:.1f}", str(r.failed)] for r in results])
    print_table(["Load: requests handled"] + [f"{s.id} (w{s.weight})" for s in results[0].servers],
                [[r.algorithm] + [str(n) for n in r.load.values()] for r in results])
    if kill:
        fo = {r.algorithm: failover(r, kill) for r in results}
        f = next(iter(fo.values()))  # times depend only on the scenario and check interval, not the algorithm
        print(f"\nFailover: {kill} killed at {secs(f.kill_ms)}, marked down at {secs(f.detect_ms)} "
              f"(health check every {interval_ms:g} ms), revived at {secs(f.revive_ms)}, "
              f"back in rotation at {secs(f.recover_ms)}")
        print_table(["Failover: " + kill, "served before kill", "refused (undetected)",
                     "routed while marked down", "served after recovery", "success % while marked down"],
                    [[a, str(x.before), str(x.refused), str(x.while_down), str(x.after),
                      f"{100 * x.ok_while_down:.1f}%"] for a, x in fo.items()])


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
    a = p.parse_args(argv)
    if a.duration <= 0 or a.rate <= 0 or a.check_interval <= 0:
        p.error("--duration, --rate and --check-interval must be positive")
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
        results = [simulate(alg, scenario, interval_ms) for alg in ALGORITHMS]
        print_comparison(scenario, results, a.rate, a.duration, a.kill_server, interval_ms)


if __name__ == "__main__":
    main()
