"""Periodic health checks.

The checker is the only thing that tells the balancer a server is down or back. It probes the
server's real state (`alive`) and, when that differs from the balancer's view (`healthy`), calls
Balancer.set_healthy, which removes the server from the heap or pushes it back: O(log n) each.
Between a server dying and the next check, the balancer still believes it is healthy.
"""

DEFAULT_INTERVAL_MS = 500


class HealthChecker:
    def __init__(self, balancer, interval_ms=DEFAULT_INTERVAL_MS):
        if interval_ms <= 0:
            raise ValueError("interval_ms must be positive")
        self.balancer = balancer
        self.interval_ms = interval_ms
        self.log = []  # (time_ms, server_id, healthy) for every change the checker made

    def check(self, now_ms):
        """One round of probes. The caller decides when it runs (the simulator's virtual clock ticks it
        every interval_ms). shortcut: no timer thread; wrap check() in one if you need real time."""
        for s in self.balancer.servers:
            if s.alive != s.healthy:
                self.balancer.set_healthy(s, s.alive)
                self.log.append((now_ms, s.id, s.alive))
