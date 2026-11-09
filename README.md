# Load Balancer Simulator

Algorithms course project #27 — Cloud Server Load Balancer (Greedy + Heap).
A **simulator**: fake servers and synthetic traffic for a fictional Indian Railways-style
booking site, *RailDhaara*, under a Tatkal-style rush. No real servers, network or IRCTC data.
Python 3 standard library only.

## Dashboard (Streamlit)

One-time setup, from this folder (the simulator itself needs no installs; only the dashboard does):

```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Run it:

```
.venv/bin/streamlit run dashboard.py
```

It opens http://localhost:8501. Press **Start**, then **Kill** a server mid-run and watch its traffic move to the others;
**Revive** brings it back. Tested with Streamlit 1.67 on Python 3.14.

| Control | What it does |
|---|---|
| Pattern | Normal load / Sudden spike (Tatkal rush) / One slow server |
| Algorithm (live view) | Which algorithm the **Live view** shows. All three always run, on the same traffic |
| Speed | 1x-8x simulated seconds per real second |
| Run settings | Seed, duration, base rate. Changing anything starts a fresh run |
| Start / Pause / Reset | Run control |
| Server + Kill / Revive | Stop or restart a server while the run is live. The same event hits all three algorithms |

**Live view** (one algorithm): per-server status and counts, bars for requests handled in the last 5 s and open connections
right now, average latency and throughput per second, and an event log (killed, marked down, revived, back in rotation).
**Compare all 3**: three side-by-side per-server load panels, the same comparison / load / failover tables the CLI prints,
latency and throughput overlaid for all three algorithms, and the CLI command that reproduces the run.
The status row's "Sent to a marked-down server" must always read 0.

**Same numbers as the CLI.** The dashboard and the CLI share one engine (`lbsim.simulator.Simulation`) and one table
builder (`lbsim.report`). Compare view prints the exact CLI command for the run, including the moment you pressed Kill:

```
python3 -m lbsim --pattern normal --seed 42 --duration 20 --rate 100 --kill-server app-3 --at 8.5178...s
```

Once a run has finished, that command prints the same tables. A test checks this.

**Real-time driver.** `lbsim.live.LiveRun` advances the simulated clock by the real time elapsed times the speed, each
time the page refreshes (every 0.5 s). There is no timer thread: nothing to lock, nothing left running when Streamlit
reruns the script, and a fake clock makes it testable. The catch is that a run only advances while the page is open.
Kill and Revive tick the clock first, so they land at the exact simulated moment you pressed them.

## Run

```
python3 -m lbsim                       # normal load, all 3 algorithms side by side
python3 -m lbsim --pattern spike       # normal | spike | slow_server | all
python3 -m lbsim --pattern all --seed 7 --duration 30 --rate 150
python3 -m lbsim --kill-server app-3 --at 10s --revive-at 15s     # failover + recovery demo
python3 -m lbsim --kill-server app-3 --at 10s --check-interval 0.1  # faster detection, fewer refused
python3 -m unittest                    # tests: 31 run anywhere; the 7 dashboard tests are skipped without Streamlit
.venv/bin/python -m unittest           # all 38, including the dashboard tests (also works under pytest)
```

## Layout

| File | What |
|---|---|
| `lbsim/servers.py` | `Server` (id, weight, connections, response time, healthy/down) and the 5-server fleet |
| `lbsim/algorithms.py` | `MinHeap` (own indexed binary heap) + Round Robin, Least Connections, Weighted Least Connections behind `acquire()` / `release()` |
| `lbsim/traffic.py` | Request generator: `normal`, `spike` (x4 rate mid-run), `slow_server` (app-2 x5 slower), plus `Fault` events (kill / revive a server) |
| `lbsim/health.py` | `HealthChecker`: periodic probes that mark servers down / up in the balancer |
| `lbsim/simulator.py` | `Simulation`: steppable virtual-clock engine (`simulate()` runs it to the end), per-run metrics, `failover()` report |
| `lbsim/live.py` | `LiveRun`: drives all three algorithms in real time for the dashboard; live kill / revive |
| `lbsim/report.py` | Tables and per-second series shared by the CLI and the dashboard |
| `lbsim/__main__.py` | The comparison CLI |
| `dashboard.py` | The Streamlit dashboard (the only file that needs Streamlit) |
| `requirements.txt` | Pinned Streamlit, for the dashboard only |

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
