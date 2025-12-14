# -*- coding: utf-8 -*-
"""Count Selected Features to Excel (ArcGIS Pro) - Improved

This Python Toolbox tool is designed for ArcGIS Pro (Python 3) and focuses on
one job: **log the current selection count** to an Excel (.xlsx) file quickly
and consistently.

Key improvements implemented:
  ✅ Auto-names the Excel file from the input layer name (optional override)
  ✅ Output is folder-based (simpler than browsing for a file each time)
  ✅ Append OR Overwrite modes
  ✅ Optional notes field
  ✅ Optional details columns (layer name + timestamp)
  ✅ Robust "count selection" logic using Describe(layer).FIDSet (Pro-safe)
  ✅ Excel-locked fallback: writes a timestamped _LOCKED copy instead of failing
  ✅ Writes from the first cell (A1) (no blank first row)

Excel layout (default "simple" mode):
  Column A: RowN
  Column B: SelectedCount

If "Include details" is enabled:
  Column C: Notes
  Column D: LayerName
  Column E: Timestamp
"""

import os
import re
import datetime

import arcpy

# ArcGIS Pro's default environment usually includes openpyxl.
# If it doesn't, install it from ArcGIS Pro > Package Manager.
import openpyxl


# ---------------------------------------------------------------------------
# Excel helper functions
# ---------------------------------------------------------------------------

def _compact_blank_first_row(ws, cols_to_check=5):
    """If row 1 is empty but row 2 has data, delete row 1.

    Why?
      openpyxl initializes a new sheet with an "empty" row 1.
      If you use ws.append(...) right away, openpyxl can start writing at row 2.
      We want A1 to be our first record.
    """
    if ws.max_row < 2:
        return

    row1_empty = True
    row2_has_data = False
    for c in range(1, cols_to_check + 1):
        if ws.cell(1, c).value is not None:
            row1_empty = False
            break
    for c in range(1, cols_to_check + 1):
        if ws.cell(2, c).value is not None:
            row2_has_data = True
            break

    if row1_empty and row2_has_data:
        ws.delete_rows(1, 1)


def _find_last_data_row(ws, cols_to_check=5):
    """Return the last row index that contains any data (in the first N columns)."""
    for r in range(ws.max_row, 0, -1):
        for c in range(1, cols_to_check + 1):
            if ws.cell(r, c).value is not None:
                return r
    return 0


def _get_next_row_number(ws):
    """Return the next RowN number.

    We look for labels like Row1, Row2, ... in column A.
    If found, we continue from the maximum.
    Otherwise, we fall back to the last used row.
    """
    max_n = 0
    for r in range(1, ws.max_row + 1):
        a = ws.cell(r, 1).value
        if isinstance(a, str):
            m = re.match(r"^Row\s*(\d+)$", a.strip(), flags=re.IGNORECASE)
            if m:
                max_n = max(max_n, int(m.group(1)))

    if max_n > 0:
        return max_n + 1

    last_data = _find_last_data_row(ws)
    return (last_data + 1) if last_data else 1


def _sanitize_filename(name: str) -> str:
    """Make a Windows-safe filename from a layer name."""
    if not name:
        return "selection_log"

    # Replace forbidden characters: \ / : * ? " < > |
    safe = re.sub(r"[\\/:\*\?\"<>\|]", "_", name)
    safe = safe.strip().strip(".")
    return safe or "selection_log"


def _open_or_create_workbook(xlsx_path: str, sheet_name: str):
    """Open workbook if exists; else create. Always returns (wb, ws)."""
    if os.path.exists(xlsx_path):
        wb = openpyxl.load_workbook(xlsx_path)
        ws = wb[sheet_name] if sheet_name in wb.sheetnames else wb.create_sheet(sheet_name)
    else:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = sheet_name
    return wb, ws


def _safe_save_workbook(wb, target_path: str):
    """Save workbook. If locked, save to a timestamped _LOCKED file instead."""
    try:
        wb.save(target_path)
        return target_path
    except PermissionError:
        # Excel is probably open/locked.
        folder = os.path.dirname(target_path)
        base, ext = os.path.splitext(os.path.basename(target_path))
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        alt_path = os.path.join(folder, f"{base}_LOCKED_{ts}{ext}")
        wb.save(alt_path)
        return alt_path


# ---------------------------------------------------------------------------
# ArcGIS Pro selection helpers
# ---------------------------------------------------------------------------

