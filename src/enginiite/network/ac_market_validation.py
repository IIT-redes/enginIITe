"""Nonlinear AC verification helpers for sensitivity-based market clearing.

"""

from __future__ import annotations

import os
import re
import shutil
import stat

import numpy as np
import pandas as pd


FSP_TYPES = ("A", "B", "C", "D")


def stage_label(_iteration):
    """Return the name of one market stage, used in folders and figure names.

    A scenario can be cleared several times; every stage-aware artefact carries
    this label, so a sensitivity figure says whether it describes the
    linearisation the main market cleared on or the one a corrective market was
    rebuilt on, and no stage overwrites another.

        iteration 0 -> main_market
        iteration 1 -> corrective_market_01
        iteration n -> corrective_market_nn
    """
    iteration = int(_iteration)
    if iteration <= 0:
        return "main_market"
    return f"corrective_market_{iteration:02d}"


def _numeric_market_sheet(_path, _sheet_name):
    """Read one market-result matrix as numeric data with string labels."""
    if not _path or not os.path.isfile(_path):
        return pd.DataFrame()
    try:
        frame = pd.read_excel(_path, sheet_name=_sheet_name, index_col=0)
    except Exception:
        return pd.DataFrame()
    frame = frame.copy()
    frame.index = [str(index) for index in frame.index]
    frame.columns = [str(column) for column in frame.columns]
    return frame.apply(pd.to_numeric, errors="coerce").fillna(0.0)


def _align_like(_frame, _template):
    frame = _frame.copy()
    frame.index = [str(index) for index in frame.index]
    frame.columns = [str(column) for column in frame.columns]
    template = _template.copy()
    template.index = [str(index) for index in template.index]
    template.columns = [str(column) for column in template.columns]
    return frame.reindex(index=template.index, columns=template.columns).fillna(0.0)


def activation_reversal_summary(_cumulative_frames):
    """Separate sequential cumulative activation into net, gross and reversal.

    The market workbook saved after a corrective pass is cumulative. For plots
    and scientific reporting the meaningful volume is therefore the sum of the
    absolute stage increments, not ``abs(final cumulative activation)``.
    """
    cumulative_frames = [
        frame.copy() for frame in _cumulative_frames
        if frame is not None and not getattr(frame, "empty", True)
    ]
    if not cumulative_frames:
        return {
            "incremental": [],
            "final_net": pd.DataFrame(),
            "gross": pd.DataFrame(),
            "reversal": pd.DataFrame(),
            "summary": {
                "final_net_abs_total": 0.0,
                "gross_total": 0.0,
                "reversal_total": 0.0,
            },
        }

    incremental = []
    previous = None
    for cumulative in cumulative_frames:
        cumulative = cumulative.apply(pd.to_numeric, errors="coerce").fillna(0.0)
        cumulative.index = [str(index) for index in cumulative.index]
        cumulative.columns = [str(column) for column in cumulative.columns]
        if previous is None:
            delta = cumulative.copy()
        else:
            delta = cumulative - _align_like(previous, cumulative)
        incremental.append(delta)
        previous = cumulative

    final_net = cumulative_frames[-1].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    gross = None
    for delta in incremental:
        term = delta.abs()
        gross = term if gross is None else gross.add(term, fill_value=0.0)
    gross = gross if gross is not None else pd.DataFrame()
    final_aligned = _align_like(final_net, gross) if not gross.empty else final_net
    reversal = (gross - final_aligned.abs()).clip(lower=0.0) / 2.0 if not gross.empty else pd.DataFrame()
    return {
        "incremental": incremental,
        "final_net": final_net,
        "gross": gross,
        "reversal": reversal,
        "summary": {
            "final_net_abs_total": float(final_aligned.abs().sum().sum()) if not final_aligned.empty else 0.0,
            "gross_total": float(gross.sum().sum()) if not gross.empty else 0.0,
            "reversal_total": float(reversal.sum().sum()) if not reversal.empty else 0.0,
        },
    }


def sequential_market_activation_summary(_market_result_files, _fsp_types=FSP_TYPES):
    """Build long activation tables for initial and corrective market stages."""
    files = [str(path) for path in _market_result_files if path and os.path.isfile(path)]
    stage_rows = []
    summary_rows = []
    for quantity, unit in (("DW", "MW"), ("DR", "MVAr")):
        for fsp_type in _fsp_types:
            sheet_name = f"{quantity}_{fsp_type}"
            cumulative = [_numeric_market_sheet(path, sheet_name) for path in files]
            metrics = activation_reversal_summary(cumulative)
            for stage_index, delta in enumerate(metrics["incremental"]):
                stage_rows.append({
                    "quantity": quantity,
                    "unit": unit,
                    "fsp_type": fsp_type,
                    "stage": stage_index,
                    "stage_name": "initial" if stage_index == 0 else f"corrective_{stage_index:02d}",
                    "incremental_net": float(delta.sum().sum()) if not delta.empty else 0.0,
                    "incremental_abs": float(delta.abs().sum().sum()) if not delta.empty else 0.0,
                })
            summary_rows.append({
                "quantity": quantity,
                "unit": unit,
                "fsp_type": fsp_type,
                **metrics["summary"],
            })
    return pd.DataFrame(stage_rows), pd.DataFrame(summary_rows)


def _named_loading_frame(_net, _ts_res):
    """Return all available branch loading results with physical asset names."""
    frames = []
    specifications = (
        ("line_loading_percent", "line"),
        ("trafo_loading_percent", "trafo"),
        ("trafo3w_loading_percent", "trafo3w"),
    )
    for result_key, table_name in specifications:
        frame = _ts_res.get(result_key)
        table = getattr(_net, table_name, None)
        if frame is None or table is None or frame.empty or table.empty:
            continue
        named = frame.copy()
        rename = {}
        for column in named.columns:
            try:
                element_index = int(column)
            except (TypeError, ValueError):
                continue
            if element_index in table.index:
                rename[column] = str(table.loc[element_index, "name"])
        frames.append(named.rename(columns=rename))
    if not frames:
        return pd.DataFrame()
    # Asset names are expected to be unique. If a legacy network reuses a name,
    # retain the worst loading because that is the conservative AC check.
    merged = pd.concat(frames, axis=1)
    if merged.columns.duplicated().any():
        merged = merged.T.groupby(level=0).max().T
    return merged


def physical_security_summary(_net, _ts_res, _vmin, _vmax, _loading_limit=100.0):
    """Summarize physical violations in the nonlinear post-market AC result."""
    loading = _named_loading_frame(_net, _ts_res)
    voltage = _ts_res.get("bus_vm_pu", pd.DataFrame())
    overload = loading.sub(float(_loading_limit)).clip(lower=0.0)
    under = float(_vmin) - voltage
    over = voltage - float(_vmax)
    voltage_residual = pd.concat(
        [under.clip(lower=0.0), over.clip(lower=0.0)], axis=0
    )
    return {
        "max_loading_percent": float(loading.max().max()) if not loading.empty else np.nan,
        "overload_cell_count": int((overload > 0.0).sum().sum()) if not overload.empty else 0,
        "max_overload_percentage_points": float(overload.max().max()) if not overload.empty else 0.0,
        "min_voltage_pu": float(voltage.min().min()) if not voltage.empty else np.nan,
        "max_voltage_pu": float(voltage.max().max()) if not voltage.empty else np.nan,
        "voltage_violation_cell_count": int(
            ((voltage < float(_vmin)) | (voltage > float(_vmax))).sum().sum()
        ) if not voltage.empty else 0,
        "max_voltage_violation_pu": float(voltage_residual.max().max())
        if not voltage_residual.empty
        else 0.0,
        "loading_by_name": loading,
        "voltage": voltage,
    }


def operating_point_market_state(_summary, _smax, _hours, _loading_limit=100.0):
    """Build CM inputs anchored at the latest nonlinear AC operating point.

    The physical threshold is not relaxed here. ``s_init`` is the apparent
    power represented by the AC loading result, while ``cong_needs`` is the
    residual above the unchanged physical loading limit.
    """
    smax_series = (
        _smax.iloc[:, 0].astype(float)
        if isinstance(_smax, pd.DataFrame)
        else pd.Series(_smax, dtype=float)
    )
    loading = _summary["loading_by_name"].reindex(
        index=list(_hours), columns=smax_series.index
    )
    if loading.isna().any().any():
        missing_columns = loading.columns[loading.isna().any(axis=0)].tolist()
        raise KeyError(
            "Nonlinear AC loading results are missing for represented assets: "
            + ", ".join(map(str, missing_columns))
        )
    s_init = loading.div(100.0).mul(smax_series, axis=1).T
    cong_needs = (
        loading.sub(float(_loading_limit)).clip(lower=0.0)
        .div(100.0).mul(smax_series, axis=1).T
    )
    congested_hours = [
        hour for hour in _hours
        if hour in cong_needs.columns and bool((cong_needs[hour] > 0.0).any())
    ]
    return {
        "s_init": s_init,
        "cong_needs": cong_needs,
        "congested_hours": congested_hours,
    }


