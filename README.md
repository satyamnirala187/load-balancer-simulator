# Load Balancer Simulator

Algorithms course project #27 — Cloud Server Load Balancer (Greedy + Heap).
A **simulator**: fake servers and synthetic traffic for a fictional Indian Railways-style
booking site, *RailDhaara*, under a Tatkal-style rush. No real servers, network or IRCTC data.
Python 3 standard library only.

## Run

```
python3 -m lbsim                       # normal load, all 3 algorithms side by side
python3 -m lbsim --pattern spike       # normal | spike | slow_server | all
python3 -m lbsim --pattern all --seed 7 --duration 30 --rate 150
python3 -m unittest                    # tests (also runs under pytest if you have it)
```

## Layout

| File | What |
|---|---|
| `lbsim/servers.py` | `Server` (id, weight, connections, response time, healthy/down) and the 5-server fleet |
| `lbsim/algorithms.py` | `MinHeap` (own indexed binary heap) + Round Robin, Least Connections, Weighted Least Connections behind `acquire()` / `release()` |
| `lbsim/traffic.py` | Request generator: `normal`, `spike` (x4 rate mid-run), `slow_server` (app-2 x5 slower) |
| `lbsim/simulator.py` | Virtual-clock simulation + per-run metrics |
| `lbsim/__main__.py` | The comparison CLI |

## How it works

- **Heap.** Healthy servers sit in a min-heap keyed by load (`connections` or `connections / weight`).
  Pick = read the root, count the connection, re-sift: **O(log n)**. A request finishing = decrease that
  server's key and sift up: **O(log n)** (the heap keeps an id → index map, so it can find any server in O(1)).
  A server going down is removed from the heap, and pushed back when it returns, both O(log n).
- **Thread safety.** `acquire()` picks and increments under a single lock, so concurrent requests cannot
  choose the same "least loaded" server from the same stale count. Connection counts belong to the balancer:
  change them only through `acquire` / `release`.
- **Time.** Discrete-event simulation on a virtual clock, not real sleeping: the same seed always gives the
  same table, and a 20-second run takes milliseconds. Concurrency is modelled as overlapping requests in virtual time;
  the threaded behaviour of the balancer itself is covered by the tests.
- **Latency model.** `base_ms x slowdown x request_work x (1 + connections / weight)`, fixed when the server
  accepts the request. A server already holding `weight x 3` connections rejects the request (a failure).
  If every server is down, the request fails.
- **Metrics.** `req/s` = successful requests / (first arrival → last completion). Latencies are over successful
  requests only. Load per server = successful requests handled. When nothing fails, req/s is just the offered
  rate, so it only separates algorithms once some requests fail.

Not built yet (by design): the dashboard.
