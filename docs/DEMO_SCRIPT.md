# Demo script: 12 minutes, word for word

Run of show for the class demo: the Tatkal rush, a server killed live, then revived. The text says "we" so two people can split it however they like. **Spoken text is in quotation blocks.** Square brackets are things to do, not to say.
Numbers marked "about" are what you should see on screen; they move by a few points with the exact second you click. The page prints the command line that reproduces
whatever you actually ran, so you can always check a figure.

## Before you start (10 minutes ahead)

1. Terminal 1, in the project folder: `.venv/bin/streamlit run dashboard.py`. Open http://localhost:8501 in a desktop browser window at least 1280 px wide, zoom 100%. The sidebar must be open.
2. In the sidebar set **Speed to 1x** (click the slider thumb and press the Left arrow once, or drag it to the far left; the label above it should read 1x). Pattern: **Normal load**. Algorithm (live view): **Weighted Least Conn.**. Server: **app-3**. Leave Run settings alone (seed 42, 20 s, 100 req/s): the numbers below depend on them.
3. Press **Start** and let one run finish, then press **Reset**. This checks that everything works and warms the page.
4. Terminal 2, in the project folder, ready for the fallback (section "If something fails"). Open `docs/fallback/` in a text viewer too.
5. Slides open in presenter view.
6. Close other apps, turn off notifications, plug in the laptop. Have a timer visible.

## Timing

| Start | Segment | Length |
|---|---|---|
| 0:00 | Slides 1 to 6 (problem, algorithms, heap, failover) | 4:20 |
| 4:20 | Demo A: a normal morning | 1:10 |
| 5:30 | Demo B: the Tatkal rush | 1:30 |
| 7:00 | Demo C: kill a server live, pause, revive it | 2:00 |
| 9:00 | Demo D: wrap up | 0:20 |
| 9:20 | Slides 7 to 10 (results, limits, close) | 2:40 |

The spoken text is about 9 minutes at a steady pace; the rest is the simulation running, clicks, and breathing room. If you finish early, stop; do not add material.

## The talk

### 0:00  Slide 1: Load Balancer Simulator  (20 s)

> Good morning. We built a simulator for what happens to a booking site at ten o'clock, when the Tatkal window opens. The site is fictional, we call it RailDhaara, and there is no real traffic and no IRCTC data in it.

*41 words, about 16 s at a steady pace.*

### 0:20  Slide 2: 10 AM, everyone arrives at once  (45 s)

> On a normal morning our site gets about 100 requests a second. At ten o'clock that jumps to four times as much, and in a bad burst, ten times. Our five servers are not equal: their weights are 8, 6, 5, 4 and 3. Together they can sustain roughly 412 requests a second, and that is an estimate from our own model. So the rush does not break the fleet, but it gets close. And that is exactly where the choice of algorithm starts to matter.

*86 words, about 34 s at a steady pace.*

### 1:05  Slide 3: Three ways to pick a server  (40 s)

> Three ways to pick a server. Round Robin takes turns and ignores everything else. Least Connections sends each request to the server with the fewest open connections. Weighted Least Connections divides that count by the server's weight, so a big server is allowed to carry more. The last two are greedy: each request goes to the best server at that moment, with no look-ahead.

*64 words, about 26 s at a steady pace.*

### 1:45  Slide 4: One heap, O(log n) per request  (75 s)

> To find the least loaded server quickly we keep the servers in a min-heap, keyed by connections divided by weight. The root is always the least loaded one. A pick reads the root, counts the connection and sifts down: log n. When a request finishes we lower that server's key and sift up: log n. When a server dies we remove it, and when it comes back we push it: log n. A lock covers the pick and the count together, so two requests can never choose from the same stale number. One honest note, because we measured it. With five servers a plain scan is actually faster: 0.50 microseconds against 0.74. The two cross at around 15 to 20 servers, and at 50,000 servers the heap is 310 times faster. The heap is the right structure. Our fleet is just small.

*142 words, about 57 s at a steady pace.*

### 3:00  Slide 5: Failover, noticing is the hard part  (70 s)

> Failover. A server has two states: whether it is really alive, and whether the balancer believes it is healthy. A health check brings them into line, but in between there is a blind window. The balancer keeps sending requests to a dead server, and they are refused. On the chart, with a two-second check, Least Connections lost 147 requests and Round Robin 43. Least Connections loses more because a dead server holds zero connections, so it looks like the least loaded server. A passive check fixes that: three refusals in a row and the server is marked down at once. That cuts the loss to 3. Two decisions: requests already running on a dying server finish, because bookings are not safe to replay; and the passive check only counts refusals, never overload.

