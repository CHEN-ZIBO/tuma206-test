"""M4 Dashboard · 🏭 Process Overview — P&ID + KPIs + Status"""

from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st

import config
from ai_assistant import AIAssistant
from engine import SimulationEngine

st.set_page_config(page_title="Production Line Control Center", layout="wide", page_icon="🏭")

# ═══ GLOBAL CSS ═══
st.markdown("""
<style>
    .stApp { background: #F5F0EB; }
    header[data-testid="stHeader"] {
        background: linear-gradient(90deg, #C8DFFC, #DAE9FD, #C8DFFC);
        border-bottom: 3px solid #8B6340;
    }
    header[data-testid="stHeader"] * { color: #3D2B1F !important; }
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #5C3A1E, #4A2D14, #3D2310);
        border-right: 2px solid #8B6340;
    }
    [data-testid="stSidebar"] * { color: #F5E6D3 !important; }
    [data-testid="stSidebar"] .stButton > button {
        background: #8B6340 !important; color: #FFF !important;
        border: 1px solid #A0784C !important; border-radius: 6px !important; font-weight: 600 !important;
    }
    [data-testid="stSidebar"] .stButton > button:hover { background: #A0784C !important; }
    [data-testid="stSidebar"] hr { border-color: #8B6340 !important; }
    [data-testid="stSidebar"] [data-testid="stSelectbox"] > div > div {
        background: #3D2310 !important; border: 1px solid #8B6340 !important;
    }
    .banner-normal { background: linear-gradient(90deg,#5C8A3C,#6B9E4A); color:#FFF;
        border-radius:8px; padding:10px 18px; font-weight:700; font-size:1rem;
        margin:6px 0; border-left:5px solid #3D6B1E; }
    .banner-alarm { background: linear-gradient(90deg,#C0392B,#D44637); color:#FFF;
        border-radius:8px; padding:10px 18px; font-weight:700; font-size:1rem;
        margin:6px 0; border-left:5px solid #7B1A10; animation: pulse 1.5s infinite; }
    .banner-frozen { background: linear-gradient(90deg,#4A4A4A,#5C5C5C); color:#CCC;
        border-radius:8px; padding:10px 18px; font-weight:700; font-size:1rem;
        margin:6px 0; border-left:5px solid #222; }
    @keyframes pulse { 0%,100%{opacity:1;} 50%{opacity:0.85;} }
    .kpi-card { border-radius:8px; padding:8px 12px; margin:2px 0; min-height:80px;
        box-shadow:0 2px 8px rgba(61,43,31,0.10); transition:transform 0.15s; }
    .kpi-card:hover { transform:translateY(-2px); }
    .section-title { color:#5C3A1E; font-size:0.95rem; font-weight:700;
        border-left:4px solid #C49860; padding-left:10px; margin:14px 0 6px 0; }
    .ai-panel { background:#FFFDF9; border-radius:8px; border:1px solid #D4C4AD;
        border-left:5px solid #C49860; padding:12px 16px; margin:8px 0; }
    .actuator-row { display:flex; align-items:center; gap:8px; padding:6px 0;
        border-bottom:1px solid #5C3A1E; }
    .actuator-name { font-size:0.78rem; font-weight:700; color:#F5E6D3; min-width:55px; }
    .highlight-box { background:#FFFDF9; border:1px solid #D4C4AD; border-radius:10px;
        padding:16px 20px; margin:8px 0; }
</style>
""", unsafe_allow_html=True)

# ═══ Shared Engine + AI (cached, shared across all pages) ═══
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

# ═══ Session state init ═══
ACTUATORS = ["pump_cmd", "inlet_valve_cmd", "heater_power_cmd", "cooling_valve_cmd", "conveyor_cmd"]
for a in ACTUATORS:
    if f"man_{a}" not in st.session_state:
        st.session_state[f"man_{a}"] = False
    if f"val_{a}" not in st.session_state:
        st.session_state[f"val_{a}"] = 0 if a == "heater_power_cmd" else 0