def expanded_operating_point_market_state(
    _net,
    _summary,
    _hours,
    _represented_assets,
    _loading_limit=100.0,
    _optimization_target_percent=100.0,
):
    """Add newly violated AC assets and build the next CM linearization state."""
    loading = _summary["loading_by_name"]
    newly_violated = []
    if not loading.empty:
        newly_violated = loading.columns[
            (loading > float(_loading_limit)).any(axis=0)
        ].astype(str).tolist()
    asset_names = list(dict.fromkeys(
        [str(name) for name in _represented_assets] + newly_violated
    ))

    ratings = {}
    element_indices = {"line": [], "trafo": [], "trafo3w": []}
    for table_name, rating_column in (
        ("line", None), ("trafo", "sn_mva"), ("trafo3w", "sn_hv_mva")
    ):
        table = getattr(_net, table_name, None)
        if table is None or table.empty:
            continue
        for element_index, row in table.iterrows():
            name = str(row.get("name", element_index))
            if name not in asset_names:
                continue
            if table_name == "line":
                from_bus = int(row["from_bus"])
                rating = (
                    np.sqrt(3.0) * float(row["max_i_ka"])
                    * float(_net.bus.loc[from_bus, "vn_kv"])
                )
            else:
                rating = float(row[rating_column])
            ratings[name] = rating
            element_indices[table_name].append(int(element_index))

    missing = [name for name in asset_names if name not in ratings]
    if missing:
        raise KeyError(
            "AC relinearization cannot map these asset names to network ratings: "
            + ", ".join(missing)
        )

    smax = pd.DataFrame({0: pd.Series(ratings, dtype=float)}).reindex(asset_names)
    base_state = operating_point_market_state(
        _summary, smax, _hours, _loading_limit
    )
    margin_fraction = max(
        100.0 - float(_optimization_target_percent), 0.0
    ) / 100.0
    ds_tol = pd.DataFrame(
        np.tile(
            (smax.iloc[:, 0] * margin_fraction).to_numpy(),
            (len(_hours), 1),
        ),
        index=list(_hours), columns=smax.index,
    ).T
    return {
        **base_state,
        "smax": smax,
        "ds_tol": ds_tol,
        "congested_assets": newly_violated,
        "line_indices": element_indices["line"],
        "trafo_indices": element_indices["trafo"],
        "trafo3w_indices": element_indices["trafo3w"],
    }


def expanded_pilot_buses(
    _net, _summary, _existing_pilot_buses, _vmin, _vmax,
    _only_mv=False, _vn_kv_mv=None,
):
    """Include newly violated controllable buses in the next HVM calculation."""
    voltage = _summary["voltage"]
    residual = []
    if not voltage.empty:
        residual = voltage.columns[
            ((voltage < float(_vmin)) | (voltage > float(_vmax))).any(axis=0)
        ].tolist()
    excluded = set()
    if hasattr(_net, "ext_grid") and not _net.ext_grid.empty:
        excluded.update(int(bus) for bus in _net.ext_grid["bus"])
    if hasattr(_net, "bus") and not _net.bus.empty:
        excluded.update(
            int(bus) for bus in _net.bus.index[
                ~_net.bus.get("in_service", True).astype(bool)
            ]
        )
    candidates = []
    residual_set = {int(value) for value in residual}
    for value in list(_existing_pilot_buses) + residual:
        bus = int(value)
        if bus in excluded:
            continue
        # only_pilot_busMV governs the
        # initial study set, but it must not hide a new physical violation at
        # another voltage level during nonlinear AC validation.
        if bus not in residual_set and _only_mv and _vn_kv_mv is not None:
            if not np.isclose(
                float(_net.bus.loc[bus, "vn_kv"]), float(_vn_kv_mv)
            ):
                continue
        candidates.append(bus)
    return sorted(set(candidates))


# ---------------------------------------------------------------------------------------------------------------------
# Independent-scenario mode.
#
# With simulation_window_as_timesteps False every window of simulation_window is an independent scenario, studied
# together with the others only to compare them, so it must clear the same in a batch as alone.  The helpers below
# give every scenario its own monitored sets (the elements outside the operational limits, tol_i and tol_v included, in THAT scenario), its own security
# verdict and its own corrective iterations.  With simulation_window_as_timesteps True (one scenario over
# consecutive time steps) the shared sets and the case-wide loop are kept unchanged.
# ---------------------------------------------------------------------------------------------------------------------

def independent_snapshot_mode(_window_as_timesteps, _consecutive_hours=1, _intertemp_cons=False):
    """True when the windows of simulation_window are independent scenarios (simulation_window_as_timesteps False).

    Independent scenarios are cleared one at a time and nothing may couple them, so the mode requires
    consecutive_hours 1 and intertemp_cons False; any other combination is a contradictory configuration.
    """
    if _window_as_timesteps is None or bool(_window_as_timesteps):
        return False
    try:
        consecutive = int(_consecutive_hours)
    except (TypeError, ValueError):
        consecutive = None
    if consecutive != 1 or bool(_intertemp_cons):
        raise ValueError(
            'simulation_window_as_timesteps is False (independent scenarios), which needs consecutive_hours 1 and '
            'intertemp_cons False, so that every scenario is cleared on its own; got consecutive_hours=%r and '
            'intertemp_cons=%r.' % (_consecutive_hours, _intertemp_cons))
    return True


def _column_for_hour(_frame, _hour):
    """The column of ``_frame`` labelled ``_hour`` (int or str label), or None."""
    if _hour in _frame.columns:
        return _hour
    for column in _frame.columns:
        if str(column) == str(_hour):
            return column
    return None


def snapshot_asset_sets(_cong_needs, _hours, _all_assets=None):
    """{hour: asset names} each scenario monitors at the start: the branches with a need in THAT scenario.

    ``_cong_needs`` holds one row per represented asset and one column per hour; a need is positive exactly when
    the branch is above the detection limit (100 - tol_i) %.  With ``_all_assets`` (full network representation)
    every scenario monitors every asset, as in joint mode.
    """
    sets = {}
    for hour in _hours:
        if _all_assets is not None:
            sets[hour] = {str(asset) for asset in _all_assets}
            continue
        column = _column_for_hour(_cong_needs, hour)
        if column is None:
            sets[hour] = set()
            continue
        needs = pd.to_numeric(_cong_needs[column], errors="coerce").fillna(0.0)
        sets[hour] = {str(asset) for asset in needs.index[needs > 0.0]}
    return sets


def snapshot_bus_sets(_pilot_bus, _bus_voltages, _vmin, _vmax, _fsp_buses, _hours):
    """{hour: bus indices} carrying the voltage band of each scenario: its FSP buses and its own buses outside the
    detection limits (_vmin, _vmax, tol_v included), both restricted to the pilot buses (so the MV filter and the
    slack exclusion of select_pilot_bus hold).

    The out-of-limit test is the strict one of flex_needs_buses: a voltage exactly at a limit is compliant.
    """
    pilots = {int(bus) for bus in _pilot_bus}
    providers = {int(bus) for bus in _fsp_buses} & pilots
    sets = {}
    for hour in _hours:
        own = set(providers)
        if _bus_voltages is not None and not _bus_voltages.empty:
            row = _bus_voltages.loc[hour] if hour in _bus_voltages.index else None
            if row is None:
                matches = [index for index in _bus_voltages.index if str(index) == str(hour)]
                row = _bus_voltages.loc[matches[0]] if matches else None
            if row is not None:
                values = pd.to_numeric(row, errors="coerce")
                outside = values.index[(values > float(_vmax)) | (values < float(_vmin))]
                own |= {int(bus) for bus in outside if int(bus) in pilots}
        sets[hour] = own
    return sets


def snapshot_security_table(_summary, _hours, _loading_limit, _vmin, _vmax):
    """One row per scenario of the post-clearing AC power-flow validation (definitions of physical_security_summary).

    A scenario is secure when it has no overload cell and no voltage-violation cell.
    """
    loading = _summary.get("loading_by_name", pd.DataFrame())
    voltage = _summary.get("voltage", pd.DataFrame())
    rows = []
    for hour in _hours:
        load_row = loading.loc[hour] if (not loading.empty and hour in loading.index) else pd.Series(dtype=float)
        volt_row = voltage.loc[hour] if (not voltage.empty and hour in voltage.index) else pd.Series(dtype=float)
        load_row = pd.to_numeric(load_row, errors="coerce")
        volt_row = pd.to_numeric(volt_row, errors="coerce")
        overload_cells = int((load_row > float(_loading_limit)).sum())
        voltage_cells = int(((volt_row < float(_vmin)) | (volt_row > float(_vmax))).sum())
        rows.append({
            "snapshot": hour,
            "post_max_loading_percent": float(load_row.max()) if not load_row.empty else np.nan,
            "post_overload_cell_count": overload_cells,
            "post_min_voltage_pu": float(volt_row.min()) if not volt_row.empty else np.nan,
            "post_max_voltage_pu": float(volt_row.max()) if not volt_row.empty else np.nan,
            "post_voltage_violation_cell_count": voltage_cells,
            "secure": overload_cells == 0 and voltage_cells == 0,
        })
    return pd.DataFrame(rows).set_index("snapshot", drop=False)


