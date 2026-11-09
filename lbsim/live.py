"""Real-time driver for the dashboard.

One Simulation per algorithm, all on the SAME scenario, advanced together at `speed` x real time.

No threads: whoever is showing the run (the dashboard's refresh loop) calls tick(), which moves the
virtual clock forward by the real time elapsed since the last tick. So there are no locks to get
wrong, nothing to leak when Streamlit reruns the script, and a fake clock makes it testable. The run
only advances while something is polling it; that is the right behaviour for a demo.

kill() / revive() tick first, so a button press lands at the exact virtual instant it was pressed,
and the same Fault goes to every algorithm so the comparison stays fair. The balancers themselves are
thread-safe (see algorithms.py), so a threaded driver would work too.
"""
import time

from .algorithms import ALGORITHMS
from .health import DEFAULT_INTERVAL_MS
from .simulator import Simulation
from .traffic import Fault


class LiveRun:
    def __init__(self, scenario, algorithms=ALGORITHMS, check_interval_ms=DEFAULT_INTERVAL_MS,
                 speed=2.0, clock=time.monotonic):
        self.scenario = scenario
        self.interval_ms = check_interval_ms
        self.sims = {a.name: Simulation(a, scenario, check_interval_ms) for a in algorithms}
        self.speed = speed  # virtual seconds per real second; may be changed mid-run
        self.clock = clock
        self.now_ms = 0.0  # virtual time
        self.running = False
        self.started = False
        self._last = 0.0  # clock() at the previous tick

    @property
    def finished(self):
        return all(s.finished for s in self.sims.values())

    def results(self):
        """Current RunResult for each algorithm, in algorithm order. Final once finished."""
        return [s.result() for s in self.sims.values()]

    def start(self):
        if not self.finished:
            self.running = self.started = True
            self._last = self.clock()

    def pause(self):
        self.tick()
        self.running = False

    def tick(self):
        """Advance virtual time by the real time elapsed since the last tick (times speed)."""
        if not self.running:
            return
        now = self.clock()
        self.now_ms += (now - self._last) * 1000 * self.speed
        self._last = now
        for sim in self.sims.values():
            sim.advance(self.now_ms)
        if self.finished:
            self.running = False

    def kill(self, server_id):
        return self._set_alive(server_id, False)

    def revive(self, server_id):
        return self._set_alive(server_id, True)

    def _set_alive(self, server_id, alive):
        """True if applied. False (and nothing happens) before the run starts, after it ends,
        or if the server is already in that state. Unknown ids always raise KeyError."""
        self.tick()
        current = next(iter(self.sims.values())).by_id[server_id].alive
        if not self.started or self.finished or current == alive:
            return False
        for sim in self.sims.values():
            sim.inject(Fault(sim.now, server_id, alive))
            sim.advance(sim.now)  # applies it right away so the UI shows it
        return True
