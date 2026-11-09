"""Tables and series shared by the CLI and the dashboard, so both show the same numbers.

Tables are (headers, rows) of ready-to-print strings.
"""
import math

from .simulator import failover


def secs(ms, never="never"):
    return never if math.isinf(ms) else f"{ms / 1000:g}s"


def comparison_table(results):
    return (["Algorithm", "req/s", "avg ms", "max ms", "failed"],
            [[r.algorithm, f"{r.requests_per_sec:.1f}", f"{r.avg_latency_ms:.1f}",
              f"{r.max_latency_ms:.1f}", str(r.failed)] for r in results])


def load_table(results):
    return (["Load: requests handled"] + [f"{s.id} (w{s.weight})" for s in results[0].servers],
            [[r.algorithm] + [str(n) for n in r.load.values()] for r in results])


def failover_table(results, server_id):
    """-> (headers, rows). One row per algorithm; see failover() for the columns."""
    fo = [(r.algorithm, failover(r, server_id)) for r in results]
    return (["Failover: " + server_id, "served before kill", "refused (undetected)",
             "routed while marked down", "served after recovery", "success % while marked down"],
            [[a, str(x.before), str(x.refused), str(x.while_down), str(x.after),
              "n/a" if x.ok_while_down is None else f"{100 * x.ok_while_down:.1f}%"] for a, x in fo])


def failover_title(result, server_id, interval_ms, never="never"):
    """One line with the times. They depend on the scenario and check interval, not on the algorithm.
    `never` is what to print for something that has not happened (a live run says "not yet")."""
    f = failover(result, server_id)
    return (f"Failover: {server_id} killed at {secs(f.kill_ms)}, marked down at {secs(f.detect_ms, never)} "
            f"(health check every {interval_ms:g} ms), revived at {secs(f.revive_ms, never)}, "
            f"back in rotation at {secs(f.recover_ms, never)}")


def cli_command(pattern, seed, duration_s, rate, faults):
    """The CLI line that reproduces a run. None if the faults need more than one kill (+ its revive)."""
    cmd = f"python3 -m lbsim --pattern {pattern} --seed {seed} --duration {duration_s:g} --rate {rate:g}"
    kills = [f for f in faults if not f.alive]
    revives = [f for f in faults if f.alive]
    if len(kills) > 1 or len(revives) > 1 or (revives and (not kills or revives[0].server_id != kills[0].server_id
                                                              or revives[0].at_ms <= kills[0].at_ms)):
        return None
    if kills:
        cmd += f" --kill-server {kills[0].server_id} --at {kills[0].at_ms / 1000!r}s"
    if revives:
        cmd += f" --revive-at {revives[0].at_ms / 1000!r}s"
    return cmd


def timeseries(records, bucket_ms=1000, upto_ms=math.inf):
    """Per-bucket stats by arrival time, only for buckets that have fully elapsed by upto_ms.

    -> {"t": [bucket start, s], "ok": [served], "failed": [failed], "avg_ms": [mean latency or None]}
    With 1 s buckets, ok / failed are per second.
    """
    n = int(records[-1].arrival_ms // bucket_ms) + 1 if records else 0
    n = min(n, int(upto_ms // bucket_ms)) if upto_ms != math.inf else n
    ok, failed, lat = [0] * n, [0] * n, [0.0] * n
    for r in records:
        b = int(r.arrival_ms // bucket_ms)
        if b >= n:
            break
        if r.ok:
            ok[b] += 1
            lat[b] += r.latency_ms
        else:
            failed[b] += 1
    return {"t": [i * bucket_ms / 1000 for i in range(n)], "ok": ok, "failed": failed,
            "avg_ms": [lat[i] / ok[i] if ok[i] else None for i in range(n)]}


def recent_load(records, server_ids, now_ms, window_ms=5000):
    """Successful requests per server that arrived in the last window_ms."""
    counts = dict.fromkeys(server_ids, 0)
    for r in reversed(records):  # records are in arrival order
        if r.arrival_ms <= now_ms - window_ms:
            break
        if r.ok:
            counts[r.server_id] += 1
    return counts
