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
from lbsim.traffic import Fault, make_scenario

PATTERNS = {"normal": "Normal load", "spike": "Sudden spike (Tatkal rush)", "slow_server": "One slow server",
            "burst": "Sudden 10x burst"}
VIEWS = ["Live view", "Compare all 3"]
REFRESH_S = 0.5
# line colours picked to keep >= 3:1 contrast on both the light and the dark theme. The page itself has no hue
# (.streamlit/config.toml), so colour on screen always means data and never looks like one of the algorithms.
SERIES_COLOR = {"Round Robin": "#d97706", "Least Connections": "#4c78a8", "Weighted Least Conn.": "#2f9e44",
                "served": "#4c78a8", "failed": "#e45756", "avg latency (ms)": "#4c78a8"}
STATE_COLOR = {"up": "#4c78a8", "dead, not detected": "#f58518", "marked down": "#e45756", "alive, not back yet": "#b79a20"}
# a dash pattern per algorithm as well as a colour, so the lines do not depend on colour alone; the rest stay solid
SERIES_DASH = {"Least Connections": [6, 3], "Weighted Least Conn.": [2, 2]}
STATE_LABEL = {"up": "up", "dead, not detected": "dead, not detected yet",
               "marked down": "marked down", "alive, not back yet": "alive, not back yet"}
LIVE_BARS, LIVE_LINES = 130, 180  # chart heights in the live view, small enough that nothing needs scrolling
AXIS = {"labelFontSize": 14, "titleFontSize": 15}  # chart text sized for a projector
# demo story: beat number -> (label, traffic pattern, server killed on schedule or None)
BEATS = {1: ("Normal morning", "normal", None), 2: ("Tatkal rush", "spike", None), 3: ("Server dies mid-rush", "spike", "app-3")}
KILL_AT = 0.45  # beat 3 kills its server this far into the run: inside the rush (traffic.SURGES), 9 s of the default 20 s
ALGO_GLOSS = {"Round Robin": "Takes turns: each request goes to the next server in line, however busy it is.",
              "Least Connections": "Each request goes to the server with the fewest open connections.",
              "Weighted Least Conn.": "Fewest open connections for its size, so bigger servers take more."}

# menu_items: with the minimal toolbar the menu, and the theme switch in it, only exists if the page sets an item
st.set_page_config(page_title="RailDhaara Load Balancer Simulator", page_icon="🚆", layout="wide",
                   menu_items={"About": "Load Balancer Simulator: a college algorithms project. Simulated servers and traffic only."})
DARK = st.context.theme.type == "dark"
MUTED = "#B9B6AE" if DARK else "#4A4D55"  # muted text: 8.9:1 on the dark background, 8.0:1 on the light one


def server_state(s):
    """alive = the truth; healthy = what the load balancer believes (it lags by up to one health check)."""
    if s.alive:
        return "up" if s.healthy else "alive, not back yet"
    return "dead, not detected" if s.healthy else "marked down"


def states_of(sim):
    return {s.id: server_state(s) for s in sim.servers}


def gloss(text, where=st):
    """Helper text in the muted colour. Not st.caption: that is the text colour at 60% opacity, too faint to project."""
    where.markdown(f"<span class='gloss' style='color:{MUTED}'>{text}</span>", unsafe_allow_html=True)


def square(state):
    """A server state's mark: a small square in the colour its bar has in the charts."""
    return f"<span style='display:inline-block;width:.75em;height:.75em;margin-right:.4em;background:{STATE_COLOR[state]}'></span>"


def stroke(series):
    """A line's mark: a short stroke in its chart colour and (roughly) its dash pattern."""
    dash = SERIES_DASH.get(series)
    style = "solid" if not dash else "dashed" if dash[0] > 3 else "dotted"
    return (f"<span style='display:inline-block;width:1.8em;margin-right:.4em;vertical-align:middle;"
            f"border-top:.2em {style} {SERIES_COLOR[series]}'></span>")


