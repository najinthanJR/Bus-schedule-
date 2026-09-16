"""
app.py
──────
Streamlit entry-point for the Bus Scheduling & Timetable Generator.

Layout:
    Sidebar  → configuration inputs (terminals, headway, breaks)
    Main     → Generate button, metrics, timetable tabs, fleet summaries,
               Excel download
"""

import streamlit as st
import pandas as pd
from datetime import time

from ui_components import (
    get_terminal_config,
    get_global_config,
    get_headway_table,
    get_break_windows,
)
from scheduler_engine import run_mu_scheduler
from excel_export import export_to_excel

# ─────────────────────── page config ────────────────────────────────────
st.set_page_config(
    page_title="Bus Schedule Generator",
    page_icon="🚌",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────── custom CSS ─────────────────────────────────────
st.markdown("""
<style>
    /* Sidebar polish */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #1a1a2e 0%, #16213e 100%);
    }
    [data-testid="stSidebar"] * {
        color: #e0e0e0 !important;
    }
    [data-testid="stSidebar"] .stNumberInput label,
    [data-testid="stSidebar"] .stTimeInput label,
    [data-testid="stSidebar"] .stToggle label {
        font-weight: 500;
    }

    /* Metric cards */
    [data-testid="stMetric"] {
        background: linear-gradient(135deg, #0f3460 0%, #533483 100%);
        border-radius: 12px;
        padding: 16px 20px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.2);
    }
    [data-testid="stMetric"] label {
        color: #b0b0d0 !important;
        font-size: 0.85rem !important;
    }
    [data-testid="stMetric"] [data-testid="stMetricValue"] {
        color: #ffffff !important;
        font-size: 1.8rem !important;
        font-weight: 700 !important;
    }

    /* Header styling */
    .main-header {
        background: linear-gradient(135deg, #0f3460, #533483);
        padding: 24px 32px;
        border-radius: 12px;
        margin-bottom: 24px;
        color: white;
    }
    .main-header h1 {
        margin: 0;
        font-size: 2rem;
        letter-spacing: -0.5px;
    }
    .main-header p {
        margin: 4px 0 0 0;
        opacity: 0.8;
        font-size: 1rem;
    }

    /* Tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 8px 8px 0 0;
        padding: 8px 20px;
    }
</style>
""", unsafe_allow_html=True)

# ─────────────────────── header ─────────────────────────────────────────
st.markdown("""
<div class="main-header">
    <h1>🚌 Bus Scheduling & Timetable Generator</h1>
    <p>Maximum-Utilization Greedy Packing &nbsp;•&nbsp; KDW ↔ KDL Two-Way Timetable</p>
</div>
""", unsafe_allow_html=True)

# ─────────────────────── sidebar inputs ─────────────────────────────────
st.sidebar.markdown("## ⚙️  Configuration")

KDW_DEFAULTS = {
    "registered_buses": 3,
    "first_start": time(6, 15),
    "last_end": time(18, 25),
    "loading_time": 10,
    "min_recovery": 10,
    "max_duty": 12.0,
    "break_provided": True,
}
KDL_DEFAULTS = {
    "registered_buses": 6,
    "first_start": time(5, 25),
    "last_end": time(17, 45),
    "loading_time": 10,
    "min_recovery": 10,
    "max_duty": 12.0,
    "break_provided": False,
}

kdw_config = get_terminal_config("KDW", KDW_DEFAULTS)
kdl_config = get_terminal_config("KDL", KDL_DEFAULTS)
global_config = get_global_config()
headway_table = get_headway_table()
break_windows = get_break_windows()

# ─────────────────────── generate button ────────────────────────────────
st.sidebar.markdown("---")
generate = st.sidebar.button(
    "🚀  Generate Schedule",
    type="primary",
    use_container_width=True,
)

if generate:
    with st.spinner("⏳ Running MU scheduler …"):
        tt_df, kdw_sum, kdl_sum = run_mu_scheduler(
            kdw_config, kdl_config, global_config, headway_table, break_windows,
        )
    st.session_state["timetable"] = tt_df
    st.session_state["kdw_summary"] = kdw_sum
    st.session_state["kdl_summary"] = kdl_sum
    st.session_state["break_windows"] = break_windows.copy()
    st.toast("✅ Schedule generated!", icon="🎉")

# ─────────────────────── display results ────────────────────────────────
if "timetable" in st.session_state:
    tt_df = st.session_state["timetable"]
    kdw_sum = st.session_state["kdw_summary"]
    kdl_sum = st.session_state["kdl_summary"]
    bw_saved = st.session_state["break_windows"]

    # ── colour map for break rows ───────────────────────────────────────
    color_map = {}
    for _, bw in bw_saved.iterrows():
        color_map[int(bw["ID"])] = str(bw["Color"])

    # ── metrics row ─────────────────────────────────────────────────────
    def _avg_util(summary_df):
        if summary_df.empty:
            return 0.0
        return summary_df["ST/DT %"].mean()

    dir1_count = len(tt_df[tt_df["Direction"] == "KDW→KDL"])
    dir2_count = len(tt_df[tt_df["Direction"] == "KDL→KDW"])
    total_buses = len(tt_df["Bus Code"].unique())
    avg_kdw = _avg_util(kdw_sum)
    avg_kdl = _avg_util(kdl_sum)
    overall_avg = (avg_kdw + avg_kdl) / 2 if (avg_kdw + avg_kdl) > 0 else 0

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Total Trips", f"{len(tt_df)}")
    m2.metric("Dir 1 Trips", f"{dir1_count}")
    m3.metric("Dir 2 Trips", f"{dir2_count}")
    m4.metric("Buses Used", f"{total_buses}")
    m5.metric("Avg Fleet Util.", f"{overall_avg:.1f}%")

    # ── prepare display DataFrame ───────────────────────────────────────
    def _display_df(df):
        """Convert Timestamps → HH:MM strings and clean Break ID."""
        d = df.copy()
        d["Departure"] = d["Departure"].dt.strftime("%H:%M")
        d["Arrival"] = d["Arrival"].dt.strftime("%H:%M")
        d["Break ID"] = d["Break ID"].apply(
            lambda x: str(int(x)) if pd.notna(x) else ""
        )
        return d

    def _style_breaks(df, cmap):
        """Return a pandas Styler that highlights break rows."""
        def _highlight(row):
            bid_str = str(row["Break ID"]).strip()
            if bid_str and bid_str.isdigit():
                bid = int(bid_str)
                if bid in cmap:
                    return [f"background-color: {cmap[bid]}; color: #1a1a1a"] * len(row)
            return [""] * len(row)

        return df.style.apply(_highlight, axis=1)

    display_all = _display_df(tt_df)

    # ── timetable tabs ──────────────────────────────────────────────────
    st.markdown("### 📋  Timetable")
    tab_all, tab_d1, tab_d2 = st.tabs([
        "All Trips", "➡️ Dir 1 (KDW→KDL)", "⬅️ Dir 2 (KDL→KDW)",
    ])

    with tab_all:
        st.dataframe(
            _style_breaks(display_all, color_map),
            use_container_width=True,
            height=500,
        )

    with tab_d1:
        d1_df = display_all[display_all["Direction"] == "KDW→KDL"].reset_index(drop=True)
        st.dataframe(
            _style_breaks(d1_df, color_map),
            use_container_width=True,
            height=500,
        )

    with tab_d2:
        d2_df = display_all[display_all["Direction"] == "KDL→KDW"].reset_index(drop=True)
        st.dataframe(
            _style_breaks(d2_df, color_map),
            use_container_width=True,
            height=500,
        )

    # ── fleet summary tables ────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 📊  Fleet Summary Dashboards")

    col_kdw, col_kdl = st.columns(2)

    with col_kdw:
        st.markdown(f"**KDW Fleet** &nbsp;•&nbsp; Avg Utilization: `{avg_kdw:.1f}%`")
        if not kdw_sum.empty:
            display_kdw = kdw_sum.copy()
            display_kdw["ST/DT %"] = display_kdw["ST/DT %"].apply(lambda x: f"{x:.1f}%")
            st.dataframe(display_kdw, use_container_width=True, hide_index=True)
        else:
            st.info("No KDW buses were used.")

    with col_kdl:
        st.markdown(f"**KDL Fleet** &nbsp;•&nbsp; Avg Utilization: `{avg_kdl:.1f}%`")
        if not kdl_sum.empty:
            display_kdl = kdl_sum.copy()
            display_kdl["ST/DT %"] = display_kdl["ST/DT %"].apply(lambda x: f"{x:.1f}%")
            st.dataframe(display_kdl, use_container_width=True, hide_index=True)
        else:
            st.info("No KDL buses were used.")

    # ── Excel export ────────────────────────────────────────────────────
    st.markdown("---")
    excel_buf = export_to_excel(tt_df, kdw_sum, kdl_sum, bw_saved)
    st.download_button(
        label="📥  Export to Excel",
        data=excel_buf,
        file_name="bus_schedule.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
    )

else:
    # ── empty-state placeholder ─────────────────────────────────────────
    st.markdown("---")
    col_l, col_c, col_r = st.columns([1, 2, 1])
    with col_c:
        st.markdown(
            """
            <div style="text-align:center; padding: 60px 20px; opacity: 0.6;">
                <p style="font-size: 3rem;">🚌</p>
                <p style="font-size: 1.1rem;">
                    Configure the sidebar and click <strong>Generate Schedule</strong>
                    to build your timetable.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
