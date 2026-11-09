# Load Balancer Simulator

Algorithms course project 27: Cloud Server Load Balancer (Greedy + Heap).

A **simulator** of a fictional Indian Railways-style booking site, *RailDhaara*, under a Tatkal-style rush: fake servers and
synthetic traffic. No real servers, network or IRCTC data. It compares Round Robin, Least Connections and Weighted Least
Connections (the last two on a min-heap we wrote), with health checks, failover and recovery, a command-line comparison and a
live Streamlit dashboard. The simulator itself uses only the Python 3 standard library. Developed and tested on Python 3.14.

| Document | What it is |
|---|---|
| [REPORT.md](REPORT.md) | complexity analysis, design decisions, measured results, honest limits |
| [slides/RailDhaara_LoadBalancer.pptx](slides/RailDhaara_LoadBalancer.pptx) | the 10-slide deck |
| [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) | word-for-word 12-minute demo, with the fallback if the dashboard fails |
| [docs/VIVA.md](docs/VIVA.md) | answers to the likely viva questions |

## Quick start

The command line needs nothing installed:

```
python3 -m lbsim                                    # normal load: all 3 algorithms side by side
python3 -m lbsim --pattern spike                    # normal | spike | slow_server | burst | all
python3 -m lbsim --pattern spike --kill-server app-3 --at 9s --revive-at 14s    # failover and recovery
python3 -m lbsim.loadtest                           # ~1k and ~10k requests x 4 patterns x 3 algorithms
python3 -m unittest                                 # tests (the dashboard tests are skipped without Streamlit)
```

The dashboard needs a one-time setup (a virtual environment with Streamlit):

```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run dashboard.py                # opens http://localhost:8501
.venv/bin/python -m unittest                        # every test, including the dashboard's
```

| CLI flag | Meaning |
|---|---|
| `--pattern normal\|spike\|slow_server\|burst\|all` | traffic: normal load; x4 spike (the Tatkal rush); one slow server; sudden x10 burst |
| `--seed N`, `--duration S`, `--rate R` | traffic seed (default 42), length in seconds (20), base requests per second (100) |
| `--kill-server ID --at S [--revive-at S]` | stop a server mid-run (it stops accepting new requests) and optionally bring it back |
| `--check-interval S` | seconds between health checks (0.5) |
| `--passive-after N` | also mark a server down after N refused requests in a row (default 0 = off) |

Other tools: `python3 -m lbsim.facts` prints every table quoted in the documents; `python3 docs/bench.py` re-runs the heap benchmark;
`.venv/bin/pip install -r slides/requirements.txt && .venv/bin/python slides/build_deck.py` rebuilds the deck;
`.venv/bin/python docs/take_screenshots.py` retakes the dashboard screenshots (needs Chrome, Brave or Chromium).

## Dashboard

Press **Start**, then **Kill** a server mid-run and watch its traffic move to the others; **Revive** brings it back.
Tested with Streamlit 1.67.

| Control | What it does |
|---|---|
| Pattern | Normal load / Sudden spike (Tatkal rush) / One slow server / Sudden 10x burst |
| Algorithm (live view) | Which algorithm the **Live view** shows. All three always run, on the same traffic |
| Speed | 1x-8x simulated seconds per real second |
| Run settings | Seed, duration, base rate. Changing anything starts a fresh run |
| Start / Pause / Reset | Run control |
| Server + Kill / Revive | Stop or restart a server while the run is live. The same event hits all three algorithms |

**Live view** (one algorithm): per-server status and counts, requests handled in the last 5 s, open connections, average latency and
throughput per second, and an event log (killed, marked down, revived, back in rotation).
**Compare all 3**: three side-by-side per-server load panels, the same comparison / load / failover tables the CLI prints, latency and
throughput for all three, and the CLI command that reproduces the run. The status row's "Sent to a marked-down server" must always read 0.