def legend(marks):
    """One legend row for the charts below it: {label: mark}. HTML, not a Vega legend, so it wraps on a phone
    instead of being cut off and one row can serve several charts."""
    st.markdown("<div class='legend' style='display:flex;flex-wrap:wrap;gap:.2rem 1.5rem'>"
                + "".join(f"<span style='white-space:nowrap'>{mark}{label}</span>" for label, mark in marks.items())
                + "</div>", unsafe_allow_html=True)


def state_legend():
    legend({"Each bar is one server, coloured by its state:": ""} | {STATE_LABEL[state]: square(state) for state in STATE_COLOR})


def bars(values, states, y_title, ymax=None, height=240):
    df = pd.DataFrame({"server": list(values), "count": list(values.values()), "state": [states[k] for k in values]})
    y = alt.Y("count:Q", title=y_title, scale=alt.Scale(domain=[0, max(ymax or 0, max(values.values()), 1)]))
    color = alt.Color("state:N", legend=None,  # see state_legend()
                      scale=alt.Scale(domain=list(STATE_COLOR), range=list(STATE_COLOR.values())))
    chart = alt.Chart(df).mark_bar().encode(x=alt.X("server:N", sort=None, title=None, axis=alt.Axis(labelAngle=0)),
                                            y=y, color=color, tooltip=["server", "count", "state"])
    st.altair_chart(chart.properties(height=height).configure_axis(**AXIS), width="stretch")


def lines(columns, t, y_title, height=340, x_title="simulated seconds"):
    # Altair, not st.line_chart: the native chart makes Vega log an "Infinite extent" warning on every live refresh
    df = pd.DataFrame(columns, index=pd.Index(t, name="second")).astype(float)
    df = df.reset_index().melt("second", var_name="series", value_name="value")
    chart = alt.Chart(df).mark_line().encode(
        x=alt.X("second:Q", title=x_title), y=alt.Y("value:Q", title=y_title, scale=alt.Scale(zero=True)),
        color=alt.Color("series:N", legend=None,  # see legend() and stroke()
                        scale=alt.Scale(domain=list(columns), range=[SERIES_COLOR[c] for c in columns])),
        strokeDash=alt.StrokeDash("series:N", legend=None,
                                  scale=alt.Scale(domain=list(columns), range=[SERIES_DASH.get(c, [1, 0]) for c in columns])),
        tooltip=["second", "series", "value"])
    st.altair_chart(chart.properties(height=height).configure_axis(**AXIS), width="stretch")


def show_table(table):
    headers, rows = table
    st.dataframe(pd.DataFrame(rows, columns=headers), hide_index=True, width="stretch")


def verdict(results):
    """(headline, detail) for a finished run. Failed requests are judged first; average latency only breaks a tie on
    failures. Both are compared at the precision the comparison table prints, so a tie on the page is a tie here."""
    def lowest(rs, value):
        low = min(value(r) for r in rs)
        return [r for r in rs if value(r) == low], low

    def ms_of(r):
        return float(f"{r.avg_latency_ms:.1f}")

    def names(rs):
        return " and ".join(r.algorithm for r in rs)

    fewest, failed = lowest(results, lambda r: r.failed)
    if len(fewest) == 1:
        fastest, ms = lowest(results, ms_of)
        if len(fastest) == len(results):
            detail = f"Average latency, which is judged second, was the same for all three ({ms} ms)."
        elif fastest == fewest:
            detail = f"It also had the lowest average latency ({ms} ms)."
        else:
            detail = (f"Average latency is judged second: {names(fastest)} "
                      f"{'tied for' if len(fastest) > 1 else 'had'} the lowest ({ms} ms).")
        return f"{fewest[0].algorithm} wins: it failed the fewest requests ({failed}).", detail
    if len(fewest) < len(results):
        tie = f"{names(fewest)} tied for the fewest failed requests ({failed} each)"
    else:
        tie = "No algorithm failed a request" if failed == 0 else f"All three failed the same number of requests ({failed})"
    fastest, ms = lowest(fewest, ms_of)  # only the algorithms still level on failures compete on latency
    if len(fastest) == 1:
        headline = f"{tie}, so average latency decides: {fastest[0].algorithm} wins ({ms} ms)."
    else:
        who = "all three" if len(fastest) == len(results) else "they" if len(fastest) == len(fewest) else names(fastest)
        headline = f"{tie}, and {who} also tied on average latency ({ms} ms): no single winner."
    return headline, "Failed requests are judged first; average latency only breaks a tie."


