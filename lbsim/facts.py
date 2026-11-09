"""The headline numbers quoted in README.md, REPORT.md, the demo script, the viva sheet and the slide deck, computed from the simulator.

    python3 -m lbsim.facts        # print every table, ready to paste into the documents

tests/test_docs.py fails when a document and these numbers disagree, so the documents cannot drift quietly.
Results are cached for the process and must be treated as read-only. Everything here is deterministic (seed 42,
base rate 100 req/s) except the benchmark timings, which are read from docs/bench_results.json (produced once by
docs/bench.py) because timings differ between runs.
"""
import contextlib
import functools
import io
import json
import os

from .algorithms import ALGORITHMS
from .loadtest import LOAD_HEADERS, tables
from .report import failover, print_table
from .servers import FLEET, OVERLOAD
from .simulator import simulate
from .traffic import SURGES, Fault, make_scenario

SEED, RATE = 42, 100
NAMES = [a.name for a in ALGORITHMS]
BENCH_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "bench_results.json")


def md(headers, rows):
    return "\n".join(["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)] +
                     ["| " + " | ".join(str(c) for c in r) + " |" for r in rows])


@functools.lru_cache(maxsize=None)
def load_rows():
    """The load table's rows (seed 42, about 1,000 and 10,000 requests): lists of ready-to-print strings."""
    return tables((1000, 10000), RATE, SEED, 1)[0]


def load_text():
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        print_table(LOAD_HEADERS, load_rows(), left=3)
    return out.getvalue().strip("\n")


def load_cell(pattern, size, algorithm):
    """-> dict of one load-table row (strings): requests, req_s, avg_ms, max_ms, failed, failed_pct."""
    for row in load_rows():
        if row[:3] == [pattern, f"{size:,}", algorithm]:
            return dict(zip(("requests", "req_s", "avg_ms", "max_ms", "failed", "failed_pct"), row[3:]))
    raise KeyError((pattern, size, algorithm))


@functools.lru_cache(maxsize=None)
def stability():
    """Largest (max - min) / min across 5 seeds, in %, over normal and slow_server and all algorithms."""
    out = {}
    for n in (1000, 10000):
        worst = {"req_s": 0.0, "avg_ms": 0.0}
        for pattern in ("normal", "slow_server"):
            from .loadtest import run
            per_seed = [run(pattern, n, SEED + i, RATE)[1] for i in range(5)]
            for j in range(len(ALGORITHMS)):
                for key, attr in (("req_s", "requests_per_sec"), ("avg_ms", "avg_latency_ms")):
                    v = [getattr(runs[j], attr) for runs in per_seed]
                    worst[key] = max(worst[key], 100 * (max(v) - min(v)) / min(v))
        out[n] = worst
    return out


@functools.lru_cache(maxsize=None)
def blind_window():
    """{(check interval ms, passive_after): {algorithm: refused requests}}: normal load, app-3 killed at 10 s, revived at 15 s."""
    scenario = make_scenario("normal", SEED, 20, RATE)
    scenario.faults = [Fault(10_000, "app-3", False), Fault(15_000, "app-3", True)]
    return {(iv, p): {a.name: failover(simulate(a, scenario, iv, p), "app-3").refused for a in ALGORITHMS}
            for iv in (2000, 500, 100) for p in (0, 3)}


def blind_window_md():
    bw = blind_window()
    cell = lambda iv, p: " / ".join(str(bw[iv, p][n]) for n in NAMES)
    return md(["check interval", "probe only: RR / LC / WLC", "with `--passive-after 3`: RR / LC / WLC"],
              [[f"{iv / 1000:g} s", cell(iv, 0), cell(iv, 3)] for iv in (2000, 500, 100)])


@functools.lru_cache(maxsize=None)
def spike_kill():
    """{passive_after: {algorithm: (refused, 'success while marked down')}}: spike pattern, app-1 killed at 8 s, revived at 12 s."""
    scenario = make_scenario("spike", SEED, 20, RATE)
    scenario.faults = [Fault(8_000, "app-1", False), Fault(12_000, "app-1", True)]
    out = {}
    for p in (0, 3):
        out[p] = {}
        for a in ALGORITHMS:
            f = failover(simulate(a, scenario, 500, p), "app-1")
            out[p][a.name] = (f.refused, f"{100 * f.ok_while_down:.1f}%")
    return out


@functools.lru_cache(maxsize=None)
def fast_detection():
    """Spike with app-1 killed at 7.9 s: success while marked down with a 0.5 s probe against a 1 ms probe.

    Shows how little of the loss is detection delay. -> {"slow": [3 floats], "fast": [3 floats], "max_diff": float}
    """
    scenario = make_scenario("spike", SEED, 20, RATE)
    scenario.faults = [Fault(7_900, "app-1", False), Fault(12_000, "app-1", True)]
    out = {key: [100 * failover(simulate(a, scenario, iv), "app-1").ok_while_down for a in ALGORITHMS]
           for key, iv in (("slow", 500), ("fast", 1))}
    out["max_diff"] = max(abs(a - b) for a, b in zip(out["slow"], out["fast"]))
    return out


def spike_kill_md():
    sk = spike_kill()
    row = lambda label, p, i: [label] + [str(sk[p][n][i]) for n in NAMES]
    return md(["", *NAMES],
              [row("success while marked down, probe only", 0, 1), row("success while marked down, `--passive-after 3`", 3, 1),
               row("refused in the blind window, probe only", 0, 0), row("refused in the blind window, `--passive-after 3`", 3, 0)])


@functools.lru_cache(maxsize=None)
def capacity():
    """Estimated sustainable req/s (whole numbers) and a steady-load sweep with app-1 dead from the first millisecond.

    A server holding c connections answers in base * (1 + c / weight) and rejects at OVERLOAD * weight, so
    Little's law gives a sustainable rate of OVERLOAD / (OVERLOAD + 1) * weight / base. It is an estimate.
    """
    per = {sid: OVERLOAD / (OVERLOAD + 1) * w / (ms / 1000) for sid, w, ms in FLEET}
    sweep = {}
    for rate in (150, 200, 250, 300, 350, 400, 450):
        scenario = make_scenario("normal", SEED, 20, rate)
        sweep[rate] = {}
        for label, faults in (("survivors", [Fault(0, "app-1", False)]), ("all", [])):
            scenario.faults = faults
            ok = []
            for a in ALGORITHMS:
                late = [r for r in simulate(a, scenario, 1).records if r.arrival_ms > 10]  # health checks every 1 ms
                ok.append(f"{100 * sum(r.ok for r in late) / len(late):.1f}")
            sweep[rate][label] = ok
    full, survivors = sum(per.values()), sum(per.values()) - per["app-1"]
    return {"full": int(full), "survivors": int(survivors), "app-1": int(per["app-1"]), "sweep": sweep,
            "ceiling_pct": round(100 * survivors / 400)}  # survivors / the spike's 400 req/s, from the unrounded estimate


@functools.lru_cache(maxsize=None)
def burst():
    """Why a x10 burst fails about 31% whatever the algorithm: the share of requests that arrive inside the burst, and what
    fraction of the burst's offered rate the whole fleet can serve (estimated capacity, unrounded). -> whole percentages."""
    factor, (lo, hi) = SURGES["burst"]
    in_burst = factor * (hi - lo)
    share = in_burst / (in_burst + (1 - (hi - lo)))
    per = {sid: OVERLOAD / (OVERLOAD + 1) * w / (ms / 1000) for sid, w, ms in FLEET}
    unserved = max(0.0, 1 - sum(per.values()) / (RATE * factor))
    return {"share_pct": round(100 * share), "floor_pct": round(100 * share * unserved)}


def capacity_md():
    sw = capacity()["sweep"]
    rates = list(sw)
    rows = [[f"{label}, {name}"] + [sw[r][fleet][i] for r in rates]
            for label, fleet in (("4 survivors", "survivors"), ("all 5 servers", "all"))
            for i, name in enumerate(NAMES)]
    return md(["steady offered req/s"] + [str(r) for r in rates], rows)


@functools.lru_cache(maxsize=None)
def spike_latency():
    """Why Weighted LC's average latency is higher in the spike even though it fails far fewer requests (10k run)."""
    from .loadtest import run
    _, (rr, lc, wlc) = run("spike", 10000, SEED, RATE)
    both = [(x.latency_ms, y.latency_ms) for x, y in zip(lc.records, wlc.records) if x.ok and y.ok]
    extra = [y.latency_ms for x, y in zip(lc.records, wlc.records) if not x.ok and y.ok]
    return {"avg_ms": {r.algorithm: f"{r.avg_latency_ms:.1f}" for r in (rr, lc, wlc)},
            "shared": len(both), "shared_lc_ms": f"{sum(p for p, _ in both) / len(both):.1f}",
            "shared_wlc_ms": f"{sum(q for _, q in both) / len(both):.1f}",
            "extra": len(extra), "extra_ms": f"{sum(extra) / len(extra):.1f}"}


@functools.lru_cache(maxsize=None)
@functools.lru_cache(maxsize=None)
def demo():
    """The three runs of the class demo (seed 42, 20 s, 100 req/s): a normal morning; the rush; the rush with app-3
    killed at 9 s and revived at 14.5 s. -> lists of strings, one per algorithm in NAMES order."""
    def run(pattern, faults=()):
        scenario = make_scenario(pattern, SEED, 20, RATE)
        scenario.faults = list(faults)
        return [simulate(a, scenario) for a in ALGORITHMS]

    normal, rush = run("normal"), run("spike")
    killed = run("spike", [Fault(9_000, "app-3", False), Fault(14_500, "app-3", True)])
    fo = [failover(r, "app-3") for r in killed]
    return {"requests": {"normal": len(normal[0].records), "rush": len(rush[0].records), "kill": len(killed[0].records)},
            "normal_avg_ms": [f"{r.avg_latency_ms:.1f}" for r in normal], "rush_failed": [str(r.failed) for r in rush],
            "kill_failed": [str(r.failed) for r in killed], "kill_refused": [str(f.refused) for f in fo],
            "kill_success": [f"{100 * f.ok_while_down:.1f}%" for f in fo]}


def bench():
    with open(BENCH_FILE) as f:
        return json.load(f)


def main():
    print("## load runs\n" + load_text())
    print("\n## blind window\n" + blind_window_md())
    print("\n## spike, app-1 killed\n" + spike_kill_md())
    c = capacity()
    print(f"\n## capacity: full fleet {c['full']} req/s, survivors {c['survivors']} req/s, app-1 {c['app-1']} req/s\n" + capacity_md())
    print("\n## stability (max-min)/min %:", {n: {k: round(v, 1) for k, v in d.items()} for n, d in stability().items()})
    print("\n## burst:", burst())
    print("\n## spike latency:", spike_latency())
    print("\n## detection delay, success while down (0.5 s probe vs 1 ms probe):", {k: ([round(x, 1) for x in v] if k != "max_diff" else round(v, 1)) for k, v in fast_detection().items()})


if __name__ == "__main__":
    main()
