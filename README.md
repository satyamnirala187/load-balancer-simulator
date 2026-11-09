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
python3 -m lbsim --pattern spike       # normal | spike | slow_server | burst | all
python3 -m lbsim --pattern all --seed 7 --duration 30 --rate 150
python3 -m lbsim --kill-server app-3 --at 10s --revive-at 15s     # failover + recovery demo
python3 -m lbsim --kill-server app-3 --at 10s --check-interval 0.1  # faster detection, fewer refused
python3 -m lbsim --kill-server app-3 --at 10s --check-interval 2 --passive-after 3   # mark down after 3 refusals
python3 -m lbsim.loadtest              # ~1k and ~10k requests x 4 patterns x 3 algorithms, plus a 5-seed stability table
python3 -m unittest                    # tests: all but the dashboard ones run anywhere (those are skipped without Streamlit)
.venv/bin/python -m unittest           # everything, including the dashboard tests (also works under pytest)
```

## Layout

| File | What |
|---|---|
| `lbsim/servers.py` | `Server` (id, weight, connections, response time, healthy/down) and the 5-server fleet |
| `lbsim/algorithms.py` | `MinHeap` (own indexed binary heap) + Round Robin, Least Connections, Weighted Least Connections behind `acquire()` / `release()` |
| `lbsim/traffic.py` | Request generator: `normal`, `spike` (x4 rate mid-run), `slow_server` (app-2 x5 slower), `burst` (sudden x10), plus `Fault` events (kill / revive a server) |
| `lbsim/health.py` | `HealthChecker`: periodic probes that mark servers down / up in the balancer, plus the optional passive check |
| `lbsim/simulator.py` | `Simulation`: steppable virtual-clock engine (`simulate()` runs it to the end), per-run metrics, `failover()` report |
| `lbsim/live.py` | `LiveRun`: drives all three algorithms in real time for the dashboard; live kill / revive |
| `lbsim/report.py` | Tables and per-second series shared by the CLI and the dashboard |
| `lbsim/loadtest.py` | Load runs at ~1k / ~10k requests across every pattern and algorithm, with a multi-seed stability table |
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
  change them only through `acquire` / `release`. `tests/test_concurrent_run.py` proves it under load: 16 threads,
  a prober, a chaos thread killing and reviving servers, 12,000+ requests per run, every algorithm, with and without
  the passive check. An audit hook inside the lock checks that every pick was the exact minimum among healthy servers
  and never a marked-down one, that a pick is always counted before the next pick, that open connections never exceed
  the worker count, and that afterwards every connection is released, every heap key equals the real load, and every
  health change was logged exactly once. Removing the lock, splitting pick from count, or removing the checker's
  lock each make it fail.
- **Time.** Discrete-event simulation on a virtual clock, not real sleeping: the same seed always gives the
  same table, and a 20-second run takes milliseconds (120 load-test simulations, up to 19k requests each, take 2 s).
  Concurrency is modelled as overlapping requests in virtual time; real threads are covered by the tests above.
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
- **Passive check (optional, `--passive-after N`, default off).** A refused request is a free health signal: after N
  refusals in a row from one server, mark it down at once instead of waiting for the probe. Only *refused* (a dead
  server) counts, never *overloaded*, so a busy-but-alive server can never be marked down by it (a test proves it),
  and bringing a server back is still the probe's job. It is off by default so every number in this README stays
  reproducible; the blind window then becomes N refused requests whatever the probe interval (table below).
- **Recovery.** When a check sees the server alive again it is pushed back into the heap with its current load
  and receives traffic again.
- **Decision: requests already in flight on a dying server finish normally** (they are not failed or retried).
  Why: real load balancers do this when they mark a server down (stop new traffic, drain accepted
  connections), and RailDhaara's requests are bookings and payments, which are not idempotent, so cutting them off and
  auto-retrying risks a double booking. Cost: a "kill" here means *the server stops accepting new requests*, not a power
  cut that drops accepted ones.
- **Known weaknesses the simulator shows**: (1) Least Connections and Weighted Least Connections see a dead server
  as idle (0 connections), so during the blind window they send it *more* traffic than Round Robin does; the passive
  check fixes this, but is opt-in. (2) When a server is lost, the survivors may simply not have the capacity, and
  Round Robin also hands them equal shares regardless of size (see the capacity result below).

## Measured results

All numbers are from the final code, base rate 100 req/s, seed 42, reproducible with the commands shown.

### Load runs: `python3 -m lbsim.loadtest`

About 1,000 and 10,000 requests per run (each scenario is sized from the pattern's average rate, so `requests` is the
real count). `burst` is a sudden x10 surge for the middle tenth of the run.

```
Pattern      Size    Algorithm               requests  req/s  avg ms  max ms  failed  failed %
----------------------------------------------------------------------------------------------
normal       1,000   Round Robin                  951   94.3    77.9   225.7       0      0.0%
normal       1,000   Least Connections            951   94.7    64.4   155.2       0      0.0%
normal       1,000   Weighted Least Conn.         951   94.7    62.7   149.5       0      0.0%
normal       10,000  Round Robin               10,001   99.9    79.3   266.8       0      0.0%
normal       10,000  Least Connections         10,001  100.0    64.6   200.3       0      0.0%
normal       10,000  Weighted Least Conn.      10,001  100.0    63.1   151.5       0      0.0%
spike        1,000   Round Robin                  949  137.3   110.0   353.7      89      9.4%
spike        1,000   Least Connections            949  139.6    94.9   359.1      76      8.0%
spike        1,000   Weighted Least Conn.         949  151.4   109.0   354.1       2      0.2%
spike        10,000  Round Robin               10,004  142.8   112.0   359.8    1076     10.8%
spike        10,000  Least Connections         10,004  145.9    97.2   358.3     880      8.8%
spike        10,000  Weighted Least Conn.      10,004  157.5   115.1   359.6     155      1.5%
slow_server  1,000   Round Robin                  951   87.5   205.6  1303.9       4      0.4%
slow_server  1,000   Least Connections            951   94.8    88.5   523.1       0      0.0%
slow_server  1,000   Weighted Least Conn.         951   93.8    86.9   504.7       0      0.0%
slow_server  10,000  Round Robin               10,001   97.7   221.3  1349.0     130      1.3%
slow_server  10,000  Least Connections         10,001   99.8    89.1   555.2       0      0.0%
slow_server  10,000  Weighted Least Conn.      10,001   99.7    87.4   561.0       0      0.0%
burst        1,000   Round Robin                  950  128.7   111.5   354.0     260     27.4%
burst        1,000   Least Connections            950  121.2    86.9   359.9     305     32.1%
burst        1,000   Weighted Least Conn.         950  130.9   104.3   357.2     253     26.6%
burst        10,000  Round Robin                9,999  130.0   112.6   359.0    3144     31.4%
burst        10,000  Least Connections          9,999  123.4    86.1   358.4    3498     35.0%
burst        10,000  Weighted Least Conn.       9,999  130.6   102.8   359.4    3119     31.2%
```

Stability across 5 seeds (the second table `loadtest` prints): at 10,000 requests req/s moves by about 1% and average
latency by about 1.5% for every algorithm on `normal` and `slow_server`; at 1,000 requests the spread is about 5%
because the sample is small. Same seed always gives identical numbers.

How to read it: `normal` and `slow_server` are easy for the fleet, and Round Robin is the only algorithm that suffers
from the slow server (1.3% failed, 221 ms average against 87-89). `spike` separates the algorithms most: Weighted Least
Connections fails 1.5%, Least Connections 8.8%, Round Robin 10.8%, because they differ in how well they fill small
servers. `burst` is x10 base = 1,000 req/s against a fleet that can sustain about 410 req/s, and 53% of all requests
arrive inside the burst, so about 31% failing is the floor for *any* balancer; Round Robin and Weighted Least
Connections sit on it (31.4%, 31.2%) and Least Connections is worse (35.0%).

### Losing the biggest server mid-spike

`python3 -m lbsim --pattern spike --kill-server app-1 --at 8s --revive-at 12s` (spike = 400 req/s from 8 s to 12 s):

| success while marked down | Round Robin | Least Connections | Weighted Least Conn. |
|---|---|---|---|
| active probe only (default) | 65.6% | 61.0% | 68.6% |
| `--passive-after 3` | 66.9% | 62.5% | 68.9% |

Routed to the dead server after detection: 0 in every case. **The survivors simply lack the capacity.** With this
latency model a server rejects once it holds 3x its weight in connections, which puts its sustainable rate at
0.75 x weight / idle-time: about 412 req/s for the full fleet and 262 req/s without app-1 (150 of the 412). The spike
offers 400 req/s, so no balancer can serve more than about 262 / 400 = 66% of it. Control experiment (app-1 dead from
the first millisecond, 1 ms health checks, so there is no failover transient at all), success at steady offered load:

| offered req/s | 150 | 200 | 250 | 300 | 350 | 400 | 450 |
|---|---|---|---|---|---|---|---|
| 4 survivors, Weighted LC | 100 | 100 | 97.2 | 85.8 | 74.5 | 65.0 | 58.3 |
| 4 survivors, Round Robin | 97.8 | 91.7 | 83.9 | 76.8 | 70.5 | 63.0 | 57.0 |
| 4 survivors, Least Connections | 100 | 99.3 | 88.6 | 76.7 | 65.8 | 58.0 | 52.0 |
| all 5 servers, Weighted LC | 100 | 100 | 100 | 100 | 100 | 97.0 | 89.6 |

The best balancer (Weighted Least Connections) starts failing between 200 and 250 req/s, close to the 262 req/s
estimate; the other two start failing earlier. At a steady 400 req/s Weighted Least Connections (65.0%) sits on the ~66%
ceiling, Round Robin (63.0%) is 2-3 points under it and Least Connections (58.0%) 7-8 under, because they do not fill
the small servers well. The steady result is within 4 points of the failover run, and detecting the kill in 1 ms
instead of 0.5 s moves the failover numbers by under 2 points: the loss is capacity, not failover. (The 262 req/s figure
is a mean-field estimate, good to a few points.)

### The blind window (refused requests), normal load, app-3 killed at 10 s

`python3 -m lbsim --kill-server app-3 --at 10s --revive-at 15s --check-interval X [--passive-after 3]`

| check interval | active probe only: RR / LC / WLC | with `--passive-after 3`: RR / LC / WLC |
|---|---|---|
| 2 s | 43 / 147 / 147 | 3 / 3 / 3 |
| 0.5 s | 9 / 28 / 28 | 3 / 3 / 3 |
| 0.1 s | 1 / 3 / 3 | 1 / 3 / 3 |

Round Robin gets 1 at 0.1 s with the passive check because the probe won that race.

### Dashboard: light theme and phone width

Checked in Chrome in light and dark theme, and at 390 CSS px (a real window cannot go that narrow, so the page was
loaded in a 390 px iframe, which gives it a genuine 390 px viewport). Found and fixed: a pale-blue line that vanished on
white (explicit colours now), line-chart legends clipped at 390 px (one entry per row), and no hint that the controls
are inside the collapsed sidebar on a phone (a hint now shows on screens up to 640 px). Left as they are, by design:
the wide tables scroll sideways inside their own frame, and the status numbers and server cards stack vertically, so
the page is long. Not tested on a physical phone, Safari or Firefox.
