# Viva answers

Short answers to say out loud, with the numbers behind them. Every figure is from `python3 -m lbsim.facts`. If you are pushed, the **If they push** line is the next layer.
Be plain about what is estimated and what is invented; the project's strength is that it says so.

## 1. "Is this what IRCTC actually runs?"

**No, and we do not know what IRCTC runs.** RailDhaara is a fictional site. The Tatkal rush is the scenario that inspired the shape of the traffic: everyone arrives at the opening time.
What is real is the algorithms. Round robin, least connections and weighted least connections are standard options in load balancers such as NGINX and HAProxy.
Our contribution is the comparison and the failover behaviour, not a claim about IRCTC's system.

**If they push:** we used no IRCTC data, logs or architecture. Anything we said about their real infrastructure would be a guess.

## 2. "Where did the traffic numbers come from?"

**We generated them.** Arrivals are a Poisson process with a base of 100 requests a second. The rush multiplies the rate by 4 for the middle fifth of the run, the burst by 10 for the middle tenth.
Each request has a random work factor between 0.5 and 1.5. The servers are invented too: five servers with weights 8, 6, 5, 4 and 3, idle response times of 40 to 60 ms, and a latency that grows with load.
We chose the numbers so that a normal morning is comfortable and the rush gets close to the fleet's capacity, about 412 req/s (an estimate), and we fixed them before looking at any results.

So the absolute numbers mean nothing for a real site. What the simulation can show is how the algorithms compare when they see exactly the same traffic.

**If they push:** would the ranking change with a different fleet? Possibly. We did not test other fleets; it is in our limits.

## 3. "Why a heap?"

**Least Connections needs the least loaded server on every request.** Scanning every server is O(n) per request. A min-heap keeps the least loaded one at the root: a pick is O(log n), and so is updating a server's load when a request finishes,
because we keep a position map from each server to its place in the heap. Marking a server down or back up is O(log n) too.

**Be honest about our size.** With 5 servers a plain scan is faster (0.50 µs against 0.74 per operation). They cross at about 15 to 20 servers, and at 50,000 servers the heap is 310 times faster
(Python, one machine). So the heap is the right structure as the fleet grows, and it is what the course asks for, but our five-server fleet does not need it.

**If they push:** why not Python's `heapq`? It cannot change the key of an arbitrary item, and we need exactly that when a request finishes on any server. So we wrote an indexed heap.

## 4. "Why does Weighted Least Connections win?"

**It equalises load relative to capacity.** Least Connections equalises the number of open connections, so a weight-3 server and a weight-8 server hold the same number. The small one is then about 2.7 times as loaded relative to its size,
and it saturates first. Weighted Least Connections picks the lowest connections divided by weight, so every server fills up at the same rate. In the rush (10,000 requests) it failed 1.5% of requests,
Least Connections 8.8%, Round Robin 10.8%.

**But it does not win everywhere, and we say so.** On a normal morning nothing fails for any of them. With one slow server, Least Connections and Weighted Least Connections tie (0 failures each).
In the blind window they tie (147 refused each). In a burst beyond capacity about 31% failing is the floor, and Weighted and Round Robin sit on it. And under the rush its average latency is higher: 115.1 ms against 97.2 ms for Least Connections.
Part of that is the 817 extra requests it serves, but even on the 9,032 requests both served it is slower (109.7 against 96.8 ms), because it runs the big servers hotter.

**If they push:** it relies on the weights being right. They are given and fixed in our model; we did not test a wrong weight.

## 5. "Why does Least Connections lose most in the blind window?"

**First, a correction: it ties with Weighted Least Connections.** At a 2 s health-check interval, after killing one server: Least Connections 147 refused requests, Weighted Least Connections 147, Round Robin 43.
So the two least-connections variants lose about 3.4 times as much as Round Robin.

**Why:** a dead server refuses instantly, so it never holds any connections. To a balancer that picks the lowest connection count, a dead server therefore looks like the least loaded server, and it keeps choosing it.
Round Robin does not look at load, so the dead server only gets its fair share, one request in five.

**The fix:** mark the server down as soon as it refuses a few requests in a row, instead of waiting for the next health check. With that passive check (3 refusals) the loss is at most 3 requests whatever the interval.
We left it off by default so every earlier number stays reproducible.

**If they push:** could the passive check wrongly mark a healthy server down? In our model no, because only a dead server refuses; an overloaded server rejects differently and never counts. In a real system that distinction is blurrier, which is a limit.

## 6. "Why does killing the biggest server still fail a third of the requests?"

**Because the survivors do not have the capacity, and no balancer can fix that.** The rush offers 400 requests a second. The whole fleet can sustain about 412. App-1 is 150 of that, which leaves about 262 for the four survivors.
That 262 is an estimate from our latency model, not a measurement. So no algorithm can serve more than about 66% of the rush, and the measured success while app-1 was down was 65.6% / 61.0% / 68.6% (Round Robin / Least Connections / Weighted).

**How we checked it is capacity and not failover:** we removed failover altogether (app-1 dead from the first millisecond, checks every millisecond) and offered a steady 400 requests a second. The four survivors served 63.0 / 58.0 / 65.0%,
within a few points of the failover run. Failover itself worked: nothing was routed to the dead server.

**If they push:** what would fix it? More capacity, shedding or queueing load, or autoscaling. A load balancer can only spread what the servers can hold.

## A few more that may come up

**What happens to requests already running on the server that dies?** They finish. Real load balancers typically stop sending new traffic and let accepted connections drain, and bookings are not safe to replay: cutting them off and retrying risks a double booking.
The cost is that our "kill" means the server stops accepting new requests, not a power cut.

**Is it really thread-safe? How do you know?** The pick and the connection count happen under one lock. A test runs 16 threads plus a health prober plus a thread that kills and revives servers, at least 12,000 requests per run, and audits every pick inside the lock.
Removing the lock, splitting the pick from the count, or removing the health checker's lock each make it fail. It does not prove a real deployment is safe; it proves the balancer's counts stay exact under that load.

**Why a simulation and not real servers?** The same seed gives the same table, all three algorithms see exactly the same traffic, and a 20-second run takes milliseconds. The cost is that we have no real network, scheduler or garbage-collection effects.

**What did you not do?** Retry refused requests (safe, but it would hide the blind window we wanted to measure), test other fleets or wrong weights, use real traffic, and check the dashboard on a phone, Safari or Firefox.