def expand_snapshot_sets(_asset_sets, _bus_sets, _summary, _hours, _loading_limit, _vmin, _vmax, _pilot_bus):
    """Keep what every scenario already monitors and add what ITS OWN post-clearing AC result newly violates.

    Only the scenarios in ``_hours`` (those that go on to the next corrective iteration) are expanded; a bus is
    added only if it is a pilot bus of the next iteration (expanded_pilot_buses already added the newly violated
    buses and excluded the slack and inactive buses).
    """
    assets = {hour: set(values) for hour, values in (_asset_sets or {}).items()}
    buses = {hour: set(values) for hour, values in (_bus_sets or {}).items()}
    loading = _summary.get("loading_by_name", pd.DataFrame())
    voltage = _summary.get("voltage", pd.DataFrame())
    pilots = {int(bus) for bus in _pilot_bus}
    for hour in _hours:
        if _asset_sets is not None and not loading.empty and hour in loading.index:
            row = pd.to_numeric(loading.loc[hour], errors="coerce")
            assets.setdefault(hour, set()).update(str(name) for name in row.index[row > float(_loading_limit)])
        if _bus_sets is not None and not voltage.empty and hour in voltage.index:
            row = pd.to_numeric(voltage.loc[hour], errors="coerce")
            outside = row.index[(row < float(_vmin)) | (row > float(_vmax))]
            buses.setdefault(hour, set()).update(int(bus) for bus in outside if int(bus) in pilots)
    return (assets if _asset_sets is not None else None), (buses if _bus_sets is not None else None)


# Sheets of a market result that hold one iteration's INCREMENT (activation of that iteration); every other hour
# sheet is a level (dispatch, state of charge, operating mode), a slack of the latest clearing, or the voltage
# prediction.
_INCREMENT_SHEET_PREFIXES = ("DW", "DR", "ABS_DW", "ABS_DR")
_NON_HOUR_SHEETS = ("ObjValue", "SequentialCostBasis")


def complete_round_result(_round_file, _previous_file, _round_hours, _all_hours):
    """Extend a corrective iteration that re-cleared only some scenarios to every studied scenario.

    For a scenario NOT re-cleared in this iteration no new activation was made and its last clearing stands:
        increment sheets (DW*, DR*, ABS_DW*, ABS_DR*)        -> 0
        every other sheet (W, R, SoC, modes, slack, VA, ...)  -> its value in the previous cumulative workbook
    so the post-clearing AC power-flow validation, the merge, the stage archive and the settlement read one workbook
    covering every scenario, exactly as when every scenario is re-cleared.  An element that entered the represented
    set in this iteration (a new branch or pilot bus) has no earlier value: its slack is 0 and its voltage
    prediction (VA) is left empty, because no clearing predicted it for that scenario.
    """
    round_sheets = pd.read_excel(_round_file, sheet_name=None, index_col=0)
    previous = pd.read_excel(_previous_file, sheet_name=None, index_col=0)
    round_labels = {str(hour) for hour in _round_hours}
    all_hours = list(_all_hours)
    completed = {}
    for name, frame in round_sheets.items():
        if name in _NON_HOUR_SHEETS or frame.shape[1] == 0:
            completed[name] = frame
            continue
        labels = [str(column) for column in frame.columns]
        if not set(labels) <= round_labels:
            completed[name] = frame          # not an hour sheet of this iteration
            continue
        by_label = dict(zip(labels, frame.columns))
        full = pd.DataFrame(np.nan, index=frame.index, columns=all_hours, dtype=float)
        earlier = previous.get(name)
        earlier_by_label = ({str(column): column for column in earlier.columns}
                            if earlier is not None else {})
        for hour in all_hours:
            key = str(hour)
            if key in by_label:
                full[hour] = pd.to_numeric(frame[by_label[key]], errors="coerce").to_numpy()
            elif name.startswith(_INCREMENT_SHEET_PREFIXES):
                full[hour] = 0.0
            elif key in earlier_by_label:
                full[hour] = pd.to_numeric(
                    earlier[earlier_by_label[key]].reindex(frame.index), errors="coerce").to_numpy()
        if name != "VA":
            full = full.fillna(0.0)
        completed[name] = full
    with pd.ExcelWriter(_round_file) as writer:
        for name, frame in completed.items():
            frame.to_excel(writer, sheet_name=name)
    return _round_file


def _aligned_market_sheet(_market_result_file, _sheet_name, _template, _hours):
    """Align one market-result sheet with an FSP-input sheet."""
    result = pd.read_excel(
        _market_result_file, sheet_name=_sheet_name, index_col=0
    )
    if len(result.index) != len(_template.index):
        raise ValueError(
            f'FSP count differs between "{_sheet_name}" and its input workbook.'
        )
    if set(_template.index).issubset(set(result.index)):
        result = result.reindex(_template.index)
    else:
        result = result.copy()
        result.index = _template.index
    # Flexibility operating points are
    # continuous values even when the source Excel cells happen to be integers.
    aligned = _template.astype(float).copy(deep=True)
    for hour in _hours:
        target_column = hour if hour in aligned.columns else str(hour)
        source_column = hour if hour in result.columns else str(hour)
        if target_column not in aligned.columns or source_column not in result.columns:
            raise KeyError(
                f'Hour {hour} is absent while aligning "{_sheet_name}".'
            )
        aligned.loc[:, target_column] = result.loc[:, source_column].astype(float)
    return aligned


def rebase_fsp_files_at_market_result(
    _market_result_file,
    _fsp_file,
    _input_root,
    _hours,
    _iteration=1,
    _result_to_input_sign=None,
):
    """Create corrective FSP inputs anchored at the accepted first dispatch.

    Absolute technical bounds and the original storage beginning-of-horizon
    state of charge are retained. Only Winit/Rinit move to the accepted first
    market operating point, so the next market variables and costs represent
    additional flexibility and their feasible ranges are the remaining
    capacity between that point and the unchanged absolute bounds.
    """
    sign_by_type = _result_to_input_sign or {}
    corrective_files = {}
    capacity_rows = []
    for fsp_type, filename in _fsp_file.items():
        if filename == 0:
            corrective_files[fsp_type] = 0
            continue
        source = os.path.join(os.path.abspath(_input_root), filename + '.xlsx')
        if not os.path.isfile(source):
            raise FileNotFoundError(source)
        sheets = pd.read_excel(source, sheet_name=None, index_col=0)
        w_name = 'Winit_' + str(fsp_type)
        r_name = 'Rinit_' + str(fsp_type)
        if w_name not in sheets or r_name not in sheets:
            raise KeyError(
                f'Corrective FSP input requires sheets "{w_name}" and "{r_name}".'
            )
        sign = float(sign_by_type.get(fsp_type, 1.0))
        sheets[w_name] = _aligned_market_sheet(
            _market_result_file, 'W_' + str(fsp_type), sheets[w_name], _hours
        ) * sign
        sheets[r_name] = _aligned_market_sheet(
            _market_result_file, 'R_' + str(fsp_type), sheets[r_name], _hours
        ) * sign

        def absolute_bounds(quantity):
            prefixes = ('WLB_', 'WUB_') if quantity == 'W' else ('RLB_', 'RUB_')
            candidates = [
                frame.astype(float)
                for sheet_name, frame in sheets.items()
                if sheet_name.startswith(prefixes)
                and sheet_name.endswith('_' + str(fsp_type))
            ]
            if not candidates:
                return None, None
            stacked = np.stack([
                frame.reindex(
                    index=sheets[quantity + 'init_' + str(fsp_type)].index,
                    columns=sheets[quantity + 'init_' + str(fsp_type)].columns,
                ).to_numpy(dtype=float)
                for frame in candidates
            ])
            template = sheets[quantity + 'init_' + str(fsp_type)]
            return (
                pd.DataFrame(stacked.min(axis=0), index=template.index, columns=template.columns),
                pd.DataFrame(stacked.max(axis=0), index=template.index, columns=template.columns),
            )

        w_min, w_max = absolute_bounds('W')
        r_min, r_max = absolute_bounds('R')
        for resource in sheets[w_name].index:
            for hour in _hours:
                column = hour if hour in sheets[w_name].columns else str(hour)
                row = {
                    'fsp_type': fsp_type,
                    'fsp_id': resource,
                    'hour': hour,
                }
                for quantity, current, lower, upper in (
                    ('P', sheets[w_name], w_min, w_max),
                    ('Q', sheets[r_name], r_min, r_max),
                ):
                    value = float(current.loc[resource, column])
                    minimum = float(lower.loc[resource, column]) if lower is not None else np.nan
                    maximum = float(upper.loc[resource, column]) if upper is not None else np.nan
                    row.update({
                        f'{quantity}_accepted_first_market': value,
                        f'{quantity}_absolute_min': minimum,
                        f'{quantity}_absolute_max': maximum,
                        f'{quantity}_remaining_to_min': max(value - minimum, 0.0)
                        if np.isfinite(minimum) else np.nan,
                        f'{quantity}_remaining_to_max': max(maximum - value, 0.0)
                        if np.isfinite(maximum) else np.nan,
                    })
                capacity_rows.append(row)

        # Write a separate corrective
        # workbook; never overwrite the reusable initial-market FSP inputs.
        target_name = f'{filename}_ACOP{int(_iteration):02d}'
        target = os.path.join(os.path.abspath(_input_root), target_name + '.xlsx')
        with pd.ExcelWriter(target) as writer:
            for sheet_name, frame in sheets.items():
                frame.to_excel(writer, sheet_name=sheet_name)
        corrective_files[fsp_type] = target_name
    if capacity_rows:
        # Save explicit remaining P/Q
        # headroom for every provider and hour used by the corrective market.
        pd.DataFrame(capacity_rows).to_csv(
            os.path.join(
                os.path.abspath(_input_root),
                f'ACCorrectiveFSPCapacity_iteration_{int(_iteration):02d}.csv',
            ),
            index=False,
        )
    return corrective_files


