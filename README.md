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
python3 -m lbsim --kill-server app-3 --at 10s --revive-at 15s     # failover + recovery demo
python3 -m lbsim --kill-server app-3 --at 10s --check-interval 0.1  # faster detection, fewer refused
python3 -m unittest                    # tests (also runs under pytest if you have it)
```

## Layout

| File | What |
|---|---|
| `lbsim/servers.py` | `Server` (id, weight, connections, response time, healthy/down) and the 5-server fleet |
| `lbsim/algorithms.py` | `MinHeap` (own indexed binary heap) + Round Robin, Least Connections, Weighted Least Connections behind `acquire()` / `release()` |
| `lbsim/traffic.py` | Request generator: `normal`, `spike` (x4 rate mid-run), `slow_server` (app-2 x5 slower), plus `Fault` events (kill / revive a server) |
| `lbsim/health.py` | `HealthChecker`: periodic probes that mark servers down / up in the balancer |
| `lbsim/simulator.py` | Virtual-clock simulation, per-run metrics, `failover()` report |
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

## Failover and recovery

- **Two states per server.** `alive` is the truth (what a fault changes); `healthy` is what the balancer believes.
  Only the `HealthChecker` moves `healthy` toward `alive`, once per `--check-interval` (default 0.5 s), through
  `Balancer.set_healthy`, which removes the server from the heap or pushes it back: O(log n) each way.
- **Blind window.** From the moment a server dies until the next check, the balancer still sends it traffic and
  those requests are *refused* (failed, not retried). Detection delay is always in (0, interval], so a shorter
  interval means fewer refused requests. After detection, **no request is routed to the dead server**.
- **Recovery.** When a check sees the server alive again it is pushed back into the heap with its current load
  and receives traffic again.
- **Decision: requests already in flight on a dying server finish normally** (they are not failed or retried).
  Why: real load balancers do this when they mark a server down (stop new traffic, drain accepted
  connections), and RailDhaara's requests are bookings and payments, which are not idempotent, so cutting them off and
  auto-retrying risks a double booking. Cost: a "kill" here means *the server stops accepting new requests*, not a power
  cut that drops accepted ones.
- **Known weaknesses the simulator shows** (not fixed): (1) Least Connections and Weighted Least Connections see a
  dead server as idle (0 connections), so during the blind window they send it *more* traffic than Round Robin does;
  (2) when a server is lost, Round Robin hands the survivors equal shares regardless of capacity, so small servers
  can overload. A passive check (mark down after N consecutive refusals) would shrink (1).

Not built yet (by design): the dashboard.
