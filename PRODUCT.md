# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **Primary: classmates watching a classroom demo.** They sit in their seats and watch a projector while the two authors drive the dashboard from a laptop. They never touch it. Most have no background in load balancing.
- **Also in the room: the professor**, who grades the algorithms project and may ask how a number was produced.
- **Operators: the two authors** (Satyam Nirala and Raghav Sihag), who click through a timed, scripted demo (`docs/DEMO_SCRIPT.md`) while talking.

## Product Purpose

A Streamlit dashboard (`dashboard.py`) for a college algorithms project: a load balancer simulator that sends the same synthetic traffic through three algorithms (Round Robin, Least Connections on a min-heap, Weighted Least Connections) and shows what each one does under a fictional Tatkal booking rush, including a server dying mid-rush.

Success: a classmate with no background can tell from the screen alone, without the presenters explaining it, which algorithm coped best and why.

## Positioning

All three algorithms get exactly the same traffic and the same failures at the same instant, and every figure on the page is one the command line prints for the same run. It is a fair, reproducible comparison, not an illustration.

## Operating Context

- Shown on a classroom projector from the presenters' laptop, read from across a room.
- Driven live against a 12-minute script with three beats: a normal morning, the Tatkal rush, a server killed mid-rush.
- The presenters talk over a 20-second simulated run, pause it, kill and revive a server, then switch to the comparison view.
- A fallback exists if the dashboard fails: saved CLI output in `docs/fallback/` and screenshots in `docs/screenshots/`.

## Capabilities and Constraints

- Live view of one algorithm (per-server state, load, open connections, latency, throughput) and a comparison view of all three.
- Start / Pause / Reset, speed control, kill and revive a chosen server during a run.
- Three story-beat buttons that set up each part of the demo; a one-sentence verdict on a finished run; plain-language helper text.
- **Fixed: Streamlit and Altair only.** No new dependencies and no move off Streamlit.
- **Fixed: numbers match the CLI.** The dashboard never shows a figure the command line would not print for the same run. The simulator (`lbsim/`) is not changed by design work.
- Terminology in use: "marked down" (the load balancer's belief) versus "dead" (the truth); "beat" for a step of the demo story.
- Not a binding constraint: support for both colour themes and a 390 px phone width. The authors did not list it as fixed; the audience sees one projected screen.

## Brand Commitments

- The scenario name **RailDhaara** and the fictional Tatkal-rush story stay.
- The disclaimer stays visible: simulated servers and traffic only, no real IRCTC data.
- The project itself is titled "Load Balancer Simulator"; RailDhaara is only the demo scenario.

## Evidence on Hand

- Measured results in `lbsim/facts.py`, `docs/bench_results.json` and the tables in `README.md` and `REPORT.md`.
- A test suite (82 tests) that checks the dashboard's tables against the CLI.
- No user research, testimonials or usage data exist; none should be invented.

## Product Principles

1. **The screen must explain itself.** If a newcomer needs the presenter to decode a chart, the screen has failed.
2. **Same traffic, same failures, same instant.** Nothing in the interface may make one algorithm look better than the comparison shows.
3. **Honest about limits.** Ties are called ties, estimates are called estimates, and simulated things are called simulated.
4. **Built for the back row.** What matters must be readable from a seat, on a projector.
5. **The demo must not stall.** Every step of the script is one obvious click.