def _get_active_map():
    """Return the active map from the CURRENT ArcGIS Pro project."""
    aprx = arcpy.mp.ArcGISProject("CURRENT")
    m = getattr(aprx, "activeMap", None)
    if m is not None:
        return m

    maps = aprx.listMaps()
    if not maps:
        raise RuntimeError("No maps found in the current ArcGIS Pro project.")
    return maps[0]


def _iter_layers(map_obj):
    """Yield layers recursively (including group layer sublayers)."""
    for lyr in map_obj.listLayers():
        yield lyr
        if lyr.isGroupLayer:
            for sub in lyr.listLayers():
                yield sub


def _selected_count_from_layer(layer_obj) -> int:
    """Count the current selection on a *layer object* (Pro-safe).

    Uses Describe(layer).FIDSet which is a semicolon-separated list of selected OIDs.
    """
    desc = arcpy.Describe(layer_obj)
    fidset = getattr(desc, "FIDSet", "")
    if not fidset:
        return 0
    parts = [p.strip() for p in str(fidset).replace(",", ";").split(";") if p.strip()]
    return len(parts)


def _auto_find_layer_with_selection():
    """Find the first feature layer in the active map with a non-zero selection."""
    m = _get_active_map()
    candidates = []

    for lyr in _iter_layers(m):
        try:
            if not lyr.isFeatureLayer:
                continue
            cnt = _selected_count_from_layer(lyr)
            if cnt > 0:
                candidates.append((lyr, cnt))
        except Exception:
            continue

    if not candidates:
        raise RuntimeError("No feature layer with a selection was found in the active map.")

    # If multiple layers have selections, we pick the first and warn.
    if len(candidates) > 1:
        names = ", ".join([c[0].name for c in candidates])
        arcpy.AddWarning(f"Multiple layers have selections. Using the first. Candidates: {names}")

    return candidates[0]  # (layer, count)


# ---------------------------------------------------------------------------
# Python Toolbox definitions
# ---------------------------------------------------------------------------

class Toolbox(object):
    def __init__(self):
        self.label = "Count Selected Features to Excel Toolbox (Improved)"
        self.alias = "CountSelectedToExcel_Improved"
        self.tools = [CountSelectedToExcel]