def archive_market_result(_market_result_file, _archive_name):
    """Preserve any cumulative market workbook under a caller-defined name."""
    # Multiple corrective markets need a
    # cumulative archive after every pass, not only one initial backup.
    source = os.path.abspath(_market_result_file)
    target = os.path.join(os.path.dirname(source), str(_archive_name))
    shutil.copy2(source, target)
    return target


def _slack_total(_sheets, _sheet_name):
    """Sum one slack sheet as numeric data."""
    frame = _sheets.get(_sheet_name)
    if frame is None or getattr(frame, "empty", True):
        return 0.0
    return float(
        frame.apply(pd.to_numeric, errors="coerce").fillna(0.0).to_numpy().sum()
    )


def _report_orientation(_sheets, _total_name):
    """Return +1 or -1: how a class's reported total relates to its up/down parts.

    The market works internally in the
    generation convention, but each class is REPORTED in its own.  A load and a
    battery have their DW and DR negated on the way out, a generator does not, so

        generator :  DW_U - DW_D = +DW
        load      :  DW_U - DW_D = -DW

    Splitting a cumulative total into up and down therefore cannot assume a
    sign.  Rather than carry a table of per-class conventions here, which would
    silently rot if a resource model changed its conversion list, the
    orientation is measured from the workbook itself and verified.
    """
    total = _sheets.get(_total_name)
    up = _sheets.get(_total_name + "_U")
    down = _sheets.get(_total_name + "_D")
    if total is None or up is None or down is None:
        return 1
    total_values = total.astype(float).to_numpy()
    directional = up.astype(float).to_numpy() - down.astype(float).to_numpy()
    if directional.shape != total_values.shape:
        return 1
    if np.allclose(directional, total_values, atol=1e-9, equal_nan=True):
        return 1
    if np.allclose(directional, -total_values, atol=1e-9, equal_nan=True):
        return -1
    # Neither orientation reproduces the directional sheets.  Fall back to the
    # dominant sign rather than guessing silently.
    scale = float(np.nansum(np.abs(total_values)))
    if scale <= 0.0:
        return 1
    agreement = float(np.nansum(directional * total_values))
    print(
        "WARNING: the directional sheets of {name} match neither +DW nor -DW "
        "exactly. The cumulative split uses the dominant orientation."
        .format(name=_total_name)
    )
    return 1 if agreement >= 0 else -1


def _class_orientation(_sheet_sets, _total_name):
    """Measure a class's report orientation from the first workbook where it moved.

    _report_orientation reads +1 from a
    workbook in which the class did not move at all (zero total and zero
    directional sheets agree with either sign).  A battery idle in the main
    market and activated only by a corrective market was therefore split with
    the generator sign, so its upward and downward volumes -- and the price each
    one is settled at -- were swapped.  The orientation is now taken from the
    first workbook in which the class actually moved.
    """
    sheet_sets = [sheets for sheets in _sheet_sets if sheets is not None]
    for sheets in sheet_sets:
        total = sheets.get(_total_name)
        if total is None or getattr(total, "empty", True):
            continue
        values = total.apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
        if float(np.nansum(np.abs(values))) > 1e-12:
            return _report_orientation(sheets, _total_name)
    return _report_orientation(sheet_sets[0], _total_name) if sheet_sets else 1


def _net_directional(_total, _orientation=1):
    """Split a signed cumulative activation into its up and down magnitudes.

    ``_orientation`` maps the reported total onto the internal generation
    convention the directional sheets are expressed in.
    """
    internal = _total.astype(float) * float(_orientation)
    return internal.clip(lower=0.0), (-internal).clip(lower=0.0)


def _directional_cost(_total, _orientation, _price_up, _price_down):
    """Pay-as-bid cost of one signed activation, each direction at its own price.

    One helper prices the main market,
    each corrective increment and the final net position, so the three costs of
    the settlement can never drift apart through three copies of the formula.
    """
    up, down = _net_directional(_total, _orientation)
    return float(
        (up * _price_up.reindex_like(up)).to_numpy().sum()
        + (down * _price_down.reindex_like(down)).to_numpy().sum()
    )


def _direction_price(_sheets, _fsp_type, _candidates):
    """Return the settlement price of one cumulative direction, or None."""
    frames = [
        _sheets[name].apply(pd.to_numeric, errors='coerce').astype(float)
        for name in (f'{c}_{_fsp_type}' for c in _candidates)
        if name in _sheets
    ]
    if not frames:
        return None
    price = frames[0]
    for other in frames[1:]:
        price = price.combine(other.reindex_like(price), np.maximum)
    return price


# Cost sheets of one FSP workbook that price a cumulative direction.  Storage
# writes its injection and absorption prices from the same Pup_cost/Pdown_cost,
# so the two coincide; taking the maximum is a safeguard, not a choice.
_NET_PRICE_SHEETS = {
    'W_U': ('W_U_Cost', 'W_U_inj_Cost', 'W_U_ads_Cost'),
    'W_D': ('W_D_Cost', 'W_D_inj_Cost', 'W_D_ads_Cost'),
    'R_U': ('R_U_Cost',),
    'R_D': ('R_D_Cost',),
}


def _round_columns(_frame, _round_hours):
    """The columns of the scenarios an iteration re-cleared."""
    if _round_hours is None:
        return _frame
    labels = {str(hour) for hour in _round_hours}
    return _frame.loc[:, [column for column in _frame.columns if str(column) in labels]]


