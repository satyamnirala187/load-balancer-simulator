"""Load-balancing algorithms behind one interface:

    server = balancer.acquire()   # None if every server is down
    ...serve the request...
    balancer.release(server)

acquire() picks AND counts the connection under one lock, so two concurrent requests
can never choose the same "least loaded" server from the same stale count.
"""
import threading


class MinHeap:
    """Binary min-heap of (key, id) with a position map, so any id's key can change in O(log n).

    push / update / remove: O(log n). peek: O(1). Entries compare as (key, id), so ties
    break by id and the pick is deterministic.
    """

    def __init__(self):
        self._a = []  # the heap array
        self._pos = {}  # id -> index in _a

    def __contains__(self, sid):
        return sid in self._pos

    def peek(self):
        return self._a[0] if self._a else None

    def push(self, sid, key):
        self._a.append((key, sid))
        self._pos[sid] = len(self._a) - 1
        self._up(len(self._a) - 1)

    def update(self, sid, key):
        i = self._pos[sid]
        old, self._a[i] = self._a[i], (key, sid)
        if self._a[i] < old:
            self._up(i)
        else:
            self._down(i)

    def remove(self, sid):
        i = self._pos.pop(sid)
        last = self._a.pop()
        if i < len(self._a):  # removed item was not the last slot: refill the hole
            self._a[i] = last
            self._pos[last[1]] = i
            self._up(i)
            self._down(i)

    def _swap(self, i, j):
        a = self._a
        a[i], a[j] = a[j], a[i]
        self._pos[a[i][1]] = i
        self._pos[a[j][1]] = j

    def _up(self, i):
        while i and self._a[i] < self._a[(i - 1) // 2]:
            self._swap(i, (i - 1) // 2)
            i = (i - 1) // 2

    def _down(self, i):
        n = len(self._a)
        while True:
            m = i
            for c in (2 * i + 1, 2 * i + 2):
                if c < n and self._a[c] < self._a[m]:
                    m = c
            if m == i:
                return
            self._swap(i, m)
            i = m


class Balancer:
    name = ""

    def __init__(self, servers):
        self.servers = list(servers)
        self._lock = threading.Lock()

    def acquire(self):
        with self._lock:
            s = self._pick()
            if s is not None:
                s.connections += 1
                self._changed(s)
            return s

    def release(self, s):
        with self._lock:
            if s.connections <= 0:
                raise ValueError(f"{s.id} has no open connections to release")
            s.connections -= 1
            self._changed(s)

    def set_healthy(self, s, healthy):
        with self._lock:
            s.healthy = healthy
            self._health_changed(s)

    def _pick(self):
        raise NotImplementedError

    def _changed(self, s):  # s.connections changed
        pass

    def _health_changed(self, s):
        pass


class RoundRobin(Balancer):
    """Cycle through servers in order, skipping down ones. Ignores load and weight."""

    name = "Round Robin"

    def __init__(self, servers):
        super().__init__(servers)
        self._next = 0

    def _pick(self):
        n = len(self.servers)
        for i in range(n):
            s = self.servers[(self._next + i) % n]
            if s.healthy:
                self._next = (self._next + i + 1) % n
                return s
        return None


class _HeapBalancer(Balancer):
    """Healthy servers live in a MinHeap keyed by score(); the root is always the pick."""

    def __init__(self, servers):
        super().__init__(servers)
        self._by_id = {s.id: s for s in self.servers}
        self._heap = MinHeap()
        for s in self.servers:
            if s.healthy:
                self._heap.push(s.id, self.score(s))

    def score(self, s):
        raise NotImplementedError

    def _pick(self):
        top = self._heap.peek()  # O(1); with the update in _changed, a whole pick is O(log n)
        return self._by_id[top[1]] if top else None

    def _changed(self, s):
        if s.id in self._heap:
            self._heap.update(s.id, self.score(s))  # O(log n): re-sift after +1 (acquire) or -1 (release)

    def _health_changed(self, s):
        if not s.healthy and s.id in self._heap:
            self._heap.remove(s.id)
        elif s.healthy and s.id not in self._heap:
            self._heap.push(s.id, self.score(s))


class LeastConnections(_HeapBalancer):
    """Fewest open connections wins. Ignores weight."""

    name = "Least Connections"

    def score(self, s):
        return s.connections


class WeightedLeastConnections(_HeapBalancer):
    """Lowest connections / weight wins, so bigger servers take proportionally more."""

    name = "Weighted Least Conn."

    def score(self, s):
        return s.connections / s.weight


ALGORITHMS = [RoundRobin, LeastConnections, WeightedLeastConnections]