if "refresh_s" not in st.session_state:
    st.session_state["refresh_s"] = 3
if "window_s" not in st.session_state:
    st.session_state["window_s"] = config.HISTORY_WINDOW_S

def apply_manual(act_name, is_manual, value):
    st.session_state[f"man_{act_name}"] = is_manual
    st.session_state[f"val_{act_name}"] = value
    if is_manual:
        engine.set_manual_actuator(act_name, value)
    else:
        engine.clear_manual_actuator(act_name)

# ═══ KPI helper ═══
CC = {
    "ok": ("#5C8A3C","#E8F0E0","#3D6B1E"), "warn": ("#C4841A","#FEF6E8","#8B5E08"),
    "bad": ("#C0392B","#FCE8E6","#8B1A10"), "idle": ("#8B7355","#EDE4D8","#5C4A32"),
    "info": ("#3B6F8C","#E3EEF4","#1E4A5E"),
}

def kpi(label, value, status="idle", sub=""):
    br, bg, fg = CC.get(status, CC["idle"])
    return (f'<div class="kpi-card" style="background:{bg};border-left:5px solid {br};">'
            f'<div style="font-size:0.65rem;font-weight:700;text-transform:uppercase;letter-spacing:0.04em;color:{fg};">{label}</div>'
            f'<div style="font-size:1.35rem;font-weight:700;color:#3D2B1F;line-height:1.2;">{value}</div>'
            f'<div style="font-size:0.62rem;color:#8B7355;">{sub}</div></div>')

