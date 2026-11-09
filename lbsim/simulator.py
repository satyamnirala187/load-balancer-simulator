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

Simulation is steppable (advance(t) any number of times, inject() faults while it runs), so the
dashboard can drive it live. simulate() is just "advance to the end"; both give identical records.
"""
import heapq
import math
from dataclasses import dataclass

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
    faults: list  # every Fault scheduled or injected

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


class Simulation:
    """One algorithm on one scenario. Event order at equal times: health check, fault, completion, arrival."""

    def __init__(self, algorithm, scenario, check_interval_ms=DEFAULT_INTERVAL_MS, passive_after=0):
        self.algorithm = algorithm
        self.requests = scenario.requests
        self.servers = make_servers(scenario.slow)
        self.by_id = {s.id: s for s in self.servers}
        self.lb = algorithm(self.servers)
        self.checker = HealthChecker(self.lb, check_interval_ms, passive_after)
        self.interval = check_interval_ms
        self.faults = list(scenario.faults)  # everything ever scheduled, kept for failover()
        self._pending = [(f.at_ms, i, f) for i, f in enumerate(self.faults)]  # heap: (time, seq, Fault)
        heapq.heapify(self._pending)
        self._seq = len(self._pending)
        self._tick = 1  # next health check is at _tick * interval
        self._next_req = 0
        self._in_flight = []  # heap of (finish_ms, request_id, server)
        self.records = []
        self.now = 0.0  # everything at or before this time has been processed
        self._last_done = 0.0

    def inject(self, fault):
        """Schedule a fault now or later (e.g. a dashboard button press). Not in the past."""
        if fault.at_ms < self.now:
            raise ValueError("cannot inject a fault in the past")
        self.faults.append(fault)
        heapq.heappush(self._pending, (fault.at_ms, self._seq, fault))
        self._seq += 1

    @property
    def finished(self):
        return self._next_event() is None

    def advance(self, to_ms):
        """Process every event up to and including virtual time to_ms (math.inf = run to the end)."""
        while (e := self._next_event()) is not None and e[0] <= to_ms:
            self.now = e[0]
            e[2]()
        if to_ms != math.inf:
            self.now = max(self.now, to_ms)

    def result(self):
        """Snapshot so far; after the last event it is the final result."""
        start = self.requests[0].arrival_ms if self.requests else 0.0
        return RunResult(self.algorithm.name, list(self.records), self.servers,
                         max(self._last_done - start, 0.0), list(self.checker.log), list(self.faults))

    def _next_event(self):
        """(time, priority, handler) of the earliest pending event, or None when nothing is left."""
        c = []
        # health checks only run while traffic is still arriving
        if self.requests and self._tick * self.interval <= self.requests[-1].arrival_ms:
            c.append((self._tick * self.interval, 0, self._health_check))
        if self._pending:
            c.append((self._pending[0][0], 1, self._fault))
        if self._in_flight:
            c.append((self._in_flight[0][0], 2, self._finish))
        if self._next_req < len(self.requests):
            c.append((self.requests[self._next_req].arrival_ms, 3, self._arrive))
        return min(c, key=lambda e: e[:2], default=None)

    def _health_check(self):
        self.checker.check(self._tick * self.interval)
        self._tick += 1

    def _fault(self):
        f = heapq.heappop(self._pending)[2]
        self.by_id[f.server_id].alive = f.alive

    def _finish(self):
        self.lb.release(heapq.heappop(self._in_flight)[2])

    def _arrive(self):
        req = self.requests[self._next_req]
        self._next_req += 1
        s = self.lb.acquire()
        why = ("no healthy server" if s is None else "refused" if not s.alive
               else "overloaded" if s.connections > s.max_connections else None)
        if why:
            if s:
                self.lb.release(s)
            self.records.append(Record(req.id, req.arrival_ms, s and s.id, None, False, why))
            if why == "refused":  # a passive mark takes effect just after this request, which was already routed
                self.checker.note_refused(s, math.nextafter(req.arrival_ms, math.inf))
            return
        self.checker.note_ok(s)
        latency = s.response_ms(req.work)
        heapq.heappush(self._in_flight, (req.arrival_ms + latency, req.id, s))
        self.records.append(Record(req.id, req.arrival_ms, s.id, latency, True))
        self._last_done = max(self._last_done, req.arrival_ms + latency)


def simulate(algorithm, scenario, check_interval_ms=DEFAULT_INTERVAL_MS, passive_after=0):
    sim = Simulation(algorithm, scenario, check_interval_ms, passive_after)
    sim.advance(math.inf)
    return sim.result()


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
    ok_while_down: float  # success rate of ALL traffic while it was marked down; None if there was none


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
        ok_while_down=sum(r.ok for r in down) / len(down) if down else None)


def routed_while_marked_down(result):
    """Requests sent to a server during any period the health checker had it marked down. Must be 0."""
    spans, down_since = [], {}
    for t, sid, up in result.health_log:
        if not up:
            down_since[sid] = t
        elif sid in down_since:
            spans.append((sid, down_since.pop(sid), t))
    spans += [(sid, t, math.inf) for sid, t in down_since.items()]
    return sum(a <= r.arrival_ms < b for r in result.records for sid, a, b in spans if r.server_id == sid)
