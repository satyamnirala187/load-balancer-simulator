# RailDhaara load-balancer simulator: report

Algorithms course, project 27 (Cloud Server Load Balancer, Greedy + Heap). Satyam Nirala and Raghav Sihag.
Code: https://github.com/satyamnirala187/load-balancer-simulator

## 1. Summary

We built a simulator of a fictional Indian Railways-style booking site, RailDhaara, under a Tatkal-style rush. It runs
three load-balancing algorithms on the same synthetic traffic: Round Robin, Least Connections and Weighted Least
Connections. The two least-connections variants keep the servers in a min-heap that we wrote, so choosing a server
and updating a load are both O(log n). On top of that there is health checking with failover and recovery, a
command-line comparison, a live Streamlit dashboard, and a test suite that includes a multi-threaded full-run test.

What the measurements say:

- Near capacity, weighting the load by server size matters. In the rush (a x4 spike, 10,000 requests) Weighted Least
  Connections failed 1.5% of requests, Least Connections 8.8% and Round
  Robin 10.8%. On a normal morning nothing failed for any of them.
- Noticing a failure is the expensive part of failover. With a 2 s health check, killing one server cost
  147 refused requests for Least Connections and Weighted Least Connections and 43 for Round Robin. A passive
  check (mark a server down after 3 refusals) cut all of them to 3.
- Killing the biggest server mid-rush still fails about a third of the requests that arrive while it is down, and the cause is capacity, not
  failover. The four survivors can sustain about 262 req/s (an estimate) and the rush offers 400.
- Weighted Least Connections is not better at everything. Under the rush its average latency is higher than Least
  Connections (115.1 ms against 97.2 ms): it serves more of the traffic and runs the large servers hotter.

Everything here is a simulation with invented servers and synthetic traffic. Section 7 lists what that does and does not
let us conclude.

## 2. What was built

| Part | File | What it does |
|---|---|---|
| Server model | `lbsim/servers.py` | id, weight, open connections, idle response time, `alive` (the truth) and `healthy` (what the balancer believes) |
| Algorithms | `lbsim/algorithms.py` | our `MinHeap`; Round Robin, Least Connections, Weighted Least Connections behind one `acquire()` / `release()` interface, thread-safe |
| Traffic | `lbsim/traffic.py` | Poisson arrivals in four patterns: normal, spike (x4), slow server, burst (x10); fault events |
| Health checks | `lbsim/health.py` | periodic probes plus an optional passive check |
| Engine | `lbsim/simulator.py` | steppable discrete-event simulation on a virtual clock |
| Live driver | `lbsim/live.py` | runs the engine at real-time speed for the dashboard, with live kill and revive |
| Reports | `lbsim/report.py`, `lbsim/loadtest.py`, `lbsim/facts.py` | tables shared by the CLI, dashboard and documents |
| Interfaces | `lbsim/__main__.py`, `dashboard.py` | the command line and the Streamlit dashboard |

**The model.** The fleet has five servers with weights 8, 6, 5, 4, 3 and idle response times of 40, 45, 50, 60, 60 ms. A server holding
c connections answers in `base x (1 + c / weight)` ms, and rejects new requests once it holds 3 x weight connections.
Each request also carries a random work factor between 0.5 and 1.5. These numbers are ours: they make a normal morning
comfortable and the rush approach the fleet's capacity. They were fixed before any results were looked at and not tuned
afterwards. A request fails if every server is marked down, if it is sent to a server that is really dead but not yet marked
down ("refused"), or if the server is at its connection limit ("overloaded").

## 3. Complexity analysis

Let n be the number of servers, R the number of requests, and m the number of requests in flight at one moment.

### 3.1 The heap

The least-loaded server is the root of a binary min-heap keyed by `(load score, server id)`, where the score is the
connection count (Least Connections) or connections divided by weight (Weighted). The heap keeps a position map from
server id to array index, which is what makes an arbitrary server's key changeable in logarithmic time.