# ═══ P&ID SVG Builder ═══
def build_svg(latest, plc_state, alarm_code, frozen, manual_overrides):
    tl = float(latest.get("tank_level", 0));  pt = float(latest.get("pasteur_temp", 0))
    ct = float(latest.get("cooler_temp", 0));  fr = float(latest.get("flow_rate", 0))
    bc = int(latest.get("bottle_count", 0));   bp = int(latest.get("bottle_present", 0))
    pc = int(latest.get("pump_cmd", 0));        pf = int(latest.get("pump_feedback", 0))
    ic = int(latest.get("inlet_valve_cmd", 0)); hc = float(latest.get("heater_power_cmd", 0))
    cc = int(latest.get("cooling_valve_cmd", 0)); fc = int(latest.get("fill_valve_cmd", 0))
    cvc = int(latest.get("conveyor_cmd", 0));   cpc = int(latest.get("capper_cmd", 0))
    fcode = int(latest.get("fault_status", 0))
    man = {k: v for k, v in (manual_overrides or {}).items()}

    pump_color   = "#EF4444" if fcode==config.FAULT_PUMP_FAIL else ("#22C55E" if pc>0 else "#9CA3AF")
    inlet_color  = "#22C55E" if ic>0 else "#9CA3AF"
    heater_color = "#EF4444" if fcode==config.FAULT_TEMP_EXCURSION else ("#F59E0B" if hc>0 else "#9CA3AF")
    cooling_color = "#22C55E" if cc>0 else "#9CA3AF"
    fill_active   = fc and bp
    fill_color   = "#22C55E" if fill_active else "#9CA3AF"
    conv_color   = "#22C55E" if cvc>0 else "#9CA3AF"
    ts_color = "#EF4444" if alarm_code==config.ALARM_SENSOR_TEMP_STUCK else (
        "#22C55E" if config.PASTEUR_SAFE_MIN<=pt<=config.PASTEUR_SAFE_MAX else "#EF4444")
    pipe_flowing = (pc and pf) and not frozen
    pipe_color = "#3B82F6" if pipe_flowing else "#94A3B8"
    pw = 3 if pipe_flowing else 2

    def man_badge(x, y, act_name):
        if act_name in man:
            return f'<rect x="{x}" y="{y}" width="44" height="16" rx="8" fill="#F59E0B" opacity="0.9"/>' \
                   f'<text x="{x+22}" y="{y+11}" text-anchor="middle" font-size="8" font-weight="700" fill="#FFF">MANUAL</text>'
        return ''

    svg = f'''<svg width="100%" viewBox="0 0 1200 440" xmlns="http://www.w3.org/2000/svg"
     style="background:#FFFDF9;border-radius:12px;box-shadow:0 2px 16px rgba(61,43,31,0.10);">
    <defs><filter id="sh"><feDropShadow dx="0" dy="1" stdDeviation="2" flood-opacity="0.12"/></filter></defs>
    <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
        <path d="M40 0L0 0 0 40" fill="none" stroke="#E8E8E8" stroke-width="0.5"/></pattern>
    <rect width="1200" height="440" fill="url(#grid)" opacity="0.4"/>

    <!-- PIPES -->
    <line x1="158" y1="195" x2="200" y2="195" stroke="{pipe_color}" stroke-width="{pw+2}" stroke-linecap="round"/>
    <line x1="260" y1="195" x2="360" y2="195" stroke="{pipe_color}" stroke-width="{pw+2}" stroke-linecap="round"/>
    <line x1="475" y1="195" x2="570" y2="195" stroke="{pipe_color}" stroke-width="{pw+2}" stroke-linecap="round"/>
    <line x1="670" y1="195" x2="780" y2="195" stroke="{pipe_color}" stroke-width="{pw+2}" stroke-linecap="round"/>
    <line x1="880" y1="195" x2="990" y2="195" stroke="{pipe_color}" stroke-width="{pw+2}" stroke-linecap="round"/>
    {''.join(f'<polygon points="{x},188 {x+10},195 {x},202" fill="#3B82F6" opacity="0.8"/>' for x in [220,310,520,720,930]) if pipe_flowing else ''}

    <!-- S1 RAW TANK -->
    <g filter="url(#sh)">
        <rect x="28" y="100" width="130" height="180" rx="10" fill="#F8FAFC" stroke="#64748B" stroke-width="2"/>
        <clipPath id="tc"><rect x="30" y="102" width="126" height="176" rx="8"/></clipPath>
        <rect x="30" y="{100+180*(1-tl/100)}" width="126" height="{180*tl/100}" fill="#3B82F6" opacity="0.35" clip-path="url(#tc)"/>
        <line x1="162" y1="145" x2="168" y2="145" stroke="#94A3B8"/><text x="170" y="148" font-size="7" fill="#94A3B8">75%</text>
        <line x1="162" y1="190" x2="168" y2="190" stroke="#94A3B8"/><text x="170" y="193" font-size="7" fill="#94A3B8">50%</text>
        <line x1="162" y1="235" x2="168" y2="235" stroke="#94A3B8"/><text x="170" y="238" font-size="7" fill="#94A3B8">25%</text>
        <text x="93" y="200" text-anchor="middle" font-size="20" font-weight="800" fill="#1E293B">{tl:.0f}%</text>
        <text x="93" y="295" text-anchor="middle" font-size="11" font-weight="700" fill="#475569">RAW TANK</text>
        <text x="93" y="310" text-anchor="middle" font-size="8" fill="#64748B">S1 · Balance Tank</text>
    </g>
    <line x1="93" y1="45" x2="93" y2="100" stroke="#94A3B8" stroke-width="8" stroke-linecap="round"/>
    <g filter="url(#sh)">
        <rect x="65" y="58" width="56" height="32" rx="6" fill="{inlet_color}" stroke="#64748B" stroke-width="1.5"/>
        <text x="93" y="72" text-anchor="middle" font-size="9" font-weight="700" fill="#FFF">INLET</text>
        <text x="93" y="84" text-anchor="middle" font-size="7" fill="#FFF">{ic:.0f}% {"OPEN" if ic>0 else "SHUT"}</text>
    </g>
    {man_badge(57, 38, 'inlet_valve_cmd')}
    <text x="93" y="38" text-anchor="middle" font-size="7" fill="#64748B">RAW SUPPLY</text>

    <!-- FEED PUMP -->
    <g filter="url(#sh)">
        <circle cx="230" cy="195" r="30" fill="#FFF" stroke={pump_color} stroke-width="3"/>
        <circle cx="230" cy="195" r="20" fill={pump_color} opacity="0.15"/>
        <circle cx="230" cy="195" r="12" fill="none" stroke={pump_color} stroke-width="2" stroke-dasharray="5,3"/>
        <circle cx="230" cy="195" r="4" fill={pump_color}/>
        <text x="230" y="248" text-anchor="middle" font-size="9" font-weight="700" fill="#475569">FEED PUMP</text>
        <text x="230" y="262" text-anchor="middle" font-size="8" fill={pump_color}>{fr:.0f} L/min</text>
        {f'<text x="230" y="276" text-anchor="middle" font-size="8" fill="#EF4444" font-weight="700">⚠ FAULT</text>' if fcode==config.FAULT_PUMP_FAIL else ''}
    </g>
    {man_badge(208, 280, 'pump_cmd')}

    <!-- S2 PASTEURIZER -->
    <g filter="url(#sh)">
        <rect x="360" y="95" width="115" height="200" rx="10" fill="#FFF" stroke="#64748B" stroke-width="2"/>
        <path d="M370 140L465 140L370 155L465 155L370 170L465 170L370 185L465 185" fill="none" stroke={heater_color} stroke-width="2.5" opacity="0.7"/>
        <text x="417" y="220" text-anchor="middle" font-size="22" font-weight="800" fill={ts_color}>{pt:.1f}°C</text>
        <text x="417" y="240" text-anchor="middle" font-size="8" fill="#64748B">Set:72°C · Safe:68–78°C</text>
        <rect x="382" y="250" width="70" height="10" rx="5" fill="#E2E8F0"/>
        <rect x="382" y="250" width="{70*hc/100}" height="10" rx="5" fill={heater_color}/>
        <text x="417" y="272" text-anchor="middle" font-size="9" fill="#64748B">Heater {hc:.0f}%</text>
        <text x="417" y="288" text-anchor="middle" font-size="11" font-weight="700" fill="#475569">PASTEURIZER</text>
        <text x="417" y="302" text-anchor="middle" font-size="8" fill="#64748B">S2</text>
    </g>
    <rect x="440" y="78" width="38" height="16" rx="8" fill={ts_color} opacity="0.2" stroke={ts_color} stroke-width="1.5"/>
    <text x="459" y="90" text-anchor="middle" font-size="9" font-weight="700" fill={ts_color}>TT</text>
    {f'<text x="459" y="72" text-anchor="middle" font-size="7" fill="#EF4444" font-weight="700">STUCK!</text>' if alarm_code==config.ALARM_SENSOR_TEMP_STUCK else ''}
    {man_badge(390, 310, 'heater_power_cmd')}

    <!-- S3 COOLER -->
    <g filter="url(#sh)">
        <rect x="570" y="110" width="100" height="170" rx="10" fill="#FFF" stroke="#64748B" stroke-width="2"/>
        <ellipse cx="620" cy="155" rx="30" ry="12" fill="none" stroke={cooling_color} stroke-width="2" stroke-dasharray="6,3"/>
        <ellipse cx="620" cy="175" rx="22" ry="9" fill="none" stroke={cooling_color} stroke-width="2" stroke-dasharray="6,3"/>
        <text x="620" y="210" text-anchor="middle" font-size="20" font-weight="800" fill="#1E293B">{ct:.1f}°C</text>
        <rect x="593" y="222" width="54" height="16" rx="8" fill={cooling_color} opacity="0.25" stroke={cooling_color} stroke-width="1.5"/>
        <text x="620" y="234" text-anchor="middle" font-size="7" font-weight="700" fill={cooling_color}>COOL {cc:.0f}%</text>
        <text x="620" y="268" text-anchor="middle" font-size="11" font-weight="700" fill="#475569">COOLER</text>
        <text x="620" y="282" text-anchor="middle" font-size="8" fill="#64748B">S3 · Target 20°C</text>
    </g>
    {man_badge(598, 290, 'cooling_valve_cmd')}

    <!-- S4 FILLER -->
    <g filter="url(#sh)">
        <rect x="780" y="105" width="100" height="180" rx="10" fill="#FFF" stroke="#64748B" stroke-width="2"/>
        <path d="M815 155L815 195Q815 212 830 212Q845 212 845 195L845 155" fill="none" stroke={fill_color} stroke-width="2"/>
        <rect x="810" y="140" width="40" height="15" rx="4" fill={fill_color} opacity="0.3" stroke={fill_color} stroke-width="1.5"/>
        {f'<rect x="816" y="172" width="28" height="38" rx="3" fill="#3B82F6" opacity="0.55"/>' if fc and bp else ''}
        <line x1="830" y1="125" x2="830" y2="143" stroke="#64748B" stroke-width="3"/>
        <text x="830" y="232" text-anchor="middle" font-size="11" font-weight="700" fill="#1E293B">{"FILLING…" if (fc and bp) else "IDLE"}</text>
        <text x="830" y="248" text-anchor="middle" font-size="8" fill="#64748B">{"Bottle present" if bp else "Waiting"}</text>
        <text x="830" y="278" text-anchor="middle" font-size="11" font-weight="700" fill="#475569">FILLER</text>
        <text x="830" y="292" text-anchor="middle" font-size="8" fill="#64748B">S4 · Fill Station</text>
    </g>

    <!-- S5 CAPPER -->
    <g filter="url(#sh)">
        <rect x="990" y="110" width="100" height="170" rx="10" fill="#FFF" stroke="#64748B" stroke-width="2"/>
        <rect x="995" y="185" width="90" height="10" rx="5" fill="#E2E8F0" stroke={conv_color} stroke-width="1.5"/>
        <circle cx="1000" cy="190" r="5" fill="#94A3B8"/><circle cx="1080" cy="190" r="5" fill="#94A3B8"/>
        <rect x="1005" y="168" width="10" height="17" rx="2" fill="#3B82F6" opacity="0.35" stroke="#3B82F6" stroke-width="0.8"/>
        <rect x="1023" y="168" width="10" height="17" rx="2" fill="#3B82F6" opacity="0.55" stroke="#3B82F6" stroke-width="0.8"/>
        <rect x="1041" y="168" width="10" height="17" rx="2" fill="#22C55E" opacity="0.65" stroke="#22C55E" stroke-width="0.8"/>
        <text x="1056" y="172" font-size="13">🧢</text>
        <text x="1040" y="222" text-anchor="middle" font-size="18" font-weight="800" fill="#1E293B">{bc}</text>
        <text x="1040" y="237" text-anchor="middle" font-size="8" fill="#64748B">Bottles Capped</text>
        <text x="1040" y="268" text-anchor="middle" font-size="11" font-weight="700" fill="#475569">CAPPER</text>
        <text x="1040" y="282" text-anchor="middle" font-size="8" fill="#64748B">S5 · Conveyor</text>
    </g>
    {man_badge(1018, 290, 'conveyor_cmd')}

    <!-- Outlet -->
    <line x1="1090" y1="195" x2="1140" y2="195" stroke="#64748B" stroke-width="6"/>
    <polygon points="1135,188 1145,195 1135,202" fill="#94A3B8"/>
    <text x="1155" y="198" font-size="8" fill="#64748B">OUTPUT</text>

    <!-- BOTTOM BAR -->
    <g filter="url(#sh)">
        <rect x="28" y="340" width="200" height="70" rx="8" fill="#FFF" stroke="#64748B" stroke-width="1.5"/>
        <text x="128" y="362" text-anchor="middle" font-size="10" font-weight="800" fill="#475569">PLC STATE</text>
        <rect x="48" y="372" width="160" height="26" rx="13"
              fill={"#22C55E" if plc_state=="RUNNING" else "#F59E0B" if plc_state in ("STARTING","STOPPING") else "#EF4444" if plc_state=="FAULT" else "#9CA3AF"}/>
        <text x="128" y="390" text-anchor="middle" font-size="12" font-weight="700" fill="#FFF">{plc_state}</text>
    </g>
    <g filter="url(#sh)">
        <rect x="242" y="340" width="280" height="70" rx="8" fill="#FFF"
              stroke={"#EF4444" if alarm_code else "#22C55E"} stroke-width="2"/>
        <text x="382" y="362" text-anchor="middle" font-size="10" font-weight="800"
              fill={"#EF4444" if alarm_code else "#22C55E"}>{"🚨 ALARM" if alarm_code else "✅ SYSTEM NORMAL"}</text>
        <text x="382" y="382" text-anchor="middle" font-size="10" font-weight="700"
              fill={"#EF4444" if alarm_code else "#475569"}>{config.ALARM_LABELS.get(alarm_code, "No active alarms")}</text>
        <text x="382" y="400" text-anchor="middle" font-size="7" fill="#64748B">
            Tick #{latest.get("tick",0)} · {config.FAULT_LABELS.get(fcode, "Normal")}</text>
    </g>
    <g>
        <rect x="536" y="340" width="640" height="70" rx="8" fill="#F8FAFC" stroke="#CBD5E1" stroke-width="1"/>
        <circle cx="556" cy="358" r="5" fill="#22C55E"/><text x="566" y="361" font-size="7" fill="#475569">OK</text>
        <circle cx="606" cy="358" r="5" fill="#F59E0B"/><text x="616" y="361" font-size="7" fill="#475569">Warning</text>
        <circle cx="666" cy="358" r="5" fill="#EF4444"/><text x="676" y="361" font-size="7" fill="#475569">Fault</text>
        <circle cx="726" cy="358" r="5" fill="#9CA3AF"/><text x="736" y="361" font-size="7" fill="#475569">Off</text>
        <rect x="556" y="370" width="14" height="4" rx="2" fill="#3B82F6"/><text x="576" y="375" font-size="7" fill="#64748B">Pipe flowing</text>
        <rect x="656" y="370" width="14" height="4" rx="2" fill="#94A3B8"/><text x="676" y="375" font-size="7" fill="#64748B">Pipe idle</text>
        <rect x="556" y="384" width="14" height="4" rx="2" fill="#F59E0B"/><text x="576" y="389" font-size="7" fill="#64748B">MANUAL badge = operator override active</text>
        <rect x="776" y="384" width="14" height="4" rx="2" fill="#22C55E"/><text x="796" y="389" font-size="7" fill="#64748B">AUTO = PLC in control</text>
    </g>
    {f'''
    <rect x="0" y="0" width="1200" height="440" fill="#1E293B" opacity="0.55"/>
    <rect x="350" y="150" width="500" height="80" rx="16" fill="#EF4444" opacity="0.9"/>
    <text x="600" y="182" text-anchor="middle" font-size="24" font-weight="900" fill="#FFF">⏸  DATA FROZEN</text>
    <text x="600" y="208" text-anchor="middle" font-size="12" fill="#FECACA">Monitoring link down · Last known values displayed</text>
    ''' if frozen else ''}
</svg>'''
    return svg


