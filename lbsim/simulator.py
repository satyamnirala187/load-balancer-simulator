"""Discrete-event simulation on a virtual clock (ms): no sleeping, no threads, fully reproducible.

A request holds a connection from its arrival until arrival + latency. Latency is fixed when the
server accepts it, from the load at that moment. A request fails if:
  - every server is marked down ("no healthy server"),
  - the server it was sent to is really dead but not yet marked down ("refused"),
  - that server is already at max_connections ("overloaded").

FAILOVER POLICY. When a server dies, requests already IN FLIGHT on it are left alone: they finish
and release their connections; only NEW requests are re-routed (after the next health check, via
the heap). Why: (1) that is what real load balancers do when they mark a server down: stop new
traffic, let accepted connections drain; (2) RailDhaara's requests are bookings and payments, which
are not idempotent, so cutting them off and auto-retrying risks a double booking. The cost is that a
"kill" models a server that stops accepting requests, not a power cut that drops accepted ones.
Requests sent to the dead server before the checker notices are refused and counted as failed;
shortcut: they are not retried (that would be safe, since the server never processed them, but it
would hide the cost of the detection delay).
"""
import heapq
import math
from collections import deque
from dataclasses import dataclass
from functools import partial

from .health import DEFAULT_INTERVAL_MS, HealthChecker
from .servers import make_servers


@dataclass
class Record:
    request_id: int
    arrival_ms: float
    server_id: str  # server that took (or turned away) the request; None if every server was down
    latency_ms: float  # None for failed requests
    ok: bool
    error: str = None  # None, "no healthy server", "refused" or "overloaded"


@dataclass
class RunResult:
    algorithm: str
    records: list
    servers: list  # final server state (ids and weights, for reporting)
    duration_ms: float  # first arrival -> last completion
    health_log: list  # (time_ms, server_id, healthy) for each change the health checker made
    faults: list  # the scenario's Fault events

    @property
    def total(self):
        return len(self.records)

    @property
    def failed(self):
        return sum(not r.ok for r in self.records)

    @property
    def requests_per_sec(self):  # successful requests only
        return (self.total - self.failed) / (self.duration_ms / 1000) if self.duration_ms else 0.0

    @property
    def _latencies(self):
        return [r.latency_ms for r in self.records if r.ok]

    @property
    def avg_latency_ms(self):  # successful requests only
        lat = self._latencies
        return sum(lat) / len(lat) if lat else 0.0

    @property
    def max_latency_ms(self):
        return max(self._latencies, default=0.0)

    @property
    def load(self):
        """Successful requests handled per server id."""
        counts = {s.id: 0 for s in self.servers}
        for r in self.records:
            if r.ok:
                counts[r.server_id] += 1
        return counts


def simulate(algorithm, scenario, check_interval_ms=DEFAULT_INTERVAL_MS):
    servers = make_servers(scenario.slow)
    by_id = {s.id: s for s in servers}
    lb = algorithm(servers)
    checker = HealthChecker(lb, check_interval_ms)

    # Control events on the virtual clock. At the same instant a health check runs BEFORE a fault, so a
    # server killed at t is first noticed one full interval later: detection delay is in (0, interval].
    events = [(f.at_ms, 1, partial(setattr, by_id[f.server_id], "alive", f.alive)) for f in scenario.faults]
    if scenario.requests:
        ticks = int(scenario.requests[-1].arrival_ms // check_interval_ms)
        events += [(k * check_interval_ms, 0, partial(checker.check, k * check_interval_ms))
                   for k in range(1, ticks + 1)]
    events = deque(sorted(events, key=lambda e: e[:2]))

    in_flight = []  # heap of (finish_ms, request_id, server)
    records = []
    last_done = 0.0
    for req in scenario.requests:
        while events and events[0][0] <= req.arrival_ms:
            events.popleft()[2]()
        while in_flight and in_flight[0][0] <= req.arrival_ms:
            lb.release(heapq.heappop(in_flight)[2])
        s = lb.acquire()
        why = ("no healthy server" if s is None else "refused" if not s.alive
               else "overloaded" if s.connections > s.max_connections else None)
        if why:
            if s:
                lb.release(s)
            records.append(Record(req.id, req.arrival_ms, s and s.id, None, False, why))
            continue
        latency = s.response_ms(req.work)
        heapq.heappush(in_flight, (req.arrival_ms + latency, req.id, s))
        records.append(Record(req.id, req.arrival_ms, s.id, latency, True))
        last_done = max(last_done, req.arrival_ms + latency)
    while in_flight:
        lb.release(heapq.heappop(in_flight)[2])
    start = scenario.requests[0].arrival_ms if scenario.requests else 0.0
    return RunResult(algorithm.name, records, servers, max(last_done - start, 0.0),
                     checker.log, list(scenario.faults))


@dataclass
class Failover:
    kill_ms: float
    revive_ms: float  # inf if never revived
    detect_ms: float  # when the health check marked it down (inf if never)
    recover_ms: float  # when the health check put it back (inf if never)
    before: int  # requests it served before it died
    refused: int  # sent to it after it died but before the checker noticed
    while_down: int  # sent to it while marked down: should always be 0
    after: int  # requests it served after being put back
    ok_while_down: float  # success rate of ALL traffic while it was marked down


def failover(result, server_id):
    """Where one killed server's traffic went. Raises ValueError if the scenario never killed it."""
    mine = [f for f in result.faults if f.server_id == server_id]
    kill = min(f.at_ms for f in mine if not f.alive)
    revive = min((f.at_ms for f in mine if f.alive and f.at_ms > kill), default=math.inf)
    detect = next((t for t, i, up in result.health_log if i == server_id and not up), math.inf)
    recover = next((t for t, i, up in result.health_log if i == server_id and up and t > detect), math.inf)
    down = [r for r in result.records if detect <= r.arrival_ms < recover]
    on_it = [r for r in result.records if r.server_id == server_id]
    return Failover(
        kill, revive, detect, recover,
        before=sum(r.ok and r.arrival_ms < kill for r in on_it),
        refused=sum(r.error == "refused" for r in on_it),
        while_down=sum(detect <= r.arrival_ms < recover for r in on_it),
        after=sum(r.ok and r.arrival_ms >= recover for r in on_it),
        ok_while_down=sum(r.ok for r in down) / len(down) if down else 1.0)