class CountSelectedToExcel(object):
    def __init__(self):
        self.label = "Count Selected Features to Excel"
        self.description = "Logs the count of currently selected features to Excel (.xlsx)."
        self.canRunInBackground = False

    def getParameterInfo(self):
        """Define GP tool parameters."""

        p_input = arcpy.Parameter(
            displayName="Input Layer (optional - auto-detect selection if empty)",
            name="input_layer",
            datatype="GPFeatureLayer",
            parameterType="Optional",
            direction="Input"
        )

        p_out_folder = arcpy.Parameter(
            displayName="Output Folder",
            name="output_folder",
            datatype="DEFolder",
            parameterType="Required",
            direction="Input"
        )
        # Default to Desktop for convenience.
        p_out_folder.value = os.path.join(os.path.expanduser("~"), "Desktop")

        p_filename = arcpy.Parameter(
            displayName="Excel File Name (optional, .xlsx)",
            name="excel_filename",
            datatype="GPString",
            parameterType="Optional",
            direction="Input"
        )

        p_append = arcpy.Parameter(
            displayName="Append to existing Excel file?",
            name="append_mode",
            datatype="GPBoolean",
            parameterType="Required",
            direction="Input"
        )
        p_append.value = True

        p_notes = arcpy.Parameter(
            displayName="Notes (optional)",
            name="notes",
            datatype="GPString",
            parameterType="Optional",
            direction="Input"
        )

        p_details = arcpy.Parameter(
            displayName="Include details columns (Notes/Layer/Timestamp)",
            name="include_details",
            datatype="GPBoolean",
            parameterType="Required",
            direction="Input"
        )
        # Default OFF to keep the sheet simple (Row + Count).
        p_details.value = False

        return [p_input, p_out_folder, p_filename, p_append, p_notes, p_details]

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        """Auto-suggest filename based on the selected input layer."""

        # Only suggest if the user hasn't typed a custom name.
        p_input = parameters[0]
        p_filename = parameters[2]

        if p_input.value and not p_filename.altered:
            try:
                desc = arcpy.Describe(p_input.value)
                layer_name = getattr(desc, "name", None) or getattr(p_input.value, "name", None)
                safe = _sanitize_filename(layer_name)
                p_filename.value = f"{safe}.xlsx"
            except Exception:
                # If we can't read the name, don't block the tool.
                pass

    def updateMessages(self, parameters):
        """User-friendly warnings (non-blocking)."""
        p_out_folder = parameters[1]
        p_filename = parameters[2]

        # Light validation: remind user about .xlsx extension.
        if p_filename.valueAsText:
            fn = p_filename.valueAsText.strip()
            if fn and not fn.lower().endswith(".xlsx"):
                p_filename.setWarningMessage("Filename does not end with .xlsx. It will be added automatically.")

        # Folder must exist or be creatable.
        if p_out_folder.valueAsText:
            folder = p_out_folder.valueAsText
            if folder and not os.path.exists(folder):
                p_out_folder.setWarningMessage("Folder does not exist yet. The tool will create it.")

    def execute(self, parameters, messages):
        """Main execution."""

        # Parameters
        input_layer_obj = parameters[0].value  # may be None
        out_folder = parameters[1].valueAsText
        filename = (parameters[2].valueAsText or "").strip()
        append_mode = bool(parameters[3].value)
        notes = (parameters[4].valueAsText or "").strip()
        include_details = bool(parameters[5].value)

        if not out_folder:
            raise RuntimeError("Output Folder is required.")

        # Create output folder if missing
        os.makedirs(out_folder, exist_ok=True)

        # Resolve layer + selection count
        if input_layer_obj is None:
            arcpy.AddMessage("No input layer provided. Auto-detecting the first layer with a selection...")
            input_layer_obj, selected_count = _auto_find_layer_with_selection()
        else:
            # IMPORTANT: use .value (layer object) to preserve selection.
            selected_count = _selected_count_from_layer(input_layer_obj)

        # Layer name for filename + logging
        try:
            desc = arcpy.Describe(input_layer_obj)
            layer_name = getattr(desc, "name", None) or getattr(input_layer_obj, "name", "(unknown)")
        except Exception:
            layer_name = getattr(input_layer_obj, "name", "(unknown)")

        arcpy.AddMessage(f"Layer: {layer_name}")
        arcpy.AddMessage(f"Selected Features Count: {selected_count}")
        if selected_count == 0:
            arcpy.AddWarning("Selection count is 0. (Either nothing is selected, or the input is not the selected layer.)")

        # Build output filename
        if not filename:
            filename = f"{_sanitize_filename(layer_name)}.xlsx"
        elif not filename.lower().endswith(".xlsx"):
            filename = f"{filename}.xlsx"

        xlsx_path = os.path.join(out_folder, filename)

        # Excel logging settings
        sheet_name = "Counts"
        timestamp_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Overwrite mode: start a fresh workbook
        if not append_mode and os.path.exists(xlsx_path):
            arcpy.AddMessage("Overwrite mode enabled: creating a fresh workbook...")
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = sheet_name
        else:
            wb, ws = _open_or_create_workbook(xlsx_path, sheet_name)

        # Fix the "blank first row" issue (and any existing sheet affected by it)
        _compact_blank_first_row(ws)

        # Compute next row + RowN label
        last_row = _find_last_data_row(ws)
        next_row = (last_row + 1) if last_row else 1
        row_n = _get_next_row_number(ws)

        # Always write Row + Count (A/B)
        ws.cell(row=next_row, column=1).value = f"Row{row_n}"
        ws.cell(row=next_row, column=2).value = int(selected_count)

        # Optional details columns
        if include_details:
            ws.cell(row=next_row, column=3).value = notes
            ws.cell(row=next_row, column=4).value = layer_name
            ws.cell(row=next_row, column=5).value = timestamp_str
        else:
            # If details disabled but user typed notes, still store notes in column C
            # (this does NOT change your A/B workflow, but preserves important context)
            if notes:
                ws.cell(row=next_row, column=3).value = notes

        # Save with lock-safe behavior
        saved_path = _safe_save_workbook(wb, xlsx_path)
        if saved_path != xlsx_path:
            arcpy.AddWarning(
                "Excel file appears locked (likely open in Excel). "
                f"Saved to an alternate file instead: {saved_path}"
            )

        arcpy.AddMessage(f"Logged: Row{row_n} = {selected_count}")
        arcpy.AddMessage(f"Excel output: {saved_path}")