# ═══ SIDEBAR ═══
with st.sidebar:
    st.markdown("""
    <div style="text-align:center;padding:10px 0;">
        <div style="font-size:1.3rem;font-weight:800;color:#F5E6D3;">🏭  PRODUCTION CONTROL</div>
        <div style="font-size:0.65rem;color:#C49860;letter-spacing:0.05em;">INTELLIGENT LINE SUPERVISOR</div>
    </div>""", unsafe_allow_html=True)
    st.divider()

    # ── Line control ──
    col_a, col_b = st.columns(2)
    if col_a.button("▶ Start line", use_container_width=True):
        engine.start_line()
    if col_b.button("⏹ Stop line", use_container_width=True):
        engine.stop_line()
        for a in ACTUATORS:
            st.session_state[f"man_{a}"] = False
            engine.clear_manual_actuator(a)

    st.divider()

    # ── Per-Actuator Manual Override ──
    st.markdown("**🖐 Manual Override**")
    st.caption("Switch to MANUAL to bypass PLC control.")

    man_pump = st.checkbox("Pump — MANUAL", key="man_pump_cb")
    if man_pump:
        val_pump = st.slider("Pump speed %", 0.0, 100.0,
                             float(st.session_state.get("val_pump_cmd", 0.0)), key="sli_pump")
        apply_manual("pump_cmd", True, float(val_pump))
    else:
        apply_manual("pump_cmd", False, 0.0)

    man_inlet = st.checkbox("Inlet Valve — MANUAL", key="man_inlet_cb")
    if man_inlet:
        val_inlet = st.slider("Inlet valve %", 0.0, 100.0,
                              float(st.session_state.get("val_inlet_valve_cmd", 0.0)), key="sli_inlet")
        apply_manual("inlet_valve_cmd", True, float(val_inlet))
    else:
        apply_manual("inlet_valve_cmd", False, 0.0)

    man_heater = st.checkbox("Heater — MANUAL", key="man_heater_cb")
    if man_heater:
        val_heater = st.slider("Heater power %", 0.0, 100.0,
                               float(st.session_state.get("val_heater_power_cmd", 0.0)), 5.0, key="sli_heater")
        apply_manual("heater_power_cmd", True, float(val_heater))
    else:
        apply_manual("heater_power_cmd", False, 0.0)

    man_cool = st.checkbox("Cooling Valve — MANUAL", key="man_cool_cb")
    if man_cool:
        val_cool = st.slider("Cooling valve %", 0.0, 100.0,
                             float(st.session_state.get("val_cooling_valve_cmd", 0.0)), key="sli_cool")
        apply_manual("cooling_valve_cmd", True, float(val_cool))
    else:
        apply_manual("cooling_valve_cmd", False, 0.0)

    man_conv = st.checkbox("Conveyor — MANUAL", key="man_conv_cb")
    if man_conv:
        val_conv = st.slider("Conveyor speed %", 0.0, 100.0,
                             float(st.session_state.get("val_conveyor_cmd", 0.0)), key="sli_conv")
        apply_manual("conveyor_cmd", True, float(val_conv))
    else:
        apply_manual("conveyor_cmd", False, 0.0)

    st.divider()

    # ── Fault Injection ──
    st.markdown("**⚠ Fault Injection**")
    fault_choice = st.selectbox("Select fault", options=list(config.FAULT_LABELS.keys()),
                                format_func=lambda c: f"{c} — {config.FAULT_LABELS[c]}")
    col_c, col_d = st.columns(2)
    if col_c.button("⚡ Inject", use_container_width=True):
        engine.inject_fault(fault_choice)
    if col_d.button("↺ Reset fault", use_container_width=True):
        engine.reset_fault()

    st.divider()
    st.markdown("**⚙ Settings**")
    st.session_state["refresh_s"] = st.slider("Refresh (s)", 1, 10,
                                               st.session_state["refresh_s"])
    st.session_state["window_s"] = st.slider("Trend window (s)", 30, 600,
                                              st.session_state["window_s"], 30)

    st.divider()
    st.caption(f"🧠 AI: **{'Claude' if assistant.using_claude else 'Rule-based'}**")
    st.caption(f"📡 Bus: **{type(engine.bus).__name__}**")
    st.caption(f"🔧 Manual overrides: **{len(engine.manual_overrides)}** active")

