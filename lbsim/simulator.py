"""Discrete-event simulation on a virtual clock (ms): no sleeping, no threads, fully reproducible.

A request holds a connection from its arrival until arrival + latency. Latency is fixed when the
server accepts it, from the load at that moment. A server already at max_connections rejects the
request (failure); if every server is down there is nobody to send it to (failure).
"""
import heapq
from dataclasses import dataclass

from .servers import make_servers


@dataclass
class Record:
    request_id: int
    server_id: str  # server that took (or rejected) the request; None if every server was down
    latency_ms: float  # None for failed requests
    ok: bool


@dataclass
class RunResult:
    algorithm: str
    records: list
    servers: list  # final server state (ids and weights, for reporting)
    duration_ms: float  # first arrival -> last completion

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


def simulate(algorithm, scenario):
    servers = make_servers(scenario.slow)
    lb = algorithm(servers)
    in_flight = []  # heap of (finish_ms, request_id, server)
    records = []
    last_done = 0.0
    for req in scenario.requests:
        while in_flight and in_flight[0][0] <= req.arrival_ms:
            lb.release(heapq.heappop(in_flight)[2])
        s = lb.acquire()
        if s is None:
            records.append(Record(req.id, None, None, False))
        elif s.connections > s.max_connections:
            lb.release(s)
            records.append(Record(req.id, s.id, None, False))
        else:
            latency = s.response_ms(req.work)
            heapq.heappush(in_flight, (req.arrival_ms + latency, req.id, s))
            records.append(Record(req.id, s.id, latency, True))
            last_done = max(last_done, req.arrival_ms + latency)
    while in_flight:
        lb.release(heapq.heappop(in_flight)[2])
    start = scenario.requests[0].arrival_ms if scenario.requests else 0.0
    return RunResult(algorithm.name, records, servers, max(last_done - start, 0.0))
