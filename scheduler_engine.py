"""
scheduler_engine.py
───────────────────
Core scheduling engine for the Bus Timetable Generator.

Responsibilities:
  1. Generate departure slots from variable-headway rules.
  2. Run Maximum-Utilization (MU) greedy bus packing across two terminals.
  3. Inject conditional meal breaks when a bus arrives at a terminal
     during or just before a break window (only if that terminal's toggle is True).
  4. Build per-fleet summary DataFrames with utilization metrics.

All time arithmetic uses pd.Timestamp / pd.Timedelta exclusively.
"""

import pandas as pd
from datetime import time as dt_time

# ── Reference date used to anchor all time-of-day Timestamps ────────────
BASE_DATE = pd.Timestamp("2026-01-01")


# ─────────────────────────── helpers ────────────────────────────────────

def time_to_timestamp(t):
    """Convert datetime.time | str 'HH:MM' | pd.Timestamp → pd.Timestamp on BASE_DATE."""
    if isinstance(t, pd.Timestamp):
        return t
    if isinstance(t, str):
        parts = t.strip().split(":")
        h, m = int(parts[0]), int(parts[1])
    elif isinstance(t, dt_time):
        h, m = t.hour, t.minute
    else:
        raise ValueError(f"Cannot convert {type(t)} to Timestamp")
    return pd.Timestamp(
        year=BASE_DATE.year, month=BASE_DATE.month, day=BASE_DATE.day,
        hour=h, minute=m,
    )


def format_timedelta(td):
    """Format a pd.Timedelta as 'HH:MM'."""
    total_seconds = int(td.total_seconds())
    h = total_seconds // 3600
    m = (total_seconds % 3600) // 60
    return f"{h:02d}:{m:02d}"


# ─────────────────────── headway lookup ─────────────────────────────────

def _parse_time(val):
    """Return datetime.time from str 'HH:MM' or datetime.time."""
    if isinstance(val, dt_time):
        return val
    parts = val.strip().split(":")
    return dt_time(int(parts[0]), int(parts[1]))


def get_headway_at(current_ts, headway_table):
    """Look up the headway (minutes) for *current_ts* from the headway table.

    Falls back to the last defined headway if no window matches.
    """
    ct = current_ts.time()
    for _, row in headway_table.iterrows():
        start = _parse_time(row["Start"])
        end = _parse_time(row["End"])
        if start <= ct < end:
            return int(row["Headway (min)"])
    # Fallback: use the last row's headway
    return int(headway_table.iloc[-1]["Headway (min)"])


# ──────────────────── departure-slot generation ─────────────────────────

def generate_departure_slots(first_start, last_end, headway_table):
    """Generate a list of pd.Timestamps for every departure at one terminal.

    Parameters
    ----------
    first_start : datetime.time | str
        First departure time-of-day.
    last_end : datetime.time | str
        No departure may be later than this time.
    headway_table : pd.DataFrame
        Columns: Start, End, Headway (min).

    Returns
    -------
    list[pd.Timestamp]
    """
    current = time_to_timestamp(first_start)
    end = time_to_timestamp(last_end)
    slots = []
    while current <= end:
        slots.append(current)
        hw = get_headway_at(current, headway_table)
        current = current + pd.Timedelta(minutes=hw)
    return slots


# ────────────────── break injection (proactive, two-case) ───────────────

