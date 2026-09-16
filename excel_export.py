"""
excel_export.py
───────────────
Formatted Excel export via openpyxl.

Creates a three-sheet workbook:
    • Timetable       – every trip row, break-rows colour-coded
    • KDW Summary     – fleet summary for KDW buses
    • KDL Summary     – fleet summary for KDL buses

Break-row colouring uses PatternFill mapped from the Break Windows
colour table.
"""

import io
import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter


def export_to_excel(timetable_df, kdw_summary, kdl_summary, break_windows):
    """Build an in-memory Excel workbook and return a BytesIO buffer.

    Parameters
    ----------
    timetable_df : pd.DataFrame
        Raw timetable from the scheduler (Timestamps in Departure / Arrival).
    kdw_summary, kdl_summary : pd.DataFrame
        Summary tables (already display-formatted strings).
    break_windows : pd.DataFrame
        Break-window config (needs 'ID' and 'Color' columns).

    Returns
    -------
    io.BytesIO
        Ready-to-download Excel file buffer.
    """
    # ── 1. Prepare display-friendly copy of the timetable ───────────────
    display_tt = timetable_df.copy()
    display_tt["Departure"] = display_tt["Departure"].dt.strftime("%H:%M")
    display_tt["Arrival"] = display_tt["Arrival"].dt.strftime("%H:%M")
    # Break ID → int string or blank
    display_tt["Break ID"] = display_tt["Break ID"].apply(
        lambda x: str(int(x)) if pd.notna(x) else ""
    )

    # Format ST/DT % in summary tables
    kdw_sum_display = _format_summary_for_excel(kdw_summary)
    kdl_sum_display = _format_summary_for_excel(kdl_summary)

    # ── 2. Write to buffer with pandas ExcelWriter ──────────────────────
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        display_tt.to_excel(writer, sheet_name="Timetable", index=False)
        if not kdw_sum_display.empty:
            kdw_sum_display.to_excel(writer, sheet_name="KDW Summary", index=False)
        if not kdl_sum_display.empty:
            kdl_sum_display.to_excel(writer, sheet_name="KDL Summary", index=False)

    # ── 3. Re-open with openpyxl for formatting ────────────────────────
    buf.seek(0)
    wb = load_workbook(buf)

    # Build Break-ID → hex-colour map (strip '#' for openpyxl)
    color_map = {}
    for _, bw in break_windows.iterrows():
        bid = str(int(bw["ID"]))
        color_map[bid] = str(bw["Color"]).lstrip("#")

    # ── 3a. Format Timetable sheet ──────────────────────────────────────
    _format_timetable_sheet(wb["Timetable"], color_map)

    # ── 3b. Format summary sheets ──────────────────────────────────────
    for name in ("KDW Summary", "KDL Summary"):
        if name in wb.sheetnames:
            _format_summary_sheet(wb[name])

    # ── 4. Save to a fresh buffer and return ────────────────────────────
    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    return out


# ──────────────────── internal helpers ──────────────────────────────────

def _format_summary_for_excel(summary_df):
    """Return a display-ready copy of a summary DataFrame."""
    if summary_df.empty:
        return summary_df.copy()
    df = summary_df.copy()
    df["ST/DT %"] = df["ST/DT %"].apply(lambda x: f"{x:.1f}%")
    return df


def _format_timetable_sheet(ws, color_map):
    """Apply header styling, break-row colouring, and auto-widths."""
    header_font = Font(bold=True, size=11)
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_font_white = Font(bold=True, size=11, color="FFFFFF")
    thin_border = Border(
        left=Side(style="thin"),
        right=Side(style="thin"),
        top=Side(style="thin"),
        bottom=Side(style="thin"),
    )

    # Header row
    for cell in ws[1]:
        cell.font = header_font_white
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")
        cell.border = thin_border

    # Locate the Break ID column index (1-based)
    break_id_col = None
    for idx, cell in enumerate(ws[1], start=1):
        if cell.value == "Break ID":
            break_id_col = idx
            break

    # Data rows: apply break colour + borders
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
        for cell in row:
            cell.border = thin_border
            cell.alignment = Alignment(horizontal="center")

        if break_id_col:
            bid_value = str(row[break_id_col - 1].value or "").strip()
            if bid_value and bid_value in color_map:
                fill = PatternFill(
                    start_color=color_map[bid_value],
                    end_color=color_map[bid_value],
                    fill_type="solid",
                )
                for cell in row:
                    cell.fill = fill

    # Auto-width columns
    _auto_width(ws)


def _format_summary_sheet(ws):
    """Apply header styling and auto-widths to a summary sheet."""
    header_font = Font(bold=True, size=11, color="FFFFFF")
    header_fill = PatternFill(start_color="2E75B6", end_color="2E75B6", fill_type="solid")
    thin_border = Border(
        left=Side(style="thin"),
        right=Side(style="thin"),
        top=Side(style="thin"),
        bottom=Side(style="thin"),
    )

    for cell in ws[1]:
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")
        cell.border = thin_border

    for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
        for cell in row:
            cell.border = thin_border
            cell.alignment = Alignment(horizontal="center")

    _auto_width(ws)


def _auto_width(ws):
    """Set each column width to fit its widest cell value."""
    for col_cells in ws.columns:
        col_letter = get_column_letter(col_cells[0].column)
        max_len = max(
            (len(str(cell.value)) for cell in col_cells if cell.value is not None),
            default=8,
        )
        ws.column_dimensions[col_letter].width = max_len + 4