| Operation | What happens | Cost |
|---|---|---|
| Pick | read the root, count the connection on it, sift it down | O(1) read + O(log n) |
| Request finishes | lower that server's key, sift it up | O(log n) |
| Server marked down | remove it from the heap | O(log n) |
| Server marked up | push it back | O(log n) |
| Find a server's position | position map | O(1) |
| Build | n pushes | O(n log n) |
| Space | one entry and one map slot per server | O(n) |

A pick and its connection count happen under one lock, so two concurrent requests cannot choose from the same stale count.
That makes the pick exact, not approximate: a randomised test compares every pick against a brute-force minimum, and a
multi-threaded test audits every pick inside the lock (section 5.5).

Round Robin is O(1) per pick while all servers are up. When servers are down it scans forward from its pointer, so the worst
case is O(n). A plain Least Connections without the heap scans every healthy server: O(n) per pick.

### 3.2 Cost of a request in the simulator

Each request is one arrival event and one completion event. The arrival does one `acquire` (O(log n)); the completion does one
`release` (O(log n)) and pops the in-flight heap (O(log m)). The next-event selection looks at four queues: O(1). With our fleet
m is at most 78, the sum of the connection limits. So the cost per request is O(log n + log m), and a run of R requests costs
O(R (log n + log m)), plus the health checks: one probe round every interval is O(n), so a run of D seconds with interval I costs O(n D / I).
Computing the metrics afterwards is O(R) per table.

### 3.3 What the measurements show

Timings are from `docs/bench.py`, one machine (macOS-27.2-arm64-arm-64bit-Mach-O, Python 3.14.3), best of three. Read the shape, not the microseconds.

**Heap against a linear scan.** One balancer operation (acquire or release) on a fleet of n servers with n connections open:

| servers | heap, µs per operation | linear scan, µs per operation | scan ÷ heap |
|---|---|---|---|
| 5 | 0.74 | 0.50 | 0.68 |
| 15 | 0.95 | 0.88 | 0.93 |
| 20 | 1.06 | 1.09 | 1.03 |
| 50 | 1.27 | 2.22 | 1.74 |
| 500 | 1.95 | 19.13 | 9.81 |
| 5,000 | 2.89 | 185.87 | 64.39 |
| 50,000 | 6.00 | 1862.53 | 310.22 |

- The heap's cost grows slowly: 0.74 µs at 5 servers to 6.00 µs at 50,000, an 8.1-fold increase for 10,000 times the servers. A logarithm grows 6.7-fold over that range, so the growth is of logarithmic order, nowhere near the 10,000-fold of a linear cost.
- The scan's cost grows in proportion to n: 0.50 µs to 1862.53 µs.
- **At our 5 servers the scan is faster** (0.50 against 0.74 µs): the heap's sifting and bookkeeping cost more than looking at five numbers.
  The two cross at roughly 15 to 20 servers (0.93 at 15, 1.03 at 20). Above that the heap wins, by 310x at 50,000.
  So the heap is the right structure for the problem, but this fleet is too small for it to matter. We say so rather than claim a speed-up we did not measure.

**Per request, end to end.** Wall time of a whole simulation divided by its request count, in µs per request:

| requests in the run | Round Robin | Least Connections | Weighted Least Conn. |
|---|---|---|---|
| 951 | 2.33 | 3.25 | 3.28 |
| 10,001 | 2.23 | 3.28 | 3.28 |
| 99,855 | 2.28 | 3.31 | 3.37 |

The cost per request does not grow with the length of the run: about 2.3 µs for Round Robin and 3.2 to 3.3 µs for the heap variants from 951 to 99,855 requests,
which is what O(R (log n + log m)) with small n and m predicts. The heap variants cost about one microsecond more per request than Round Robin.
The full load test (120 simulations of about 1,000 or 10,000 requests each) runs in about 2 seconds.

## 4. Design decisions

### 4.1 A virtual clock

The simulation advances a virtual clock from event to event instead of sleeping. A 20-second run takes milliseconds, the same
seed always gives the same table, and all three algorithms see exactly the same traffic, so differences between them are the
algorithms and not timing noise. The cost: no real network, scheduler or garbage-collection effects, and concurrency is modelled as
overlapping requests in virtual time. Real threads are tested separately on the balancer and on a full run (section 5.5), but the
comparison numbers come from the virtual clock. The dashboard drives the same engine at real-time speed, with no timer thread:
whatever shows the run calls `tick()`, which moves the clock by the real time elapsed. That avoids locks and leftover threads
when Streamlit reruns the script, and it makes the driver testable with a fake clock.