def merge_sequential_market_results(_initial_market_file, _corrective_market_file, _fsp_file,
                                    _alpha_cost=None, _beta_cost=None, _input_root=None, _round_hours=None):
    """Settle the initial market and every corrective market as ONE market.

    Three costs are now kept apart, so
    the solver objective of a corrective round can never be read as the cost of
    the market.

        main_market_cost_eur             the main market's own activation, priced
        corrective_incremental_cost_eur  the gross cost of every corrective
                                         increment, priced by its own direction
                                         -- a diagnostic of redispatch effort
        final_net_settlement_cost_eur    the final NET position of every provider
                                         against the original pre-market point,
                                         priced by its final direction -- what is
                                         paid, and what ObjValue reports

    A corrective iteration is priced
    incrementally: it optimises only its
    own increment, so its solver objective is that increment's cost plus the
    iteration's not served flexibility penalty.  The objective is reconciled
    against exactly that, never against the net settlement, which it was never
    meant to equal.

    A scenario may be cleared more than once: an initial market, then a
    corrective market on relinearized sensitivities.  Those rounds are not
    separate products.  They are one local flexibility market whose clearing was
    computed in stages, so what a provider is finally committed to, and what it
    is finally paid, must both be read off the FINAL NET position.

    COMMITMENT is netted.  DW and DR are signed, so adding the rounds already
    gives the net: a provider moved +3 MW upward by the initial market and
    -2 MW downward by a corrective one has a cumulative DW of +1 MW.  The
    directional sheets are then REBUILT from that net total rather than added
    round by round, so the same provider shows 1 MW upward and 0 MW downward
    instead of 3 MW upward and 2 MW downward.  Adding them would report 5 MW of
    traded volume for 1 MW of delivered service and inflate every liquidity and
    market-power index built on it.

    COST follows the same net position.  The cumulative procurement is the net
    directional quantity priced at the provider's own offer, so the example
    above is paid for 1 MW upward and not for 3 MW upward plus 2 MW downward.
    The corrective solver objective is the increment's cost instead; both are
    reported in SequentialCostBasis so the reconciliation is auditable.

    SLACK is NOT cumulative.  alpha_primo and beta are the violation the market
    could not clear, and every round penalises the same physical residual of the
    same hour, so the workbook keeps the LATEST round's alpha and beta.

    ``_round_hours`` names the
    scenarios this iteration actually re-cleared (independent-scenario mode).  The
    workbook covers every scenario (complete_round_result), so the commitment, the
    settlement and the residual not served flexibility are still computed over all
    of them; only the check of the solver objective is restricted to the re-cleared
    scenarios, the only ones that solver saw.  None: every scenario.
    """
    if _input_root is None:
        raise ValueError(
            'merge_sequential_market_results needs _input_root, the folder that '
            'holds the FSP workbooks, to price the NET committed position of '
            'every provider. Without it the sequence could only be settled by '
            'adding each round gross, which would pay a provider for 3 MW '
            'upward plus 2 MW downward when it is finally committed to 1 MW '
            'upward.'
        )

    initial = pd.read_excel(_initial_market_file, sheet_name=None, index_col=0)
    corrective = pd.read_excel(_corrective_market_file, sheet_name=None, index_col=0)

    has_slack = bool(
        _slack_total(initial, 'ABS_alpha_primo') or _slack_total(initial, 'ABS_beta')
        or _slack_total(corrective, 'ABS_alpha_primo')
        or _slack_total(corrective, 'ABS_beta')
    )
    if has_slack and (_alpha_cost is None or _beta_cost is None):
        raise ValueError(
            'merge_sequential_market_results needs _alpha_cost and _beta_cost to '
            'charge the residual this sequence could not clear. Pass the same '
            'alpha_cost/beta_cost the market used.'
        )

    def add_frames(first, second):
        first_aligned = first.reindex(index=second.index, columns=second.columns)
        if first_aligned.isna().any().any():
            raise ValueError('Sequential market result sheets cannot be aligned.')
        return first_aligned.astype(float) + second.astype(float)

    # From the second corrective round on,
    # the earlier workbook is itself a merged one.  Its SequentialCostBasis
    # carries the main-market cost and the corrective transactions already
    # procured, because its DW sheets hold the net position, not the main
    # market's own activation.
    carried = None
    previous_basis = initial.get('SequentialCostBasis')
    if (previous_basis is not None and not previous_basis.empty
            and 'main_market_cost_eur' in previous_basis.columns):
        carried = previous_basis.iloc[0]

    net_procurement_cost = 0.0
    # The main market and this corrective
    # round priced on their own activation, each direction at its own price.
    main_market_cost = 0.0
    corrective_round_cost = 0.0
    orientations = {}
    priced_classes = []
    unpriced_classes = []
    for fsp_type, filename in _fsp_file.items():
        if filename == 0:
            continue
        source = os.path.join(os.path.abspath(_input_root), str(filename) + '.xlsx')
        if not os.path.isfile(source):
            raise FileNotFoundError(
                'Cannot settle the net position of resource class {t}: its FSP '
                'workbook was not found at {p}.'.format(t=fsp_type, p=source)
            )
        price_sheets = pd.read_excel(source, sheet_name=None, index_col=0)
        prices = {
            direction: _direction_price(price_sheets, fsp_type, candidates)
            for direction, candidates in _NET_PRICE_SHEETS.items()
        }

        for quantity, price_up, price_down in (
            ('DW', prices.get('W_U'), prices.get('W_D')),
            ('DR', prices.get('R_U'), prices.get('R_D')),
        ):
            total_name = f'{quantity}_{fsp_type}'
            if total_name not in initial or total_name not in corrective:
                continue
            # Measured on the raw
            # corrective round first, then on the earlier workbook (see
            # _class_orientation), and kept for the storage mode sheets below.
            orientation = _class_orientation((corrective, initial), total_name)
            orientations[total_name] = orientation
            # This round's own increment,
            # read before the sheet is overwritten with the cumulative total.
            round_increment = corrective[total_name].astype(float).copy()
            cumulative = add_frames(initial[total_name], corrective[total_name])
            corrective[total_name] = cumulative

            absolute_name = f'ABS_{quantity}_{fsp_type}'
            if absolute_name in corrective:
                corrective[absolute_name] = cumulative.abs()

            up, down = _net_directional(cumulative, orientation)
            up_name, down_name = f'{total_name}_U', f'{total_name}_D'
            if up_name in corrective:
                corrective[up_name] = up.reindex_like(corrective[up_name].astype(float))
            if down_name in corrective:
                corrective[down_name] = down.reindex_like(corrective[down_name].astype(float))

            if price_up is not None and price_down is not None:
                net_procurement_cost += _directional_cost(
                    cumulative, orientation, price_up, price_down)
                # The gross transaction
                # costs, kept as diagnostics beside the net settlement.
                corrective_round_cost += _directional_cost(
                    round_increment, orientation, price_up, price_down)
                if carried is None:
                    main_market_cost += _directional_cost(
                        initial[total_name], orientation, price_up, price_down)
                priced_classes.append(f'{fsp_type}:{quantity}')
            elif float(np.nansum(np.abs(cumulative.to_numpy()))) > 0.0:
                # A class that moved but carries no price cannot be settled, and
                # silently leaving it out would under-report what the DSO bought.
                unpriced_classes.append(f'{fsp_type}:{quantity}')

        # A storage unit also reports its cumulative active activation split by
        # operating mode.  Those sheets describe HOW the net position is
        # delivered, so they follow the net direction and the mode the battery
        # finally settles in, given by the latest round's b1 (injecting) and b2
        # (absorbing) binaries.  Carrying the per-round magnitudes here would
        # contradict the netted directional sheets above.
        total_name = f'DW_{fsp_type}'
        mode_sheets = [
            name for name in corrective
            if name.startswith((f'{total_name}_U_', f'{total_name}_D_'))
        ]
        if mode_sheets and total_name in corrective:
            # The orientation the net
            # split above used, not a fresh read of the earlier workbook.
            up, down = _net_directional(
                corrective[total_name],
                orientations.get(total_name, _class_orientation((corrective, initial), total_name))
            )
            injecting = corrective.get(f'b1_{fsp_type}')
            absorbing = corrective.get(f'b2_{fsp_type}')
            for sheet_name in mode_sheets:
                template = corrective[sheet_name].astype(float)
                direction = up if f'{total_name}_U_' in sheet_name else down
                selector = injecting if sheet_name.endswith('_inj') else absorbing
                value = direction.reindex_like(template).fillna(0.0)
                if selector is not None:
                    mask = selector.astype(float).reindex_like(template).fillna(0.0)
                    value = value * mask.round()
                corrective[sheet_name] = value

    # Slack stays at the latest round.  Its cost is charged once, on the residual
    # that actually remains after the final clearing.
    final_slack_cost = 0.0
    round_slack_cost = 0.0  # Of the re-cleared scenarios only
    if _alpha_cost is not None and _beta_cost is not None:
        final_slack_cost = (
            float(_alpha_cost) * _slack_total(corrective, 'ABS_alpha_primo')
            + float(_beta_cost) * _slack_total(corrective, 'ABS_beta')
        )
        round_sheets = {
            name: _round_columns(corrective[name], _round_hours)
            for name in ('ABS_alpha_primo', 'ABS_beta') if name in corrective
        }
        round_slack_cost = (
            float(_alpha_cost) * _slack_total(round_sheets, 'ABS_alpha_primo')
            + float(_beta_cost) * _slack_total(round_sheets, 'ABS_beta')
        )

    solver_objective = (
        float(corrective['ObjValue'].to_numpy().ravel()[0])
        if 'ObjValue' in corrective and not corrective['ObjValue'].empty
        else float('nan')
    )

    if unpriced_classes:
        raise ValueError(
            'These resource classes were activated but their FSP workbook holds '
            'no directional price, so the sequence cannot be settled as one '
            'market: ' + ', '.join(unpriced_classes)
        )

    # The costs carried from earlier
    # rounds, and the ones this round adds.
    if carried is not None:
        main_market_cost = float(carried['main_market_cost_eur'])
        corrective_incremental_cost = (
            float(carried['corrective_incremental_cost_eur']) + corrective_round_cost)
        corrective_rounds = int(carried.get('corrective_rounds', 1)) + 1
    else:
        corrective_incremental_cost = corrective_round_cost
        corrective_rounds = 1

    settled_objective = solver_objective
    reconciliation = float('nan')
    solver_target = float('nan')
    solver_gap = float('nan')
    solver_basis = 'corrective_round_increment_plus_slack'
    if priced_classes:
        settled_objective = net_procurement_cost + final_slack_cost
        reconciliation = settled_objective - solver_objective
        if 'ObjValue' in corrective:
            corrective['ObjValue'] = pd.DataFrame(
                [[settled_objective]],
                index=corrective['ObjValue'].index[:1],
                columns=corrective['ObjValue'].columns[:1],
            )
        # The solver objective is checked against what that solver optimised:
        # under incremental pricing, this iteration's increment plus its not
        # served flexibility penalty over the scenarios it re-cleared, not the
        # net settlement.  The settlement is reported either way.
        solver_target = corrective_round_cost + round_slack_cost
        solver_gap = solver_objective - solver_target
        if abs(solver_gap) > max(1e-4 * abs(solver_target), 1e-2):
            print(
                'WARNING: the corrective solver objective {b:.2f} EUR does not '
                'match the {basis} it optimised ({a:.2f} EUR); difference '
                '{d:.2f} EUR. The final net settlement {s:.2f} EUR is what is '
                'reported; the difference is recorded in SequentialCostBasis.'
                .format(b=solver_objective, basis=solver_basis.replace('_', ' '),
                        a=solver_target, d=solver_gap, s=net_procurement_cost)
            )

    corrective['SequentialCostBasis'] = pd.DataFrame([{
        'objective_eur': settled_objective,
        'cumulative_procurement_eur': settled_objective - final_slack_cost,
        'final_round_slack_eur': final_slack_cost,
        'solver_objective_eur': solver_objective,
        'settlement_minus_solver_eur': reconciliation,
        'priced_classes': ','.join(priced_classes) if priced_classes else 'none',
        'alpha_basis': 'latest_round',
        'beta_basis': 'latest_round',
        'commitment_basis': 'net_across_all_rounds',
        'procurement_basis': 'net_across_all_rounds',
        # The three economic quantities,
        # kept apart.  objective_eur (= ObjValue) is final_net_settlement_cost_eur
        # plus the final residual penalty; the solver objective is never it.
        'corrective_rounds': corrective_rounds,
        'main_market_cost_eur': main_market_cost,
        'corrective_round_cost_eur': corrective_round_cost,
        'corrective_incremental_cost_eur': corrective_incremental_cost,
        'final_net_settlement_cost_eur': net_procurement_cost,
        'gross_transaction_cost_eur': main_market_cost + corrective_incremental_cost,
        'reversed_activation_cost_eur':
            main_market_cost + corrective_incremental_cost - net_procurement_cost,
        'solver_reconciliation_basis': solver_basis,
        'solver_reconciliation_target_eur': solver_target,
        'solver_minus_target_eur': solver_gap,
    }])

    # W/R and SoC remain the final corrective operating point, while DW/DR and
    # the directional sheets are the NET commitment across every round.
    with pd.ExcelWriter(_corrective_market_file) as writer:
        for sheet_name, frame in corrective.items():
            frame.to_excel(writer, sheet_name=sheet_name)
    return _corrective_market_file