def status(run, results):
    """One line: the run is context, not the result."""
    dur = run.scenario.duration_ms
    state = "Finished" if run.finished else "Running" if run.running else "Paused" if run.started else "Ready"
    st.markdown(f"<div class='status'><b>{state}</b> · {min(run.now_ms, dur) / 1000:.1f} s / {dur / 1000:g} s · "
                f"{results[0].total} requests so far · {sum(routed_while_marked_down(r) for r in results)} "
                "sent to a marked-down server</div>", unsafe_allow_html=True)
    st.progress(1.0 if run.finished else min(run.now_ms / dur, 1.0))


def events(sim, now_ms, planned):
    ev = [(f.at_ms, f"{f.server_id} {'revived' if f.alive else 'killed'} {'on schedule' if f in planned else 'by you'}")
          for f in sim.faults if f.at_ms <= now_ms]
    ev += [(t, f"{sid} {'back in rotation' if up else 'marked down'} (health check)") for t, sid, up in sim.checker.log]
    # the last 4: enough for all of beat 3 (killed, noticed, revived, back) and short enough to stay on screen
    st.markdown("**Events**<br>" + "<br>".join(f"{t / 1000:.2f} s: {text}" for t, text in sorted(ev)[-4:]), unsafe_allow_html=True)
    if not ev:
        gloss("No server has been killed or revived yet.")


def live_view(run, results, r):
    """Three columns that fit one screen: a 20 s run leaves no time to scroll."""
    sim = run.sims[r.algorithm]
    states, load = states_of(sim), r.load
    state_legend()
    side, left, right = st.columns([5, 4, 4])
    with side:
        st.markdown("**Servers**<br>" + "<br>".join(
            f"{square(states[s.id])}<b>{s.id}</b> · weight {s.weight} · {STATE_LABEL[states[s.id]]}<br>"
            f"<span class='gloss' style='color:{MUTED};margin-left:1.15em'>{s.connections} open · {load[s.id]} handled</span>"
            for s in sim.servers), unsafe_allow_html=True)
        events(sim, run.now_ms, run.scenario.faults)
    ts = timeseries(r.records, upto_ms=run.now_ms)
    with left:
        st.markdown(f"**Handled in the last 5 s** · {r.algorithm}")
        bars(recent_load(r.records, list(load), run.now_ms), states, "requests", height=LIVE_BARS)
        gloss("Requests answered in the last 5 s.")
        if ts["t"]:
            st.markdown("**Average latency per second**")
            lines({"avg latency (ms)": ts["avg_ms"]}, ts["t"], "ms", LIVE_LINES, x_title=None)
        else:
            gloss("Press **Start** in the sidebar. Then try **Kill** on a server and watch its bar drain to zero.")
    with right:
        st.markdown("**Open connections right now**")
        bars({s.id: s.connections for s in sim.servers}, states, "connections", height=LIVE_BARS)
        gloss("Requests being served right now.")
        if ts["t"]:
            st.markdown(f"**Throughput per second**<br>{stroke('served')}served &nbsp; {stroke('failed')}failed",
                        unsafe_allow_html=True)
            lines({"served": ts["ok"], "failed": ts["failed"]}, ts["t"], "requests/s", LIVE_LINES, x_title=None)