*132 words, about 53 s at a steady pace.*

### 4:10  Slide 6: Watch the failover live  (10 s)

> Now let's watch it. This is the dashboard, running the same engine as the command line.

*16 words, about 6 s at a steady pace.*

### 4:20  Demo A: a normal morning  (70 s)

**Switch to the browser.** Pattern is *Normal load*, speed 1x, algorithm *Weighted Least Conn.*

1. [Click **Start**.] The run lasts 20 seconds. Speak over it:

> This is a normal morning, about 100 requests a second. Each bar is a server, and the height is how many requests it handled in the last five seconds. The bars follow the weights: app-1 is the biggest server and takes the most. On the right are the open connections. Nothing is failing.

*53 words.*

2. [When it says Finished, click **Compare all 3**.]

> Same traffic through all three. No failures for any of them. The only difference is latency: about 78 milliseconds for Round Robin, 64 and 63 for the other two. Round Robin gives the small servers the same share as the big ones.

*42 words.*

**You should see:** 1,957 requests; failed 0 / 0 / 0; average latency 77.9 / 64.2 / 62.8 ms (Round Robin / Least Connections / Weighted).
**If the page misbehaves:** press F5 and press Start again, or use the fallback.

### 5:30  Demo B: the Tatkal rush  (90 s)

1. [Click **Reset**. In the sidebar choose Pattern: *Sudden spike (Tatkal rush)*. Changing the pattern starts a fresh run. Click **Start**.] Speak over the run, and watch *Simulated time*:

> Now ten o'clock. Watch the simulated time: the rush starts at 8 seconds and lasts 4. Requests per second go from 100 to 400. There it is: the bars jump, and the open connections climb on every server.

*38 words.*

2. [When it says Finished, click **Compare all 3**.]

> Same rush through all three. Round Robin failed 307 requests, Least Connections 224, Weighted Least Connections 17. Weighted Least Connections divides by weight, so every server fills up evenly and no small one overflows first. Over 10,000 requests the figures are 1.5% for Weighted, 8.8% for Least Connections and 10.8% for Round Robin.

*53 words.*

**You should see:** 3,131 requests; failed 307 / 224 / 17 (Round Robin / Least Connections / Weighted). This run is deterministic, so these numbers are exact.

### 7:00  Demo C: kill a server live, pause, revive it  (120 s)

The run is only 20 seconds and the kill and revive are 5 seconds apart, so **use Pause** to talk on a frozen screen. The sequence is: Start, Kill at 9 s, Pause at 14.5 s, Revive, Start again.

1. [Click **Reset**. Pattern stays on *Sudden spike*. Check that *Server* says **app-3** and that the **Live view** is showing. Click **Start**.] Speak while the clock runs to 9 seconds:

> Same rush again. Watch the clock. At 9 seconds, in the middle of the rush, we kill app-3.

*18 words.*

2. [At about **9 seconds**, click **Kill**. A toast says when.] Speak:

> app-3 is dead. For a moment the balancer does not know. Then it notices, and app-3 goes red: marked down.

*20 words.*

3. [At about **14.5 seconds**, click **Pause**. The screen freezes with app-3 red, its bar at zero.] Speak:

> Look at the top right: sent to a marked-down server, zero. Nothing is routed to it. Its bar has drained to nothing, and the others have picked up its share.

*30 words.*

4. [Still paused, click **Revive**. app-3 turns yellow: alive, not back in rotation.] Speak, and click **Start** (the button now says Start) at "when we resume":

> Now we bring it back. The balancer has not noticed yet: that is the yellow state, alive but not back in rotation. When we resume, the next health check sees it, and traffic returns.

*34 words.*

5. [Let it run to Finished (about 5 more seconds). Click **Compare all 3** and scroll to the failover table and the command-line box at the bottom.]

> Here is what it cost. While the balancer did not know, Round Robin lost about 43 requests, Least Connections about 179, Weighted Least Connections about 172. After that, zero were routed to the dead server. While it was down, Weighted Least Connections still succeeded on about 91% of requests, the others about 79%. And this command line reproduces exactly this run, down to the moment we clicked.

*67 words.*

**You should see (kill at 9 s, revive at 14.5 s; about):** failed 422 / 506 / 288; refused before the balancer noticed 43 / 179 / 172;
routed while marked down 0 / 0 / 0; success while marked down 78.6% / 78.7% / 90.9%. Clicking a second earlier or later moves these by up to about 5 points; the refused counts and the zeros hold.
**The orange state** (dead, not yet detected) lasts at most half a second, so you may only catch it for a refresh or two; the red and yellow states you can hold on the pause. Say "for a moment" and carry on.
**If you miss the window** (Kill after 12 s, or no Pause): it still works, you just lose the timing. Skip the pause, say "and now we kill a server", and read the table at the end.
**If you click Revive while it is running** it also works: the yellow state is just shorter.