# A final net position smaller than this
# is "back at baseline" -- no direction, no settled volume, no payment.
SETTLEMENT_ZERO_TOL = 1e-9


def _numeric_labelled(_frame):
    """A numeric copy of one result or price sheet with string row/column labels.

    Result sheets and FSP price sheets
    label hours as int or str depending on how Excel stored them; the
    settlement aligns them on strings before multiplying.
    """
    frame = _frame.copy()
    frame.index = [str(index) for index in frame.index]
    frame.columns = [str(column) for column in frame.columns]
    return frame.apply(pd.to_numeric, errors="coerce")


def final_net_settlement_table(_market_result_files, _fsp_file, _input_root,
                               _settled_market_file=None, _fsp_types=FSP_TYPES):
    """Settle every provider, hour and product on its final NET position.

    ``_market_result_files`` are the cumulative archives of one case in order
    (ACValidationCumulativeMarket_iteration_00, _01, ...): the first is the main
    market, every later one the net position after one more corrective round.
    For every provider, hour and P/Q component

        final_net_activation = main_activation + sum(corrective increments)

    and the final net position alone is settled, at the price of its final
    direction:

        > 0   settled volume x upward bid price
        < 0   |settled volume| x downward bid price
        = 0   nothing, even if the rounds moved it and moved it back

    Main +2.0 MW then a corrective -0.5 MW is paid as 1.5 MW upward; +2.0 then
    -3.0 is paid as 1.0 MW downward; +2.0 then -2.0 is not paid at all.

    Activation columns use ONE sign for every class: positive is upward
    flexibility (more injection or less consumption), priced at the upward
    bid.  ``reported_sign`` maps them back onto the DW/DR sign of the workbook
    (workbook value = activation x reported_sign).

    The gross diagnostics are kept beside the settlement: the cost of the main
    market's own activation, the gross cost of the corrective increments, the
    gross activation and the reversed activation (what one round bought and a
    later round undid).

    Returns ``(table, checks)``.  ``checks`` holds the consistency tests of the
    settlement; every ``*_rows`` count and ``*_error`` must be zero.
    """
    files = [str(path) for path in _market_result_files if path and os.path.isfile(str(path))]
    if not files:
        return pd.DataFrame(), {}
    books = [pd.read_excel(path, sheet_name=None, index_col=0) for path in files]
    n_corrective = len(books) - 1
    corrective_columns = [f"corrective_{k:02d}_increment" for k in range(1, n_corrective + 1)]

    frames = []
    for fsp_type, filename in _fsp_file.items():
        if filename == 0 or str(fsp_type) not in _fsp_types:
            continue
        source = os.path.join(os.path.abspath(_input_root), str(filename) + ".xlsx")
        price_sheets = pd.read_excel(source, sheet_name=None, index_col=0) if os.path.isfile(source) else {}
        prices = {
            direction: _direction_price(price_sheets, fsp_type, candidates)
            for direction, candidates in _NET_PRICE_SHEETS.items()
        }
        for quantity, product, unit, dispatch_name, price_up, price_down in (
            ("DW", "P", "MW", "W", prices.get("W_U"), prices.get("W_D")),
            ("DR", "Q", "MVAr", "R", prices.get("R_U"), prices.get("R_D")),
        ):
            total_name = f"{quantity}_{fsp_type}"
            if any(total_name not in book for book in books):
                continue
            orientation = _class_orientation(books, total_name)
            template = _numeric_labelled(books[0][total_name]).fillna(0.0)
            reported = [_align_like(_numeric_labelled(book[total_name]).fillna(0.0), template) for book in books]
            cumulative = [frame * orientation for frame in reported]
            increments = [cumulative[0]] + [
                cumulative[k] - cumulative[k - 1] for k in range(1, len(cumulative))
            ]
            final = cumulative[-1]

            def aligned_price(price):
                if price is None:
                    return pd.DataFrame(np.nan, index=template.index, columns=template.columns)
                return _numeric_labelled(price).reindex(index=template.index, columns=template.columns)

            p_up, p_down = aligned_price(price_up), aligned_price(price_down)

            def cost(activation):
                return activation.clip(lower=0.0) * p_up + (-activation).clip(lower=0.0) * p_down

            corrective_sum = sum(increments[1:], template * 0.0)
            gross = sum((frame.abs() for frame in increments), template * 0.0)
            settled = final.where(final.abs() > SETTLEMENT_ZERO_TOL, 0.0)
            settlement_price = p_up.where(settled > 0.0, p_down.where(settled < 0.0, 0.0))
            columns = {
                "main_activation": increments[0],
                **{name: frame for name, frame in zip(corrective_columns, increments[1:])},
                "corrective_increment_total": corrective_sum,
                "final_net_activation": final,
                "gross_activation": gross,
                "reversed_activation": ((gross - final.abs()) / 2.0).clip(lower=0.0),
                "settled_volume": settled.abs(),
                "price_up": p_up,
                "price_down": p_down,
                "settlement_price": settlement_price,
                "main_market_cost_eur": cost(increments[0]),
                "corrective_incremental_cost_eur": sum((cost(f) for f in increments[1:]), template * 0.0),
                "final_net_settlement_cost_eur": settled.abs() * settlement_price,
            }
            # The final net activation must be the dispatch the network was
            # finally given: W - DW is the original pre-market point in every
            # workbook, so the last one must reproduce the first.
            dispatch = f"{dispatch_name}_{fsp_type}"
            if dispatch in books[0] and dispatch in books[-1]:
                first_point = _align_like(_numeric_labelled(books[0][dispatch]).fillna(0.0), template) - reported[0]
                last_point = _align_like(_numeric_labelled(books[-1][dispatch]).fillna(0.0), template) - reported[-1]
                columns["dispatch_residual"] = (last_point - first_point).abs()
            else:
                columns["dispatch_residual"] = pd.DataFrame(np.nan, index=template.index, columns=template.columns)

            keys = pd.MultiIndex.from_product([template.index, template.columns], names=["provider", "hour"])
            long = pd.DataFrame({
                name: frame.reindex(index=template.index, columns=template.columns).to_numpy(dtype=float).ravel()
                for name, frame in columns.items()
            }, index=keys).reset_index()
            long.insert(0, "unit", unit)
            long.insert(0, "product", product)
            long.insert(0, "fsp_type", str(fsp_type))
            long["reported_sign"] = int(orientation)
            long["final_direction"] = np.where(
                long["final_net_activation"] > SETTLEMENT_ZERO_TOL, "upward",
                np.where(long["final_net_activation"] < -SETTLEMENT_ZERO_TOL, "downward", "none"))
            frames.append(long)

    if not frames:
        return pd.DataFrame(), {}
    table = pd.concat(frames, ignore_index=True)
    hours = pd.to_numeric(table["hour"], errors="coerce")
    if hours.notna().all():
        table["hour"] = hours.astype(int)
    return table, settlement_consistency_checks(table, _settled_market_file)