def compare_view(run, results):
    st.markdown("**Same traffic through all three algorithms:** the requests each server has answered so far.")
    state_legend()
    ymax = max(max(r.load.values()) for r in results)
    for col, r in zip(st.columns(3), results):
        with col:
            st.markdown(f"#### {r.algorithm}")
            a, b = st.columns(2)  # the two figures the verdict is about, at the size of an answer
            a.metric("failed", r.failed)
            b.metric("avg latency", f"{r.avg_latency_ms:.1f} ms")
            bars(r.load, states_of(run.sims[r.algorithm]), "requests", ymax)
            gloss(ALGO_GLOSS[r.algorithm])
    show_table(comparison_table(results))
    show_table(load_table(results))
    # a kill scheduled by story beat 3 only gets its table once it has happened
    for sid in sorted({f.server_id for f in results[0].faults if not f.alive and f.at_ms <= run.now_ms}):
        gloss(failover_title(results[0], sid, run.interval_ms, never="never" if run.finished else "(not yet)"))
        show_table(failover_table(results, sid))
    ts = {r.algorithm: timeseries(r.records, upto_ms=run.now_ms) for r in results}
    t = ts[results[0].algorithm]["t"]
    if t:
        legend({name: stroke(name) for name in ts})
        left, right = st.columns(2)
        with left:
            st.markdown("**Average latency per second**")
            lines({n: x["avg_ms"] for n, x in ts.items()}, t, "ms")
        with right:
            st.markdown("**Throughput per second** (lines overlap when nothing fails)")
            lines({n: x["ok"] for n, x in ts.items()}, t, "requests/s")
    cmd = cli_command(*st.session_state.cfg, results[0].faults)
    gloss("The same run from the command line (numbers are identical once the run has finished):"
          if cmd else "This sequence of kills needs more than one CLI command, so there is no single CLI equivalent.")
    if cmd:
        st.code(cmd, language="bash")


def panel(run, view, algo, polling):
    run.tick()
    if polling and not run.running:
        st.rerun()  # the run just ended: redraw once more, this time without polling
    results = run.results()
    status(run, results)
    if view == VIEWS[1] and run.finished:  # only a finished run has final numbers to judge
        headline, detail = verdict(results)
        st.subheader(headline, anchor=False)
        st.markdown(detail)
    if view == VIEWS[0]:
        live_view(run, results, results[[r.algorithm for r in results].index(algo)])
    else:
        compare_view(run, results)


def new_run(cfg, speed, beat=None):
    scenario = make_scenario(*cfg)
    victim = BEATS[beat][2] if beat else None
    if victim:  # scheduled in the scenario all three algorithms share, so they lose the server at the same instant
        scenario.faults.append(Fault(scenario.duration_ms * KILL_AT, victim, False))
    return LiveRun(scenario, speed=speed)


def toggle_run():
    """Start / Pause callback. It runs before the script, so the button is drawn with its new label straight away."""
    run = st.session_state.run
    if run.running:
        run.pause()
    else:
        run.start()


def set_beat(n):
    """Button callback: runs before the script, so it may set the Pattern widget's value."""
    st.session_state.pattern, st.session_state.beat = BEATS[n][1], n
    st.session_state.pop("run", None)  # a beat always starts a fresh run, even when the pattern does not change
    if BEATS[n][2]:
        st.session_state.target = BEATS[n][2]  # Kill / Revive point at the server this beat is about
    st.toast(f"Beat {n}: {BEATS[n][0]} is set up. Press Start in the sidebar.")


with st.sidebar:
    st.header("Traffic")
    pattern = st.selectbox("Pattern", list(PATTERNS), format_func=PATTERNS.get, key="pattern")
    algo = st.selectbox("Algorithm (live view)", [a.name for a in ALGORITHMS])
    gloss(ALGO_GLOSS[algo])
    speed = st.select_slider("Speed", [1, 2, 4, 8], value=2, format_func=lambda x: f"{x}x")
    with st.expander("Run settings"):
        seed = st.number_input("Seed", value=42, step=1)
        duration = st.number_input("Duration (s)", min_value=5, max_value=60, value=20, step=1)
        rate = st.number_input("Base rate (requests/s)", min_value=10, max_value=300, value=100, step=10)

beat = st.session_state.get("beat")
if beat and BEATS[beat][1] != pattern:
    beat = st.session_state.beat = None  # the pattern was changed by hand: no beat is active any more
cfg = (pattern, int(seed), int(duration), int(rate))
if st.session_state.get("cfg") != cfg or "run" not in st.session_state:
    st.session_state.cfg, st.session_state.run = cfg, new_run(cfg, speed, beat)