### 4.2 Drain, not retry

When a server dies, requests already in flight on it finish normally. Only new requests are re-routed. Load balancers
typically behave this way when they mark a server down (HAProxy's default, for example), and RailDhaara's requests are bookings and payments, which are not idempotent: cutting
them off and replaying them risks a double booking. The cost is that a "kill" here means the server stops accepting new requests. It
does not model a power cut that drops accepted ones. Requests sent to a dead server before the balancer notices are refused and not
retried; retrying them would be safe, since the server never processed them, but it would hide the cost of the blind window,
which is what we want to measure.

### 4.3 Probe and passive check

A server has two states: `alive` (the truth) and `healthy` (what the balancer believes). A probe every interval brings `healthy`
into line with `alive`. In between, the balancer is blind (section 5.3).

The passive check uses the refusals themselves as a signal: after 3 refused requests in a row from one server, mark it down at once.
We added it because it is small (about 15 lines) and safe in this model. Only a refusal, which only a dead server produces, counts; an
overload rejection never does, so an overloaded but alive server cannot be marked down by it (a test proves this with a burst that
causes thousands of overload rejections and marks nothing down). A success resets the count, and bringing a server back is still the probe's job.

It is **off by default** (`--passive-after 3` turns it on). That keeps every earlier number reproducible, and keeps the blind window
visible in the demo. Turning it on by default is a one-line change plus updating the tests that assume probe-only detection.
In a real system the distinction between "refused" and "overloaded" is blurrier than it is here, which is a limit of this comparison.

### 4.4 Why Weighted Least Connections wins, and where it does not

Least Connections equalises the number of open connections. A server of weight 3 and a server of weight 8 then hold the same
number, so the small one is about 2.7 times as loaded relative to its capacity. Response time is `base x (1 + c / weight)` and the limit is
3 x weight, so the small servers saturate first. Weighted Least Connections equalises connections divided by weight, so every server
has the same utilisation and they all approach their limits together. Round Robin ignores load entirely and hands each server the same
share, which overloads the small ones even sooner.

The evidence is the rush: 1.5% failed against 8.8% and 10.8% at 10,000 requests, and 2 failures against 76 and 89 at about 1,000.
Under steady load on the four survivors of a lost server, Weighted Least Connections reaches the capacity ceiling while the others fall short (section 5.4).

It does not win everywhere:

- **Light load.** On a normal morning nothing fails for any algorithm. The gap appears only when load approaches capacity.
- **A slow server.** Least Connections and Weighted Least Connections both adapt, because a slow server holds its connections longer and so looks busy: 0 failures for both
  (89.1 and 87.4 ms). Round Robin does not adapt (1.3% failed, 221.3 ms).
- **The blind window.** Weighted Least Connections and Least Connections tie (147 refused each at a 2 s interval), because both see a dead server as idle.
- **A burst beyond capacity.** About 31% failing is the floor for any balancer. Round Robin (31.4%) and Weighted Least Connections (31.2%) sit on it; Least Connections is worse (35.0%).
- **Latency under the rush.** Weighted Least Connections averages 115.1 ms against 97.2 ms for Least Connections. Part of that is that it serves 817 requests that Least Connections
  failed, and those average 174.6 ms. But even on the 9,032 requests both served, it is slower (109.7 against 96.8 ms): it runs the large servers hotter. It trades some latency for completing more requests.
- **It needs correct weights.** The weights are given and static here. We did not test what a wrong weight does.

## 5. Measured results

All numbers come from the final code with base rate 100 req/s and seed 42, and are reproduced by `python3 -m lbsim.facts`
(which `tests/test_docs.py` checks against this file).

### 5.1 Load runs

`python3 -m lbsim.loadtest`. About 1,000 and 10,000 requests per run (each scenario is sized from the pattern's average rate, so `requests`
is the real count). `burst` is a sudden x10 surge for the middle tenth of the run.

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

**Stability.** Across 5 seeds, the range (max minus min, relative to min) on `normal` and `slow_server` is at most 1.3% for req/s and 1.5% for
average latency at 10,000 requests, and 9.5% and 5.5% at 1,000 requests. The same seed always gives identical numbers.
The 10,000-request runs are the ones to quote; the 1,000-request runs are noisy.

### 5.2 Reading the load table

- `normal`: no failures for any algorithm; Round Robin is slowest (79.3 ms against 64.6 and 63.1).
- `spike`: the algorithms separate (1.5%, 8.8%, 10.8% failed).
- `slow_server`: only Round Robin suffers (1.3% failed, 221.3 ms average, 1349.0 ms maximum).
- `burst`: 1,000 req/s offered against a fleet that sustains about 412, with 53% of all requests arriving inside the burst, so about 31% failing is unavoidable.

### 5.3 The blind window

`python3 -m lbsim --kill-server app-3 --at 10s --revive-at 15s --check-interval X [--passive-after 3]`, normal load.
Refused requests, as Round Robin / Least Connections / Weighted Least Connections:

| check interval | probe only: RR / LC / WLC | with `--passive-after 3`: RR / LC / WLC |
|---|---|---|
| 2 s | 43 / 147 / 147 | 3 / 3 / 3 |
| 0.5 s | 9 / 28 / 28 | 3 / 3 / 3 |
| 0.1 s | 1 / 3 / 3 | 1 / 3 / 3 |

A dead server refuses instantly, so it never accumulates connections. Least Connections and Weighted Least Connections read that as "idle" and keep choosing it,
which is why, at a 2 s interval, they lose about 3.4 times as many requests as Round Robin, which only sends the dead server its fair share. The two tie.
With the passive check the window is 3 refused requests whatever the interval (Round Robin gets 1 at 0.1 s because the probe won that race).
Requests routed to a server while it was marked down: 0 in every run.

### 5.4 Losing the biggest server mid-rush

`python3 -m lbsim --pattern spike --kill-server app-1 --at 8s --revive-at 12s`. The rush runs from 8 s to 12 s at 400 req/s.

|  | Round Robin | Least Connections | Weighted Least Conn. |
|---|---|---|---|
| success while marked down, probe only | 65.6% | 61.0% | 68.6% |
| success while marked down, `--passive-after 3` | 66.9% | 62.5% | 68.9% |
| refused in the blind window, probe only | 34 | 174 | 174 |
| refused in the blind window, `--passive-after 3` | 3 | 3 | 3 |

Requests routed to the dead server after detection: 0 in every case.

**The survivors lack the capacity.** With our latency model a server holding c connections answers in `base x (1 + c / weight)` and rejects at
3 x weight, and by Little's law its sustainable rate is `3 / (3 + 1) x weight / base`. That is 150 req/s for app-1 and about 412 req/s for the whole fleet,
which leaves **about 262 req/s for the four survivors**. This is an **estimate** from our own model, good to a few points, not a measurement. The rush offers 400 req/s,
so no balancer can serve more than about 66% of it.

To check that the loss is capacity and not failover, we removed the failover transient altogether: app-1 dead from the first millisecond, health checks every 1 ms,
and steady offered load (success %, after the first 10 ms):

| steady offered req/s | 150 | 200 | 250 | 300 | 350 | 400 | 450 |
|---|---|---|---|---|---|---|---|
| 4 survivors, Round Robin | 97.8 | 91.7 | 83.9 | 76.8 | 70.5 | 63.0 | 57.0 |
| 4 survivors, Least Connections | 100.0 | 99.3 | 88.6 | 76.7 | 65.8 | 58.0 | 52.0 |
| 4 survivors, Weighted Least Conn. | 100.0 | 100.0 | 97.2 | 85.8 | 74.5 | 65.0 | 58.3 |
| all 5 servers, Round Robin | 99.9 | 97.4 | 92.9 | 88.4 | 83.9 | 79.2 | 75.3 |
| all 5 servers, Least Connections | 100.0 | 100.0 | 100.0 | 99.0 | 92.6 | 83.2 | 75.3 |
| all 5 servers, Weighted Least Conn. | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 97.0 | 89.6 |

- The best balancer (Weighted Least Connections) starts failing between 200 and 250 req/s on the four survivors, close to the 262 req/s estimate; the other two start failing earlier.
- At a steady 400 req/s Weighted Least Connections (65.0%) sits on the ~66% ceiling, Round Robin (63.0%) is 2 to 3 points under, and Least Connections (58.0%) is 7 to 8 under, because they do not fill the small servers well.
- The steady result is within 4 points of the failover run. Detecting the kill in 1 ms instead of 0.5 s (kill at 7.9 s) moves the failover figures by at most 1.8 points, so detection delay explains almost none of the loss. (`python3 -m lbsim.facts` prints both sets.)

So the verdict is capacity: after losing 150 of 412 req/s the fleet cannot carry a 400 req/s rush, whichever algorithm balances it. A load balancer can only spread what the servers can hold.

### 5.5 Thread safety under load

The original lock test hit the balancer alone. `tests/test_concurrent_run.py` runs the whole system with real threads: 16 workers pushing at least 12,000 requests per
run, a health-prober thread, and a chaos thread that kills and revives servers underneath them, for every algorithm, with and without the passive check.
An audit inside the balancer's lock checks that every pick is the true minimum among healthy servers and never a marked-down one, and that a pick is counted before the next pick happens.
Afterwards every connection must be released, every heap key must equal the server's real load, open connections must never have exceeded the worker count, and every health
change must have been logged exactly once. Removing the balancer's lock, splitting pick and count into separate lock holds, or removing the health checker's lock each makes the test fail.

### 5.6 Dashboard checks

The dashboard was driven in Brave, a Chromium browser, in light and dark themes and at 390 CSS px, through a 390 px iframe because a desktop window cannot be made that narrow.
It showed no browser console errors or warnings after the fixes. Three problems found that way were fixed: a pale line invisible on white, clipped chart legends at 390 px, and no hint
that the controls sit in a collapsed sidebar on a phone. Automated tests (Streamlit's AppTest) check that every control works and that the numbers shown equal the CLI's for the same run.

## 6. Reproducing

```
python3 -m lbsim --pattern spike --kill-server app-3 --at 9s --revive-at 14s    # one run, all three algorithms
python3 -m lbsim.loadtest                                                       # the load tables
python3 -m lbsim.facts                                                          # every table in this report
python3 docs/bench.py                                                           # heap vs scan timings (machine-specific)
.venv/bin/streamlit run dashboard.py                                            # the dashboard
python3 -m unittest                                                             # the tests (the dashboard ones need the venv)
```

## 7. Honest limits

- **Synthetic everything.** The arrivals are Poisson, the five servers and the latency formula are ours, and the rush and burst shapes are chosen. There is no real traffic and no IRCTC data, and we do not know what IRCTC runs.
  The parameters make a normal morning comfortable and the rush approach capacity; a different fleet would shift every number, and could change which algorithm looks best.
- **Simulated clock.** No real network, kernel queues, garbage collection or packet loss. Real threads are tested on the balancer, but nothing here is a network load test.
- **A kill is not a crash.** The killed server stops accepting new requests; requests already accepted finish. A server that drops accepted requests is not modelled, and neither are partial failures or flapping.
- **The 262 req/s figure is an estimate** from our latency model (section 5.4). The control experiment agrees with it to within a few points, which supports it but does not make it a measurement of anything real.
- **The passive check is flattered by the model.** Here a refusal always means a dead server. In a real system a refusal can also be a transient network fault.
- **Small samples.** 1,000-request runs vary by up to 9.5% in req/s between seeds. One fleet and one set of 5 seeds.
- **Benchmark timings are one machine and one Python build.** The shape (log against linear, flat per-request cost) is the result, not the microseconds.
- **Browser coverage.** Brave (Chromium 156) in light and dark, and a 390 px iframe. Not checked on a physical phone, Safari, Firefox or Google Chrome itself (same engine, not run).
- **The dashboard advances only while the page is open**, and its mid-run numbers are partial; they equal the CLI's once the run finishes.
- **Repeated kills.** If the same server is killed twice in one run, the failover table covers the first cycle; the "routed while marked down" total covers all of them.