def _compute_ready_and_break(arrival_ts, terminal_config, break_windows_df):
    """Compute a bus's ready-time at the arrival terminal, with optional break.

    Break injection logic (proactive, two-case):

    **Case 1 – Bus arrives DURING a break window:**
      arrival is in [window_start, window_end) and enough remaining
      window time for the break's minimum duration.
      effective_recovery = max(min_recovery, break_duration).
      ready = arrival + effective_recovery + loading.

    **Case 2 – Bus arrives BEFORE a window but recovery carries into it:**
      recovery_end is in [window_start, window_end).
      The break starts right after recovery (at or after window start).
      ready = break_end + loading.

    Only fires when the terminal's *break_provided* flag is True.
    The first matching break window (ordered by start time) wins.

    Returns
    -------
    (ready_time: pd.Timestamp, break_id: int | None, break_name: str)
    """
    min_rec = terminal_config["min_recovery"]
    loading = terminal_config["loading_time"]
    break_provided = terminal_config["break_provided"]

    if break_provided and not break_windows_df.empty:
        recovery_end = arrival_ts + pd.Timedelta(minutes=min_rec)

        for _, bw in break_windows_df.iterrows():
            bw_start = time_to_timestamp(bw["Start"])
            bw_end = time_to_timestamp(bw["End"])
            dur = int(bw["Min Duration (min)"])

            # Case 1: Bus arrives DURING the break window
            if arrival_ts >= bw_start and arrival_ts < bw_end:
                remaining_mins = (bw_end - arrival_ts).total_seconds() / 60
                if remaining_mins >= dur:
                    effective_rec = max(min_rec, dur)
                    ready = arrival_ts + pd.Timedelta(minutes=effective_rec) + pd.Timedelta(minutes=loading)
                    return ready, int(bw["ID"]), str(bw["Name"])

            # Case 2: Bus arrives BEFORE the window, but recovery ends inside it
            elif arrival_ts < bw_start and recovery_end >= bw_start and recovery_end < bw_end:
                break_start = max(recovery_end, bw_start)
                break_end_ts = break_start + pd.Timedelta(minutes=dur)
                if break_end_ts <= bw_end:
                    ready = break_end_ts + pd.Timedelta(minutes=loading)
                    return ready, int(bw["ID"]), str(bw["Name"])

    # Normal turnaround (no break)
    ready = arrival_ts + pd.Timedelta(minutes=min_rec) + pd.Timedelta(minutes=loading)
    return ready, None, ""


# ──────────────────── MU scheduler (main) ───────────────────────────────

def run_mu_scheduler(kdw_config, kdl_config, global_config, headway_table, break_windows):
    """Run the Maximum-Utilization greedy scheduler.

    Parameters
    ----------
    kdw_config, kdl_config : dict
        Keys: registered_buses, first_start, last_end, loading_time,
              min_recovery, max_duty, break_provided.
    global_config : dict
        Keys: travel_time (minutes).
    headway_table : pd.DataFrame
        Columns: Start, End, Headway (min).
    break_windows : pd.DataFrame
        Columns: ID, Name, Start, End, Min Duration (min), Color.

    Returns
    -------
    (timetable_df, kdw_summary_df, kdl_summary_df)
    """
    travel_time = global_config["travel_time"]

    # ── 1. Generate departure slots for each terminal ───────────────────
    kdw_slots = generate_departure_slots(
        kdw_config["first_start"], kdw_config["last_end"], headway_table,
    )
    kdl_slots = generate_departure_slots(
        kdl_config["first_start"], kdl_config["last_end"], headway_table,
    )

    # ── 2. Merge into a chronological event list ────────────────────────
    events = []
    for dep in kdw_slots:
        events.append({"dep": dep, "terminal": "KDW", "direction": "KDW→KDL"})
    for dep in kdl_slots:
        events.append({"dep": dep, "terminal": "KDL", "direction": "KDL→KDW"})
    events.sort(key=lambda e: (e["dep"], e["terminal"]))

    # ── 3. Initialise bus pools ─────────────────────────────────────────
    pools = {
        "KDW": [
            {"bus_code": f"KDW{i:02d}", "ready_time": BASE_DATE}
            for i in range(1, kdw_config["registered_buses"] + 1)
        ],
        "KDL": [
            {"bus_code": f"KDL{i:02d}", "ready_time": BASE_DATE}
            for i in range(1, kdl_config["registered_buses"] + 1)
        ],
    }
    configs = {"KDW": kdw_config, "KDL": kdl_config}
    opposite = {"KDW": "KDL", "KDL": "KDW"}
    adhoc_counter = {
        "KDW": kdw_config["registered_buses"],
        "KDL": kdl_config["registered_buses"],
    }

    # ── 4. Greedy assignment loop ───────────────────────────────────────
    trips = []
    trip_no = 0

    for ev in events:
        dep_time = ev["dep"]
        terminal = ev["terminal"]
        direction = ev["direction"]
        pool = pools[terminal]

        # Find available buses (ready_time <= departure_time)
        available = [b for b in pool if b["ready_time"] <= dep_time]

        if available:
            # Pick the bus that has been ready the longest (earliest ready_time)
            available.sort(key=lambda b: b["ready_time"])
            bus = available[0]
            pool.remove(bus)
        else:
            # Fleet auto-expansion: create an ad-hoc bus
            adhoc_counter[terminal] += 1
            bus = {
                "bus_code": f"{terminal}{adhoc_counter[terminal]:02d}",
                "ready_time": dep_time,
            }

        # Compute arrival at the opposite terminal
        arr_time = dep_time + pd.Timedelta(minutes=travel_time)
        arr_terminal = opposite[terminal]

        # Compute ready-time (with possible break injection) at arrival terminal
        ready, break_id, break_name = _compute_ready_and_break(
            arr_time, configs[arr_terminal], break_windows,
        )

        trip_no += 1
        trips.append({
            "Trip No": trip_no,
            "Direction": direction,
            "Bus Code": bus["bus_code"],
            "Departure": dep_time,
            "Arrival": arr_time,
            "Break ID": break_id,
            "Break Name": break_name,
        })

        # Insert bus into the arrival terminal's pool
        pools[arr_terminal].append({
            "bus_code": bus["bus_code"],
            "ready_time": ready,
        })

    # ── 5. Build output DataFrames ──────────────────────────────────────
    timetable_df = pd.DataFrame(trips)

    kdw_summary = _build_summary(timetable_df, "KDW", travel_time)
    kdl_summary = _build_summary(timetable_df, "KDL", travel_time)

    return timetable_df, kdw_summary, kdl_summary


