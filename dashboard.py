"""RailDhaara load balancer dashboard (simulated servers and traffic only).

    .venv/bin/streamlit run dashboard.py

The page drives lbsim.live.LiveRun; every table comes from lbsim.report, the same code the CLI prints with.
"""
import altair as alt
import pandas as pd
import streamlit as st

from lbsim.algorithms import ALGORITHMS
from lbsim.live import LiveRun
from lbsim.report import (cli_command, comparison_table, failover_table, failover_title, load_table,
                          recent_load, timeseries)
from lbsim.servers import FLEET
from lbsim.simulator import routed_while_marked_down
from lbsim.traffic import make_scenario

PATTERNS = {"normal": "Normal load", "spike": "Sudden spike (Tatkal rush)", "slow_server": "One slow server",
            "burst": "Sudden 10x burst"}
VIEWS = ["Live view", "Compare all 3"]
REFRESH_S = 0.5
# line colours picked to keep >= 3:1 contrast on both the light and the dark theme
SERIES_COLOR = {"Round Robin": "#d97706", "Least Connections": "#4c78a8", "Weighted Least Conn.": "#2f9e44",
                "served": "#4c78a8", "failed": "#e45756", "avg latency (ms)": "#4c78a8"}
STATE_COLOR = {"up": "#4c78a8", "dead, not detected": "#f58518", "marked down": "#e45756", "alive, not back yet": "#b79a20"}
STATE_LABEL = {"up": "🟢 up", "dead, not detected": "🟠 dead, not detected yet",
               "marked down": "🔴 marked down", "alive, not back yet": "🟡 alive, not back yet"}

st.set_page_config(page_title="RailDhaara Load Balancer Simulator", page_icon="🚆", layout="wide")


def server_state(s):
    """alive = the truth; healthy = what the load balancer believes (it lags by up to one health check)."""
    if s.alive:
        return "up" if s.healthy else "alive, not back yet"
    return "dead, not detected" if s.healthy else "marked down"


def states_of(sim):
    return {s.id: server_state(s) for s in sim.servers}


def bars(values, states, y_title, ymax=None):
    df = pd.DataFrame({"server": list(values), "count": list(values.values()), "state": [states[k] for k in values]})
    y = alt.Y("count:Q", title=y_title, scale=alt.Scale(domain=[0, max(ymax or 0, max(values.values()), 1)]))
    color = alt.Color("state:N", title=None, scale=alt.Scale(domain=list(STATE_COLOR), range=list(STATE_COLOR.values())),
                      legend=alt.Legend(orient="bottom", columns=2))
    chart = alt.Chart(df).mark_bar().encode(x=alt.X("server:N", sort=None, title=None, axis=alt.Axis(labelAngle=0)),
                                            y=y, color=color, tooltip=["server", "count", "state"])
    st.altair_chart(chart.properties(height=240), width="stretch")


def lines(columns, t, y_title):
    # Altair, not st.line_chart: the native chart makes Vega log an "Infinite extent" warning on every live refresh
    df = pd.DataFrame(columns, index=pd.Index(t, name="second")).astype(float)
    df = df.reset_index().melt("second", var_name="series", value_name="value")
    chart = alt.Chart(df).mark_line().encode(
        x=alt.X("second:Q", title="simulated seconds"), y=alt.Y("value:Q", title=y_title, scale=alt.Scale(zero=True)),
        color=alt.Color("series:N", title=None, legend=alt.Legend(orient="bottom", columns=1),
                        scale=alt.Scale(domain=list(columns), range=[SERIES_COLOR[c] for c in columns])),
        tooltip=["second", "series", "value"])
    st.altair_chart(chart.properties(height=240), width="stretch")


def show_table(table):
    headers, rows = table
    st.dataframe(pd.DataFrame(rows, columns=headers), hide_index=True, width="stretch")


def status(run, results):
    dur = run.scenario.duration_ms
    state = "Finished" if run.finished else "Running" if run.running else "Paused" if run.started else "Ready"
    c = st.columns(4)
    c[0].metric("Run", state)
    c[1].metric("Simulated time", f"{min(run.now_ms, dur) / 1000:.1f} s / {dur / 1000:g} s")
    c[2].metric("Requests so far", results[0].total)
    c[3].metric("Sent to a marked-down server", sum(routed_while_marked_down(r) for r in results),
                help="Requests routed to a server while the health checker had it marked down. Always 0 for all three algorithms.")
    st.progress(1.0 if run.finished else min(run.now_ms / dur, 1.0))


def events(sim, now_ms):
    ev = [(f.at_ms, f"{f.server_id} {'revived' if f.alive else 'killed'} by you") for f in sim.faults if f.at_ms <= now_ms]
    ev += [(t, f"{sid} {'back in rotation' if up else 'marked down'} by the health check") for t, sid, up in sim.checker.log]
    if ev:
        st.markdown("**Events**\n" + "\n".join(f"- {t / 1000:.2f} s: {text}" for t, text in sorted(ev)[-8:]))


def live_view(run, results, r):
    sim = run.sims[r.algorithm]
    states, load = states_of(sim), r.load
    for col, s in zip(st.columns(len(sim.servers)), sim.servers):
        col.markdown(f"**{s.id}** · weight {s.weight}  \n{STATE_LABEL[states[s.id]]}")
        col.caption(f"{s.connections} open · {load[s.id]} handled")
    left, right = st.columns(2)
    with left:
        st.markdown(f"**Handled in the last 5 s** · {r.algorithm}")
        bars(recent_load(r.records, list(load), run.now_ms), states, "requests")
    with right:
        st.markdown("**Open connections right now**")
        bars({s.id: s.connections for s in sim.servers}, states, "connections")
    ts = timeseries(r.records, upto_ms=run.now_ms)
    if not ts["t"]:
        st.info("Press **Start** in the sidebar. Then try **Kill** on a server and watch its bar drain to zero.")
        return
    left, right = st.columns(2)
    with left:
        st.markdown("**Average latency per second**")
        lines({"avg latency (ms)": ts["avg_ms"]}, ts["t"], "ms")
    with right:
        st.markdown("**Throughput per second**")
        lines({"served": ts["ok"], "failed": ts["failed"]}, ts["t"], "requests/s")
    events(sim, run.now_ms)


