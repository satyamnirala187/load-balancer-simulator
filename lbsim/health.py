"""Health checking: how the balancer learns a server is down or back.

Active: a probe every interval_ms looks at the server's real state (`alive`) and, when it differs from
the balancer's view (`healthy`), calls Balancer.set_healthy. That removes the server from the heap or
pushes it back: O(log n) each. Between a server dying and the next probe the balancer still believes it
is healthy, so requests sent to it are refused (the "blind window").

Passive (optional, passive_after=N): a refused request is a free health signal. After N refusals in a
row, with no success from that server in between, the server is marked down at once. Only "refused" (a
dead server) counts, never "overloaded", so a busy-but-alive server can never be marked down by it, and
coming back up still waits for the active probe. With it, the blind window is N refused requests
however long the probe interval is. Default 0 = off.

Locking: the checker's lock is taken first and then the balancer's (inside set_healthy); the balancer
never calls the checker, so they cannot deadlock. The lock also keeps a probe and a passive mark from both
logging the same change.
"""
import threading

DEFAULT_INTERVAL_MS = 500


class HealthChecker:
    def __init__(self, balancer, interval_ms=DEFAULT_INTERVAL_MS, passive_after=0):
        if interval_ms <= 0:
            raise ValueError("interval_ms must be positive")
        if passive_after < 0:
            raise ValueError("passive_after must be 0 (off) or a positive count")
        self.balancer = balancer
        self.interval_ms = interval_ms
        self.passive_after = passive_after
        self.log = []  # (time_ms, server_id, healthy) for every change the checker made
        self._refused = {}  # server id -> refusals in a row
        self._lock = threading.Lock()

    def check(self, now_ms):
        """One round of probes. The caller decides when it runs (the simulator's virtual clock ticks it
        every interval_ms). shortcut: no timer thread; wrap check() in one if you need real time."""
        with self._lock:
            for s in self.balancer.servers:
                if s.alive != s.healthy:
                    self.balancer.set_healthy(s, s.alive)
                    self.log.append((now_ms, s.id, s.alive))

    def note_refused(self, server, now_ms):
        """Passive check: a request sent to `server` was refused."""
        if not self.passive_after:
            return
        with self._lock:
            n = self._refused[server.id] = self._refused.get(server.id, 0) + 1
            if n >= self.passive_after and server.healthy:
                self._refused[server.id] = 0
                self.balancer.set_healthy(server, False)
                self.log.append((now_ms, server.id, False))

    def note_ok(self, server):
        """Passive check: `server` took a request, so its refusal streak is over."""
        if self.passive_after:
            with self._lock:
                self._refused.pop(server.id, None)