def settlement_consistency_checks(_table, _settled_market_file=None):
    """Consistency tests of a final net settlement table.

    Every ``*_rows`` count and
    ``*_error`` is zero for a consistent settlement.
    """
    table = _table
    tol = 1e-6
    corrective = table["corrective_increment_total"]
    final = table["final_net_activation"]
    main = table["main_activation"]
    final_cost = table["final_net_settlement_cost_eur"]
    up_price_expected = final > SETTLEMENT_ZERO_TOL
    down_price_expected = final < -SETTLEMENT_ZERO_TOL
    crossing = (main * final) < -SETTLEMENT_ZERO_TOL
    by_class = table.groupby(["fsp_type", "product"])["final_net_settlement_cost_eur"].sum()
    by_provider = table.groupby(["fsp_type", "provider", "product"])["final_net_settlement_cost_eur"].sum()
    system_total = float(final_cost.sum())
    checks = {
        "rows": int(len(table)),
        "main_market_cost_eur": float(table["main_market_cost_eur"].sum()),
        "corrective_incremental_cost_eur": float(table["corrective_incremental_cost_eur"].sum()),
        "final_net_settlement_cost_eur": system_total,
        "reversed_activation_cost_eur": float(
            table["main_market_cost_eur"].sum() + table["corrective_incremental_cost_eur"].sum() - system_total),
        "gross_activation": float(table["gross_activation"].sum()),
        "reversed_activation": float(table["reversed_activation"].sum()),
        "final_net_abs_activation": float(table["settled_volume"].sum()),
        # final = main + sum of the corrective increments
        "net_identity_max_error": float((final - (main + corrective)).abs().max()),
        # the final net position reproduces the dispatch the network was given
        "dispatch_max_residual": float(table["dispatch_residual"].max(skipna=True))
        if table["dispatch_residual"].notna().any() else float("nan"),
        # no reversed volume is paid: the settled volume is |final| and never more
        "double_counted_rows": int(((table["settled_volume"] - final.abs()).abs() > tol).sum()
                                   + (table["settled_volume"] > table["gross_activation"] + tol).sum()),
        # a position back at baseline is paid nothing
        "baseline_paid_rows": int(((final.abs() <= SETTLEMENT_ZERO_TOL) & (final_cost.abs() > tol)).sum()),
        # the price is the final direction's, also when a round crossed zero
        "crossing_rows": int(crossing.sum()),
        "wrong_direction_price_rows": int(
            (up_price_expected & ~np.isclose(table["settlement_price"], table["price_up"], equal_nan=True)).sum()
            + (down_price_expected & ~np.isclose(table["settlement_price"], table["price_down"], equal_nan=True)).sum()),
        # provider, technology and system totals agree
        "provider_total_eur": float(by_provider.sum()),
        "technology_total_eur": float(by_class.sum()),
        "aggregation_error": float(max(abs(by_provider.sum() - system_total), abs(by_class.sum() - system_total))),
        "unpriced_activation_rows": int(((table["settled_volume"] > tol) & table["settlement_price"].isna()).sum()),
    }
    # The reported final cost is the settlement, never the solver objective.
    if _settled_market_file and os.path.isfile(str(_settled_market_file)):
        try:
            sheets = pd.read_excel(_settled_market_file, sheet_name=None, index_col=0)
        except Exception:
            sheets = {}
        basis = sheets.get("SequentialCostBasis")
        if basis is not None and not basis.empty and "final_net_settlement_cost_eur" in basis.columns:
            row = basis.iloc[0]
            checks.update({
                "workbook_final_net_settlement_eur": float(row["final_net_settlement_cost_eur"]),
                "workbook_settlement_error": float(abs(float(row["final_net_settlement_cost_eur"]) - system_total)),
                "workbook_objective_eur": float(row["objective_eur"]),
                "workbook_final_slack_eur": float(row["final_round_slack_eur"]),
                "corrective_solver_objective_eur": float(row["solver_objective_eur"]),
                "objective_is_settlement_error": float(abs(
                    float(row["objective_eur"]) - float(row["final_round_slack_eur"]) - system_total)),
            })
    return checks


def _remove_file(path, attempts=5):
    """Delete one file, clearing read-only and retrying briefly.

    On Windows, and above all inside a
    cloud-synced folder, a file or folder being synced (or open in Explorer/Excel)
    refuses deletion for a moment with WinError 5.  A second run of a case then
    died in shutil.rmtree on its own previous results.
    """
    import time
    for attempt in range(attempts):
        try:
            if os.path.exists(path):
                os.chmod(path, stat.S_IWRITE)
                os.remove(path)
            return True
        except OSError:
            time.sleep(0.2 * (attempt + 1))
    return False


def clear_tree_files(root):
    """Remove every FILE under ``root`` but keep the folders.

    Folders are what sync clients and Explorer
    hold on to, so they are left in place and only their files are removed.  A
    file that still cannot be removed is reported, not fatal.
    """
    locked = []
    if not os.path.isdir(root):
        return locked
    for walk_root, _, files in os.walk(root):
        for name in files:
            path = os.path.join(walk_root, name)
            if not _remove_file(path):
                locked.append(path)
    if locked:
        print(f"WARNING: {len(locked)} file(s) could not be removed under {root} "
              f"(open or being synced?); they are overwritten where possible.")
    return locked


def sync_tree(source, target):
    """Make ``target`` an exact copy of ``source`` without deleting any folder.

    Replaces the rmtree-then-copytree
    pattern.  Files are overwritten in place and files that no longer exist in
    ``source`` are removed, so a re-run never fails on a locked folder.
    """
    source = os.path.abspath(source)
    target = os.path.abspath(target)
    wanted = set()
    for walk_root, _, files in os.walk(source):
        rel = os.path.relpath(walk_root, source)
        os.makedirs(os.path.join(target, rel), exist_ok=True)
        for name in files:
            wanted.add(os.path.normcase(os.path.join(rel, name)))
            dst = os.path.join(target, rel, name)
            if os.path.exists(dst):
                os.chmod(dst, stat.S_IWRITE)
            shutil.copy2(os.path.join(walk_root, name), dst)
    for walk_root, _, files in os.walk(target):
        rel = os.path.relpath(walk_root, target)
        for name in files:
            if os.path.normcase(os.path.join(rel, name)) not in wanted:
                _remove_file(os.path.join(walk_root, name))
    return target


def snapshot_market_stage(
    _output_root,
    _output_ts_root,
    _market_result_file,
    _iteration,
    _sensitivity_root="",
    _pilot_bus=None,
    _sim_tag=None,  # Archive only this run's matrices
):
    """Copy one market/AC-validation stage into a non-overwritten folder."""
    # Corrective markets reuse the normal
    # output filenames while running, so every stage is snapshotted before the
    # next pass can overwrite workbooks, post-market AC CSVs, or visual inputs.
    iteration = int(_iteration)
    stage_name = (
        "stage_00_initial"
        if iteration == 0 else f"stage_{iteration:02d}_corrective"
    )
    label = stage_label(iteration)
    output_root = os.path.abspath(_output_root)
    stage_root = os.path.join(output_root, "ACCorrectionStages", stage_name)
    os.makedirs(stage_root, exist_ok=True)

    market_result_file = os.path.abspath(_market_result_file)
    if os.path.isfile(market_result_file):
        shutil.copy2(
            market_result_file,
            os.path.join(stage_root, os.path.basename(market_result_file)),
        )

    output_ts_root = os.path.abspath(_output_ts_root)
    if os.path.isdir(output_ts_root):
        ts_target = os.path.join(stage_root, "FullTS_postMKT")
        # Overwrite in place instead of
        # rmtree + copytree, which failed with WinError 5 on a re-run.
        sync_tree(output_ts_root, ts_target)

    for filename in (
        "total_cm_PreMKT.xlsx",
        "VM_Problems_Stats_preMKT.xlsx",
        "CMHoursToStudy.csv",
        "VCHoursToStudy.csv",
    ):
        source = os.path.join(output_root, filename)
        if os.path.isfile(source):
            shutil.copy2(source, os.path.join(stage_root, filename))

    if _pilot_bus is not None:
        # The market writes VA and
        # alpha_DVpu with a positional row index, so the accuracy analysis needs
        # this stage's own pilot-bus order to pair each row with the right AC bus
        # voltage.  A corrective iteration may expand the represented pilot-bus
        # set, so the order is recorded per stage rather than once per scenario.
        pd.DataFrame({
            "va_row": range(len(list(_pilot_bus))),
            "bus": list(_pilot_bus),
        }).to_csv(os.path.join(stage_root, "PilotBusOrder.csv"), index=False)

    # Archive the sensitivity matrices this
    # stage actually cleared on, next to the result it produced.
    #
    # The initial matrices live in the reusable cache shared by every scenario of
    # a network, and the corrective ones live in an iteration cache that is
    # deliberately deleted before it is rebuilt, so neither survives the next run
    # of the same scenario.  That makes it impossible to compare, after the fact,
    # the linearisation the initial market used with the one a corrective market
    # was given -- which is exactly the comparison that says whether relinearising
    # changed anything.  Copying them into the stage folder makes each stage's
    # matrices permanent, self-describing and directly comparable.
    sensitivity_root = os.path.abspath(str(_sensitivity_root)) if _sensitivity_root else ""
    archived_sensitivity_root = ""
    archived_matrix_count = 0
    if sensitivity_root and os.path.isdir(sensitivity_root):
        archived_sensitivity_root = os.path.join(stage_root, "sensitivity_matrices")
        # Clear the previous archive's
        # files, keep the folder (no rmtree on a possibly locked folder).
        clear_tree_files(archived_sensitivity_root)
        os.makedirs(archived_sensitivity_root, exist_ok=True)
        # The initial cache is shared by
        # every run of the network, so it also holds the matrices of other
        # simulation tags (other runs, earlier check runs).  Copying all of
        # them put 834 files into every stage of every case, and the figures that
        # scan the case folder read them all.  With _sim_tag only the matrices of
        # this run (<name>_h<hour>_<sim_tag>.csv) are archived.
        own_matrix = (
            re.compile(r"^[A-Za-z]+(?:_FSP[A-Za-z0-9]+)?_h\d+_" + re.escape(str(_sim_tag)) + r"\.csv$")
            if _sim_tag else None
        )
        for entry in sorted(os.listdir(sensitivity_root)):
            source = os.path.join(sensitivity_root, entry)
            if os.path.isfile(source) and entry.lower().endswith(".csv"):
                if own_matrix is not None and not own_matrix.match(entry):
                    continue
                shutil.copy2(source, os.path.join(archived_sensitivity_root, entry))
                archived_matrix_count += 1

    manifest = pd.DataFrame([{
        "iteration": iteration,
        "stage_name": stage_name,
        "stage_label": label,
        "market_stage": "main" if iteration == 0 else "corrective",
        "stage_root": stage_root,
        "market_result_file": os.path.join(stage_root, os.path.basename(market_result_file)),
        "post_market_ts_root": os.path.join(stage_root, "FullTS_postMKT"),
        "sensitivity_cache_root": sensitivity_root,
        "sensitivity_archive_root": archived_sensitivity_root,
        "sensitivity_matrix_files": archived_matrix_count,
    }])
    manifest.to_csv(os.path.join(stage_root, "ACCorrectionStageManifest.csv"), index=False)
    return stage_root