def compare_view(run, results):
    st.markdown("**Same traffic through all three algorithms: requests handled per server so far**")
    ymax = max(max(r.load.values()) for r in results)
    for col, r in zip(st.columns(3), results):
        with col:
            st.markdown(f"#### {r.algorithm}")
            st.caption(f"{r.requests_per_sec:.1f} req/s · avg {r.avg_latency_ms:.1f} ms · {r.failed} failed")
            bars(r.load, states_of(run.sims[r.algorithm]), "requests", ymax)
    show_table(comparison_table(results))
    show_table(load_table(results))
    for sid in sorted({f.server_id for f in results[0].faults if not f.alive}):
        st.caption(failover_title(results[0], sid, run.interval_ms, never="never" if run.finished else "(not yet)"))
        show_table(failover_table(results, sid))
    ts = {r.algorithm: timeseries(r.records, upto_ms=run.now_ms) for r in results}
    t = ts[results[0].algorithm]["t"]
    if t:
        left, right = st.columns(2)
        with left:
            st.markdown("**Average latency per second**")
            lines({n: x["avg_ms"] for n, x in ts.items()}, t, "ms")
        with right:
            st.markdown("**Throughput per second** (lines overlap when nothing fails)")
            lines({n: x["ok"] for n, x in ts.items()}, t, "requests/s")
    cmd = cli_command(*st.session_state.cfg, results[0].faults)
    st.caption("The same run from the command line (numbers are identical once the run has finished):"
               if cmd else "This sequence of kills needs more than one CLI command, so there is no single CLI equivalent.")
    if cmd:
        st.code(cmd, language="bash")


def panel(run, view, algo, polling):
    run.tick()
    if polling and not run.running:
        st.rerun()  # the run just ended: redraw once more, this time without polling
    results = run.results()
    status(run, results)
    if view == VIEWS[0]:
        live_view(run, results, results[[r.algorithm for r in results].index(algo)])
    else:
        compare_view(run, results)


def new_run(cfg, speed):
    return LiveRun(make_scenario(*cfg), speed=speed)


with st.sidebar:
    st.header("Traffic")
    pattern = st.selectbox("Pattern", list(PATTERNS), format_func=PATTERNS.get)
    algo = st.selectbox("Algorithm (live view)", [a.name for a in ALGORITHMS])
    speed = st.select_slider("Speed", [1, 2, 4, 8], value=2, format_func=lambda x: f"{x}x")
    with st.expander("Run settings"):
        seed = st.number_input("Seed", value=42, step=1)
        duration = st.number_input("Duration (s)", min_value=5, max_value=60, value=20, step=1)
        rate = st.number_input("Base rate (requests/s)", min_value=10, max_value=300, value=100, step=10)

cfg = (pattern, int(seed), int(duration), int(rate))
if st.session_state.get("cfg") != cfg or "run" not in st.session_state:
    st.session_state.cfg, st.session_state.run = cfg, new_run(cfg, speed)
run = st.session_state.run
run.speed = speed

with st.sidebar:
    st.header("Run")
    a, b = st.columns(2)
    if a.button("Pause" if run.running else "Start", key="start", type="primary", disabled=run.finished, width="stretch"):
        if run.running:  # a plain if/else: Streamlit would print a bare `a() if c else b()` expression
            run.pause()
        else:
            run.start()
    if b.button("Reset", key="reset", width="stretch"):
        st.session_state.run = run = new_run(cfg, speed)
    st.header("Failure injection")
    target = st.selectbox("Server", [f[0] for f in FLEET])
    live = run.started and not run.finished
    a, b = st.columns(2)
    if a.button("Kill", key="kill", disabled=not live, width="stretch"):
        st.toast(f"{target} killed at {run.now_ms / 1000:.1f} s" if run.kill(target) else f"{target} is already down")
    if b.button("Revive", key="revive", disabled=not live, width="stretch"):
        st.toast(f"{target} revived at {run.now_ms / 1000:.1f} s" if run.revive(target) else f"{target} is already up")
    st.caption("Kill: the server stops accepting new requests. The load balancer only notices at its next health "
               "check (every 0.5 s), and requests already in flight on it finish.")

st.title("RailDhaara load balancer simulator")
st.caption("A fictional Indian Railways-style booking site under a Tatkal-style rush. Simulated servers and traffic only.")
# On a phone the sidebar starts collapsed and the controls live in it, so say so (hidden on wider screens)
st.markdown("<style>.mobile-hint{display:none}@media (max-width:640px){.mobile-hint{display:block;padding:.5rem .75rem;"
            "border-radius:.5rem;background:rgba(128,128,128,.15);font-size:.9rem}}</style>"
            "<div class='mobile-hint'>Controls (Start, Kill, Revive) are in the sidebar: tap <b>&raquo;</b> at the top left.</div>",
            unsafe_allow_html=True)
view = st.radio("View", VIEWS, horizontal=True, label_visibility="collapsed")
st.fragment(panel, run_every=REFRESH_S if run.running else None)(run, view, algo, run.running)
