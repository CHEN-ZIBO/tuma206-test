"""📈 Trends & Charts — Real-time data visualization"""

from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
# import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import config
from engine import SimulationEngine

st.set_page_config(page_title="Trends · Production Line", layout="wide", page_icon="📈")

# ═══ Shared Engine ═══
@st.cache_resource
def get_engine() -> SimulationEngine:
    e = SimulationEngine(use_mqtt=os.environ.get("USE_MQTT", "0") == "1")
    e.start()
    return e

engine = get_engine()

# ═══ Init session defaults ═══
if "refresh_s" not in st.session_state:
    st.session_state["refresh_s"] = 3
if "window_s" not in st.session_state:
    st.session_state["window_s"] = config.HISTORY_WINDOW_S

# ═══ SIDEBAR ═══
with st.sidebar:
    st.markdown("""
    <div style="text-align:center;padding:10px 0;">
        <div style="font-size:1.2rem;font-weight:800;color:#F5E6D3;">📈  TRENDS & CHARTS</div>
    </div>""", unsafe_allow_html=True)
    st.divider()

    st.markdown("**📐 Chart Settings**")
    st.session_state["window_s"] = st.slider("Trend window (s)", 30, 600,
                                              st.session_state["window_s"], 30)
    st.session_state["refresh_s"] = st.slider("Refresh interval (s)", 1, 10,
                                               st.session_state["refresh_s"])
    st.divider()

    if st.button("📥 Export CSV", width="stretch"):
        path = engine.historian.export_csv()
        st.success(f"✅ Exported → `{path}`")

    st.divider()
    st.caption(f"💾 Historian: SQLite")

# ═══ MAIN ═══
st.markdown("""
<div style="background:linear-gradient(90deg,#C8DFFC,#DBEAFC,#C8DFFC);border-radius:10px;
padding:14px 20px;margin-bottom:10px;border-bottom:3px solid #8B6340;">
<div style="font-size:1.3rem;font-weight:800;color:#3D2B1F;">📈 Real-Time Process Trends</div>
<div style="font-size:0.72rem;color:#5C4A32;">Live sensor data · Historical comparison · Anomaly markers</div>
</div>""", unsafe_allow_html=True)

