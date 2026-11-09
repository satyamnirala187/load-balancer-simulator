"""Simulated backend servers. Nothing here touches a network."""
from dataclasses import dataclass

OVERLOAD = 3  # a server rejects new requests once it holds weight * OVERLOAD connections


@dataclass
class Server:
    id: str
    weight: int  # relative capacity: connections it serves comfortably
    base_ms: float  # response time when idle
    connections: int = 0  # in-flight requests; only Balancer.acquire/release may change it
    healthy: bool = True  # False = down
    slowdown: float = 1.0  # > 1 simulates a degraded server

    @property
    def max_connections(self):
        return self.weight * OVERLOAD

    def response_ms(self, work=1.0):
        """Simulated latency; grows linearly with current load, so overloading a small server hurts."""
        return self.base_ms * self.slowdown * work * (1 + self.connections / self.weight)


# RailDhaara's fake fleet: (id, weight, idle response ms). Bigger boxes are faster.
FLEET = [("app-1", 8, 40), ("app-2", 6, 45), ("app-3", 5, 50), ("app-4", 4, 60), ("app-5", 3, 60)]


def make_servers(slow=None):
    """Fresh servers (every run starts from zero connections). slow: {server id: slowdown factor}."""
    slow = slow or {}
    return [Server(i, w, ms, slowdown=slow.get(i, 1.0)) for i, w, ms in FLEET]