run = st.session_state.run
run.speed = speed

with st.sidebar:
    st.header("Run")
    a, b = st.columns(2)
    a.button("Pause" if run.running else "Start", key="start", type="primary", disabled=run.finished, on_click=toggle_run,
             width="stretch")
    if b.button("Reset", key="reset", width="stretch"):
        st.session_state.run = run = new_run(cfg, speed, beat)
    st.header("Failure injection")
    target = st.selectbox("Server", [f[0] for f in FLEET], key="target")
    live = run.started and not run.finished
    a, b = st.columns(2)
    if a.button("Kill", key="kill", disabled=not live, width="stretch"):
        st.toast(f"{target} killed at {run.now_ms / 1000:.1f} s" if run.kill(target) else f"{target} is already down")
    if b.button("Revive", key="revive", disabled=not live, width="stretch"):
        st.toast(f"{target} revived at {run.now_ms / 1000:.1f} s" if run.revive(target) else f"{target} is already up")
    gloss("Kill: the server stops accepting new requests. The load balancer only notices at its next health "
               "check (every 0.5 s), and requests already in flight on it finish.")

# A small title with the disclaimer beside it: the screen belongs to the run, not to the name.
title, disclaimer = st.columns(2, vertical_alignment="center")
title.markdown("<h1 style='font-size:1.4rem;padding:0;margin:0'>RailDhaara load balancer simulator</h1>", unsafe_allow_html=True)
gloss("A fictional Indian Railways-style booking site under a Tatkal-style rush. Simulated servers and traffic only.", disclaimer)
# .st-key-story: the story buttons get 44 px touch targets (Streamlit's default is 40 px).
# Wide screens: less padding round the page (4rem still clears Streamlit's header bar); a phone keeps the default.
# .mobile-hint: on a phone the sidebar starts collapsed and the controls live in it, so say so.
st.markdown("<style>.st-key-story button{min-height:44px}"
            "@media (min-width:641px){[data-testid='stMainBlockContainer']{padding:4rem 2.5rem 1rem}}"
            # dark theme: the primary colour is near-white, so its button text must be dark (Streamlit's is white)
            + ("[data-testid='stBaseButton-primary']:not(:disabled){color:#16171A}" if DARK else "") +
            ".mobile-hint{display:none}@media (max-width:640px){.mobile-hint{display:block;padding:.5rem .75rem;"
            "border-radius:.5rem;background:rgba(128,128,128,.15);font-size:.9rem}}</style>"
            "<div class='mobile-hint'>Controls (Start, Kill, Revive) are in the sidebar: tap <b>&raquo;</b> at the top left.</div>",
            unsafe_allow_html=True)
with st.container(key="story"):  # the three demo beats; the columns stack full-width on a phone
    for col, (n, (name, _, victim)) in zip(st.columns(len(BEATS)), BEATS.items()):
        col.button(f"{n} {name}", key=f"beat{n}", type="primary" if n == beat else "secondary", on_click=set_beat, args=(n,),
                   width="stretch")
pick, note, info = st.columns([3, 5, 3], vertical_alignment="center")
view = pick.radio("View", VIEWS, horizontal=True, label_visibility="collapsed")
if beat and BEATS[beat][2]:
    gloss(f"Beat {beat}: {BEATS[beat][2]} is killed at {duration * KILL_AT:g} s, for all three algorithms at once.", note)
with info.expander("What am I looking at?"):
    st.markdown(f"- **The setup:** {len(FLEET)} simulated servers of different sizes (weights "
                f"{', '.join(str(f[1]) for f in FLEET)}) share the incoming booking requests.\n"
                "- **The question:** which rule for picking the next server (the algorithm) fails the fewest requests "
                "and answers the fastest.\n"
                "- **How to use it:** pick a story beat above, press **Start** in the sidebar, then open *Compare all 3* "
                "to see the same traffic through all three rules.")
st.fragment(panel, run_every=REFRESH_S if run.running else None)(run, view, algo, run.running)