### 9:00  Demo D: wrap up  (20 s)

> So failover works, nothing is routed to a dead server, and what it costs is the time it takes to notice. Back to the slides for the numbers.

*28 words.* [Switch back to the slides, slide 7.]

### 9:20  Slide 7: Near capacity, weighting wins  (45 s)

> Ten thousand requests per run. Each cell is the percentage that failed and the average latency of the ones served. On a normal morning nothing fails. In the spike, Weighted Least Connections fails 1.5%, Least Connections 8.8%, Round Robin 10.8%. In the burst nobody wins: it is more than twice what the fleet can sustain. And a cost: in the spike Weighted averages about 115 milliseconds against 97 for Least Connections, because it serves more of the load.

*78 words, about 31 s at a steady pace.*

### 10:05  Slide 8: The survivors run out of capacity  (50 s)

> We killed the biggest server, app-1, in the middle of the rush. Failover works: nothing was routed to it. But about a third of the requests still failed. The four survivors can sustain roughly 262 requests a second, an estimate from our model, and the rush offers 400. So no balancer can serve more than about 66 percent. As a check, we removed the failover entirely, app-1 dead from the start, and a steady 400 gave 63.0, 58.0 and 65.0 percent. It is capacity, not failover.

*86 words, about 34 s at a steady pace.*

### 10:55  Slide 9: What this does not show  (30 s)

> Before you ask. The traffic and the servers are invented, and there is no IRCTC data. Time is simulated, so no real network effects. A kill here means the server stops taking new requests, not a power cut. The 262 figure is an estimate. Small runs are noisy. And we checked the dashboard in one desktop browser, not on a phone.

*61 words, about 24 s at a steady pace.*

### 11:25  Slide 10: What to take away  (35 s)

> Three things to take away. Weigh the load by capacity: 1.5% failed against 8.8% and 10.8%. How fast you notice a failure matters as much as how you route: 147 requests lost in a two-second blind window, cut to 3 by a passive check. And no balancer fixes missing capacity. The code and the tests are on GitHub. We are happy to take questions.

*64 words, about 26 s at a steady pace.*

## If something fails

| What fails | What to do |
|---|---|
| The dashboard will not start | Say "the dashboard is not cooperating, so here is the same engine from the command line." Use Terminal 2 (below). Same numbers. |
| The page loads but a click does nothing | Press F5 (the run restarts). If it still misbehaves, switch to the command line. |
| The browser tab crashes mid-demo | Reopen http://localhost:8501. If the server died, restart it (about 3 seconds) or go to the command line. |
| You are running late | Cut Demo A's Compare view (go straight to B), then shorten slide 3 to one sentence. That saves about 1:15. |
| The projector or laptop dies | The deck is `slides/RailDhaara_LoadBalancer.pptx`; the screenshots are in `docs/screenshots/`; the tables are in `docs/fallback/`. |

**The command-line backup.** Each command prints a table with all three algorithms; the saved output is in `docs/fallback/` if even the terminal fails.

| Demo step | Command | Saved output |
|---|---|---|
| A: normal morning | `python3 -m lbsim` | `docs/fallback/1_normal_morning.txt` |
| B: the rush | `python3 -m lbsim --pattern spike` | `docs/fallback/2_tatkal_rush.txt` |
| C: kill and revive | `python3 -m lbsim --pattern spike --kill-server app-3 --at 9s --revive-at 14.5s` | `docs/fallback/3_kill_and_revive.txt` |
| Results slides | `python3 -m lbsim.loadtest --seeds 1` | `docs/fallback/4_load_table.txt` |

While showing the tables, say the same things as in the demo, reading the numbers off the table: the *failed* column for A and B, and the *Failover* table at the bottom of C
(*refused (undetected)*, *routed while marked down*, *success % while marked down*). The command-line run is exact, so unlike the live demo its numbers will not move.

## Numbers to have in your head

- Normal morning (1,957 requests): failed 0 / 0 / 0; average 77.9 / 64.2 / 62.8 ms.
- Rush (3,131 requests): failed 307 / 224 / 17.
- Rush, 10,000 requests: failed 10.8% / 8.8% / 1.5%.
- Blind window at 2 s: 43 / 147 / 147 refused; with the passive check 3 / 3 / 3.
- Fleet capacity about 412 req/s; without app-1 about 262 req/s (estimates); the rush offers 400.
- Heap against scan: 0.50 against 0.74 µs at 5 servers, 310x faster at 50,000.