**Same numbers as the CLI.** The dashboard and the CLI share one engine (`lbsim.simulator.Simulation`) and one table builder
(`lbsim.report`). The Compare view prints the exact CLI command for the run, including the moment you pressed Kill; once the run has
finished that command prints the same tables, and a test checks it.

**Real-time driver.** `lbsim.live.LiveRun` moves the simulated clock by the real time elapsed times the speed each time the page refreshes
(every 0.5 s). There is no timer thread, so nothing to lock and nothing left running when Streamlit reruns the script. A run only advances while
the page is open. Kill and Revive tick the clock first, so they land at the exact simulated moment you pressed them.

## Measured results

All numbers are from the final code, base rate 100 req/s, seed 42, and are printed by `python3 -m lbsim.facts`
(`tests/test_docs.py` fails if this file disagrees). The full discussion is in [REPORT.md](REPORT.md).

### Load runs: `python3 -m lbsim.loadtest`

About 1,000 and 10,000 requests per run (each scenario is sized from the pattern's average rate, so `requests` is the real count).
`burst` is a sudden x10 surge for the middle tenth of the run.

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

Across 5 seeds the range (max minus min, relative to min) on `normal` and `slow_server` is at most 1.3% for req/s and 1.5% for average latency
at 10,000 requests, and 9.5% and 5.5% at 1,000 requests, so quote the 10,000-request rows. The same seed always gives identical numbers.

How to read it: `normal` and `slow_server` are easy for the fleet, and only Round Robin suffers from the slow server (1.3% failed, 221.3 ms average
against 89.1 and 87.4). `spike` separates the algorithms most: Weighted Least Connections fails 1.5%, Least Connections 8.8%,
Round Robin 10.8%, because they differ in how well they fill the small servers. `burst` offers 1,000 req/s against a fleet that sustains about 412, and 53% of all requests
arrive inside the burst, so about 31% failing is the floor for any balancer: Round Robin (31.4%) and Weighted Least Connections (31.2%) sit on it, Least Connections is worse (35.0%).
Weighted Least Connections is not faster everywhere: in the spike its average latency is 115.1 ms against 97.2 ms for Least Connections, because it serves more of the load.

### The blind window: `python3 -m lbsim --kill-server app-3 --at 10s --revive-at 15s --check-interval X [--passive-after 3]`

Refused requests after killing a server, normal load, as Round Robin / Least Connections / Weighted Least Connections:

| check interval | probe only: RR / LC / WLC | with `--passive-after 3`: RR / LC / WLC |
|---|---|---|
| 2 s | 43 / 147 / 147 | 3 / 3 / 3 |
| 0.5 s | 9 / 28 / 28 | 3 / 3 / 3 |
| 0.1 s | 1 / 3 / 3 | 1 / 3 / 3 |

Until the next health check the balancer still sends traffic to the dead server. Least Connections and Weighted Least Connections see a dead server as idle (0 connections), so they send it more
than Round Robin does. The passive check marks a server down after 3 refusals in a row; only a dead server's refusals count, never overload. It is off by default so every number here stays reproducible.
Requests routed to a server while it was marked down: 0 in every run.

### Losing the biggest server mid-spike: `python3 -m lbsim --pattern spike --kill-server app-1 --at 8s --revive-at 12s`

|  | Round Robin | Least Connections | Weighted Least Conn. |
|---|---|---|---|
| success while marked down, probe only | 65.6% | 61.0% | 68.6% |
| success while marked down, `--passive-after 3` | 66.9% | 62.5% | 68.9% |
| refused in the blind window, probe only | 34 | 174 | 174 |
| refused in the blind window, `--passive-after 3` | 3 | 3 | 3 |

Routed to the dead server after detection: 0 in every case. **The survivors simply lack the capacity.** The estimated sustainable rate is about 412 req/s for the fleet and
**about 262 req/s without app-1** (an estimate from the latency model: a server rejects at 3 x weight connections, which puts its sustainable rate at 3/(3+1) x weight / idle time).
The spike offers 400 req/s, so no balancer can serve more than about 66% of it. With app-1 dead from the first millisecond, no failover transient at all, and a steady 400 req/s, the four survivors
serve 63.0 / 58.0 / 65.0%, in line with the failover run. The full sweep is in REPORT.md section 5.4.

### Heap against a linear scan: `python3 docs/bench.py`

At our 5 servers a plain scan is faster than the heap; they cross at roughly 15 to 20 servers; at 50,000 servers the heap is 310x faster. The per-request cost of a whole
simulation is flat as runs grow (REPORT.md section 3.3).

## Layout

| File | What |
|---|---|
| `lbsim/servers.py` | `Server` (id, weight, connections, response time, `alive` and `healthy`) and the 5-server fleet |
| `lbsim/algorithms.py` | `MinHeap` (own indexed binary heap) + Round Robin, Least Connections, Weighted Least Connections behind `acquire()` / `release()` |
| `lbsim/traffic.py` | Request generator: `normal`, `spike` (x4), `slow_server` (app-2 x5 slower), `burst` (x10), plus `Fault` events |
| `lbsim/health.py` | `HealthChecker`: periodic probes that mark servers down / up, plus the optional passive check |
| `lbsim/simulator.py` | `Simulation`: steppable virtual-clock engine (`simulate()` runs it to the end), per-run metrics, `failover()` report |
| `lbsim/live.py` | `LiveRun`: drives all three algorithms in real time for the dashboard; live kill / revive |
| `lbsim/report.py`, `lbsim/loadtest.py`, `lbsim/facts.py` | Tables shared by the CLI, the dashboard and the documents; the load runs; the headline numbers |
| `lbsim/__main__.py` | The comparison CLI |
| `dashboard.py`, `requirements.txt` | The Streamlit dashboard (the only part that needs Streamlit) |
| `tests/` | The test suite, including a multi-threaded full-run test and the dashboard tests |
| `slides/`, `docs/` | The deck and its builder; the demo script, viva sheet, benchmark, screenshots and CLI fallback outputs |

## How it works

- **Heap.** Healthy servers sit in a min-heap keyed by load (`connections` or `connections / weight`), with an id-to-index map. A pick (read the root, count the connection, re-sift) is **O(log n)**; a request finishing
  (lower that server's key, sift up) is **O(log n)**; a server going down or coming back is removed or pushed, both O(log n).
- **Thread safety.** `acquire()` picks and counts under a single lock, so concurrent requests cannot choose the same "least loaded" server from the same stale count. Connection counts belong to the balancer: change them only through
  `acquire` / `release`. `tests/test_concurrent_run.py` proves it under load with 16 threads, a prober and a chaos thread killing and reviving servers; an audit inside the lock checks every pick, and removing the lock, splitting
  pick from count, or removing the health checker's lock each make it fail.
- **Time.** Discrete-event simulation on a virtual clock, not real sleeping: the same seed always gives the same table, and the whole load test (120 simulations of about 1,000 or 10,000 requests) takes about 2 s.
- **Latency model.** `base_ms x slowdown x request_work x (1 + connections / weight)`, fixed when the server accepts the request. A server already holding 3 x weight connections rejects the request.
  A request also fails if every server is marked down, or if it is sent to a server that is dead but not yet marked down.
- **Failover.** A server has two states: `alive` (the truth) and `healthy` (what the balancer believes). A probe every `--check-interval` brings them into line. Requests already in flight on a dying server finish
  (bookings are not safe to retry); only new requests are re-routed.
- **Metrics.** `req/s` = successful requests / (first arrival to last completion). Latencies are over successful requests only. Load per server = successful requests handled.

## Limits

Synthetic traffic and invented servers; a simulated clock; a "kill" that stops new requests rather than crashing; capacity figures that are estimates from our latency model; small 1,000-request samples; the dashboard
checked in Brave (Chromium) in light and dark and at 390 px in an iframe, not on a phone, Safari or Firefox. [REPORT.md](REPORT.md) section 7 has the full list.
