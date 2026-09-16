"""
ui_components.py
────────────────
Streamlit sidebar / configuration-section helpers.

Each function renders widgets and returns the collected values
as dicts or DataFrames consumed by the scheduling engine.
"""

import streamlit as st
import pandas as pd
from datetime import time


def get_terminal_config(name: str, defaults: dict) -> dict:
    """Render an expander for one terminal and return its configuration dict.

    Parameters
    ----------
    name : str
        Terminal short-code (e.g. "KDW" or "KDL").
    defaults : dict
        Default values.  Expected keys:
            registered_buses, first_start, last_end,
            loading_time, min_recovery, max_duty, break_provided.
    """
    with st.sidebar.expander(f"🚏  {name} Terminal Config", expanded=True):
        registered = st.number_input(
            "Registered Buses",
            min_value=1, max_value=50,
            value=defaults["registered_buses"],
            key=f"{name}_reg",
        )
        first_start = st.time_input(
            "First Trip Start Time",
            value=defaults["first_start"],
            key=f"{name}_first",
        )
        last_end = st.time_input(
            "Last Trip End Time",
            value=defaults["last_end"],
            key=f"{name}_last",
        )
        loading = st.number_input(
            "Loading Time (min)",
            min_value=0, max_value=60,
            value=defaults["loading_time"],
            key=f"{name}_load",
        )
        recovery = st.number_input(
            "Min Recovery Time (min)",
            min_value=0, max_value=60,
            value=defaults["min_recovery"],
            key=f"{name}_rec",
        )
        max_duty = st.number_input(
            "Max Duty Time (hrs)",
            min_value=1.0, max_value=24.0,
            value=defaults["max_duty"],
            step=0.5,
            key=f"{name}_duty",
        )
        break_provided = st.toggle(
            "Break Provided Here?",
            value=defaults["break_provided"],
            key=f"{name}_brk",
        )

    return {
        "registered_buses": registered,
        "first_start": first_start,
        "last_end": last_end,
        "loading_time": loading,
        "min_recovery": recovery,
        "max_duty": max_duty,
        "break_provided": break_provided,
    }


def get_global_config() -> dict:
    """Render global-variable inputs and return them as a dict."""
    with st.sidebar.expander("🌐  Global Variables", expanded=True):
        travel_time = st.number_input(
            "Base Travel Time (min)",
            min_value=1, max_value=180,
            value=24,
            key="global_travel",
        )
    return {"travel_time": travel_time}


def get_headway_table() -> pd.DataFrame:
    """Render an editable Variable-Headway table in the sidebar."""
    st.sidebar.markdown("### ⏱  Variable Headway")
    default_df = pd.DataFrame({
        "Start": ["05:00", "08:00", "14:00"],
        "End":   ["08:00", "14:00", "19:00"],
        "Headway (min)": [10, 15, 10],
    })
    edited = st.sidebar.data_editor(
        default_df,
        num_rows="dynamic",
        use_container_width=True,
        key="headway_editor",
    )
    return edited


def get_break_windows() -> pd.DataFrame:
    """Render an editable Break-Windows table in the sidebar."""
    st.sidebar.markdown("### 🍽  Break Windows")
    default_df = pd.DataFrame({
        "ID":               [1, 2, 3, 4, 5],
        "Name":             ["Breakfast", "Morning Tea", "Lunch", "Evening Tea", "Dinner"],
        "Start":            ["07:00", "09:00", "12:00", "15:00", "19:30"],
        "End":              ["09:00", "11:00", "14:30", "17:30", "22:00"],
        "Min Duration (min)": [20, 15, 30, 15, 30],
        "Color":            ["#CCFFFF", "#00CCFF", "#FFCC00", "#CC99FF", "#9999FF"],
    })
    edited = st.sidebar.data_editor(
        default_df,
        num_rows="dynamic",
        use_container_width=True,
        key="break_editor",
    )
    return edited
