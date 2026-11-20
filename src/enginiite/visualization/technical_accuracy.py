"""Technical comparison figures of the accuracy of the linear market model: hourly cell map and predicted against actual scatter.
"""
from __future__ import annotations

import os
import glob
import re
from typing import Optional, Dict, Any, List, Tuple

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from . import window_mode
from . import figure_helpers as eva
from . import accuracy_core


# Reuse the final Phase-2 numerical tolerance.
ACTIVATION_ZERO_TOL = getattr(eva, "ACTIVATION_ZERO_TOL", 1e-6)


COMPARISON_ROOT_FOLDER = "comparison"


COMPARISON_CATEGORIES = {
    "technical": "technical comparison",
}


COMPARISON_FIGURE_CATEGORIES = {
    "ProductDesignResponseCurve": "technical",
    "TechnicalSecurityTrendByFlex": "technical",
    "TechnicalProductFlexHeatmap": "technical",
    "TechnicalHourlyCellAccuracyMap": "technical",
    "TechnicalAveragePredictedVsActualScatter": "technical",
}


def _scenario_bundle_root(output_folder: str, market_tag: str) -> str:
    """Return the one shared scenario-bundle folder under data_out.

    Example
    -------
    output_folder = .../data_out/net_CMVC_SK01_T1/net_CMVC_PQ_.../visualization
    returns       = .../data_out/net_CMVC_SK01_T1

    This prevents duplicated comparison figures inside every scenario's
    visualization folder.  All multi-scenario comparison outputs are written
    once to data_out/<scenario_bundle>/comparison/...
    """
    norm = os.path.abspath(str(output_folder or os.getcwd()))
    parts = norm.split(os.sep)
    if "data_out" in parts:
        idx = parts.index("data_out")
        if idx + 1 < len(parts) and parts[idx + 1].lower() != "comparison":
            return os.sep.join(parts[:idx + 2])

    try:
        visualization_root = eva._resolve_scenario_visualization_folder(output_folder, market_tag)
        scenario_root = eva._scenario_root_from_visualization(visualization_root)
        parent = os.path.dirname(os.path.abspath(scenario_root))
        if os.path.isdir(parent):
            return parent
    except Exception:
        pass

    group = None
    try:
        group = eva._scenario_group_from_market_tag(market_tag)
    except Exception:
        group = None
    if "data_out" in parts:
        idx = parts.index("data_out")
        data_out_root = os.sep.join(parts[:idx + 1])
        if group:
            return os.path.join(data_out_root, group)
        return data_out_root
    return os.path.abspath(os.path.join(norm, "comparison_bundle"))


def _comparison_category_from_filename(filename: str) -> str:
    name = str(filename)
    for prefix, cat in COMPARISON_FIGURE_CATEGORIES.items():
        if name.startswith(prefix):
            return cat
    return "technical"


def _comparison_output_folder(output_folder: str, market_tag: str, category: str) -> str:
    bundle = _scenario_bundle_root(output_folder, market_tag)
    category_folder = COMPARISON_CATEGORIES.get(category, COMPARISON_CATEGORIES["technical"])
    return eva._ensure_folder(os.path.join(bundle, COMPARISON_ROOT_FOLDER, category_folder))


def _save_comparison_fig(
    fig: go.Figure,
    filename: str,
    output_folder: str,
    market_tag: str,
    header_title: str,
    figure_note: str = "",
) -> str:
    """Save a scenario-comparison figure once at bundle level.

    Output structure:
        data_out/<scenario_bundle>/comparison/
            technical comparison/
    """
    if not filename.endswith(".html"):
        filename += ".html"
    # Use the bundle name in filenames, not the current scenario tag.
    # This avoids duplicated comparison outputs when the comparison is drawn
    # once per scenario; each run overwrites the same bundle-level comparison.
    bundle_tag = os.path.basename(os.path.normpath(_scenario_bundle_root(output_folder, market_tag)))
    filename = str(filename).replace(str(market_tag), bundle_tag)
    category = _comparison_category_from_filename(filename)
    folder = _comparison_output_folder(output_folder, market_tag, category)
    html_path = os.path.join(folder, filename)
    # Comparison figures are bundle-level outputs, not a single scenario view.
    # Clear the plot-area scenario title inserted by the shared IEEE layout and
    # keep only the concise blue HTML header title.
    fig.update_layout(title=dict(text=""))
    try:
        eva._polish_axis_units_and_overlap(fig)
    except Exception:
        pass
    eva._write_themed_plotly_html(fig, html_path, header_title, figure_note=figure_note)
    print("Saved comparison:", html_path)
    return html_path


def _scenario_ordered(df: pd.DataFrame) -> pd.DataFrame:
    """Sort scenarios consistently by product family and increasing F-case."""
    if df is None or df.empty:
        return pd.DataFrame()
    out = _decorate_comparison_dimensions(df).copy()
    product_order = {"P": 0, "Q": 1, "PQ": 2}
    out["_product_order"] = out["product"].map(product_order).fillna(99)
    flex_level = out["flex_level"] if "flex_level" in out.columns else pd.Series(np.nan, index=out.index)
    out["_flex_order"] = pd.to_numeric(flex_level, errors="coerce").fillna(999)
    out = out.sort_values(["_product_order", "_flex_order", "short_label", "scenario"]).reset_index(drop=True)
    return out.drop(columns=[c for c in ["_product_order", "_flex_order"] if c in out.columns])


def _scenario_product_order(label: str) -> int:
    product_order = {"P": 0, "Q": 1, "PQ": 2}
    return int(product_order.get(str(_parse_scenario_dimensions(label).get("product") or ""), 99))


def _scenario_flex_order(label: str) -> int:
    try:
        return int(float(_parse_scenario_dimensions(label).get("flex_level")))
    except Exception:
        return 999


def _apply_phase3_layout(fig: go.Figure, market_tag: str, height: int = 820, show_legend: bool = True) -> go.Figure:
    eva._apply_ieee_layout(fig, market_tag, height=height, show_legend=show_legend)
    fig.update_layout(
        hovermode="closest",
        hoverlabel=dict(
            bgcolor="rgba(255,255,255,0.98)",
            bordercolor="rgba(75,85,99,0.55)",
            font=dict(family="Times New Roman, Times, serif", size=14, color="#111827"),
            namelength=-1,
        ),
        colorway=["#4C78A8", "#72B7B2", "#54A24B", "#F58518", "#9C755F", "#B279A2", "#79706E", "#BAB0AC"],
    )
    return fig


def _safe_div(num: float, den: float, default: float = 0.0) -> float:
    try:
        den = float(den)
        if abs(den) <= 1e-12:
            return default
        return float(num) / den
    except Exception:
        return default


def _finite_abs_max(*values, default: float = 1.0) -> float:
    """Return a finite, positive full-data scale for accuracy colorbars."""
    maxima = []
    for value in values:
        array = np.asarray(value, dtype=float)
        finite = np.abs(array[np.isfinite(array)])
        if finite.size:
            maxima.append(float(np.max(finite)))
    maximum = max(maxima) if maxima else 0.0
    return maximum if maximum > 1e-12 else float(default)


def _normalise_series(s: pd.Series) -> pd.Series:
    s = pd.to_numeric(s, errors="coerce").fillna(0.0).astype(float)
    mx = float(s.max()) if len(s) else 0.0
    if mx <= 1e-12:
        return pd.Series(np.zeros(len(s)), index=s.index, dtype=float)
    return s / mx


def _parse_scenario_dimensions(label: str) -> Dict[str, Any]:
    """Parse platform scenario tags such as net_CMVC_PQ_VL01_F05_SK01_T1."""
    s = str(label or "")
    out = {"network": "", "market": "", "product": "", "voltage_level": "", "flex_case": "", "flex_level": np.nan, "storage_case": "", "ess_case": ""}
    parts = s.split("_")
    if len(parts) >= 2:
        out["network"] = parts[0]
        out["market"] = parts[1]
    # robust regex parsing
    m = re.search(r"_(PQ|P|Q)_", s)
    if m:
        out["product"] = m.group(1)
    m = re.search(r"_(VL\d+)_", s)
    if m:
        out["voltage_level"] = m.group(1)
    m = re.search(r"_(F\d+)_", s)
    if m:
        out["flex_case"] = m.group(1)
        try:
            out["flex_level"] = int(m.group(1).replace("F", ""))
        except Exception:
            pass
    m = re.search(r"_(SK\d+)_", s)
    if m:
        out["storage_case"] = m.group(1)
    m = re.search(r"_(\d+ESS)$", s)
    if m:
        out["ess_case"] = m.group(1)
    return out


def _scenario_label_short(label: str) -> str:
    """Compact scenario label for comparison figures.

    Examples
    --------
    net_CMVC_PQ_VL01_F05_SK01_T1 -> PQ-F05
    net_CMVC_P_VL01_F01_SK01_T1  -> P-F01

    The storage case is intentionally omitted in comparison plots to avoid
    long, repeated axis labels when all compared scenarios share the same
    storage configuration.
    """
    dims = _parse_scenario_dimensions(label)
    product = str(dims.get("product") or "?")
    flex_case = str(dims.get("flex_case") or "?")
    return f"{product}-{flex_case}"


def _product_style(product: Any) -> Dict[str, str]:
    """Consistent product color/marker map for all comparison figures."""
    product = str(product)
    colors = {"P": "#4C78A8", "Q": "#54A24B", "PQ": "#9C755F"}
    symbols = {"P": "circle", "Q": "square", "PQ": "diamond"}
    return {"color": colors.get(product, "#79706E"), "symbol": symbols.get(product, "circle")}


def _auto_discover_sibling_scenarios(output_folder: str, market_tag: str) -> List[str]:
    """Find scenario folders next to the current scenario folder.

    General platform logic: when output_folder is .../<scenario>/visualization,
    the parent directory normally contains all scenario folders for the same
    simulation bundle. This avoids hard-coded machine paths and allows scenario
    comparison without manually passing scenario_roots.
    """
    try:
        viz = eva._resolve_scenario_visualization_folder(output_folder, market_tag)
        current_root = eva._scenario_root_from_visualization(viz)
    except Exception:
        base = os.path.abspath(output_folder or os.getcwd())
        current_root = os.path.dirname(base) if os.path.basename(base).lower() == "visualization" else base
    parent = os.path.dirname(current_root)
    if not os.path.isdir(parent):
        return []
    roots = []
    for d in sorted(glob.glob(os.path.join(parent, "*"))):
        if not os.path.isdir(d):
            continue
        if os.path.basename(d).startswith("KPI_") or os.path.basename(d).lower() in {"visualization"}:
            continue
        if glob.glob(os.path.join(d, "model_results_*.xlsx")):
            roots.append(os.path.abspath(d))
    # Keep scenarios from the same network/storage bundle when possible.
    dims = _parse_scenario_dimensions(market_tag)
    net = dims.get("network")
    sk = dims.get("storage_case")
    filtered = []
    for r in roots:
        b = os.path.basename(r)
        if net and not b.startswith(net + "_"):
            continue
        if sk and ("_" + sk + "_") not in ("_" + b + "_"):
            continue
        filtered.append(r)
    return filtered or roots


def _decorate_comparison_dimensions(comparison: pd.DataFrame) -> pd.DataFrame:
    if comparison is None or comparison.empty:
        return pd.DataFrame()
    df = comparison.copy()
    def _numeric_column(name: str, default: float = 0.0) -> pd.Series:
        if name in df.columns:
            return pd.to_numeric(df[name], errors="coerce").fillna(default)
        return pd.Series(default, index=df.index, dtype=float)
    dims = df["scenario"].apply(_parse_scenario_dimensions).apply(pd.Series)
    for c in dims.columns:
        if c not in df.columns:
            df[c] = dims[c]
    df["short_label"] = df["scenario"].apply(_scenario_label_short)
    df["local_market_power_index"] = (
        _normalise_series(_numeric_column("residual_hours")) * 0.30
        + _numeric_column("avg_hhi") * 0.45
        + (_numeric_column("top_provider_share_pct") / 100.0) * 0.25
    )
    df["security_score"] = 0.60 * _numeric_column("cm_relief_pct") + 0.40 * _numeric_column("voltage_relief_pct")
    return df


def _market_concentration_statement(hhi: float) -> str:
    h = float(hhi or 0.0)
    if h >= 0.75:
        return "Very high concentration risk / market power"
    if h >= 0.50:
        return "High concentration risk"
    if h >= 0.25:
        return "Moderate concentration"
    if h > 0.0:
        return "Low concentration / diversified response"
    return "No activated market response"


def _find_timeseries_root_for_scenario(scenario_root: str, stage: str) -> Optional[str]:
    """Find pre/post pandapower time-series folder for a scenario.

    The platform usually stores the post-market power-flow results in
    ``scenario_root/FullTS_postMKT``.  Some runs also store
    ``FullTS_preMKT`` or equivalent names.  Scenario-comparison figures must
    not silently set voltage/overload values to zero when these folders are not
    passed from ``main.py``.  This helper searches only inside the scenario
    folder and its parent bundle, so it remains general and machine independent.
    """
    if not scenario_root:
        return None
    root = os.path.abspath(str(scenario_root))
    stage_low = str(stage).lower()
    if stage_low.startswith("post"):
        candidates = [
            "FullTS_postMKT", "FullTS_post_market", "postMKT", "post_market",
            "TimeSeries_postMKT", "TS_postMKT",
        ]
    else:
        candidates = [
            "FullTS_preMKT", "FullTS_pre_market", "preMKT", "pre_market",
            "TimeSeries_preMKT", "TS_preMKT", "FullTS_pre",
        ]
    search_roots = [root, os.path.dirname(root)]
    for sr in search_roots:
        for name in candidates:
            path = os.path.join(sr, name)
            if os.path.isdir(path) and os.path.isdir(os.path.join(path, "res_bus")):
                return path
    # bounded fuzzy search
    keys = ["post" if stage_low.startswith("post") else "pre", "ts"]
    try:
        for sr in search_roots:
            for dirpath, dirnames, _ in os.walk(sr):
                rel = os.path.relpath(dirpath, sr)
                depth = 0 if rel == "." else rel.count(os.sep) + 1
                if depth > 3:
                    dirnames[:] = []
                    continue
                low = os.path.basename(dirpath).lower()
                if all(k in low for k in keys) and os.path.isdir(os.path.join(dirpath, "res_bus")):
                    return dirpath
    except Exception:
        pass
    return None


