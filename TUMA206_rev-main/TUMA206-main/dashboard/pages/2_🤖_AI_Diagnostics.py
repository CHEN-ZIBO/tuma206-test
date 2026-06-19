"""🤖 AI Diagnostics — Operator assistant + alarm history"""

from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import streamlit as st

import config
from ai_assistant import AIAssistant
from engine import SimulationEngine

st.set_page_config(page_title="AI Diagnostics · Production Line", layout="wide", page_icon="🤖")

# ═══ Shared Engine + AI ═══
@st.cache_resource
def get_engine() -> SimulationEngine:
    e = SimulationEngine(use_mqtt=os.environ.get("USE_MQTT", "0") == "1")
    e.start()
    return e

@st.cache_resource
def get_assistant() -> AIAssistant:
    return AIAssistant()

engine = get_engine()
assistant = get_assistant()

if "refresh_s" not in st.session_state:
    st.session_state["refresh_s"] = 3
if "window_s" not in st.session_state:
    st.session_state["window_s"] = config.HISTORY_WINDOW_S

# ═══ SIDEBAR ═══
with st.sidebar:
    st.markdown("""
    <div style="text-align:center;padding:10px 0;">
        <div style="font-size:1.2rem;font-weight:800;color:#F5E6D3;">🤖  AI DIAGNOSTICS</div>
    </div>""", unsafe_allow_html=True)
    st.divider()

    st.markdown("**🔍 Quick Actions**")
    if st.button("🔄 Force Analysis", use_container_width=True):
        st.session_state.pop("ai_cache", None)
        st.rerun()

    if st.button("🗑 Clear AI Cache", use_container_width=True):
        st.session_state.pop("ai_cache", None)
        st.success("Cache cleared.")

    st.divider()
    st.caption(f"🧠 Engine: **{'Claude API' if assistant.using_claude else 'Rule-based (offline)'}**")

# ═══ MAIN HEADER ═══
st.markdown("""
<div style="background:linear-gradient(90deg,#C8DFFC,#DBEAFC,#C8DFFC);border-radius:10px;
padding:14px 20px;margin-bottom:10px;border-bottom:3px solid #8B6340;">
<div style="font-size:1.3rem;font-weight:800;color:#3D2B1F;">🤖 AI Operator Assistant & Alarm History</div>
<div style="font-size:0.72rem;color:#5C4A32;">Automatic fault diagnosis · Operator recommendations · Event log</div>
</div>""", unsafe_allow_html=True)

# ═══ LIVE VIEW ═══
@st.fragment(run_every=f"{st.session_state['refresh_s']}s")
def ai_view():
    latest = engine.latest()
    alarm_code = int(latest.get("alarm_code", config.ALARM_NONE))
    history = engine.historian.recent(window_s=st.session_state["window_s"])

    # ── Current Status ──
    col1, col2, col3 = st.columns(3)
    col1.metric("PLC State", latest.get("plc_state", "IDLE"))
    col2.metric("Active Alarm", config.ALARM_LABELS.get(alarm_code, "None"),
                delta="🚨" if alarm_code else "✅")
    col3.metric("Fault Status", config.FAULT_LABELS.get(int(latest.get("fault_status", 0)), "Normal"))

    st.divider()

    # ── AI Diagnosis Panel ──
    st.markdown("### 🧠 AI Diagnosis & Recommendation")

    cache = st.session_state.setdefault("ai_cache", {})

    if alarm_code or st.session_state.get("_force_ai", False):
        if alarm_code not in cache:
            with st.spinner("🔍 Analyzing system state..."):
                cache[alarm_code] = assistant.diagnose(latest, alarm_code, history)
        result = cache.get(alarm_code)

        if result:
            conf = result["confidence_level"]
            conf_color = "#22C55E" if conf == "high" else ("#F59E0B" if conf == "medium" else "#EF4444")

            st.markdown(f"""
            <div style="background:#FFFDF9;border-radius:10px;border:1px solid #D4C4AD;
            border-left:5px solid #C49860;padding:16px 20px;margin:8px 0;">
                <div style="display:flex;align-items:center;gap:12px;margin-bottom:8px;">
                    <span style="font-size:1.1rem;font-weight:700;color:#5C3A1E;">📋 {result['diagnosis_label']}</span>
                    <span style="background:{conf_color};color:#FFF;padding:2px 10px;border-radius:10px;font-size:0.72rem;font-weight:700;">
                        {conf.upper()}
                    </span>
                    <span style="font-size:0.72rem;color:#8B7355;">via {result['engine']}</span>
                </div>
                <div style="color:#3D2B1F;line-height:1.6;font-size:0.95rem;padding:8px 0;">
                    {result['recommendation_text']}
                </div>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.info("Analysis pending...")
    else:
        st.success("""
        ✅ **No active alarms** — system operating normally.

        The AI assistant monitors continuously and activates automatically when an alarm is detected.
        Use the **🔄 Force Analysis** button in the sidebar to request a manual assessment.
        """)

    st.divider()

    # ── Alarm History ──
    st.markdown("### 📜 Alarm Event Log")

    alarms = engine.historian.recent_alarms(100)
    if alarms:
        adf = pd.DataFrame(alarms)
        adf["time"] = pd.to_datetime(adf["ts"], unit="s")
        adf = adf.sort_values("time", ascending=False)

        # Show stats
        total_alarms = len(adf)
        unique_types = adf["label"].nunique() if "label" in adf.columns else 0
        st.caption(f"📊 {total_alarms} events recorded · {unique_types} unique alarm types")

        # Color-code by alarm type
        def highlight_row(row):
            code = row.get("alarm_code", 0)
            if code == 0:
                return [''] * len(row)
            return ['background-color: #FCE8E6'] * len(row)

        styled = adf[["time", "label", "description"]].style.apply(highlight_row, axis=1)
        st.dataframe(styled, width="stretch", hide_index=True, height=300)

        # ── Alarm distribution ──
        if "label" in adf.columns and total_alarms > 1:
            st.markdown("#### Alarm Type Distribution")
            dist = adf["label"].value_counts()
            cols = st.columns(len(dist))
            for i, (label, count) in enumerate(dist.items()):
                cols[i].metric(label, count)
    else:
        st.info("No alarm events recorded yet. Start the line and inject faults to see alarms here.")

ai_view()