# ═══ MAIN HEADER ═══
st.markdown("""
<div style="background:linear-gradient(90deg,#C8DFFC,#DBEAFC,#C8DFFC);border-radius:10px;
padding:14px 20px;margin-bottom:10px;border-bottom:3px solid #8B6340;">
<div style="font-size:1.4rem;font-weight:800;color:#3D2B1F;">🏭 Intelligent Beverage Production Line</div>
<div style="font-size:0.72rem;color:#5C4A32;">Real-Time Monitoring · PLC Control · Data Analytics · AI Diagnostics</div>
</div>""", unsafe_allow_html=True)

# ═══ LIVE VIEW: P&ID + KPIs ═══
@st.fragment(run_every=f"{st.session_state['refresh_s']}s")
def live_view():
    latest = engine.latest()
    alarm_code = int(latest.get("alarm_code", config.ALARM_NONE))
    plc_state = latest.get("plc_state", config.PLC_IDLE)
    frozen = alarm_code == config.ALARM_DATA_STALE

    # ── Status Banner ──
    if frozen:
        st.markdown(f'<div class="banner-frozen">⏸ DATA FROZEN · PLC: {plc_state}</div>', unsafe_allow_html=True)
    elif alarm_code:
        st.markdown(f'<div class="banner-alarm">🚨 ALARM [{config.ALARM_LABELS.get(alarm_code)}] · '
                    f'{config.ALARM_DESCRIPTIONS.get(alarm_code)} · PLC: {plc_state}</div>', unsafe_allow_html=True)
    else:
        n_man = len(engine.manual_overrides)
        man_note = f" · 🖐 {n_man} actuator(s) in MANUAL" if n_man else " · 🔄 All actuators AUTO"
        st.markdown(f'<div class="banner-normal">✅ Normal Operation · PLC: {plc_state}{man_note}</div>',
                    unsafe_allow_html=True)

    # ── P&ID Flow Diagram ──
    st.markdown('<div class="section-title">🏭  PROCESS FLOW DIAGRAM (P&ID)</div>', unsafe_allow_html=True)
    svg = build_svg(latest, plc_state, alarm_code, frozen, engine.manual_overrides)
    st.components.v1.html(svg, height=460, scrolling=False)

    # ── KPI Cards ──
    st.markdown('<div class="section-title">📊  KEY PERFORMANCE INDICATORS</div>', unsafe_allow_html=True)
    temp = float(latest.get("pasteur_temp", 0))
    level = float(latest.get("tank_level", 0))
    flow = float(latest.get("flow_rate", 0))
    if frozen:
        ts = ls = fs = "idle"
    else:
        ts = "bad" if temp > config.PASTEUR_SAFE_MAX else ("warn" if temp < config.PASTEUR_SAFE_MIN else "ok")
        ls = "warn" if (level < config.TANK_LEVEL_LOW or level > config.TANK_LEVEL_HIGH) else "ok"
        fs = "ok" if flow > 0.1 else "idle"

    kpis = [
        ("Tank Level", f"{level:.1f} %", ls, ""),
        ("Pasteur Temp", f"{temp:.1f} °C", ts, f"Safe {config.PASTEUR_SAFE_MIN:.0f}–{config.PASTEUR_SAFE_MAX:.0f}°C"),
        ("Cooler Temp", f"{latest.get('cooler_temp', 0):.1f} °C", "info", ""),
        ("Flow Rate", f"{flow:.1f} L/min", fs, ""),
        ("Bottles", f"{int(latest.get('bottle_count', 0))}", "info", ""),
        ("Heater", f"{latest.get('heater_power_cmd', 0):.0f} %", "info", ""),
    ]
    for col, (lb, vl, stt, sub) in zip(st.columns(6), kpis):
        col.markdown(kpi(lb, vl, stt, sub), unsafe_allow_html=True)

    # ── Quick stats ──
    st.markdown('<div class="section-title">📋  PRODUCTION SUMMARY</div>', unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Ticks", latest.get("tick", 0))
    c2.metric("PLC State", plc_state)
    c3.metric("Active Alarms", "1" if alarm_code else "0",
              delta="⚠" if alarm_code else "✓", delta_color="off" if alarm_code else "normal")
    c4.metric("Manual Overrides", len(engine.manual_overrides),
              delta="🖐" if engine.manual_overrides else "AUTO")

live_view()