@st.fragment(run_every=f"{st.session_state['refresh_s']}s")
def trends_view():
    window = st.session_state["window_s"]
    history = engine.historian.recent(window_s=window)

    if not history:
        st.info("⏳ No data yet. Press **Start line** on the 🏭 Process Overview page.")
        return

    df = pd.DataFrame(history)
    df["time"] = pd.to_datetime(df["ts"], unit="s")

    latest = engine.latest()
    alarm_code = int(latest.get("alarm_code", 0))
    frozen = alarm_code == config.ALARM_DATA_STALE

    if frozen:
        st.warning("⏸ Data feed is frozen — displaying last known values.")

    # ── Main 2x2 trend grid ──
    st.markdown('<div class="section-title" style="color:#5C3A1E;font-size:0.95rem;font-weight:700;'
                'border-left:4px solid #C49860;padding-left:10px;margin:14px 0 6px 0;">'
                '📊  SENSOR TRENDS (2×2)</div>', unsafe_allow_html=True)

    fig = make_subplots(rows=2, cols=2,
                        subplot_titles=("Pasteur Temp (°C)", "Tank Level (%)",
                                        "Flow Rate (L/min)", "Bottles Capped"))
    clrs = {"pasteur_temp": "#C0392B", "tank_level": "#3B6F8C",
            "flow_rate": "#5C8A3C", "bottle_count": "#C4841A"}

    for (key, clr), (row, col) in zip(clrs.items(), [(1,1),(1,2),(2,1),(2,2)]):
        fig.add_trace(go.Scatter(x=df["time"], y=df[key], name=key,
                      line=dict(color=clr, width=2.2),
                      fill="tozeroy",
                      fillcolor=f"rgba({','.join(str(int(clr[i:i+2],16)) for i in (1,3,5))},0.06)"),
                      row=row, col=col)

    # Safe-zone bands for pasteur temp
    fig.add_hline(y=config.PASTEUR_SAFE_MAX, line_dash="dot", line_color="#C0392B", row=1, col=1)
    fig.add_hline(y=config.PASTEUR_SAFE_MIN, line_dash="dot", line_color="#C0392B", row=1, col=1)

    # Alarm event markers
    for ev in engine.historian.recent_alarms(50):
        if int(ev.get("alarm_code", 0)) and ev["ts"] >= df["ts"].iloc[0]:
            fig.add_vline(x=pd.to_datetime(ev["ts"], unit="s"), line_color="#C0392B",
                          line_dash="dash", line_width=1.8, row=1, col=1)

    fig.update_layout(height=520, showlegend=False, margin=dict(t=45, b=15, l=40, r=20),
                      plot_bgcolor="#FFFDF9", paper_bgcolor="#FFFDF9",
                      font=dict(color="#3D2B1F", size=11))
    fig.update_xaxes(gridcolor="#E8DDD0"); fig.update_yaxes(gridcolor="#E8DDD0")
    st.plotly_chart(fig, width="stretch", key="trend_2x2")

    # ── Additional charts ──
    st.markdown('<div class="section-title" style="color:#5C3A1E;font-size:0.95rem;font-weight:700;'
                'border-left:4px solid #C49860;padding-left:10px;margin:14px 0 6px 0;">'
                '🔬  ACTUATOR COMMANDS</div>', unsafe_allow_html=True)

    c1, c2 = st.columns(2)

    with c1:
        # Heater power over time
        if "heater_power_cmd" in df.columns:
            fig_h = go.Figure()
            fig_h.add_trace(go.Scatter(x=df["time"], y=df["heater_power_cmd"],
                                       name="Heater", line=dict(color="#F59E0B", width=2.5),
                                       fill="tozeroy", fillcolor="rgba(245,158,11,0.08)"))
            fig_h.update_layout(height=250, title="Heater Power (%)",
                               plot_bgcolor="#FFFDF9", paper_bgcolor="#FFFDF9",
                               margin=dict(t=35, b=15, l=30, r=10),
                               font=dict(color="#3D2B1F", size=10))
            fig_h.update_xaxes(gridcolor="#E8DDD0"); fig_h.update_yaxes(gridcolor="#E8DDD0")
            st.plotly_chart(fig_h, width="stretch")

    with c2:
        # Cooler temp + cooling valve
        fig_c = make_subplots(specs=[[{"secondary_y": True}]])
        fig_c.add_trace(go.Scatter(x=df["time"], y=df["cooler_temp"],
                                   name="Cooler °C", line=dict(color="#3B6F8C", width=2.2)))
        fig_c.add_trace(go.Scatter(x=df["time"], y=df.get("cooling_valve_cmd", [0]*len(df)),
                                   name="Cooling %", line=dict(color="#22C55E", width=1.8, dash="dot")),
                        secondary_y=True)
        fig_c.update_layout(height=250, title="Cooler Temperature & Valve",
                           plot_bgcolor="#FFFDF9", paper_bgcolor="#FFFDF9",
                           margin=dict(t=35, b=15, l=30, r=10),
                           font=dict(color="#3D2B1F", size=10), showlegend=True,
                           legend=dict(orientation="h", yanchor="bottom", y=1.02))
        fig_c.update_xaxes(gridcolor="#E8DDD0"); fig_c.update_yaxes(gridcolor="#E8DDD0")
        st.plotly_chart(fig_c, width="stretch")

    # ── Raw data table ──
    with st.expander("📋 Raw Data (last 20 records)"):
        st.dataframe(df.tail(20).sort_values("time", ascending=False),
                     width="stretch", hide_index=True)

trends_view()