def _read_voltage_exposure_from_problem_stats(path: Optional[str], stage: str, vmin: float, vmax: float) -> pd.DataFrame:
    """Fallback voltage exposure reader from VM_Problems_Stats_*.xlsx.

    Unit: pu-deviation exposure outside [vmin, vmax], grouped by studied hour.
    This is used when the full pandapower pre/post vm_pu.csv folders are not
    available during scenario comparison.
    """
    if path is None or not os.path.exists(str(path)):
        return pd.DataFrame(columns=["hour", "voltage_exposure_pu", "max_vm_pu", "min_vm_pu", "stage"])
    rows = []
    try:
        xl = pd.ExcelFile(path)
    except Exception:
        return pd.DataFrame(columns=["hour", "voltage_exposure_pu", "max_vm_pu", "min_vm_pu", "stage"])
    for sheet in ["Vbus_over", "Vbus_under"]:
        if sheet not in xl.sheet_names:
            continue
        try:
            df = pd.read_excel(path, sheet_name=sheet)
        except Exception:
            continue
        if df is None or df.empty or "TimeStep" not in df.columns or "VMpu" not in df.columns:
            continue
        tmp = df[["TimeStep", "VMpu"]].copy()
        tmp["hour"] = pd.to_numeric(tmp["TimeStep"], errors="coerce")
        tmp["vm"] = pd.to_numeric(tmp["VMpu"], errors="coerce")
        tmp = tmp.dropna(subset=["hour", "vm"])
        if tmp.empty:
            continue
        if sheet == "Vbus_over":
            tmp["exposure"] = np.maximum(tmp["vm"].astype(float) - float(vmax), 0.0)
        else:
            tmp["exposure"] = np.maximum(float(vmin) - tmp["vm"].astype(float), 0.0)
        for h, g in tmp.groupby("hour"):
            rows.append({
                "hour": int(h),
                "voltage_exposure_pu": float(g["exposure"].sum()),
                "max_vm_pu": float(g["vm"].max()),
                "min_vm_pu": float(g["vm"].min()),
                "stage": stage,
            })
    if not rows:
        return pd.DataFrame(columns=["hour", "voltage_exposure_pu", "max_vm_pu", "min_vm_pu", "stage"])
    out = pd.DataFrame(rows).groupby("hour", as_index=False).agg(
        voltage_exposure_pu=("voltage_exposure_pu", "sum"),
        max_vm_pu=("max_vm_pu", "max"),
        min_vm_pu=("min_vm_pu", "min"),
    )
    out["stage"] = stage
    return out


def _complete_voltage_table_from_fallbacks(voltage: pd.DataFrame, scenario_root: str, vmin: float, vmax: float) -> pd.DataFrame:
    """Complete missing pre/post voltage exposure using VM_Problems_Stats files."""
    frames = [] if voltage is None or voltage.empty else [voltage.copy()]
    existing_stages = set(voltage["stage"].astype(str)) if voltage is not None and not voltage.empty and "stage" in voltage.columns else set()
    if "Pre-market" not in existing_stages:
        pre = _read_voltage_exposure_from_problem_stats(os.path.join(scenario_root, "VM_Problems_Stats_preMKT.xlsx"), "Pre-market", vmin, vmax)
        if not pre.empty:
            frames.append(pre)
    if "Post-market" not in existing_stages:
        post = _read_voltage_exposure_from_problem_stats(os.path.join(scenario_root, "VM_Problems_Stats_postMKT.xlsx"), "Post-market", vmin, vmax)
        if not post.empty:
            frames.append(post)
    if not frames:
        return pd.DataFrame(columns=["hour", "voltage_exposure_pu", "max_vm_pu", "min_vm_pu", "stage"])
    return pd.concat(frames, ignore_index=True)