# ─────────────────── summary-table builder ──────────────────────────────

def _build_summary(timetable_df, fleet_prefix, travel_time):
    """Build the summary dashboard table for one fleet (KDW or KDL).

    Columns produced:
        Run No, Bus Code, Trips D1, Trips D2, ST - D1, ST - D2,
        Tot ST, DT, ST/DT %, Total Trips, MealBreak Provided?
    """
    if timetable_df.empty:
        return pd.DataFrame()

    mask = timetable_df["Bus Code"].str.startswith(fleet_prefix)
    fleet_df = timetable_df[mask]
    if fleet_df.empty:
        return pd.DataFrame()

    rows = []
    for run_no, bus_code in enumerate(sorted(fleet_df["Bus Code"].unique()), start=1):
        bus_trips = fleet_df[fleet_df["Bus Code"] == bus_code]

        d1 = bus_trips[bus_trips["Direction"] == "KDW→KDL"]
        d2 = bus_trips[bus_trips["Direction"] == "KDL→KDW"]

        trips_d1 = len(d1)
        trips_d2 = len(d2)

        st_d1 = pd.Timedelta(minutes=travel_time * trips_d1)
        st_d2 = pd.Timedelta(minutes=travel_time * trips_d2)
        tot_st = st_d1 + st_d2

        first_dep = bus_trips["Departure"].min()
        last_arr = bus_trips["Arrival"].max()
        dt = last_arr - first_dep

        utilization = (tot_st / dt * 100) if dt.total_seconds() > 0 else 0.0

        # Unique break IDs this bus received (sorted, concatenated)
        break_ids = bus_trips["Break ID"].dropna().unique()
        breaks_str = "".join(str(int(b)) for b in sorted(break_ids)) or "None"

        rows.append({
            "Run No": run_no,
            "Bus Code": bus_code,
            "Trips D1": trips_d1,
            "Trips D2": trips_d2,
            "ST - D1": format_timedelta(st_d1),
            "ST - D2": format_timedelta(st_d2),
            "Tot ST": format_timedelta(tot_st),
            "DT": format_timedelta(dt),
            "ST/DT %": round(utilization, 1),
            "Total Trips": trips_d1 + trips_d2,
            "MealBreak Provided?": breaks_str,
        })

    return pd.DataFrame(rows)
