"""Synthetic traffic for the fictional RailDhaara booking site. All times are in milliseconds."""
import random
from dataclasses import dataclass, field

PATTERNS = ("normal", "spike", "slow_server")
SPIKE_FACTOR = 4  # Tatkal rush: arrival rate x4 ...
SPIKE_WINDOW = (0.4, 0.6)  # ... during the middle fifth of the run
SLOW_SERVER = {"app-2": 5.0}  # slow_server pattern: app-2 answers 5x slower for the whole run


@dataclass(frozen=True)
class Request:
    id: int
    arrival_ms: float
    work: float  # relative cost of this request (1.0 = average)


@dataclass(frozen=True)
class Fault:
    at_ms: float
    server_id: str
    alive: bool  # False = the server dies at at_ms, True = it comes back


@dataclass
class Scenario:
    name: str
    requests: list
    slow: dict = field(default_factory=dict)  # server id -> slowdown factor
    faults: list = field(default_factory=list)  # Fault events, any order
    duration_ms: float = 0.0  # length of the run (the dashboard's progress bar)


def make_scenario(pattern, seed=42, duration_s=20, rate=100):
    """Poisson arrivals at `rate` req/s for `duration_s`. Same seed => same arrivals."""
    if pattern not in PATTERNS:
        raise ValueError(f"unknown pattern {pattern!r}; choose from {PATTERNS}")
    rng = random.Random(seed)
    end = duration_s * 1000
    segments = [(0, end, rate)]
    if pattern == "spike":
        a, b = (end * f for f in SPIKE_WINDOW)
        segments = [(0, a, rate), (a, b, rate * SPIKE_FACTOR), (b, end, rate)]
    arrivals = []
    for start, stop, r in segments:  # Poisson is memoryless, so restarting per segment is exact
        t = start
        while (t := t + rng.expovariate(r / 1000)) < stop:
            arrivals.append(t)
    requests = [Request(i, t, rng.uniform(0.5, 1.5)) for i, t in enumerate(arrivals)]
    return Scenario(pattern, requests, dict(SLOW_SERVER) if pattern == "slow_server" else {},
                    duration_ms=end)