def _complete_ts_roots_for_scenario(scenario_root: str, pre_ts_root: Optional[str], post_ts_root: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Use explicit TS folders when provided, otherwise discover them per scenario."""
    pre = pre_ts_root if pre_ts_root and os.path.exists(str(pre_ts_root)) else _find_timeseries_root_for_scenario(scenario_root, "pre")
    post = post_ts_root if post_ts_root and os.path.exists(str(post_ts_root)) else _find_timeseries_root_for_scenario(scenario_root, "post")
    return pre, post


def _read_ts_bus_voltage_matrix(ts_root: Optional[str]) -> pd.DataFrame:
    """Read vm_pu.csv as bus x hour with string labels."""
    if not ts_root:
        return pd.DataFrame()
    path = os.path.join(str(ts_root), "res_bus", "vm_pu.csv")
    if not os.path.exists(path):
        return pd.DataFrame()
    try:
        df = pd.read_csv(path, index_col=0)
        df = df.apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
        out = df.T
        out.index = [str(i) for i in out.index]
        out.columns = [str(c) for c in out.columns]
        return out
    except Exception:
        return pd.DataFrame()


def _read_model_sheet_numeric(xls: pd.ExcelFile, sheet_name: str) -> pd.DataFrame:
    """Read model-results sheet case-insensitively as numeric dataframe."""
    target = str(sheet_name).strip().lower().replace(" ", "").replace("-", "_")
    actual = None
    for sh in xls.sheet_names:
        key = str(sh).strip().lower().replace(" ", "").replace("-", "_")
        if key == target:
            actual = sh
            break
    if actual is None:
        return pd.DataFrame()
    try:
        df = pd.read_excel(xls, sheet_name=actual, index_col=0)
        df = df.apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan).fillna(0.0)
        df.index = [str(i) for i in df.index]
        df.columns = [str(c) for c in df.columns]
        return df
    except Exception:
        return pd.DataFrame()


def _align_model_voltage_sheet(df: pd.DataFrame, target_index, target_columns) -> pd.DataFrame:
    """Align a model-results voltage sheet to a bus x hour AC matrix."""
    target_index = [str(i) for i in target_index]
    target_columns = [str(c) for c in target_columns]
    if df is None or df.empty:
        return pd.DataFrame(index=target_index, columns=target_columns, dtype=float)
    out = df.copy()
    out.index = [str(i) for i in out.index]
    out.columns = [str(c) for c in out.columns]
    # If the sheet was written as hour x bus, transpose it.
    if len([c for c in target_columns if c in out.index]) > len([c for c in target_columns if c in out.columns]):
        out = out.T
        out.index = [str(i) for i in out.index]
        out.columns = [str(c) for c in out.columns]
    aligned = pd.DataFrame(np.nan, index=target_index, columns=target_columns, dtype=float)
    common_cols = [c for c in target_columns if c in out.columns]
    if not common_cols:
        n = min(len(target_columns), out.shape[1])
        tmp = out.iloc[:, :n].copy()
        tmp.columns = target_columns[:n]
    else:
        tmp = out[common_cols].copy()
    common_rows = [r for r in target_index if r in tmp.index]
    if common_rows:
        aligned.loc[common_rows, [c for c in tmp.columns if c in aligned.columns]] = tmp.loc[common_rows, [c for c in tmp.columns if c in aligned.columns]].to_numpy(dtype=float)
    elif tmp.shape[0] and len(target_index):
        nr = min(len(target_index), tmp.shape[0])
        nc = min(len(target_columns), tmp.shape[1])
        aligned.iloc[:nr, :nc] = tmp.iloc[:nr, :nc].to_numpy(dtype=float)
    return aligned


def _voltage_residual_matrix_local(vm: pd.DataFrame, vmin: float, vmax: float) -> pd.DataFrame:
    if vm is None or vm.empty:
        return pd.DataFrame()
    num = vm.apply(pd.to_numeric, errors="coerce")
    return (float(vmin) - num).clip(lower=0.0).fillna(0.0) + (num - float(vmax)).clip(lower=0.0).fillna(0.0)


def _infer_pilot_bus_ids_for_model(market_result_file: Optional[str]) -> List[str]:
    if not market_result_file:
        return []
    try:
        scenario_root = os.path.dirname(os.path.abspath(str(market_result_file)))
        path = os.path.join(scenario_root, "pilot_bus_vm_post.csv")
        if os.path.exists(path):
            return [str(c) for c in pd.read_csv(path, index_col=0, nrows=1).columns]
    except Exception:
        pass
    return []


def _raw_linear_voltage_accuracy_from_model(market_result_file: Optional[str], post_ts_root: Optional[str], vmin: float, vmax: float) -> Dict[str, float]:
    """Voltage accuracy using raw linear voltage = VA - alpha_DVpu.

    VA alone is bounded by the optimization voltage interval and must not be
    used as the linear voltage estimate.  This function reconstructs the raw
    sensitivity estimate from the model-results workbook and compares it with
    FullTS_postMKT/res_bus/vm_pu.csv.
    """
    if not market_result_file or not os.path.exists(str(market_result_file)):
        return {}
    post_vm = _read_ts_bus_voltage_matrix(post_ts_root)
    if post_vm.empty:
        return {}
    try:
        xls = pd.ExcelFile(market_result_file)
        va = _read_model_sheet_numeric(xls, "VA")
        if va.empty:
            return {}
        pilot_ids = _infer_pilot_bus_ids_for_model(market_result_file)
        if pilot_ids and len(pilot_ids) == va.shape[0]:
            va = va.copy()
            va.index = [str(x) for x in pilot_ids]
        alpha = _read_model_sheet_numeric(xls, "alpha_DVpu")
        if alpha.empty:
            alpha = _read_model_sheet_numeric(xls, "ABS_alpha_DVpu")
        if alpha.empty:
            alpha = _read_model_sheet_numeric(xls, "ABS_alphaDVpu")
        if pilot_ids and not alpha.empty and len(pilot_ids) == alpha.shape[0]:
            alpha = alpha.copy()
            alpha.index = [str(x) for x in pilot_ids]
        va_a = _align_model_voltage_sheet(va, post_vm.index, post_vm.columns)
        alpha_a = _align_model_voltage_sheet(alpha, post_vm.index, post_vm.columns).fillna(0.0)
        vlin = va_a - alpha_a
        if pilot_ids:
            pilot_set = {str(x) for x in pilot_ids}
            for r in vlin.index:
                if r not in pilot_set:
                    vlin.loc[r, :] = np.nan
        common_rows = [r for r in post_vm.index if r in vlin.index and vlin.loc[r].notna().any()]
        common_cols = [c for c in post_vm.columns if c in vlin.columns and vlin[c].notna().any()]
        if not common_rows or not common_cols:
            return {}
        ac = post_vm.loc[common_rows, common_cols].apply(pd.to_numeric, errors="coerce")
        lin = vlin.loc[common_rows, common_cols].apply(pd.to_numeric, errors="coerce")
        err = ac - lin
        vals = err.to_numpy(dtype=float).ravel()
        vals = vals[np.isfinite(vals)]
        lin_res = _voltage_residual_matrix_local(lin, vmin, vmax)
        lin_res_sum = float(np.nansum(lin_res.to_numpy(dtype=float)))
        if vals.size == 0:
            return {"linear_vc_residual_pu": lin_res_sum}
        return {
            "linear_vc_residual_pu": lin_res_sum,
            "vc_voltage_mae_pu": float(np.nanmean(np.abs(vals))),
            "vc_voltage_rmse_pu": float(np.sqrt(np.nanmean(vals ** 2))),
            "vc_voltage_max_abs_error_pu": float(np.nanmax(np.abs(vals))),
            "vc_voltage_bias_pu": float(np.nanmean(vals)),
            "vc_voltage_error_cells": int(vals.size),
        }
    except Exception:
        return {}


def _read_hcm_matrix_local(sens_root: str, kind: str, fsp_type: str, hour, sim_tag: str) -> pd.DataFrame:
    if not sens_root or not os.path.isdir(sens_root):
        return pd.DataFrame()
    try:
        hh = str(int(float(hour))).zfill(2)
    except Exception:
        hh = str(hour).zfill(2)
    fname = f"{kind}_FSP{fsp_type}_h{hh}_{sim_tag}.csv"
    path = os.path.join(sens_root, fname)
    if not os.path.exists(path):
        matches = [os.path.join(sens_root, f) for f in os.listdir(sens_root)
                   if f.startswith(f"{kind}_FSP{fsp_type}_h{hh}_") and f.endswith('.csv')]
        path = matches[0] if matches else path
    if not os.path.exists(path):
        return pd.DataFrame()
    try:
        return pd.read_csv(path, index_col=0).apply(pd.to_numeric, errors='coerce').fillna(0.0)
    except Exception:
        return pd.DataFrame()


def _sheet_value_by_hour_local(df: pd.DataFrame, row_pos: int, hour, hour_pos: int) -> float:
    if df is None or getattr(df, 'empty', True):
        return 0.0
    try:
        if row_pos >= df.shape[0]:
            return 0.0
        cols = [str(c) for c in df.columns]
        h = str(hour)
        if h in cols:
            val = pd.to_numeric(df.iloc[row_pos, cols.index(h)], errors='coerce')
        elif hour_pos < df.shape[1]:
            val = pd.to_numeric(df.iloc[row_pos, hour_pos], errors='coerce')
        else:
            return 0.0
        return float(val) if np.isfinite(float(val)) else 0.0
    except Exception:
        return 0.0


def _infer_model_study_hour_columns_local(sheets: Dict[str, pd.DataFrame]) -> List[str]:
    """Infer actual studied-hour labels from model action sheets."""
    if not isinstance(sheets, dict):
        return []
    for key in ['DW_A', 'DR_A', 'DW_B', 'DR_B', 'DW_C', 'DR_C', 'VA', 'alpha_DVpu']:
        df = sheets.get(key)
        if df is not None and not getattr(df, 'empty', True):
            return [str(int(c)) if isinstance(c, (int, float)) and float(c).is_integer() else str(c) for c in df.columns]
    return []


def _read_phase3_inputs(
    pre_ts_root: Optional[str],
    post_ts_root: Optional[str],
    market_result_file: Optional[str],
    output_folder: str,
    market_tag: str,
    vmin: float = 0.95,
    vmax: float = 1.05,
    sensitivity_root: Optional[str] = None,
) -> Dict[str, Any]:
    visualization_root = eva._resolve_scenario_visualization_folder(output_folder, market_tag)
    scenario_root = eva._scenario_root_from_visualization(visualization_root)

    # Critical for multi-scenario comparison: when sibling scenarios are loaded
    # automatically, main.py does not pass their pre/post time-series folders.
    # Discover them here, otherwise voltage/physical-overload metrics would be
    # silently evaluated as zero.
    pre_ts_root, post_ts_root = _complete_ts_roots_for_scenario(scenario_root, pre_ts_root, post_ts_root)

    if market_result_file is None or not os.path.exists(str(market_result_file)):
        candidate = eva._find_file(scenario_root, "model_results_" + market_tag + ".xlsx")
        market_result_file = candidate or market_result_file

    cm_need, overload_100, voltage = eva._build_security_tables(
        pre_ts_root=pre_ts_root,
        post_ts_root=post_ts_root,
        scenario_root=scenario_root,
        vmin=vmin,
        vmax=vmax,
    )
    # If vm_pu.csv is unavailable for pre or post state, use the platform's
    # VM_Problems_Stats files so voltage relief and residual-risk hours are not
    # incorrectly set to 100%/zero during comparison.
    voltage = _complete_voltage_table_from_fallbacks(voltage, scenario_root, vmin, vmax)
    activation = eva._read_corrected_activation_long(str(market_result_file)) if market_result_file else pd.DataFrame()
    act = eva._activation_with_product(activation)

    hourly = _build_phase3_hourly_table(cm_need, overload_100, voltage, act)
    providers = _build_provider_table(act, hourly)
    liquidity = _build_liquidity_table(act)
    technology = _build_technology_table(act)

    return {
        "visualization_root": visualization_root,
        "scenario_root": scenario_root,
        "market_result_file": market_result_file,
        "pre_ts_root": pre_ts_root,
        "post_ts_root": post_ts_root,
        "market_tag": market_tag,
        "cm_need": cm_need,
        "overload_100": overload_100,
        "voltage": voltage,
        "activation": act,
        "sensitivity_root": sensitivity_root,
        "vmin": vmin,
        "vmax": vmax,
        "hourly": hourly,
        "providers": providers,
        "liquidity": liquidity,
        "technology": technology,
    }


def _need_type(cm_value: float, v_value: float) -> str:
    cm_active = float(cm_value or 0.0) > ACTIVATION_ZERO_TOL
    vc_active = float(v_value or 0.0) > 1e-9
    if cm_active and vc_active:
        return "CMVC"
    if cm_active:
        return "CM"
    if vc_active:
        return "VC"
    return "No need"


def _need_type_code(label: str) -> int:
    return {"No need": 0, "CM": 1, "VC": 2, "CMVC": 3}.get(str(label), 0)


def _aggregate_by_stage_hour(
    df: Optional[pd.DataFrame],
    stage: str,
    value_candidates: List[str],
    output_col: str,
) -> pd.DataFrame:
    """Safely aggregate a technical table by hour for a requested stage.

    The Phase-2 helper may return different column names depending on the
    revision. For physical overload exposure, older code used
    'overload_exposure_pp' while the current helper returns
    'exposure_percent_point'. This helper accepts both and falls back to zeros
    instead of failing with a KeyError.
    """
    if df is None or df.empty:
        return pd.DataFrame(columns=["hour", output_col])
    work = df.copy()
    if "stage" in work.columns:
        work = work[work["stage"] == stage].copy()
    if work.empty or "hour" not in work.columns:
        return pd.DataFrame(columns=["hour", output_col])

    value_col = None
    for c in value_candidates:
        if c in work.columns:
            value_col = c
            break
    if value_col is None:
        return pd.DataFrame(columns=["hour", output_col])

    work[value_col] = pd.to_numeric(work[value_col], errors="coerce").fillna(0.0)
    return work.groupby("hour", as_index=False)[value_col].sum().rename(columns={value_col: output_col})


def _build_phase3_hourly_table(
    cm_need: pd.DataFrame,
    overload_100: pd.DataFrame,
    voltage: pd.DataFrame,
    act: pd.DataFrame,
) -> pd.DataFrame:
    # CM need from total_cm_PreMKT/postMKT.
    pre_cm = (
        cm_need[cm_need["stage"] == "Pre-market"].groupby("hour", as_index=False)["cm_need_mva"].sum().rename(columns={"cm_need_mva": "pre_cm_mva"})
        if cm_need is not None and not cm_need.empty else pd.DataFrame(columns=["hour", "pre_cm_mva"])
    )
    post_cm = (
        cm_need[cm_need["stage"] == "Post-market"].groupby("hour", as_index=False)["cm_need_mva"].sum().rename(columns={"cm_need_mva": "post_cm_mva"})
        if cm_need is not None and not cm_need.empty else pd.DataFrame(columns=["hour", "post_cm_mva"])
    )

    # Physical overload exposure above 100%, if available.
    # Phase 2 currently returns column 'exposure_percent_point'. Older Phase 3
    # expected 'overload_exposure_pp'. Support both names for compatibility.
    pre_over = _aggregate_by_stage_hour(
        overload_100,
        stage="Pre-market",
        value_candidates=["overload_exposure_pp", "exposure_percent_point", "exposure_pp"],
        output_col="pre_overload_pp",
    )
    post_over = _aggregate_by_stage_hour(
        overload_100,
        stage="Post-market",
        value_candidates=["overload_exposure_pp", "exposure_percent_point", "exposure_pp"],
        output_col="post_overload_pp",
    )

    pre_v = (
        voltage[voltage["stage"] == "Pre-market"].groupby("hour", as_index=False)["voltage_exposure_pu"].sum().rename(columns={"voltage_exposure_pu": "pre_voltage_pu"})
        if voltage is not None and not voltage.empty else pd.DataFrame(columns=["hour", "pre_voltage_pu"])
    )
    post_v = (
        voltage[voltage["stage"] == "Post-market"].groupby("hour", as_index=False)["voltage_exposure_pu"].sum().rename(columns={"voltage_exposure_pu": "post_voltage_pu"})
        if voltage is not None and not voltage.empty else pd.DataFrame(columns=["hour", "post_voltage_pu"])
    )

    p_act = (
        act[act["product"] == "P"].groupby("hour", as_index=False)["abs_value"].sum().rename(columns={"abs_value": "p_activation_mw"})
        if act is not None and not act.empty else pd.DataFrame(columns=["hour", "p_activation_mw"])
    )
    q_act = (
        act[act["product"] == "Q"].groupby("hour", as_index=False)["abs_value"].sum().rename(columns={"abs_value": "q_activation_mvar"})
        if act is not None and not act.empty else pd.DataFrame(columns=["hour", "q_activation_mvar"])
    )

    dfs = [pre_cm, post_cm, pre_over, post_over, pre_v, post_v, p_act, q_act]
    out = None
    for df in dfs:
        out = df.copy() if out is None else out.merge(df, on="hour", how="outer")

    if out is None:
        out = pd.DataFrame(columns=["hour"])

    numeric_cols = [
        "pre_cm_mva", "post_cm_mva", "pre_overload_pp", "post_overload_pp",
        "pre_voltage_pu", "post_voltage_pu", "p_activation_mw", "q_activation_mvar",
    ]
    for c in numeric_cols:
        if c not in out.columns:
            out[c] = 0.0
    out[numeric_cols] = out[numeric_cols].fillna(0.0).infer_objects(copy=False).astype(float)

    if out.empty:
        return out

    out["hour"] = out["hour"].apply(eva._to_int_hour)
    out = out[out["hour"].notna()].copy()
    out["hour"] = out["hour"].astype(int)
    out = out.sort_values("hour").reset_index(drop=True)
    out["hour_label"] = [window_mode.point_label(h) for h in out["hour"]]

    out["cm_relief_mva"] = out["pre_cm_mva"] - out["post_cm_mva"]
    out["voltage_relief_pu"] = out["pre_voltage_pu"] - out["post_voltage_pu"]
    out["physical_overload_relief_pp"] = out["pre_overload_pp"] - out["post_overload_pp"]
    out["s_activation_mva"] = np.sqrt(out["p_activation_mw"] ** 2 + out["q_activation_mvar"] ** 2)
    out["need_type"] = [_need_type(cm, vc) for cm, vc in zip(out["pre_cm_mva"], out["pre_voltage_pu"])]
    out["need_code"] = out["need_type"].apply(_need_type_code)
    out["pre_need_score"] = _normalise_series(out["pre_cm_mva"]) + _normalise_series(out["pre_voltage_pu"])
    out["post_residual_score"] = _normalise_series(out["post_cm_mva"]) + _normalise_series(out["post_voltage_pu"])
    return out


def _build_provider_table(act: pd.DataFrame, hourly: pd.DataFrame) -> pd.DataFrame:
    if act is None or act.empty:
        return pd.DataFrame()

    a = act[act["abs_value"] >= ACTIVATION_ZERO_TOL].copy()
    if a.empty:
        return pd.DataFrame()

    # Product pivot per provider-hour to compute P/Q/S consistently.
    by_hr = a.groupby(["resource", "resource_type", "hour", "product"], as_index=False)["abs_value"].sum()
    piv = by_hr.pivot_table(index=["resource", "resource_type", "hour"], columns="product", values="abs_value", aggfunc="sum", fill_value=0.0).reset_index()
    if "P" not in piv.columns:
        piv["P"] = 0.0
    if "Q" not in piv.columns:
        piv["Q"] = 0.0
    piv["S"] = np.sqrt(piv["P"].astype(float) ** 2 + piv["Q"].astype(float) ** 2)

    critical_hours = set()
    if hourly is not None and not hourly.empty:
        critical_hours = set(hourly.loc[hourly["need_type"].isin(["CM", "VC", "CMVC"]), "hour"].astype(int).tolist())
    piv["critical_hour"] = piv["hour"].astype(int).isin(critical_hours)

    agg = piv.groupby(["resource", "resource_type"], as_index=False).agg(
        activated_p_mw=("P", "sum"),
        activated_q_mvar=("Q", "sum"),
        activated_s_mva=("S", "sum"),
        active_hours=("hour", "nunique"),
    )
    crit = (
        piv[piv["critical_hour"]]
        .groupby(["resource", "resource_type"], as_index=False)["S"]
        .sum()
        .rename(columns={"S": "critical_activation_mva"})
    )
    agg = agg.merge(crit, on=["resource", "resource_type"], how="left")
    agg["critical_activation_mva"] = agg["critical_activation_mva"].fillna(0.0)
    total_s = float(agg["activated_s_mva"].sum())
    max_hours = float(agg["active_hours"].max()) if len(agg) else 0.0
    agg["activation_share_pct"] = 100.0 * agg["activated_s_mva"] / total_s if total_s > 0 else 0.0
    agg["critical_share_pct"] = 100.0 * agg["critical_activation_mva"] / agg["activated_s_mva"].replace(0.0, np.nan)
    agg["critical_share_pct"] = agg["critical_share_pct"].fillna(0.0)

    # Strategic score: high volume, frequent use, and use in hours with detected need.
    volume_component = _normalise_series(agg["activated_s_mva"])
    frequency_component = agg["active_hours"].astype(float) / max_hours if max_hours > 0 else 0.0
    critical_component = agg["critical_share_pct"].astype(float) / 100.0
    agg["priority_score"] = 100.0 * (0.55 * volume_component + 0.25 * frequency_component + 0.20 * critical_component)
    agg = agg.sort_values("priority_score", ascending=False).reset_index(drop=True)
    return agg


def _build_liquidity_table(act: pd.DataFrame) -> pd.DataFrame:
    if act is None or act.empty:
        return pd.DataFrame()
    a = act[act["abs_value"] >= ACTIVATION_ZERO_TOL].copy()
    if a.empty:
        return pd.DataFrame()

    rows = []
    for (hour, product), g in a.groupby(["hour", "product"]):
        by_provider = g.groupby("resource", as_index=False)["abs_value"].sum()
        total = float(by_provider["abs_value"].sum())
        if total <= ACTIVATION_ZERO_TOL:
            hhi = 0.0
            n = 0
        else:
            shares = by_provider["abs_value"].astype(float) / total
            hhi = float((shares ** 2).sum())
            n = int(len(by_provider))
        rows.append({
            "hour": int(hour),
            "product": str(product),
            "active_fsp_count": n,
            "volume": total,
            "hhi": hhi,
        })
    liq = pd.DataFrame(rows)
    if not liq.empty:
        liq["hour_label"] = [window_mode.point_label(h) for h in liq["hour"]]
    return liq


def _build_technology_table(act: pd.DataFrame) -> pd.DataFrame:
    if act is None or act.empty:
        return pd.DataFrame()
    a = act[act["abs_value"] >= ACTIVATION_ZERO_TOL].copy()
    if a.empty:
        return pd.DataFrame()
    tech = a.groupby(["resource_type", "product"], as_index=False)["abs_value"].sum()
    return tech


def _market_quality_metrics(data: Dict[str, Any]) -> Dict[str, float]:
    hourly = data.get("hourly", pd.DataFrame())
    providers = data.get("providers", pd.DataFrame())
    liquidity = data.get("liquidity", pd.DataFrame())
    if hourly is None or hourly.empty:
        return {}
    pre_cm = float(hourly["pre_cm_mva"].sum())
    post_cm = float(hourly["post_cm_mva"].sum())
    pre_v = float(hourly["pre_voltage_pu"].sum())
    post_v = float(hourly["post_voltage_pu"].sum())
    cm_relief = 100.0 * (1.0 - _safe_div(post_cm, pre_cm, default=0.0)) if pre_cm > 0 else 100.0
    vc_relief = 100.0 * (1.0 - _safe_div(post_v, pre_v, default=0.0)) if pre_v > 0 else 100.0
    residual_hours = int(hourly[(hourly["post_cm_mva"] > ACTIVATION_ZERO_TOL) | (hourly["post_voltage_pu"] > 1e-9)]["hour"].nunique())
    critical_hours = int(hourly[hourly["need_type"].isin(["CM", "VC", "CMVC"])]["hour"].nunique())
    total_s = float(hourly["s_activation_mva"].sum())
    total_p = float(hourly["p_activation_mw"].sum())
    total_q = float(hourly["q_activation_mvar"].sum())
    # Use the combined equivalent-flexibility hourly market-power table for
    # scenario-comparison KPIs.  The older liquidity table is P/Q-product
    # specific; averaging P-HHI and Q-HHI can hide the actual provider-level
    # concentration in mixed PQ scenarios.
    hourly_power = _hourly_market_power_table(data)
    active_power_hours = hourly_power[hourly_power["activation_volume"] > ACTIVATION_ZERO_TOL] if hourly_power is not None and not hourly_power.empty else pd.DataFrame()
    if not active_power_hours.empty:
        avg_fsp = float(active_power_hours["active_fsp_count"].mean())
        max_hhi = float(active_power_hours["hhi"].max())
        avg_hhi = float(active_power_hours["hhi"].mean())
        top_provider_share = float(active_power_hours["top_provider_share_pct"].max())
        avg_top_provider_share = float(active_power_hours["top_provider_share_pct"].mean())
    else:
        avg_fsp = 0.0
        max_hhi = 0.0
        avg_hhi = 0.0
        top_provider_share = 0.0
        avg_top_provider_share = 0.0
    providers_top_share = float(providers["activation_share_pct"].max()) if providers is not None and not providers.empty else 0.0
    market_diversity = 100.0 * max(0.0, 1.0 - avg_hhi)
    provider_independence = max(0.0, 100.0 - top_provider_share)
    activation_efficiency = 100.0 / (1.0 + total_s)
    residual_penalty_score = 100.0 / (1.0 + residual_hours)
    regulatory_score = max(0.0, min(100.0, 0.30 * cm_relief + 0.22 * vc_relief + 0.18 * market_diversity + 0.12 * provider_independence + 0.10 * activation_efficiency + 0.08 * residual_penalty_score))
    return {
        "cm_relief_pct": cm_relief,
        "voltage_relief_pct": vc_relief,
        "pre_cm_mva": pre_cm,
        "post_cm_mva": post_cm,
        "pre_voltage_pu": pre_v,
        "post_voltage_pu": post_v,
        "market_diversity_pct": market_diversity,
        "provider_independence_pct": provider_independence,
        "regulatory_score": regulatory_score,
        "residual_hours": residual_hours,
        "critical_hours": critical_hours,
        "total_activation_mva": total_s,
        "total_p_mw": total_p,
        "total_q_mvar": total_q,
        "avg_active_fsp": avg_fsp,
        "max_hhi": max_hhi,
        "avg_hhi": avg_hhi,
        "top_provider_share_pct": top_provider_share,
        "avg_top_provider_share_pct": avg_top_provider_share,
        "providers_top_share_pct": providers_top_share,
    }


def _provider_hour_table(data: Dict[str, Any]) -> pd.DataFrame:
    act = data.get("activation", pd.DataFrame())
    hourly = data.get("hourly", pd.DataFrame())
    if act is None or act.empty:
        return pd.DataFrame()
    a = act[act["abs_value"] >= ACTIVATION_ZERO_TOL].copy()
    if a.empty:
        return pd.DataFrame()
    by = a.groupby(["resource", "resource_type", "hour", "product"], as_index=False)["abs_value"].sum()
    piv = by.pivot_table(index=["resource", "resource_type", "hour"], columns="product", values="abs_value", aggfunc="sum", fill_value=0.0).reset_index()
    if "P" not in piv.columns:
        piv["P"] = 0.0
    if "Q" not in piv.columns:
        piv["Q"] = 0.0
    piv["S"] = np.sqrt(piv["P"].astype(float) ** 2 + piv["Q"].astype(float) ** 2)
    if hourly is not None and not hourly.empty:
        piv = piv.merge(hourly[["hour", "need_type", "pre_need_score", "post_residual_score"]], on="hour", how="left")
    return piv


def _hourly_market_power_table(data: Dict[str, Any]) -> pd.DataFrame:
    hourly = data.get("hourly", pd.DataFrame())
    ph = _provider_hour_table(data)
    if hourly is None or hourly.empty:
        return pd.DataFrame()
    rows = []
    for _, hrow in hourly.iterrows():
        h = int(hrow["hour"])
        g = ph[ph["hour"].astype(int) == h] if ph is not None and not ph.empty else pd.DataFrame()
        if g.empty:
            active_fsp = 0
            hhi = 0.0
            top_share = 0.0
            volume = 0.0
        else:
            byp = g.groupby("resource", as_index=False)["S"].sum()
            total = float(byp["S"].sum())
            volume = total
            if total > ACTIVATION_ZERO_TOL:
                shares = byp["S"].astype(float) / total
                hhi = float((shares ** 2).sum())
                top_share = float(shares.max())
                active_fsp = int(len(byp))
            else:
                hhi = 0.0; top_share = 0.0; active_fsp = 0
        rows.append({
            "hour": h,
            "hour_label": hrow.get("hour_label", window_mode.point_label(h)),
            "need_type": hrow.get("need_type", "No need"),
            "pre_need_score": float(hrow.get("pre_need_score", 0.0)),
            "post_residual_score": float(hrow.get("post_residual_score", 0.0)),
            "s_activation_mva": float(hrow.get("s_activation_mva", 0.0)),
            "active_fsp_count": active_fsp,
            "activation_volume": volume,
            "hhi": hhi,
            "top_provider_share_pct": 100.0 * top_share,
            "market_power_statement": _market_concentration_statement(hhi),
        })
    return pd.DataFrame(rows).sort_values("hour")


def _read_objective_value_from_market_results(market_result_file: Optional[str]) -> float:
    """Read final objective value from model_results_*.xlsx, if available.

    The current platform stores the optimized objective in sheet ``ObjValue``.
    This helper is intentionally conservative: if the sheet is absent or has a
    different layout, it scans numeric cells in the sheet and returns the first
    meaningful value. Missing objective values are returned as NaN so the
    objective-comparison figure can skip gracefully.
    """
    if market_result_file is None or not os.path.exists(str(market_result_file)):
        return float("nan")
    try:
        obj = pd.read_excel(str(market_result_file), sheet_name="ObjValue")
    except Exception:
        return float("nan")
    if obj is None or obj.empty:
        return float("nan")
    # Prefer a column explicitly named ObjValue.
    for c in obj.columns:
        if str(c).strip().lower() == "objvalue":
            vals = pd.to_numeric(obj[c], errors="coerce").dropna()
            if not vals.empty:
                return float(vals.iloc[0])
    nums = obj.apply(pd.to_numeric, errors="coerce").stack().dropna()
    if nums.empty:
        return float("nan")
    # Many Excel exports include an index column 0; prefer a non-zero value if present.
    nz = nums[nums.abs() > 1e-12]
    return float(nz.iloc[-1] if not nz.empty else nums.iloc[-1])


def _numeric_matrix_from_model_sheet(market_result_file: Optional[str], sheet_name: str) -> pd.DataFrame:
    """Read one numeric matrix sheet from model_results_*.xlsx.

    The platform exports optimization variables as a matrix whose first column
    is often an index (``Unnamed: 0``). This helper drops index-like columns and
    returns only numeric values. Missing sheets return an empty dataframe.
    """
    if market_result_file is None or not os.path.exists(str(market_result_file)):
        return pd.DataFrame()
    try:
        df = pd.read_excel(str(market_result_file), sheet_name=sheet_name)
    except Exception:
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    keep = []
    for c in df.columns:
        low = str(c).strip().lower()
        if low.startswith("unnamed") or low in {"index", "hour", "time", "timestep"}:
            continue
        vals = pd.to_numeric(df[c], errors="coerce")
        if vals.notna().sum() > 0:
            keep.append(c)
    if not keep:
        return pd.DataFrame()
    out = df[keep].apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return out


def _model_sheet_abs_sum(market_result_file: Optional[str], sheet_names: List[str], positive_only: bool = False) -> float:
    """Return the absolute or positive sum of the first available sheet."""
    for sheet in sheet_names:
        df = _numeric_matrix_from_model_sheet(market_result_file, sheet)
        if df.empty:
            continue
        arr = df.to_numpy(dtype=float)
        if positive_only:
            return float(np.maximum(arr, 0.0).sum())
        return float(np.abs(arr).sum())
    return float("nan")


def _linearization_error_summary(data: Dict[str, Any]) -> Dict[str, float]:
    """Compare linear market residuals with nonlinear AC post-market residuals.

    Congestion:
        Linear residual proxy = positive beta, fallback ABS_beta [MVA-equivalent]
        AC residual          = post-market CM need from post AC validation [MVA]

    Voltage:
        Linear residual proxy = |alpha_DVpu|, fallback |ABS_alpha_DVpu| [pu]
        AC residual          = post-market voltage exposure from post AC validation [pu-index]

    Positive error means the AC validation found more residual risk than the
    linearized market model predicted. This is the key signal that the initial
    sensitivity matrix is no longer accurate for that activation range.
    """
    hourly = data.get("hourly", pd.DataFrame())
    market_result_file = data.get("market_result_file")
    if hourly is None or hourly.empty:
        return {}
    pre_cm = float(pd.to_numeric(hourly.get("pre_cm_mva", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum())
    post_cm = float(pd.to_numeric(hourly.get("post_cm_mva", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum())
    pre_v = float(pd.to_numeric(hourly.get("pre_voltage_pu", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum())
    post_v = float(pd.to_numeric(hourly.get("post_voltage_pu", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum())

    # Congestion linearization must be based on the raw sensitivity-model CM
    # need reconstructed from HCM matrices and accepted DW/DR actions. beta is
    # only a slack variable; use it only as a fallback when matrices are missing.
    cm_acc = _raw_linear_cm_accuracy_from_model(
        market_result_file=market_result_file,
        scenario_root=data.get("scenario_root"),
        sensitivity_root=data.get("sensitivity_root"),
        market_tag=data.get("market_tag"),
        pre_ts_root=data.get("pre_ts_root"),
    )
    cm_linear_res = float(cm_acc.get("linear_cm_residual_mva", float("nan")))
    cm_proxy_used = 0.0
    if not np.isfinite(cm_linear_res):
        cm_linear_res = _model_sheet_abs_sum(market_result_file, ["beta"], positive_only=True)
        cm_proxy_used = 1.0
    if not np.isfinite(cm_linear_res):
        cm_linear_res = _model_sheet_abs_sum(market_result_file, ["ABS_beta"], positive_only=False)
        cm_proxy_used = 2.0

    # Voltage linearization must be based on the raw sensitivity voltage
    # VA - alpha_DVpu.  VA alone is bounded/clipped by the optimization band,
    # while alpha_DVpu is the correction between bounded VA and the raw voltage.
    # Only if VA is unavailable do we fall back to alpha/alpha_primo as a
    # qualitative slack proxy.
    vc_acc = _raw_linear_voltage_accuracy_from_model(
        market_result_file=market_result_file,
        post_ts_root=data.get("post_ts_root"),
        vmin=float(data.get("vmin", 0.95)) if "vmin" in data else 0.95,
        vmax=float(data.get("vmax", 1.05)) if "vmax" in data else 1.05,
    )
    vc_linear_res = float(vc_acc.get("linear_vc_residual_pu", float("nan")))
    vc_proxy_used = 0.0
    if not np.isfinite(vc_linear_res):
        vc_linear_res = _model_sheet_abs_sum(market_result_file, ["alpha_DVpu", "ABS_alpha_DVpu", "ABS_alphaDVpu"], positive_only=False)
        vc_proxy_used = 1.0
    if not np.isfinite(vc_linear_res):
        vc_linear_res = _model_sheet_abs_sum(market_result_file, ["ABS_alpha_primo", "alpha_primo"], positive_only=False)
        vc_proxy_used = 2.0

    cm_error = float(cm_acc.get("cm_loading_mean_signed_error_mva", post_cm - cm_linear_res)) if isinstance(cm_acc, dict) and np.isfinite(cm_acc.get("cm_loading_mean_signed_error_mva", np.nan)) else (float(post_cm - cm_linear_res) if np.isfinite(cm_linear_res) else float("nan"))
    vc_error = float(post_v - vc_linear_res) if np.isfinite(vc_linear_res) else float("nan")
    # CM validity is now asset-hour physical MVA accuracy, normalized by each asset's own Smax.
    # It is not normalized by pre/post CM need and it is not based on beta.
    cm_error_pct = float(cm_acc.get("cm_loading_p95_pct_smax", np.nan)) if isinstance(cm_acc, dict) else float("nan")
    if not np.isfinite(cm_error_pct):
        cm_error_pct = 100.0 * abs(cm_error) / max(abs(pre_cm), 1e-9) if np.isfinite(cm_error) else float("nan")
    vc_error_pct = 100.0 * abs(vc_error) / max(abs(pre_v), 1e-9) if np.isfinite(vc_error) else float("nan")
    vals = [v for v in [cm_error_pct, vc_error_pct] if np.isfinite(v)]
    max_error_pct = float(max(vals)) if vals else float("nan")
    weighted_error_pct = float(0.60 * (cm_error_pct if np.isfinite(cm_error_pct) else 0.0) + 0.40 * (vc_error_pct if np.isfinite(vc_error_pct) else 0.0)) if vals else float("nan")
    if not np.isfinite(max_error_pct):
        validity_class = "Missing linear residual"
        validity_score = float("nan")
    elif max_error_pct <= 5.0:
        validity_class = "Valid"
        validity_score = 100.0
    elif max_error_pct <= 10.0:
        validity_class = "Acceptable"
        validity_score = 75.0
    elif max_error_pct <= 20.0:
        validity_class = "Warning"
        validity_score = 45.0
    else:
        validity_class = "Invalid"
        validity_score = 10.0
    return {
        "linear_cm_residual_mva": cm_linear_res,
        "actual_cm_residual_mva": post_cm,
        "cm_linearization_error_mva": cm_error,
        "cm_linearization_error_pct_pre": cm_error_pct,
        "linear_vc_residual_pu": vc_linear_res,
        "actual_vc_residual_pu": post_v,
        "vc_linearization_error_pu": vc_error,
        "vc_linearization_error_pct_pre": vc_error_pct,
        "linearization_error_max_pct": max_error_pct,
        "linearization_error_weighted_pct": weighted_error_pct,
        "linearization_validity_score": validity_score,
        "linearization_vc_proxy_used": vc_proxy_used,
        "linearization_cm_proxy_used": cm_proxy_used,
        "vc_voltage_mae_pu": vc_acc.get("vc_voltage_mae_pu", np.nan) if isinstance(vc_acc, dict) else np.nan,
        "vc_voltage_rmse_pu": vc_acc.get("vc_voltage_rmse_pu", np.nan) if isinstance(vc_acc, dict) else np.nan,
        "vc_voltage_max_abs_error_pu": vc_acc.get("vc_voltage_max_abs_error_pu", np.nan) if isinstance(vc_acc, dict) else np.nan,
        "vc_voltage_bias_pu": vc_acc.get("vc_voltage_bias_pu", np.nan) if isinstance(vc_acc, dict) else np.nan,
        "vc_voltage_error_cells": vc_acc.get("vc_voltage_error_cells", np.nan) if isinstance(vc_acc, dict) else np.nan,
        "cm_need_mae_mva": cm_acc.get("cm_loading_mae_mva", cm_acc.get("cm_need_mae_mva", np.nan)) if isinstance(cm_acc, dict) else np.nan,
        "cm_need_rmse_mva": cm_acc.get("cm_loading_rmse_mva", cm_acc.get("cm_need_rmse_mva", np.nan)) if isinstance(cm_acc, dict) else np.nan,
        "cm_need_max_abs_error_mva": cm_acc.get("cm_loading_max_abs_error_mva", cm_acc.get("cm_need_max_abs_error_mva", np.nan)) if isinstance(cm_acc, dict) else np.nan,
        "cm_need_bias_mva": cm_acc.get("cm_loading_bias_mva", cm_acc.get("cm_need_bias_mva", np.nan)) if isinstance(cm_acc, dict) else np.nan,
        "cm_need_error_cells": cm_acc.get("cm_loading_error_cells", cm_acc.get("cm_need_error_cells", np.nan)) if isinstance(cm_acc, dict) else np.nan,
        "cm_loading_mean_pct_smax": cm_acc.get("cm_loading_mean_pct_smax", np.nan) if isinstance(cm_acc, dict) else np.nan,
        "cm_loading_p95_pct_smax": cm_acc.get("cm_loading_p95_pct_smax", np.nan) if isinstance(cm_acc, dict) else np.nan,
        "linearization_validity_class": validity_class,
    }


def _scenario_summary_from_data(label: str, data: Dict[str, Any]) -> Dict[str, Any]:
    m = _market_quality_metrics(data)
    lin = _linearization_error_summary(data)
    act = data.get("activation", pd.DataFrame())
    providers = data.get("providers", pd.DataFrame())
    technology = data.get("technology", pd.DataFrame())
    row = {
        "scenario": label,
        "cm_relief_pct": m.get("cm_relief_pct", 0.0),
        "voltage_relief_pct": m.get("voltage_relief_pct", 0.0),
        "regulatory_score": m.get("regulatory_score", 0.0),
        "avg_active_fsp": m.get("avg_active_fsp", 0.0),
        "avg_hhi": m.get("avg_hhi", 0.0),
        "max_hhi": m.get("max_hhi", 0.0),
        "residual_hours": m.get("residual_hours", 0),
        "critical_hours": m.get("critical_hours", 0),
        "total_activation_mva": m.get("total_activation_mva", 0.0),
        "top_provider_share_pct": m.get("top_provider_share_pct", 0.0),
        "avg_top_provider_share_pct": m.get("avg_top_provider_share_pct", 0.0),
        "providers_top_share_pct": m.get("providers_top_share_pct", 0.0),
        "security_score": 0.60 * m.get("cm_relief_pct", 0.0) + 0.40 * m.get("voltage_relief_pct", 0.0),
        "objective_value": _read_objective_value_from_market_results(data.get("market_result_file")),
        "pre_cm_mva": m.get("pre_cm_mva", 0.0),
        "post_cm_mva": m.get("post_cm_mva", 0.0),
        "pre_voltage_pu": m.get("pre_voltage_pu", 0.0),
        "post_voltage_pu": m.get("post_voltage_pu", 0.0),
        "linear_cm_residual_mva": lin.get("linear_cm_residual_mva", np.nan),
        "actual_cm_residual_mva": lin.get("actual_cm_residual_mva", np.nan),
        "cm_linearization_error_mva": lin.get("cm_linearization_error_mva", np.nan),
        "cm_linearization_error_pct_pre": lin.get("cm_linearization_error_pct_pre", np.nan),
        "linear_vc_residual_pu": lin.get("linear_vc_residual_pu", np.nan),
        "actual_vc_residual_pu": lin.get("actual_vc_residual_pu", np.nan),
        "vc_linearization_error_pu": lin.get("vc_linearization_error_pu", np.nan),
        "vc_linearization_error_pct_pre": lin.get("vc_linearization_error_pct_pre", np.nan),
        "linearization_error_max_pct": lin.get("linearization_error_max_pct", np.nan),
        "linearization_error_weighted_pct": lin.get("linearization_error_weighted_pct", np.nan),
        "linearization_validity_score": lin.get("linearization_validity_score", np.nan),
        "linearization_vc_proxy_used": lin.get("linearization_vc_proxy_used", np.nan),
        "linearization_cm_proxy_used": lin.get("linearization_cm_proxy_used", np.nan),
        "cm_need_mae_mva": lin.get("cm_need_mae_mva", np.nan),
        "cm_need_rmse_mva": lin.get("cm_need_rmse_mva", np.nan),
        "cm_need_max_abs_error_mva": lin.get("cm_need_max_abs_error_mva", np.nan),
        "linearization_validity_class": lin.get("linearization_validity_class", ""),
    }
    # Product-specific activation burden.
    if act is not None and not act.empty:
        row["total_p_mw"] = float(act.loc[act.get("product", "") == "P", "abs_value"].sum()) if "product" in act.columns else 0.0
        row["total_q_mvar"] = float(act.loc[act.get("product", "") == "Q", "abs_value"].sum()) if "product" in act.columns else 0.0
    else:
        row["total_p_mw"] = 0.0
        row["total_q_mvar"] = 0.0
    # Technology contribution to support investor/regulatory technology messages.
    if technology is not None and not technology.empty and "resource_type" in technology.columns:
        tech = technology.groupby("resource_type")["abs_value"].sum().to_dict() if "abs_value" in technology.columns else {}
        row["load_activation"] = float(tech.get("Load", 0.0))
        row["generator_activation"] = float(tech.get("Generator", 0.0))
        row["storage_activation"] = float(tech.get("Storage", 0.0))
    else:
        row["load_activation"] = row["generator_activation"] = row["storage_activation"] = 0.0
    dims = _parse_scenario_dimensions(label)
    row.update(dims)
    row["short_label"] = _scenario_label_short(label)
    return row


def _load_comparison_data(
    scenario_roots: Optional[List[str]],
    scenario_labels: Optional[List[str]],
    vmin: float,
    vmax: float,
    output_folder: Optional[str] = None,
    market_tag: Optional[str] = None,
    sensitivity_root: Optional[str] = None,
) -> pd.DataFrame:
    # If the user did not explicitly pass scenario_roots, try to discover sibling
    # scenarios in the same data_out bundle. This makes scenario-comparison
    # figures available automatically after several scenarios have been run.
    auto_mode = False
    if not scenario_roots:
        scenario_roots = _auto_discover_sibling_scenarios(output_folder or os.getcwd(), market_tag or "")
        auto_mode = True
    if not scenario_roots:
        return pd.DataFrame()
    rows = []
    for i, root in enumerate(scenario_roots):
        if not root:
            continue
        root = os.path.abspath(root)
        tag = os.path.basename(root.rstrip(os.sep))
        label = scenario_labels[i] if scenario_labels and i < len(scenario_labels) else tag
        candidates = sorted(glob.glob(os.path.join(root, "model_results_*.xlsx")))
        market_result_file = candidates[0] if candidates else None
        try:
            data = _read_phase3_inputs(
                pre_ts_root=None,
                post_ts_root=None,
                market_result_file=market_result_file,
                output_folder=os.path.join(root, "visualization"),
                market_tag=tag,
                vmin=vmin,
                vmax=vmax,
                sensitivity_root=sensitivity_root,
            )
            rows.append(_scenario_summary_from_data(label, data))
        except Exception as exc:
            print("Skipped scenario comparison item:", root, "-", exc)
    df = _decorate_comparison_dimensions(pd.DataFrame(rows))
    if auto_mode and not df.empty:
        print(f"Auto-discovered {len(df)} sibling scenario(s) for strategic comparison.")
    return df


def _infer_country_from_market_tag(market_tag: Optional[str]) -> Optional[str]:
    if not market_tag:
        return None
    tag = str(market_tag).strip()
    return tag.split("_")[0] if "_" in tag else tag


def _candidate_sensitivity_roots(
    scenario_root: str,
    sensitivity_root: Optional[str] = None,
    market_tag: Optional[str] = None,
) -> List[str]:
    """Build general search roots for platform sensitivity matrices.

    No user-specific or machine-specific path is hard-coded here. The function
    looks for sensitivity matrices using the platform structure:

        data_in/<network>/market_inputs/h24SensitivityMatrixes

    It derives candidate project roots from the current working directory and
    from the scenario output location, then also performs a bounded discovery
    search for any folder named ``h24SensitivityMatrixes`` under detected
    ``data_in`` folders.

    ``sensitivity_root`` remains available as an optional override, but the
    normal workflow should not require it.
    """
    roots: List[str] = []

    def add(path: Optional[str]) -> None:
        if not path:
            return
        try:
            path = os.path.abspath(os.path.expanduser(str(path)))
        except Exception:
            return
        if path not in roots:
            roots.append(path)

    country = _infer_country_from_market_tag(market_tag)

    # 1) Optional explicit override, still general because it is user-provided.
    add(sensitivity_root)

    # 2) Candidate project roots from cwd and from the scenario output folder.
    candidate_project_roots: List[str] = []

    def add_project_root(path: Optional[str]) -> None:
        if not path:
            return
        try:
            path = os.path.abspath(str(path))
        except Exception:
            return
        if path and path not in candidate_project_roots:
            candidate_project_roots.append(path)

    add_project_root(os.getcwd())

    if scenario_root:
        sr = os.path.abspath(str(scenario_root))
        add_project_root(sr)
        # Walk upward. This normally reaches the platform root that contains
        # both data_out and data_in.
        cur = sr
        for _ in range(8):
            add_project_root(cur)
            parent = os.path.dirname(cur)
            if not parent or parent == cur:
                break
            cur = parent

    # 3) Direct platform convention under each candidate root.
    for root in candidate_project_roots:
        if country:
            add(os.path.join(root, "data_in", country, "market_inputs", "h24SensitivityMatrixes"))
        add(os.path.join(root, "data_in"))
        add(os.path.join(root, "market_inputs", "h24SensitivityMatrixes"))
        add(os.path.join(root, "h24SensitivityMatrixes"))

    # 4) If candidate roots include a data_out branch, infer its platform root.
    for root in list(candidate_project_roots):
        parts = os.path.normpath(root).split(os.sep)
        if "data_out" in parts:
            idx = parts.index("data_out")
            platform_root = os.sep.join(parts[:idx]) or os.sep
            if country:
                add(os.path.join(platform_root, "data_in", country, "market_inputs", "h24SensitivityMatrixes"))
            add(os.path.join(platform_root, "data_in"))

    # 5) Bounded discovery under detected data_in folders. This is general and
    # avoids scanning the entire disk.
    data_in_roots = []
    for root in candidate_project_roots:
        din = os.path.join(root, "data_in")
        if os.path.isdir(din) and din not in data_in_roots:
            data_in_roots.append(din)
    # Also include any already-added root that itself is data_in.
    for r in list(roots):
        if os.path.basename(os.path.normpath(r)).lower() == "data_in" and os.path.isdir(r) and r not in data_in_roots:
            data_in_roots.append(r)

    for din in data_in_roots:
        try:
            for dirpath, dirnames, _ in os.walk(din):
                # Keep the search bounded: no need to descend very deeply below
                # data_in for this platform structure.
                rel = os.path.relpath(dirpath, din)
                depth = 0 if rel == "." else rel.count(os.sep) + 1
                if depth > 5:
                    dirnames[:] = []
                    continue
                if os.path.basename(dirpath).lower() == "h24sensitivitymatrixes":
                    add(dirpath)
        except Exception:
            continue

    # Return only unique existing folders first, then possible direct paths.
    existing = [r for r in roots if os.path.isdir(r)]
    missing = [r for r in roots if r not in existing]
    return existing + missing


def plot_product_design_response_curve(comparison: pd.DataFrame, output_folder: str, market_tag: str) -> Optional[str]:
    """Scenario-family response curves across flexibility cases and products.

    Regulatory meaning: shows whether increasing flexibility quantity improves
    security, whether it increases activation burden, and whether market power
    becomes worse as fewer providers dominate the solution.
    """
    df = _decorate_comparison_dimensions(comparison)
    if df.empty or df["product"].replace("", np.nan).dropna().nunique() < 1:
        return None
    df = df[df["flex_level"].notna()].copy()
    if df.empty:
        return None
    df = df.sort_values(["product", "flex_level"])

    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=(
            "Security delivery versus flexibility case",
            "Activation burden versus flexibility case",
            "Market concentration risk versus flexibility case",
            "Residual-risk hours versus flexibility case",
        ),
        vertical_spacing=0.14,
        horizontal_spacing=0.12,
    )
    product_colors = {"PQ": "#4C78A8", "P": "#54A24B", "Q": "#9C755F"}
    for product, sub in df.groupby("product", sort=False):
        sub = sub.sort_values("flex_level")
        color = product_colors.get(str(product), None)
        common = dict(mode="lines+markers", name=str(product), line=dict(width=2.8, color=color), marker=dict(size=8, color=color))
        fig.add_trace(go.Scatter(x=sub["flex_case"], y=sub["security_score"], legendgroup=str(product), showlegend=True, hovertemplate="%{x}<br>Security score: %{y:.2f}%<extra>"+str(product)+"</extra>", **common), row=1, col=1)
        fig.add_trace(go.Scatter(x=sub["flex_case"], y=sub["total_activation_mva"], legendgroup=str(product), showlegend=False, hovertemplate="%{x}<br>Activation burden: %{y:.6f} MVA<extra>"+str(product)+"</extra>", **{k:v for k,v in common.items() if k!='name'}), row=1, col=2)
        fig.add_trace(go.Scatter(x=sub["flex_case"], y=sub["avg_hhi"], legendgroup=str(product), showlegend=False, hovertemplate="%{x}<br>Average HHI: %{y:.4f}<extra>"+str(product)+"</extra>", **{k:v for k,v in common.items() if k!='name'}), row=2, col=1)
        fig.add_trace(go.Scatter(x=sub["flex_case"], y=sub["residual_hours"], legendgroup=str(product), showlegend=False, hovertemplate="%{x}<br>Residual-risk hours: %{y}<extra>"+str(product)+"</extra>", **{k:v for k,v in common.items() if k!='name'}), row=2, col=2)

    fig.update_yaxes(title_text="Security score [%]", row=1, col=1)
    fig.update_yaxes(title_text="MVA-equivalent", row=1, col=2)
    fig.update_yaxes(title_text="HHI [-]", row=2, col=1)
    # This axis is a COUNT of insecure windows, so it gets an explicit count title (a bare "Hours" would be read
    # as a window axis by figure_style.retitle_window_axes).
    fig.update_yaxes(title_text=f"Residual-risk {window_mode.noun(plural=True)} [count]", row=2, col=2)
    fig.update_xaxes(title_text="Flexibility case", row=2, col=1)
    fig.update_xaxes(title_text="Flexibility case", row=2, col=2)
    _apply_phase3_layout(fig, market_tag, height=980, show_legend=True)
    fig.update_layout(
        legend=dict(orientation="h", yanchor="top", y=-0.10, xanchor="center", x=0.5),
        margin=dict(l=95, r=95, t=110, b=130),
    )
    return _save_comparison_fig(fig, "ProductDesignResponseCurve_" + market_tag, output_folder, market_tag, "Comparison - Product design response curve")


def _comparison_color_marker_maps() -> Tuple[Dict[str, str], Dict[str, str]]:
    """Consistent product colors and marker symbols for comparison figures."""
    colors = {
        "P": "#54A24B",
        "Q": "#9C755F",
        "PQ": "#4C78A8",
    }
    markers = {
        "P": "circle",
        "Q": "square",
        "PQ": "diamond",
    }
    return colors, markers


def plot_technical_security_trend_by_flex(comparison: pd.DataFrame, output_folder: str, market_tag: str) -> Optional[str]:
    """Technical comparison by increasing flexibility range F01-F05.

    Revised to avoid overlapping point labels: all exact values are kept in
    hover panels, while the visible plot remains clean and journal-style.
    """
    df = _scenario_ordered(comparison)
    if df.empty or df["flex_level"].dropna().empty:
        return None
    flex_order = sorted(
        df["flex_case"].dropna().astype(str).unique(),
        key=lambda value: int(str(value).replace("F", "")) if str(value).replace("F", "").isdigit() else 999,
    )
    residual_values = pd.to_numeric(df["residual_hours"], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    residual_max = float(residual_values.max()) if not residual_values.empty else 0.0
    residual_upper = max(1.0, residual_max * 1.08)
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=False, vertical_spacing=0.25,
        subplot_titles=("Security delivery trend", "Residual-risk trend"),
    )
    for product, sub in df.groupby("product", sort=False):
        sub = sub.sort_values("flex_level")
        style = _product_style(product)
        common_line = dict(width=3, color=style["color"])
        common_marker = dict(size=10, color=style["color"], symbol=style["symbol"], line=dict(color="white", width=0.8))
        fig.add_trace(go.Scatter(
            x=sub["flex_case"], y=sub["security_score"], mode="lines+markers",
            name=str(product), legendgroup=str(product), line=common_line, marker=common_marker,
            customdata=np.column_stack([sub["cm_relief_pct"], sub["voltage_relief_pct"], sub["short_label"]]),
            hovertemplate=(
                "Scenario: %{customdata[2]}<br>Flex case: %{x}"
                "<br>Security score: %{y:.2f}%"
                "<br>CM relief: %{customdata[0]:.2f}%"
                "<br>Voltage relief: %{customdata[1]:.2f}%<extra></extra>"
            ),
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=sub["flex_case"], y=sub["residual_hours"], mode="lines+markers",
            name=str(product), legendgroup=str(product), showlegend=False, line=common_line, marker=common_marker,
            customdata=np.column_stack([sub["short_label"]]),
            hovertemplate="Scenario: %{customdata[0]}<br>Flex case: %{x}<br>Residual-risk hours: %{y:.0f} h<extra></extra>",
        ), row=2, col=1)
    # Both independent numerical axes
    # explicitly increase from minimum at the bottom to maximum at the top.
    fig.update_yaxes(title_text="Security score [%]", range=[0.0, 100.0], tick0=0, dtick=20, row=1, col=1)
    fig.update_yaxes(
        title_text="Residual-risk hours [h]", range=[0.0, residual_upper], nticks=6,
        tickformat=".0f", row=2, col=1,
    )
    for row in (1, 2):
        fig.update_xaxes(
            title_text="Flexibility case [-]", categoryorder="array", categoryarray=flex_order,
            showticklabels=True, row=row, col=1,
        )
    _apply_phase3_layout(fig, market_tag, height=1080, show_legend=True)
    fig.update_layout(legend=dict(orientation="h", yanchor="top", y=-0.10, xanchor="center", x=0.5), margin=dict(l=130, r=120, t=125, b=210))
    return _save_comparison_fig(
        fig,
        "TechnicalSecurityTrendByFlex_" + market_tag,
        output_folder,
        market_tag,
        "Comparison - Technical security trend by flexibility range",
        figure_note=(
            "The two panels use separate units and separate vertical axes. In both panels the numerical direction is "
            "minimum at the bottom and maximum at the top: 0–100% for security and 0–the displayed maximum hours "
            "for residual risk. Security should generally rise with F; rising residual risk can indicate product "
            "limitations, cost-driven dispatch, or AC/nonlinear validation mismatch."
        ),
    )


def plot_technical_product_flex_heatmap(comparison: pd.DataFrame, output_folder: str, market_tag: str) -> Optional[str]:
    """Heatmap of security score by product and F-case."""
    df = _scenario_ordered(comparison)
    if df.empty or df["flex_level"].dropna().empty:
        return None
    products = [p for p in ["P", "Q", "PQ"] if p in set(df["product"].astype(str))]
    flex_cases = sorted(df["flex_case"].dropna().unique(), key=lambda x: int(str(x).replace("F", "")) if str(x).replace("F", "").isdigit() else 999)
    pivot = df.pivot_table(index="product", columns="flex_case", values="security_score", aggfunc="mean").reindex(index=products, columns=flex_cases)
    text = pivot.applymap(lambda v: "" if pd.isna(v) else f"{v:.1f}%")
    fig = go.Figure(go.Heatmap(
        z=pivot.values, x=flex_cases, y=products, colorscale="YlGnBu", zmin=0, zmax=100,
        text=text.values, texttemplate="%{text}", textfont=dict(size=14, color="#111827"),
        colorbar=dict(title=dict(text="Security score [%]", side="right")),
        hovertemplate="Product: %{y}<br>Flex case: %{x}<br>Security score: %{z:.2f}%<extra></extra>",
    ))
    fig.update_xaxes(title_text="Flexibility case, ordered F01 to F05 [-]")
    fig.update_yaxes(title_text="Product type [-]")
    _apply_phase3_layout(fig, market_tag, height=max(560, 340 + 52 * len(products)), show_legend=False)
    fig.update_layout(margin=dict(l=120, r=170, t=115, b=140))
    return _save_comparison_fig(fig, "TechnicalProductFlexHeatmap_" + market_tag, output_folder, market_tag, "Comparison - Technical product/flex heatmap")


# --- Asset-hour congestion accuracy, physical MVA vs AC MVA ---
def _sv_find_network_file_for_asset_loading(sensitivity_root=None, scenario_root=None, network_file=None):
    """Return the network workbook that gives the line ratings for the physical-MVA diagnostics, or None.

    The workbook is not located automatically. Pass it with ``network_file``. Without it the function returns None
    and the diagnostics that need the line ratings are skipped.
    """
    import os
    if network_file and os.path.exists(str(network_file)):
        return str(network_file)
    return None


def _sv_find_pre_line_loading(pre_ts_root=None, scenario_root=None):
    import os
    candidates = []
    if pre_ts_root:
        candidates.append(os.path.join(str(pre_ts_root), 'res_line', 'loading_percent.csv'))
    if scenario_root:
        sr = os.path.abspath(str(scenario_root))
        candidates += [
            os.path.join(sr, 'res_ts_net', 'res_line', 'loading_percent.csv'),
            os.path.join(os.path.dirname(sr), 'res_ts_net', 'res_line', 'loading_percent.csv'),
            os.path.join(os.path.dirname(os.path.dirname(sr)), 'res_ts_net', 'res_line', 'loading_percent.csv'),
        ]
    for c in candidates:
        if c and os.path.exists(c):
            try:
                return pd.read_csv(c, index_col=0).apply(pd.to_numeric, errors='coerce')
            except Exception:
                pass
    return pd.DataFrame()


def _sv_line_asset_metadata(sensitivity_root=None, scenario_root=None):
    import math
    net_file = _sv_find_network_file_for_asset_loading(sensitivity_root, scenario_root)
    if not net_file:
        return {}, {}, {}
    try:
        line = pd.read_excel(net_file, sheet_name='line')
        bus = pd.read_excel(net_file, sheet_name='bus').set_index('Unnamed: 0')
    except Exception:
        return {}, {}, {}
    asset_to_line = {}
    smax = {}
    desc = {}
    for _, row in line.iterrows():
        try:
            name = str(row['name'])
            idx = int(row['Unnamed: 0'])
            vn = float(bus.loc[int(row['from_bus']), 'vn_kv'])
            sm = math.sqrt(3.0) * float(row['max_i_ka']) * vn
            asset_to_line[name] = idx
            smax[name] = sm
            desc[name] = str(row.get('description', name))
        except Exception:
            continue
    return asset_to_line, smax, desc


def _sv_post_line_loading_for_scenario(scenario_root):
    if not scenario_root:
        return pd.DataFrame()
    p = os.path.join(str(scenario_root), 'FullTS_postMKT', 'res_line', 'loading_percent.csv')
    if not os.path.exists(p):
        return pd.DataFrame()
    try:
        return pd.read_csv(p, index_col=0).apply(pd.to_numeric, errors='coerce')
    except Exception:
        return pd.DataFrame()


def _sv_equivalent_injection_delta(fsp_type, saved_delta):
    """Convert exported market-sheet deltas to the sign used by raw HCM CSVs.

    The saved HCM matrices are dS/d(+virtual sgen injection).  The exported
    model results are written in physical element convention:
      A load:    DW/DR > 0 means more consumption, so equivalent injection is negative.
      B sgen:    DW/DR > 0 means more generation, so equivalent injection is positive.
      C storage: DW/DR > 0 follows pandapower storage absorption convention, so
                 equivalent injection is negative.  For active power this is
                 the same as discharge minus charge; with the exported sheets,
                 equivalent injection delta = -DW_C.
    """
    try:
        v = float(saved_delta)
    except Exception:
        return 0.0
    return -v if str(fsp_type) in {'A', 'C'} else v


def _sv_hcm_raw_effect(market_result_file, sheets, sensitivity_root, scenario_root, market_tag, asset_cols, hours):
    """Return asset x hour raw physical HCM effect in MVA.

    This uses the saved raw HCM CSVs directly, so the quantity added to S_pre is:
        sum(HCMdSdP_raw * equivalent_P_injection_delta
          + HCMdSdQ_raw * equivalent_Q_injection_delta)
    It is not beta, and it does not use the internally sign-flipped market matrix.
    """
    sim_tag = str(market_tag).split('_')[-1] if market_tag else ''
    sens_roots = [r for r in _candidate_sensitivity_roots(str(scenario_root), sensitivity_root, market_tag) if os.path.isdir(r)]
    if not sens_roots:
        return pd.DataFrame()
    sens_root = sens_roots[0]
    effect = pd.DataFrame(0.0, index=[str(a) for a in asset_cols], columns=[str(h) for h in hours])
    for hpos, h in enumerate(hours):
        for fsp_type in ['A', 'B', 'C']:
            for kind, sheet_name in [('HCMdSdP', 'DW_' + fsp_type), ('HCMdSdQ', 'DR_' + fsp_type)]:
                mat = _read_hcm_matrix_local(sens_root, kind, fsp_type, h, sim_tag)
                sheet = sheets.get(sheet_name)
                if mat.empty or sheet is None or sheet.empty:
                    continue
                n = min(mat.shape[0], sheet.shape[0])
                for i in range(n):
                    saved_delta = _sheet_value_by_hour_local(sheet, i, h, hpos)
                    inj_delta = _sv_equivalent_injection_delta(fsp_type, saved_delta)
                    if abs(inj_delta) <= 1e-15:
                        continue
                    for asset in asset_cols:
                        if str(asset) in mat.columns:
                            effect.loc[str(asset), str(h)] += float(mat.loc[mat.index[i], str(asset)]) * inj_delta
    return effect


def _raw_linear_cm_accuracy_from_model(market_result_file, scenario_root, sensitivity_root, market_tag, pre_ts_root=None):
    """Asset-hour CM accuracy: compare physical MVA loading, not aggregate CM need.

    Linear model with saved raw HCM CSVs: S_linear(asset,h) = S_pre(asset,h) + HCM_raw_effect(asset,h), where HCM_raw_effect is computed with equivalent injection deltas.
    The optimization internally loads CM matrices with _cm_factor=-1, so its internal
    k_market = -HCM_raw_effect and the constraint S_init - k_market - beta <= Smax - ds_tol
    is consistent after converting exported load/storage deltas to equivalent injection; beta remains a non-physical slack.

    AC model: S_AC(asset,h) = loading_percent_post(asset,h)/100 * Smax(asset).
    Error is AC - linear. Normalized error is |error|/Smax(asset), so tol_i,
    tol_i_opt, pre need and post need do not affect the denominator.
    """
    if not market_result_file or not os.path.exists(str(market_result_file)) or not scenario_root:
        return {}
    try:
        xls = pd.ExcelFile(market_result_file)
        sheets = {name: _read_model_sheet_numeric(xls, name) for name in ['DW_A','DR_A','DW_B','DR_B','DW_C','DR_C','beta']}
    except Exception:
        return {}
    study_hours = _infer_model_study_hour_columns_local(sheets)
    if not study_hours:
        return {}
    hours = [str(h) for h in study_hours]
    asset_to_line, smax, _desc = _sv_line_asset_metadata(sensitivity_root, scenario_root)
    if not asset_to_line:
        return {}
    # Use beta row count to infer monitored CM assets; for this platform these map to L1, L2, ...
    beta = sheets.get('beta')
    n_assets = beta.shape[0] if beta is not None and not beta.empty else 0
    asset_cols = [f'L{i+1}' for i in range(n_assets) if f'L{i+1}' in asset_to_line]
    if not asset_cols:
        asset_cols = [a for a in ['L1','L2'] if a in asset_to_line]
    pre_loading = _sv_find_pre_line_loading(pre_ts_root, scenario_root)
    post_loading = _sv_post_line_loading_for_scenario(scenario_root)
    if pre_loading.empty or post_loading.empty:
        return {}
    hcm_raw_effect = _sv_hcm_raw_effect(market_result_file, sheets, sensitivity_root, scenario_root, market_tag, asset_cols, hours)
    if hcm_raw_effect.empty:
        return {}
    rows = []
    for pos, h in enumerate(hours):
        for asset in asset_cols:
            try:
                line_idx = asset_to_line[asset]
                sm = float(smax[asset])
                s_pre = float(pre_loading.loc[int(h), str(line_idx)] / 100.0 * sm)
                k = float(hcm_raw_effect.loc[str(asset), str(h)])
                s_linear = s_pre + k
                s_ac = float(post_loading.iloc[pos][str(line_idx)] / 100.0 * sm)
                err = s_ac - s_linear
                rows.append((asset, int(h), sm, s_pre, k, s_linear, s_ac, err, abs(err), 100.0*abs(err)/sm, 100.0*err/sm))
            except Exception:
                continue
    if not rows:
        return {}
    df = pd.DataFrame(rows, columns=['asset','hour','smax_mva','pre_mva','hcm_raw_effect_mva','linear_mva','ac_mva','error_mva','abs_error_mva','abs_error_pct_smax','signed_error_pct_smax'])
    vals = df['error_mva'].to_numpy(dtype=float)
    absvals = np.abs(vals)
    pct = df['abs_error_pct_smax'].to_numpy(dtype=float)
    # Residuals for the existing residual scatter are physical overload above Smax, not beta/need.
    linear_over = np.maximum(df['linear_mva'].to_numpy(dtype=float) - df['smax_mva'].to_numpy(dtype=float), 0.0)
    ac_over = np.maximum(df['ac_mva'].to_numpy(dtype=float) - df['smax_mva'].to_numpy(dtype=float), 0.0)
    return {
        'cm_reconstruction_available': 1.0,
        'linear_cm_residual_mva': float(np.nansum(linear_over)),
        'actual_cm_residual_mva': float(np.nansum(ac_over)),
        'cm_loading_error_cells': int(len(df)),
        'cm_loading_mae_mva': float(np.nanmean(absvals)),
        'cm_loading_rmse_mva': float(np.sqrt(np.nanmean(vals**2))),
        'cm_loading_p95_abs_error_mva': float(np.nanpercentile(absvals, 95)),
        'cm_loading_max_abs_error_mva': float(np.nanmax(absvals)),
        'cm_loading_bias_mva': float(np.nanmean(vals)),
        'cm_loading_mean_signed_error_mva': float(np.nanmean(vals)),
        'cm_loading_mean_pct_smax': float(np.nanmean(pct)),
        'cm_loading_p95_pct_smax': float(np.nanpercentile(pct, 95)),
        'cm_loading_max_pct_smax': float(np.nanmax(pct)),
        'cm_asset_hour_detail': df,
        # Backward-compatible aliases used by older figure functions.
        'cm_need_mae_mva': float(np.nanmean(absvals)),
        'cm_need_rmse_mva': float(np.sqrt(np.nanmean(vals**2))),
        'cm_need_max_abs_error_mva': float(np.nanmax(absvals)),
        'cm_need_bias_mva': float(np.nanmean(vals)),
        'cm_need_error_cells': int(len(df)),
    }


# --- Final cell-level technical accuracy comparison (asset-hour and bus-hour) ---
def _tech_acc_scenario_parts_v11(tag):
    parts = str(tag).split('_')
    out = {'network': None, 'market': None, 'product': None, 'voltage_level': None, 'flex_case': None, 'storage_case': None, 'ess_case': None}
    if len(parts) >= 7:
        out.update({'network': parts[0], 'market': parts[1], 'product': parts[2], 'voltage_level': parts[3], 'flex_case': parts[4], 'storage_case': parts[5], 'ess_case': parts[6]})
    return out


def _tech_acc_scenario_label_v11(tag):
    p = _tech_acc_scenario_parts_v11(tag)
    if p.get('product') and p.get('flex_case'):
        return str(p['product']) + '-' + str(p['flex_case'])
    return str(tag)


def _tech_acc_discover_scenario_roots_v11(output_folder, market_tag, scenario_roots=None):
    if scenario_roots:
        return [os.path.abspath(str(r)) for r in scenario_roots if r]
    roots = _auto_discover_sibling_scenarios(output_folder or os.getcwd(), market_tag or '')
    if roots:
        return roots
    return []


def _tech_acc_build_tables_v11(output_folder, market_tag, scenario_roots=None, sensitivity_root=None):
    roots = _tech_acc_discover_scenario_roots_v11(output_folder, market_tag, scenario_roots)
    cm_detail_list = []
    v_detail_list = []
    pre_ts_root = os.path.join(_scenario_bundle_root(output_folder or os.getcwd(), market_tag or ''), 'res_ts_net')
    resolved_config = accuracy_core._resolve_config_path(roots)
    # One accuracy row per MARKET STAGE.
    # build_scenario_accuracy_data(case_root) analyses only the case's last
    # stage, so a case with a corrective round reported only that round (whose
    # small increments are almost exactly linear) and a case without one
    # reported its main market: rows of one figure silently compared different
    # stages, and the main-market linearisation error of every corrected case
    # was never shown.  Every stage is now analysed and labelled.
    stage_jobs = []
    for root in roots:
        stage_roots = accuracy_core._stage_roots(root) or [root]
        stage_jobs.extend((root, stage_root) for stage_root in stage_roots)
    for root, stage_root in stage_jobs:
        accuracy = accuracy_core.build_scenario_accuracy_data(
            stage_root, sensitivity_root=sensitivity_root, pre_ts_root=pre_ts_root,
            config_path=resolved_config,
        )
        tag = os.path.basename(os.path.normpath(str(root)))
        parts = _tech_acc_scenario_parts_v11(tag)
        iteration = int(accuracy.get('stage_iteration') or 0)
        stage_label = 'main market' if iteration == 0 else f'corrective round {iteration}'
        cm_long = accuracy.get('congestion_long', pd.DataFrame())
        smax = accuracy.get('congestion_smax', pd.Series(dtype=float))
        # Hours without any activation of
        # this stage have linear = baseline = AC by construction; they verify
        # nothing and are left out (blank cells), instead of showing a zero error.
        if not cm_long.empty and 'dispatched' in cm_long:
            cm_long = cm_long[cm_long['dispatched'].astype(bool)]
        if not cm_long.empty:
            # All strategic congestion
            # charts adapt the canonical physical-MVA accuracy cells instead of
            # guessing monitored assets from beta row positions.
            cm = pd.DataFrame({
                'scenario': tag,
                'short_label': _tech_acc_scenario_label_v11(tag),
                'product': parts.get('product'),
                'flex_case': parts.get('flex_case'),
                'asset': cm_long['element'].astype(str),
                'hour': pd.to_numeric(cm_long['hour'], errors='coerce'),
                's_linear_mva': pd.to_numeric(cm_long['linear'], errors='coerce'),
                's_ac_mva': pd.to_numeric(cm_long['ac'], errors='coerce'),
                'error_mva': pd.to_numeric(cm_long['error'], errors='coerce'),
                'abs_error_mva': pd.to_numeric(cm_long['abs_error'], errors='coerce'),
                'abs_error_pct_smax': pd.to_numeric(cm_long['percent_error'], errors='coerce'),
            })
            asset_order = {asset: pos for pos, asset in enumerate(pd.unique(cm['asset']))}
            cm['line_index'] = cm['asset'].map(asset_order)
            cm['asset_description'] = cm['asset']
            cm['smax_mva'] = cm['asset'].map(smax)
            cm['signed_error_pct_smax'] = 100.0 * cm['error_mva'] / cm['smax_mva']
            cm['stage_iteration'] = iteration
            cm['stage'] = stage_label
            cm_detail_list.append(cm)
        v_long = accuracy.get('voltage_long', pd.DataFrame())
        if not v_long.empty and 'dispatched' in v_long:
            v_long = v_long[v_long['dispatched'].astype(bool)]
        if not v_long.empty:
            # Voltage error is defined
            # once as AC - (VA - alpha_DVpu) for every technical figure.
            vv = pd.DataFrame({
                'scenario': tag,
                'short_label': _tech_acc_scenario_label_v11(tag),
                'product': parts.get('product'),
                'flex_case': parts.get('flex_case'),
                'bus': v_long['element'].astype(str),
                'hour': pd.to_numeric(v_long['hour'], errors='coerce'),
                'v_linear_pu': pd.to_numeric(v_long['linear'], errors='coerce'),
                'v_ac_pu': pd.to_numeric(v_long['ac'], errors='coerce'),
                'error_pu': pd.to_numeric(v_long['error'], errors='coerce'),
                'abs_error_pu': pd.to_numeric(v_long['abs_error'], errors='coerce'),
                'signed_error_pct_nominal': 100.0 * pd.to_numeric(v_long['error'], errors='coerce'),
                'abs_error_pct_nominal': pd.to_numeric(v_long['percent_error'], errors='coerce'),
            })
            vv['v_linear_pct_nominal'] = 100.0 * vv['v_linear_pu']
            vv['v_ac_pct_nominal'] = 100.0 * vv['v_ac_pu']
            vv['stage_iteration'] = iteration
            vv['stage'] = stage_label
            v_detail_list.append(vv)
    cm_detail = pd.concat(cm_detail_list, ignore_index=True) if cm_detail_list else pd.DataFrame()
    v_detail = pd.concat(v_detail_list, ignore_index=True) if v_detail_list else pd.DataFrame()
    if not v_detail.empty:
        # Express voltage accuracy in percent of nominal voltage. Since 1 pu is
        # the nominal value, percentage error is error_pu * 100. These columns
        # make the plotting functions independent of whether the raw detail
        # table was produced by an older or newer code version.
        if 'abs_error_pct_nominal' not in v_detail.columns and 'abs_error_pu' in v_detail.columns:
            v_detail['abs_error_pct_nominal'] = 100.0 * pd.to_numeric(v_detail['abs_error_pu'], errors='coerce')
        if 'signed_error_pct_nominal' not in v_detail.columns and 'error_pu' in v_detail.columns:
            v_detail['signed_error_pct_nominal'] = 100.0 * pd.to_numeric(v_detail['error_pu'], errors='coerce')
        if 'v_linear_pct_nominal' not in v_detail.columns and 'v_linear_pu' in v_detail.columns:
            v_detail['v_linear_pct_nominal'] = 100.0 * pd.to_numeric(v_detail['v_linear_pu'], errors='coerce')
        if 'v_ac_pct_nominal' not in v_detail.columns and 'v_ac_pu' in v_detail.columns:
            v_detail['v_ac_pct_nominal'] = 100.0 * pd.to_numeric(v_detail['v_ac_pu'], errors='coerce')
    # Statistics are kept per market stage
    if not cm_detail.empty:
        cm_hour = cm_detail.groupby(['scenario', 'short_label', 'product', 'flex_case', 'stage_iteration', 'stage', 'hour'], as_index=False).agg(
            cm_cells=('asset', 'count'),
            cm_mean_abs_error_mva=('abs_error_mva', 'mean'),
            cm_min_abs_error_mva=('abs_error_mva', 'min'),
            cm_max_abs_error_mva=('abs_error_mva', 'max'),
            cm_p95_abs_error_mva=('abs_error_mva', lambda x: float(np.nanpercentile(x, 95))),
            cm_mean_abs_error_pct_smax=('abs_error_pct_smax', 'mean'),
            cm_p95_abs_error_pct_smax=('abs_error_pct_smax', lambda x: float(np.nanpercentile(x, 95))),
            cm_max_abs_error_pct_smax=('abs_error_pct_smax', 'max'),
            cm_bias_mva=('error_mva', 'mean'),
        )
        cm_summary = cm_detail.groupby(['scenario', 'short_label', 'product', 'flex_case', 'stage_iteration', 'stage'], as_index=False).agg(
            cm_cells=('asset', 'count'),
            cm_mae_mva=('abs_error_mva', 'mean'),
            cm_rmse_mva=('error_mva', lambda x: float(np.sqrt(np.nanmean(np.square(x))))),
            cm_p95_abs_error_mva=('abs_error_mva', lambda x: float(np.nanpercentile(x, 95))),
            cm_max_abs_error_mva=('abs_error_mva', 'max'),
            cm_mean_abs_error_pct_smax=('abs_error_pct_smax', 'mean'),
            cm_p95_abs_error_pct_smax=('abs_error_pct_smax', lambda x: float(np.nanpercentile(x, 95))),
            cm_max_abs_error_pct_smax=('abs_error_pct_smax', 'max'),
            cm_bias_mva=('error_mva', 'mean'),
        )
    else:
        cm_hour = pd.DataFrame(); cm_summary = pd.DataFrame()
    if not v_detail.empty:
        v_hour = v_detail.groupby(['scenario', 'short_label', 'product', 'flex_case', 'stage_iteration', 'stage', 'hour'], as_index=False).agg(
            v_cells=('bus', 'count'),
            v_mean_abs_error_pu=('abs_error_pu', 'mean'),
            v_min_abs_error_pu=('abs_error_pu', 'min'),
            v_max_abs_error_pu=('abs_error_pu', 'max'),
            v_p95_abs_error_pu=('abs_error_pu', lambda x: float(np.nanpercentile(x, 95))),
            v_mean_abs_error_pct_nominal=('abs_error_pct_nominal', 'mean'),
            v_p95_abs_error_pct_nominal=('abs_error_pct_nominal', lambda x: float(np.nanpercentile(x, 95))),
            v_max_abs_error_pct_nominal=('abs_error_pct_nominal', 'max'),
            v_bias_pct_nominal=('signed_error_pct_nominal', 'mean'),
            v_rmse_pct_nominal=('signed_error_pct_nominal', lambda x: float(np.sqrt(np.nanmean(np.square(x))))),
        )
        v_summary = v_detail.groupby(['scenario', 'short_label', 'product', 'flex_case', 'stage_iteration', 'stage'], as_index=False).agg(
            v_cells=('bus', 'count'),
            v_mae_pu=('abs_error_pu', 'mean'),
            v_rmse_pct_nominal=('signed_error_pct_nominal', lambda x: float(np.sqrt(np.nanmean(np.square(x))))),
            v_p95_abs_error_pu=('abs_error_pu', lambda x: float(np.nanpercentile(x, 95))),
            v_max_abs_error_pu=('abs_error_pu', 'max'),
            v_bias_pct_nominal=('signed_error_pct_nominal', 'mean'),
        )
    else:
        v_hour = pd.DataFrame(); v_summary = pd.DataFrame()
    return cm_detail, cm_hour, cm_summary, v_detail, v_hour, v_summary


def plot_technical_hourly_cell_accuracy_map(output_folder, market_tag, scenario_roots=None, sensitivity_root=None, vmin=0.95, vmax=1.05):
    """Comparison figure for true accuracy, calculated cell-by-cell first.

    This replaces accumulated residual plots for accuracy assessment.  CM is
    compared at each monitored asset and studied hour in MVA, then normalized by
    that asset's Smax.  Voltage is compared at each pilot bus and studied hour in pu.
    The heatmaps show hourly statistics across assets or buses, not scenario-level sums.
    """
    cm_detail, cm_hour, cm_summary, v_detail, v_hour, v_summary = _tech_acc_build_tables_v11(output_folder, market_tag, scenario_roots, sensitivity_root)
    if cm_hour.empty and v_hour.empty:
        return None
    bundle_root = _scenario_bundle_root(output_folder, market_tag)
    bundle_tag = os.path.basename(os.path.normpath(bundle_root))
    comp_folder = eva._ensure_folder(os.path.join(bundle_root, COMPARISON_ROOT_FOLDER))
    tech_folder = eva._ensure_folder(os.path.join(comp_folder, 'technical comparison'))
    # Keep the plotting pipeline focused on figures.
    # Accuracy tables are computed in memory for the heatmaps and the diagonal scenario scatter; this plotting
    # routine does not export them as CSV files.
    keys = ['scenario', 'short_label', 'product', 'flex_case', 'stage_iteration', 'stage']
    summary = cm_summary.merge(v_summary, on=keys, how='outer') if not cm_summary.empty and not v_summary.empty else (cm_summary if not cm_summary.empty else v_summary)
    if not summary.empty:
        summary = _scenario_ordered(summary)
    # One row per case AND market stage
    # (main market, corrective round k), labelled, so no row silently mixes stages.
    row_keys = set()
    for frame in (cm_hour, v_hour):
        if not frame.empty:
            row_keys.update(zip(frame['scenario'].astype(str), frame['stage_iteration'].astype(int)))
    rows = sorted(row_keys, key=lambda k: (_scenario_product_order(k[0]), _scenario_flex_order(k[0]), k[0], k[1]))
    scenarios = sorted({k[0] for k in rows})
    labels = [_tech_acc_scenario_label_v11(s) + (' main market' if it == 0 else f' corrective {it}') for s, it in rows]
    row_index = pd.MultiIndex.from_tuples(rows, names=['scenario', 'stage_iteration'])
    hours = sorted(set(cm_hour.get('hour', pd.Series(dtype=int)).dropna().astype(int).unique()).union(set(v_hour.get('hour', pd.Series(dtype=int)).dropna().astype(int).unique())))
    def pivot(df, value):
        if df.empty or value not in df.columns:
            return pd.DataFrame(np.nan, index=row_index, columns=hours)
        frame = df.assign(scenario=df['scenario'].astype(str), stage_iteration=df['stage_iteration'].astype(int),
                          hour=pd.to_numeric(df['hour'], errors='coerce').astype(int))
        return frame.pivot_table(index=['scenario', 'stage_iteration'], columns='hour', values=value, aggfunc='mean').reindex(index=row_index, columns=hours)
    cm_mean = pivot(cm_hour, 'cm_mean_abs_error_pct_smax')
    cm_p95 = pivot(cm_hour, 'cm_p95_abs_error_pct_smax')
    cm_max = pivot(cm_hour, 'cm_max_abs_error_pct_smax')
    v_mean = pivot(v_hour, 'v_mean_abs_error_pct_nominal')
    v_p95 = pivot(v_hour, 'v_p95_abs_error_pct_nominal')
    v_max = pivot(v_hour, 'v_max_abs_error_pct_nominal')
    # Larger subplot gutters reserve a
    # real column for every colorbar, so no congestion scale appears beside a
    # voltage panel and axis labels remain readable.
    fig = make_subplots(rows=2, cols=3, horizontal_spacing=0.16, vertical_spacing=0.20,
                        subplot_titles=(
                            'Congestion mean<br>|AC − linear| [% of asset Smax]',
                            'Congestion P95<br>|AC − linear| [% of asset Smax]',
                            'Congestion maximum<br>|AC − linear| [% of asset Smax]',
                            'Voltage mean<br>|AC − linear| [% nominal]',
                            'Voltage P95<br>|AC − linear| [% nominal]',
                            'Voltage maximum<br>|AC − linear| [% nominal]',
                        ))
    congestion_scale = _finite_abs_max(cm_mean, cm_p95, cm_max)
    voltage_scale = _finite_abs_max(v_mean, v_p95, v_max)
    specs = [
        (cm_mean, 1, 1, '[% Smax]', '.3f', congestion_scale),
        (cm_p95, 1, 2, '[% Smax]', '.3f', congestion_scale),
        (cm_max, 1, 3, '[% Smax]', '.3f', congestion_scale),
        (v_mean, 2, 1, '[% nominal]', '.3f', voltage_scale),
        (v_p95, 2, 2, '[% nominal]', '.3f', voltage_scale),
        (v_max, 2, 3, '[% nominal]', '.3f', voltage_scale),
    ]
    colorbar_x = {1: 0.245, 2: 0.632, 3: 1.018}
    for mat, row, col, unit, fmt, scale_max in specs:
        fig.add_trace(go.Heatmap(
            x=hours, y=labels, z=mat.to_numpy(dtype=float), colorscale='Viridis',
            zmin=0.0, zmax=scale_max,
            colorbar=dict(
                title=dict(text=unit, side='right'), len=0.32,
                y=0.79 if row == 1 else 0.21, x=colorbar_x[col],
                thickness=12, xpad=4, outlinewidth=0.6,
            ),
            hovertemplate='Case and market stage: %{y}<br>Scenario: S%{customdata}<br>Error: %{z:' + fmt + '} ' + unit + '<extra></extra>',
            customdata=np.tile(np.array(hours) + 1, (len(labels), 1)),
        ), row=row, col=col)
    # The columns are the windows of simulation_window -- independent
    # scenarios S1, S2, ... or consecutive time steps h0, h1, ... (simulation_window_as_timesteps); blank cells:
    # the stage activated nothing in that window, so there is no linear prediction to verify.
    w_ticks = [window_mode.point_label(h) for h in hours]
    for col in range(1, 4):
        fig.update_xaxes(title_text=window_mode.axis_title(), row=2, col=col, automargin=True,
                         tickmode='array', tickvals=hours, ticktext=w_ticks)
        fig.update_xaxes(title_text=None, row=1, col=col, automargin=True,
                         tickmode='array', tickvals=hours, ticktext=w_ticks)
        fig.update_yaxes(showticklabels=(col == 1), title_text='Case and market stage' if col == 1 else None,
                         row=1, col=col, automargin=True, autorange='reversed')
        fig.update_yaxes(showticklabels=(col == 1), title_text='Case and market stage' if col == 1 else None,
                         row=2, col=col, automargin=True, autorange='reversed')
    fig.add_annotation(x=0.5, y=-0.13, xref='paper', yref='paper', showarrow=False,
                       text='Linear prediction of each market stage (sensitivities at the operating point of the stage, applied '
                            'to its activation) against the AC power flow after the stage. Blank cell: no activation '
                            'in that stage and scenario.', font=dict(size=13, color='#4B5563'))
    _apply_phase3_layout(fig, market_tag, height=max(980, 430 + 36 * len(rows)), show_legend=False)
    fig.update_layout(margin=dict(l=210, r=195, t=135, b=150))
    return _save_comparison_fig(fig, 'TechnicalHourlyCellAccuracyMap_' + bundle_tag, output_folder, market_tag, 'Comparison - Hourly cell-level linear-model accuracy')


def plot_technical_average_predicted_vs_actual_scatter(output_folder, market_tag, scenario_roots=None, sensitivity_root=None):
    """Scenario points comparing average linear estimate vs average AC value.

    Left panel: average estimated congestion across monitored assets and hours
    vs average AC congestion across the same asset-hour cells.
    Right panel: average estimated voltage across pilot buses and hours vs
    average AC voltage across the same bus-hour cells.
    """
    cm_detail, cm_hour, cm_summary, v_detail, v_hour, v_summary = _tech_acc_build_tables_v11(output_folder, market_tag, scenario_roots, sensitivity_root)
    if cm_detail.empty and v_detail.empty:
        return None
    rows = []
    # One point per case AND market stage.
    row_keys = set()
    for frame in (cm_detail, v_detail):
        if not frame.empty:
            row_keys.update(zip(frame['scenario'].astype(str), frame['stage_iteration'].astype(int)))
    stage_rows = sorted(row_keys, key=lambda k: (_scenario_product_order(k[0]), _scenario_flex_order(k[0]), k[0], k[1]))
    for scenario, iteration in stage_rows:
        cm_s = cm_detail[(cm_detail['scenario'].astype(str) == scenario) & (cm_detail['stage_iteration'].astype(int) == iteration)].copy() if not cm_detail.empty else pd.DataFrame()
        v_s = v_detail[(v_detail['scenario'].astype(str) == scenario) & (v_detail['stage_iteration'].astype(int) == iteration)].copy() if not v_detail.empty else pd.DataFrame()
        row = {
            'scenario': scenario,
            'short_label': _tech_acc_scenario_label_v11(scenario) + (' main' if iteration == 0 else f' corr. {iteration}'),
            'product': _tech_acc_scenario_parts_v11(scenario).get('product'),
            'flex_case': _tech_acc_scenario_parts_v11(scenario).get('flex_case'),
            'cm_linear_avg_mva': float(cm_s['s_linear_mva'].mean()) if not cm_s.empty else np.nan,
            'cm_ac_avg_mva': float(cm_s['s_ac_mva'].mean()) if not cm_s.empty else np.nan,
            'cm_cells': int(len(cm_s)) if not cm_s.empty else 0,
            'v_linear_avg_pu': float(v_s['v_linear_pu'].mean()) if not v_s.empty else np.nan,
            'v_ac_avg_pu': float(v_s['v_ac_pu'].mean()) if not v_s.empty else np.nan,
            'v_cells': int(len(v_s)) if not v_s.empty else 0,
        }
        rows.append(row)
    df = _scenario_ordered(pd.DataFrame(rows))
    colors, markers = _comparison_color_marker_maps()
    fig = make_subplots(rows=1, cols=2, horizontal_spacing=0.18, subplot_titles=(
        'Congestion average<br>linear estimate vs AC exact value',
        'Voltage average<br>linear estimate vs AC exact value',
    ))
    for prod in ['P', 'Q', 'PQ']:
        g = df[df['product'] == prod].copy()
        if not g.empty:
            fig.add_trace(go.Scatter(
                x=pd.to_numeric(g['cm_linear_avg_mva'], errors='coerce'), y=pd.to_numeric(g['cm_ac_avg_mva'], errors='coerce'),
                mode='markers+text', name=prod, legendgroup=prod, text=g['short_label'].astype(str), textposition='top center',
                marker=dict(color=colors.get(prod), symbol=markers.get(prod), size=12, line=dict(color='white', width=1.0)),
                customdata=np.column_stack([pd.to_numeric(g['cm_cells'], errors='coerce')]),
                hovertemplate='Scenario: %{text}<br>Average linear congestion: %{x:.6f} MVA<br>Average AC congestion: %{y:.6f} MVA<br>Monitored asset-hour cells: %{customdata[0]:.0f}<extra></extra>',
            ), row=1, col=1)
            fig.add_trace(go.Scatter(
                x=pd.to_numeric(g['v_linear_avg_pu'], errors='coerce'), y=pd.to_numeric(g['v_ac_avg_pu'], errors='coerce'),
                mode='markers+text', name=prod + ' ', legendgroup=prod, showlegend=False, text=g['short_label'].astype(str), textposition='top center',
                marker=dict(color=colors.get(prod), symbol=markers.get(prod), size=12, line=dict(color='white', width=1.0)),
                customdata=np.column_stack([pd.to_numeric(g['v_cells'], errors='coerce')]),
                hovertemplate='Scenario: %{text}<br>Average linear voltage: %{x:.6f} pu<br>Average AC voltage: %{y:.6f} pu<br>Pilot bus-hour cells: %{customdata[0]:.0f}<extra></extra>',
            ), row=1, col=2)
    def _identity_line(vals_x, vals_y):
        vals = pd.concat([pd.Series(vals_x), pd.Series(vals_y)], ignore_index=True)
        vals = pd.to_numeric(vals, errors='coerce').replace([np.inf, -np.inf], np.nan).dropna()
        if vals.empty:
            return (0.0, 1.0)
        lo = float(vals.min())
        hi = float(vals.max())
        pad = max((hi - lo) * 0.08, 1e-6)
        return lo - pad, hi + pad
    cm_lo, cm_hi = _identity_line(df.get('cm_linear_avg_mva', pd.Series(dtype=float)), df.get('cm_ac_avg_mva', pd.Series(dtype=float)))
    v_lo, v_hi = _identity_line(df.get('v_linear_avg_pu', pd.Series(dtype=float)), df.get('v_ac_avg_pu', pd.Series(dtype=float)))
    fig.add_trace(go.Scatter(x=[cm_lo, cm_hi], y=[cm_lo, cm_hi], mode='lines', showlegend=False, line=dict(color='rgba(17,24,39,0.55)', width=1.8, dash='dash'), hoverinfo='skip'), row=1, col=1)
    fig.add_trace(go.Scatter(x=[v_lo, v_hi], y=[v_lo, v_hi], mode='lines', showlegend=False, line=dict(color='rgba(17,24,39,0.55)', width=1.8, dash='dash'), hoverinfo='skip'), row=1, col=2)
    fig.update_xaxes(title_text='Average linear estimated congestion [MVA]', row=1, col=1)
    fig.update_xaxes(range=[cm_lo, cm_hi], row=1, col=1)
    fig.update_yaxes(title_text='Average AC exact congestion [MVA]', range=[cm_lo, cm_hi],
                     scaleanchor='x', scaleratio=1, row=1, col=1)
    fig.update_xaxes(title_text='Average linear estimated voltage [pu]', row=1, col=2)
    fig.update_xaxes(range=[v_lo, v_hi], row=1, col=2)
    # predicted-versus-actual panels use
    # identical x/y ranges so the diagonal has an undistorted 45-degree meaning.
    fig.update_yaxes(title_text='Average AC exact voltage [pu]', range=[v_lo, v_hi],
                     scaleanchor='x2', scaleratio=1, row=1, col=2)
    _apply_phase3_layout(fig, market_tag, height=720, show_legend=True)
    fig.update_layout(margin=dict(l=120, r=90, t=125, b=145), legend=dict(orientation='h', y=-0.14, x=0.5, xanchor='center'))
    return _save_comparison_fig(fig, 'TechnicalAveragePredictedVsActualScatter_' + os.path.basename(os.path.normpath(_scenario_bundle_root(output_folder, market_tag))), output_folder, market_tag, 'Comparison - Average linear estimate versus AC exact value')


def technical_comparison(
    pre_ts_root: Optional[str],
    post_ts_root: Optional[str],
    market_result_file: Optional[str],
    output_folder: str,
    market_tag: str,
    vmin: float = 0.95,
    vmax: float = 1.05,
    scenario_roots: Optional[List[str]] = None,
    scenario_labels: Optional[List[str]] = None,
    sensitivity_root: Optional[str] = None,
) -> Dict[str, Optional[str]]:
    """Draw the technical comparison figures that need the scenarios of the study side by side.

    The three figures are written to comparison/technical comparison/ of the study folder and are overwritten
    as more sibling scenarios finish, so after the last scenario they hold the whole comparison.  The hourly
    accuracy map and the predicted-versus-actual scatter of the same folder are drawn by market_analytics.
    """
    print("\n----- Running technical comparison -----")
    print("Scenario:", market_tag)
    comparison = _load_comparison_data(scenario_roots, scenario_labels, vmin, vmax, output_folder=output_folder,
                                       market_tag=market_tag, sensitivity_root=sensitivity_root)
    if comparison is None or comparison.empty:
        # A single scenario still gets its figures, as a benchmark against itself.
        data = _read_phase3_inputs(
            pre_ts_root=pre_ts_root, post_ts_root=post_ts_root, market_result_file=market_result_file,
            output_folder=output_folder, market_tag=market_tag, vmin=vmin, vmax=vmax,
            sensitivity_root=sensitivity_root)
        comparison = pd.DataFrame([_scenario_summary_from_data(market_tag, data)])
    calls = [
        ("TechnicalSecurityTrendByFlex", lambda: plot_technical_security_trend_by_flex(comparison, output_folder, market_tag)),
        ("TechnicalProductFlexHeatmap", lambda: plot_technical_product_flex_heatmap(comparison, output_folder, market_tag)),
        ("ProductDesignResponseCurve", lambda: plot_product_design_response_curve(comparison, output_folder, market_tag)),
    ]
    saved: Dict[str, Optional[str]] = {}
    for name, func in calls:
        try:
            saved[name] = func()
            if saved[name] is None:
                print("Skipped:", name, "- required data not available or not meaningful.")
        except Exception as exc:
            saved[name] = None
            print("Skipped:", name, "- error:", str(exc))
    print("----- Technical comparison finished -----\n")
    return saved