MAIN_MARKET_FOLDER = "main_market_results"


def export_main_market_csv(_output_root, _main_stage_root, _final_iteration):
    """Write the MAIN (initial) market of one case as plain CSV files.

    The case folder shows the FINAL market
    -- the settled result after the last corrective market -- and every figure is
    drawn from it.  The main market is kept only as data, for comparing it with
    the final market after the simulation:

        <case>/main_market_results/
            market/<sheet>.csv          every sheet of the main market workbook
            FullTS_postMKT/...          the AC power flow after the main market
            PilotBusOrder.csv           pilot-bus order of the VA / alpha rows
            README.txt                  what the folder is and how it relates
                                        to the final market

    When no corrective market ran, the final market IS the main market; the
    folder is still written so every case has the same layout.
    """
    stage_root = os.path.abspath(str(_main_stage_root))
    target = os.path.join(os.path.abspath(_output_root), MAIN_MARKET_FOLDER)
    # Clear files, keep folders, so a
    # re-run never fails on a folder that a sync client or Explorer holds open.
    clear_tree_files(target)
    os.makedirs(os.path.join(target, "market"), exist_ok=True)

    workbooks = sorted(
        name for name in os.listdir(stage_root)
        if name.lower().endswith(".xlsx") and name.startswith("model_results")
    ) if os.path.isdir(stage_root) else []
    sheet_count = 0
    if workbooks:
        sheets = pd.read_excel(os.path.join(stage_root, workbooks[0]), sheet_name=None, index_col=0)
        for sheet_name, frame in sheets.items():
            safe = re.sub(r"[^A-Za-z0-9._-]", "_", str(sheet_name))
            frame.to_csv(os.path.join(target, "market", safe + ".csv"))
            sheet_count += 1

    ts_source = os.path.join(stage_root, "FullTS_postMKT")
    if os.path.isdir(ts_source):
        sync_tree(ts_source, os.path.join(target, "FullTS_postMKT"))
    for filename in ("PilotBusOrder.csv", "ACCorrectionStageManifest.csv"):
        source = os.path.join(stage_root, filename)
        if os.path.isfile(source):
            shutil.copy2(source, os.path.join(target, filename))

    final_iteration = int(_final_iteration)
    with open(os.path.join(target, "README.txt"), "w", encoding="utf-8") as handle:
        handle.write(
            "MAIN (initial) market of this case, as CSV, for comparison only.\n\n"
            "The case folder above holds the FINAL market: the settled result after "
            "the last corrective market, and every figure under visualization/ is "
            "drawn from it.\n\n"
            + (
                "No corrective market ran for this case, so the final market is "
                "identical to this main market.\n"
                if final_iteration == 0 else
                f"{final_iteration} corrective market(s) ran after this main market; "
                "the per-stage archive is in ACCorrectionStages/.\n"
            )
            + f"\nmarket/ holds {sheet_count} sheet(s) of the main market workbook "
            "(one CSV per sheet).\nFullTS_postMKT/ is the AC power flow after the "
            "main market.\n"
        )
    return target


def iteration_sensitivity_root(_input_root, _folder_name, _iteration, _reset=False,
                               _sim_tag=None):
    """Return a separate cache folder for one AC relinearization iteration.

    The folder is scoped by simulation tag.

    The path is derived from the network input folder, which every scenario of a
    study shares, and ``_reset`` deletes the whole folder so a corrective matrix
    is never reused.  Without the tag, two simulations on one network that reach
    their corrective round at the same time delete each other's matrices, and
    the second market dies on a missing HVM file:

        FileNotFoundError: ...ACOperatingPointSensitivity/iteration_01/
                              HVMP_FSPA_h00_<tag>.csv

    The matrix filenames already carry the tag, so only the reset collided.
    Giving each simulation tag its own subfolder makes concurrent runs safe
    while keeping the guarantee that a corrective matrix is always rebuilt.
    ``_sim_tag=None`` reproduces the previous unscoped path.
    """
    safe_folder = str(_folder_name or "ACOperatingPointSensitivity").strip()
    if not safe_folder:
        safe_folder = "ACOperatingPointSensitivity"
    parts = [os.path.abspath(_input_root), safe_folder]
    if _sim_tag is not None and str(_sim_tag).strip():
        # Keep the folder name filesystem-safe whatever the tag contains.
        parts.append(re.sub(r"[^A-Za-z0-9._-]", "_", str(_sim_tag).strip()))
    parts.append(f"iteration_{int(_iteration):02d}")
    # post-dispatch Jacobian matrices
    # never overwrite the reusable initial operating-point sensitivity cache.
    root = os.path.join(*parts)
    input_root = os.path.abspath(_input_root)
    if os.path.commonpath((input_root, os.path.abspath(root))) != input_root:
        raise ValueError('Corrective sensitivity root escaped the market input folder.')
    if _reset and os.path.isdir(root):
        # Corrective operating-point
        # sensitivities are run-specific and must never be reused.
        def clear_readonly_and_retry(function, failed_path, _error_info):
            os.chmod(failed_path, stat.S_IWRITE)
            function(failed_path)

        try:
            shutil.rmtree(root, onerror=clear_readonly_and_retry)
        except OSError:
            # A folder held by a sync client or
            # Explorer cannot be removed; removing its files is enough to
            # guarantee that no corrective matrix is ever reused.
            clear_tree_files(root)
    os.makedirs(root, exist_ok=True)
    return root


def validation_record(
    _iteration,
    _summary,
    _vmin_opt,
    _vmax_opt,
    _ds_tol,
    _smax,
    _linearization="initial",
    _sensitivity_root="",
):
    """Create one compact, CSV-ready AC-validation audit record."""
    smax_series = _smax.iloc[:, 0] if isinstance(_smax, pd.DataFrame) else pd.Series(_smax)
    normalized_margin = _ds_tol.div(smax_series, axis=0) * 100.0
    corrective = int(_iteration) > 0
    return {
        "iteration": int(_iteration),
        # Expose sequential capacity and
        # sensitivity provenance directly in the validation CSV.
        "market_stage": "corrective_remaining_capacity" if corrective else "initial_market",
        "fsp_capacity_basis": "remaining_after_first_dispatch" if corrective else "original_available_capacity",
        "sensitivity_policy": "fresh_post_dispatch" if corrective else "reusable_initial",
        "linearization_operating_point": str(_linearization),
        "sensitivity_cache_root": str(_sensitivity_root),
        "optimization_vmin_pu": float(_vmin_opt),
        "optimization_vmax_pu": float(_vmax_opt),
        "maximum_cm_margin_percent": float(normalized_margin.max().max())
        if not normalized_margin.empty
        else 0.0,
        "post_max_loading_percent": _summary["max_loading_percent"],
        "post_overload_cell_count": _summary["overload_cell_count"],
        "post_max_overload_percentage_points": _summary["max_overload_percentage_points"],
        "post_min_voltage_pu": _summary["min_voltage_pu"],
        "post_max_voltage_pu": _summary["max_voltage_pu"],
        "post_voltage_violation_cell_count": _summary["voltage_violation_cell_count"],
        "post_max_voltage_violation_pu": _summary["max_voltage_violation_pu"],
    }
