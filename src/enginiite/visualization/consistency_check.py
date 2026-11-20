"""Cross-scenario KPI consistency checks and diagnostic visualizations.

The module reads the current enginIITe workbook schema and compares the physical
standard, the detection tolerance and the optimization tolerance independently.

Outputs are written to ``data_out/<scenario bundle>/ConsistencyCheck`` beside
the bundle-level ``comparison`` directory.  The checks use existing KPI and
market results only; they do not rerun the network simulation.
"""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from enginiite.visualization import figure_helpers as eva


THRESHOLDS: Tuple[Tuple[str, str, str, str], ...] = (
    ("standard", "Physical standard", "standard", "standard"),
    ("detection", "Detection tolerance", "tol_v", "tol_i"),
    ("optimization", "Optimization tolerance", "tol_v_opt", "tol_i_opt"),
)
PRODUCT_ORDER = {"P": 0, "Q": 1, "PQ": 2}
PRODUCT_COLORS = {"P": "#0057B8", "Q": "#00843D", "PQ": "#F77F00"}
PRODUCT_SYMBOLS = {"P": "circle", "Q": "square", "PQ": "diamond"}
PRODUCT_GLYPHS = {"P": "○", "Q": "□", "PQ": "◇"}
STATUS_CODE = {"PASS": 0.0, "REVIEW": 1.0, "FAIL": 2.0, "N/A": np.nan}
THRESHOLD_SHORT = {"standard": "Std", "detection": "Det", "optimization": "Opt"}
THRESHOLD_NOTE = (
    "Threshold codes: Std = physical standard; Det = detection threshold using tol_v or tol_i; "
    "Opt = optimization threshold using tol_v + tol_v_opt or tol_i + tol_i_opt."
)
STATUS_NOTE = (
    "Status criteria: PASS = all structural checks pass and no diagnostic warning is present; "
    "REVIEW = structure passes, but a zero-cost/100%-resolution mismatch or a negative avoided KPI needs review; "
    "FAIL = missing KPI data, invalid threshold order, or non-monotonic congestion counts."
)


def _scenario_parts(scenario: str) -> Dict[str, object]:
    match = re.search(r"_CMVC_(PQ|P|Q)_(VL\d+)_(F\d+)_(SK\d+)(?:_|$)", str(scenario))
    if not match:
        return {
            "product": "",
            "voltage_level": "",
            "flex_case": "",
            "flex_number": 999,
            "storage_case": "",
            "short_label": str(scenario),
        }
    product, voltage_level, flex_case, storage_case = match.groups()
    flex_number = int(re.search(r"\d+", flex_case).group())
    return {
        "product": product,
        "voltage_level": voltage_level,
        "flex_case": flex_case,
        "flex_number": flex_number,
        "storage_case": storage_case,
        "short_label": f"{product}-{flex_case}",
    }


def _read_kpi_sheet(workbook: Path, sheet_name: str) -> pd.DataFrame:
    frame = pd.read_excel(workbook, sheet_name=sheet_name)
    if frame.empty:
        raise ValueError(f"Worksheet {sheet_name!r} is empty in {workbook}.")
    first = frame.columns[0]
    if str(first).startswith("Unnamed") or str(first).strip() == "":
        frame = frame.rename(columns={first: "Scenario"})
    if "Scenario" not in frame.columns:
        frame = frame.rename(columns={frame.columns[0]: "Scenario"})
    frame = frame.loc[frame["Scenario"].notna()].copy()
    frame["Scenario"] = frame["Scenario"].astype(str).str.strip()
    if frame["Scenario"].duplicated().any():
        duplicated = frame.loc[frame["Scenario"].duplicated(keep=False), "Scenario"].unique().tolist()
        raise ValueError(f"Duplicated scenarios in {sheet_name}: {duplicated}")
    return frame.set_index("Scenario")


def _numeric_column(frame: pd.DataFrame, candidates: Sequence[str], required: bool = False) -> pd.Series:
    lookup = {str(column).casefold(): column for column in frame.columns}
    selected = None
    for candidate in candidates:
        if candidate in frame.columns:
            selected = candidate
            break
        if candidate.casefold() in lookup:
            selected = lookup[candidate.casefold()]
            break
    if selected is None:
        if required:
            raise KeyError(f"None of the required columns were found: {list(candidates)}")
        return pd.Series(np.nan, index=frame.index, dtype=float)
    return pd.to_numeric(frame[selected], errors="coerce")


def _find_kpi_workbook(bundle_root: Path) -> Path:
    bundle_name = bundle_root.name
    preferred = bundle_root / f"KPI_results_{bundle_name}" / f"{bundle_name}.xlsx"
    if preferred.is_file():
        return preferred
    candidates = sorted(bundle_root.glob("KPI_results_*/*.xlsx"))
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise FileNotFoundError(f"No KPI workbook was found below {bundle_root}.")
    raise ValueError(f"Multiple KPI workbooks were found below {bundle_root}; pass --workbook explicitly.")


def _resolve_bundle_root(workbook: Optional[Path], bundle_root: Optional[Path]) -> Tuple[Path, Path]:
    if bundle_root is not None:
        resolved_bundle = bundle_root.expanduser().resolve()
        resolved_workbook = workbook.expanduser().resolve() if workbook else _find_kpi_workbook(resolved_bundle)
        return resolved_bundle, resolved_workbook
    if workbook is not None:
        resolved_workbook = workbook.expanduser().resolve()
        parent = resolved_workbook.parent
        resolved_bundle = parent.parent if parent.name.startswith("KPI_results_") else parent
        return resolved_bundle, resolved_workbook
    candidates = sorted(Path("data_out").glob("*/KPI_results_*/*.xlsx"))
    if len(candidates) != 1:
        raise ValueError("Pass --bundle-root or --workbook when the KPI workbook cannot be inferred uniquely.")
    resolved_workbook = candidates[0].resolve()
    return resolved_workbook.parent.parent, resolved_workbook


def _join_current_results(workbook: Path) -> pd.DataFrame:
    overall = _read_kpi_sheet(workbook, "Overall_Results")
    voltage = _read_kpi_sheet(workbook, "AvoidVoltageViol_Results")
    congestion = _read_kpi_sheet(workbook, "AvoidCongestions_Results")
    all_scenarios = overall.index.union(voltage.index).union(congestion.index)
    result = pd.DataFrame(index=all_scenarios)
    result.index.name = "scenario"

    result["in_overall"] = result.index.isin(overall.index)
    result["in_voltage"] = result.index.isin(voltage.index)
    result["in_congestion"] = result.index.isin(congestion.index)
    result["data_complete"] = result[["in_overall", "in_voltage", "in_congestion"]].all(axis=1)

    result["objective_eur"] = _numeric_column(overall, ["ObjValue [Eur]", "ObjValue [EUR]"], required=True).reindex(all_scenarios)
    result["cost_alpha_eur"] = _numeric_column(overall, ["CostAlpha_Total [Eur]", "CostAlpha_Total [EUR]"], required=True).reindex(all_scenarios)
    result["cost_beta_eur"] = _numeric_column(overall, ["CostBeta_Total [Eur]", "CostBeta_Total [EUR]"], required=True).reindex(all_scenarios)
    result["active_cost_eur"] = _numeric_column(overall, ["ActivePowerCost [Eur]", "ActivePowerCost [EUR]"]).reindex(all_scenarios)
    result["reactive_cost_eur"] = _numeric_column(overall, ["ReactivePowerCost [Eur]", "ReactivePowerCost [EUR]"]).reindex(all_scenarios)
    result["reported_total_cost_eur"] = _numeric_column(overall, ["TotalCost [Eur]", "TotalCost [EUR]"]).reindex(all_scenarios)

    for internal, _label, voltage_suffix, congestion_suffix in THRESHOLDS:
        # The KPI workbook names its threshold columns
        # 'standard', 'detection' and 'optimization' (e.g. AvoidVoltage_detection [%]); only the
        # older suffixes tol_v / tol_i / *_opt were read, so the detection and optimization
        # columns came out empty and every scenario was reported as FAIL.  Both names are read.
        v_sfx = list(dict.fromkeys([internal, voltage_suffix]))
        c_sfx = list(dict.fromkeys([internal, congestion_suffix]))
        voltage_candidates = [f"AvoidVoltage_{s} [%]" for s in v_sfx]
        congestion_candidates = [f"AvoidCongestion_{s} [%]" for s in c_sfx]
        if internal == "standard":
            voltage_candidates.append("AvoidVoltageViolations [%]")
            congestion_candidates.append("AvoidCongestions [%]")
        result[f"avoid_voltage_{internal}_pct"] = _numeric_column(voltage, voltage_candidates).reindex(all_scenarios)
        result[f"avoid_congestion_{internal}_pct"] = _numeric_column(congestion, congestion_candidates).reindex(all_scenarios)
        result[f"voltage_min_{internal}_pu"] = _numeric_column(voltage, [f"ThresholdMin_{s} [pu]" for s in v_sfx]).reindex(all_scenarios)
        result[f"voltage_max_{internal}_pu"] = _numeric_column(voltage, [f"ThresholdMax_{s} [pu]" for s in v_sfx]).reindex(all_scenarios)
        result[f"current_limit_{internal}_pct"] = _numeric_column(congestion, [f"Threshold_{s} [%]" for s in c_sfx]).reindex(all_scenarios)
        result[f"resolved_congestion_{internal}"] = _numeric_column(congestion, [f"ResolvedCongestion_{s} [u]" for s in c_sfx]).reindex(all_scenarios)
        result[f"persistent_congestion_{internal}"] = _numeric_column(congestion, [f"PersistentCongestion_{s} [u]" for s in c_sfx]).reindex(all_scenarios)
        result[f"new_congestion_{internal}"] = _numeric_column(congestion, [f"NewCongestion_{s} [u]" for s in c_sfx]).reindex(all_scenarios)

    metadata = pd.DataFrame([_scenario_parts(scenario) for scenario in result.index], index=result.index)
    result = pd.concat([metadata, result], axis=1)
    result["product_order"] = result["product"].map(PRODUCT_ORDER).fillna(99)
    result = result.sort_values(["voltage_level", "product_order", "flex_number", "scenario"])
    return result


def _nondecreasing(values: Iterable[float], tolerance: float = 1e-9) -> bool:
    clean = [float(value) for value in values if pd.notna(value)]
    return len(clean) >= 2 and all(right + tolerance >= left for left, right in zip(clean, clean[1:]))


def _nonincreasing(values: Iterable[float], tolerance: float = 1e-9) -> bool:
    clean = [float(value) for value in values if pd.notna(value)]
    return len(clean) >= 2 and all(right <= left + tolerance for left, right in zip(clean, clean[1:]))


def _evaluate_consistency(data: pd.DataFrame, resolution_tolerance: float, cost_tolerance: float) -> pd.DataFrame:
    out = data.copy()
    voltage_mins = [f"voltage_min_{name}_pu" for name, *_ in THRESHOLDS]
    voltage_maxs = [f"voltage_max_{name}_pu" for name, *_ in THRESHOLDS]
    current_limits = [f"current_limit_{name}_pct" for name, *_ in THRESHOLDS]
    out["voltage_threshold_order_ok"] = out.apply(
        lambda row: _nondecreasing(row[column] for column in voltage_mins)
        and _nonincreasing(row[column] for column in voltage_maxs), axis=1
    )
    out["current_threshold_order_ok"] = out.apply(
        lambda row: _nonincreasing(row[column] for column in current_limits), axis=1
    )
    out["threshold_order_ok"] = out["voltage_threshold_order_ok"] & out["current_threshold_order_ok"]

    pre_columns = []
    post_columns = []
    for internal, *_ in THRESHOLDS:
        pre_name = f"congestion_pre_{internal}"
        post_name = f"congestion_post_{internal}"
        out[pre_name] = out[f"resolved_congestion_{internal}"] + out[f"persistent_congestion_{internal}"]
        out[post_name] = out[f"persistent_congestion_{internal}"] + out[f"new_congestion_{internal}"]
        pre_columns.append(pre_name)
        post_columns.append(post_name)
    out["congestion_count_monotonic"] = out.apply(
        lambda row: _nondecreasing(row[column] for column in pre_columns)
        and _nondecreasing(row[column] for column in post_columns), axis=1
    )

    out["beta_zero"] = out["cost_beta_eur"].abs() <= cost_tolerance
    out["alpha_zero"] = out["cost_alpha_eur"].abs() <= cost_tolerance
    out["congestion_opt_target"] = np.isclose(
        out["avoid_congestion_optimization_pct"], 100.0, rtol=0.0, atol=resolution_tolerance
    )
    out["voltage_opt_target"] = np.isclose(
        out["avoid_voltage_optimization_pct"], 100.0, rtol=0.0, atol=resolution_tolerance
    )
    out["congestion_cost_resolution_match"] = out["congestion_opt_target"] == out["beta_zero"]
    out["voltage_cost_resolution_match"] = out["voltage_opt_target"] == out["alpha_zero"]
    avoided_columns = [
        f"avoid_{service}_{threshold}_pct"
        for service in ("voltage", "congestion")
        for threshold, *_ in THRESHOLDS
    ]
    out["deterioration_detected"] = out[avoided_columns].lt(-resolution_tolerance).any(axis=1)
    out["combined_optimization_effectiveness_pct"] = out[
        ["avoid_voltage_optimization_pct", "avoid_congestion_optimization_pct"]
    ].mean(axis=1)
    calculated_total = out[["cost_alpha_eur", "cost_beta_eur", "active_cost_eur", "reactive_cost_eur"]].sum(axis=1, min_count=1)
    out["analysis_total_cost_eur"] = out["reported_total_cost_eur"].where(out["reported_total_cost_eur"].notna(), calculated_total)

    structural_fail = (~out["data_complete"]) | (~out["threshold_order_ok"]) | (~out["congestion_count_monotonic"])
    review = (~out["congestion_cost_resolution_match"]) | (~out["voltage_cost_resolution_match"]) | out["deterioration_detected"]
    out["overall_status"] = np.where(structural_fail, "FAIL", np.where(review, "REVIEW", "PASS"))
    out.attrs["resolution_tolerance"] = float(resolution_tolerance)
    out.attrs["cost_tolerance"] = float(cost_tolerance)
    return out


def _safe_range(*series: pd.Series, include: Sequence[float] = ()) -> Tuple[float, float]:
    values = pd.concat([pd.to_numeric(item, errors="coerce") for item in series], ignore_index=True)
    values = values.replace([np.inf, -np.inf], np.nan).dropna().tolist() + list(include)
    if not values:
        return 0.0, 1.0
    low, high = float(min(values)), float(max(values))
    span = high - low
    pad = max(0.06 * span, 1.0)
    return low - pad, high + pad


def _save_figure(
    fig: go.Figure,
    output_dir: Path,
    filename: str,
    header_title: str,
    figure_note: str = "",
) -> str:
    path = output_dir / filename
    fig.update_layout(title=dict(text=""))
    eva._polish_axis_units_and_overlap(fig)
    eva._write_themed_plotly_html(fig, str(path), header_title, figure_note=figure_note)
    return str(path)


def _scenario_number_labels(frame: pd.DataFrame) -> pd.Series:
    return pd.to_numeric(frame["flex_number"], errors="coerce").astype("Int64").astype(str)


def _scenario_axis_labels(frame: pd.DataFrame) -> pd.Series:
    return frame.apply(
        lambda row: f"{PRODUCT_GLYPHS.get(row['product'], '·')} {int(row['flex_number'])}",
        axis=1,
    )


def _status_border(status: pd.Series) -> Tuple[List[str], List[float]]:
    colors = status.map({"PASS": "#FFFFFF", "REVIEW": "#F9A825", "FAIL": "#C62828"}).fillna("#6B7280")
    widths = status.map({"PASS": 1.0, "REVIEW": 3.0, "FAIL": 3.5}).fillna(1.0)
    return colors.tolist(), widths.tolist()


def _technical_effectiveness_figure(data: pd.DataFrame, output_dir: Path) -> str:
    fig = make_subplots(rows=3, cols=1, vertical_spacing=0.10, subplot_titles=[
        f"{THRESHOLD_SHORT[name]} — voltage versus congestion effectiveness"
        for name, _label, *_ in THRESHOLDS
    ])
    x_series = [data[f"avoid_congestion_{name}_pct"] for name, *_ in THRESHOLDS]
    y_series = [data[f"avoid_voltage_{name}_pct"] for name, *_ in THRESHOLDS]
    x_range = _safe_range(*x_series, include=(0.0, 100.0))
    y_range = _safe_range(*y_series, include=(0.0, 100.0))
    for row, (threshold, _label, *_suffixes) in enumerate(THRESHOLDS, start=1):
        for product in ("P", "Q", "PQ"):
            subset = data.loc[data["product"] == product].sort_values("flex_number")
            if subset.empty:
                continue
            fig.add_trace(go.Scatter(
                x=subset[f"avoid_congestion_{threshold}_pct"],
                y=subset[f"avoid_voltage_{threshold}_pct"],
                mode="lines+markers+text",
                text=_scenario_number_labels(subset), textposition="top center",
                name=product, legendgroup=product, showlegend=(row == 1),
                line=dict(color=PRODUCT_COLORS[product], width=2.4),
                marker=dict(
                    size=12, color=PRODUCT_COLORS[product], symbol=PRODUCT_SYMBOLS[product],
                    line=dict(color="white", width=1.2), showscale=False,
                ),
                customdata=np.column_stack([subset.index, subset["overall_status"]]),
                hovertemplate="Scenario: %{customdata[0]}<br>Congestion avoided: %{x:.3f}%<br>Voltage avoided: %{y:.3f}%<br>Status: %{customdata[1]}<extra></extra>",
            ), row=row, col=1)
        fig.add_vline(x=0.0, line_dash="dot", line_color="rgba(107,114,128,0.55)", row=row, col=1)
        fig.add_hline(y=0.0, line_dash="dot", line_color="rgba(107,114,128,0.55)", row=row, col=1)
        fig.add_vline(x=100.0, line_dash="dash", line_color="rgba(0,87,184,0.45)", row=row, col=1)
        fig.add_hline(y=100.0, line_dash="dash", line_color="rgba(0,87,184,0.45)", row=row, col=1)
        fig.update_xaxes(title_text="Avoided congestion [%]", range=x_range, row=row, col=1)
        fig.update_yaxes(title_text="Avoided voltage violations [%]", range=y_range, row=row, col=1)
    fig.update_layout(height=1780, margin=dict(l=120, r=90, t=155, b=205), legend=dict(orientation="h", y=-0.08, x=0.5, xanchor="center"))
    return _save_figure(
        fig, output_dir, "01_TechnicalEffectivenessByThreshold.html",
        "Consistency check - Technical effectiveness by threshold",
        figure_note=f"Labels 1, 2, ... identify the flexibility cases (bid depths) F01, F02, .... Marker shapes: circle = P, square = Q, diamond = PQ. {THRESHOLD_NOTE}",
    )


def _cost_resolution_figure(data: pd.DataFrame, output_dir: Path) -> str:
    panels = [
        (service, cost_column, threshold, THRESHOLD_SHORT[threshold])
        for service, cost_column in (("congestion", "cost_beta_eur"), ("voltage", "cost_alpha_eur"))
        for threshold, *_ in THRESHOLDS
    ]
    titles = [
        f"{service.capitalize()} — {short}<br>{'CostBeta' if service == 'congestion' else 'CostAlpha'} versus avoided KPI"
        for service, _cost, _threshold, short in panels
    ]
    fig = make_subplots(rows=6, cols=1, vertical_spacing=0.055, subplot_titles=titles)
    for row, (service, cost_column, threshold, _short) in enumerate(panels, start=1):
        x_column = f"avoid_{service}_{threshold}_pct"
        for product in ("P", "Q", "PQ"):
            subset = data.loc[data["product"] == product].sort_values("flex_number").copy()
            if subset.empty:
                continue
            actual_cost = subset[cost_column].abs()
            border_colors, border_widths = _status_border(subset["overall_status"])
            fig.add_trace(go.Scatter(
                x=subset[x_column], y=np.log10(1.0 + actual_cost), mode="markers+text",
                text=_scenario_number_labels(subset), textposition="top center",
                name=product, legendgroup=product, showlegend=(row == 1),
                    marker=dict(
                        size=12, color=PRODUCT_COLORS[product], symbol=PRODUCT_SYMBOLS[product],
                        line=dict(color=border_colors, width=border_widths), showscale=False,
                ),
                customdata=np.column_stack([subset.index, actual_cost, subset["overall_status"]]),
                hovertemplate="Scenario: %{customdata[0]}<br>Avoided KPI: %{x:.3f}%<br>Penalty cost: %{customdata[1]:,.6f} EUR<br>Status: %{customdata[2]}<extra></extra>",
            ), row=row, col=1)
        fig.add_vline(x=100.0, line_dash="dash", line_color="rgba(0,87,184,0.45)", row=row, col=1)
        fig.add_hline(y=0.0, line_dash="dot", line_color="rgba(107,114,128,0.55)", row=row, col=1)
        fig.update_xaxes(title_text=f"Avoided {service} KPI [%]", row=row, col=1)
        fig.update_yaxes(title_text="log10(1 + cost [EUR])", rangemode="tozero", row=row, col=1)
    fig.update_layout(height=2920, margin=dict(l=125, r=90, t=160, b=220), legend=dict(orientation="h", y=-0.035, x=0.5, xanchor="center"))
    return _save_figure(
        fig, output_dir, "02_CostResolutionConsistency.html",
        "Consistency check - Penalty cost versus technical resolution",
        figure_note=(
            f"Labels 1, 2, ... identify the flexibility cases (bid depths) F01, F02, .... Marker shapes: circle = P, square = Q, diamond = PQ. "
            f"Amber/red marker borders identify REVIEW/FAIL scenarios. {THRESHOLD_NOTE} {STATUS_NOTE}"
        ),
    )


def _threshold_impact_figure(data: pd.DataFrame, output_dir: Path) -> str:
    panels = [
        (product, service)
        for service in ("voltage", "congestion")
        for product in ("P", "Q", "PQ")
    ]
    titles = [
        f"{product} — avoided {'voltage violations' if service == 'voltage' else 'congestion'}"
        for product, service in panels
    ]
    fig = make_subplots(rows=6, cols=1, vertical_spacing=0.055, subplot_titles=titles)
    threshold_names = [THRESHOLD_SHORT[name] for name, *_ in THRESHOLDS]
    flex_cases = sorted(data["flex_case"].dropna().unique(), key=lambda value: int(re.search(r"\d+", value).group()))
    colors = ["#0057B8", "#00A6D6", "#00843D", "#F77F00", "#7B2CBF", "#D62828"]
    voltage_range = _safe_range(*[data[f"avoid_voltage_{name}_pct"] for name, *_ in THRESHOLDS], include=(0.0, 100.0))
    congestion_range = _safe_range(*[data[f"avoid_congestion_{name}_pct"] for name, *_ in THRESHOLDS], include=(0.0, 100.0))
    for row, (product, service) in enumerate(panels, start=1):
        subset = data.loc[data["product"] == product]
        for flex_index, flex_case in enumerate(flex_cases):
            row_data = subset.loc[subset["flex_case"] == flex_case]
            if row_data.empty:
                continue
            scenario_row = row_data.iloc[0]
            y_values = [scenario_row[f"avoid_{service}_{name}_pct"] for name, *_ in THRESHOLDS]
            case_number = int(scenario_row["flex_number"])
            fig.add_trace(go.Scatter(
                x=threshold_names, y=y_values, mode="lines+markers", name=str(case_number),
                legendgroup=str(case_number), showlegend=(row == 1),
                line=dict(color=colors[flex_index % len(colors)], width=2.4),
                marker=dict(size=10, symbol=PRODUCT_SYMBOLS[product], showscale=False),
                customdata=[scenario_row.name] * len(threshold_names),
                hovertemplate="Scenario: %{customdata}<br>Threshold: %{x}<br>Avoided KPI: %{y:.3f}%<extra></extra>",
            ), row=row, col=1)
        fig.update_yaxes(
            title_text="Avoided voltage violations [%]" if service == "voltage" else "Avoided congestion [%]",
            range=voltage_range if service == "voltage" else congestion_range,
            row=row, col=1,
        )
        fig.update_xaxes(title_text="Threshold code", row=row, col=1)
    fig.update_layout(height=2660, margin=dict(l=125, r=90, t=155, b=220), legend=dict(orientation="h", y=-0.035, x=0.5, xanchor="center"))
    return _save_figure(
        fig, output_dir, "03_ThresholdImpactAcrossScenarios.html",
        "Consistency check - Impact of tolerance thresholds",
        figure_note=(
            f"Legend numbers 1, 2, ... identify the flexibility cases (bid depths) F01, F02, .... Marker shapes: circle = P, square = Q, diamond = PQ. "
            f"{THRESHOLD_NOTE}"
        ),
    )


def _cost_heatmap_figure(data: pd.DataFrame, output_dir: Path) -> str:
    metrics = [
        # The objective and CostAlpha/CostBeta are named as what they are.
        ("objective_eur", "Market objective incl. penalty [kEUR]", 1000.0),
        ("cost_alpha_eur", "Not served flexibility, voltage (CostAlpha) [kEUR]", 1000.0),
        ("cost_beta_eur", "Not served flexibility, congestion (CostBeta) [kEUR]", 1000.0),
        ("active_cost_eur", "Active-power cost [EUR]", 1.0),
        ("reactive_cost_eur", "Reactive-power cost [EUR]", 1.0),
    ]
    actual = pd.DataFrame({label: data[column] / divisor for column, label, divisor in metrics}, index=data.index)
    maxima = actual.abs().max(axis=0).replace(0.0, 1.0).fillna(1.0)
    normalized = actual.abs().divide(maxima, axis=1)
    labels = _scenario_axis_labels(data)
    fig = go.Figure(go.Heatmap(
        z=normalized.to_numpy(dtype=float), x=list(actual.columns), y=labels,
        customdata=actual.to_numpy(dtype=float), colorscale="Viridis", zmin=0.0, zmax=1.0,
        showscale=False,
        hovertemplate="Scenario: %{y}<br>Metric: %{x}<br>Actual value: %{customdata:,.6f}<br>Column-normalized magnitude: %{z:.3f}<extra></extra>",
    ))
    for row_index, scenario_label in enumerate(labels):
        for column_index, metric_label in enumerate(actual.columns):
            value = actual.iloc[row_index, column_index]
            relative = normalized.iloc[row_index, column_index]
            text_value = "—" if pd.isna(value) else f"{float(value):,.2f}"
            text_color = "#111827" if pd.notna(relative) and float(relative) >= 0.68 else "#FFFFFF"
            fig.add_annotation(
                x=metric_label, y=scenario_label, text=text_value, showarrow=False,
                font=dict(size=12, color=text_color), xref="x", yref="y",
            )
    fig.update_xaxes(title_text="Economic KPI", tickangle=-12)
    fig.update_yaxes(title_text="Scenario: shape + case number")
    fig.update_layout(height=max(980, 390 + 38 * len(data)), margin=dict(l=145, r=175, t=140, b=190))
    return _save_figure(
        fig, output_dir, "04_NormalizedCostKPIHeatmap.html",
        "Consistency check - Scenario cost KPI heatmap",
        figure_note=(
            "Every cell displays its actual numeric value in the unit written in the column heading. Cell color only "
            "helps compare relative magnitude within the same column, so no redundant colorbar is shown. Row shapes: circle = P, square = Q, "
            "diamond = PQ; row numbers 1, 2, ... identify F01, F02, ...."
        ),
    )


def _status_matrix_figure(data: pd.DataFrame, output_dir: Path) -> str:
    status = pd.DataFrame(index=data.index)
    status["Data complete"] = np.where(data["data_complete"], "PASS", "FAIL")
    status["Threshold order"] = np.where(data["threshold_order_ok"], "PASS", "FAIL")
    status["Counts monotonic"] = np.where(data["congestion_count_monotonic"], "PASS", "FAIL")
    status["Beta vs Opt"] = np.where(data["congestion_cost_resolution_match"], "PASS", "REVIEW")
    status["Alpha vs Opt"] = np.where(data["voltage_cost_resolution_match"], "PASS", "REVIEW")
    status["No deterioration"] = np.where(data["deterioration_detected"], "REVIEW", "PASS")
    z = status.apply(lambda column: column.map(STATUS_CODE)).astype(float)
    labels = _scenario_axis_labels(data)
    colorscale = [[0.0, "#2E7D32"], [0.499, "#2E7D32"], [0.5, "#F9A825"], [0.749, "#F9A825"], [0.75, "#C62828"], [1.0, "#C62828"]]
    fig = go.Figure(go.Heatmap(
        z=z.to_numpy(dtype=float), x=list(status.columns), y=labels, text=status.to_numpy(),
        texttemplate="%{text}", colorscale=colorscale, zmin=0.0, zmax=2.0, showscale=False,
        hovertemplate="Scenario: %{y}<br>Check: %{x}<br>Status: %{text}<extra></extra>",
    ))
    fig.update_xaxes(title_text="Consistency rule", tickangle=-12)
    fig.update_yaxes(title_text="Scenario: shape + case number")
    fig.update_layout(height=max(980, 390 + 38 * len(data)), margin=dict(l=145, r=95, t=140, b=195))
    resolution_tolerance = float(data.attrs.get("resolution_tolerance", 1e-9))
    cost_tolerance = float(data.attrs.get("cost_tolerance", 1e-6))
    rule_note = (
        "How each x-axis rule is checked:\n"
        "1. Data complete - PASS when the scenario exists in Overall_Results, AvoidVoltageViol_Results, and "
        "AvoidCongestions_Results; otherwise FAIL.\n"
        "2. Threshold order - PASS when voltage limits tighten from Std to Det to Opt (Vmin never decreases and "
        "Vmax never increases) and current limits never increase (100%, then tol_i, then tol_i + tol_i_opt); "
        "otherwise FAIL.\n"
        "3. Counts monotonic - PASS when the number of congestion cells cannot decrease as the loading threshold "
        "becomes stricter, checked separately before and after the market; otherwise FAIL. Pre count = resolved + "
        "persistent, and post count = persistent + new.\n"
        f"4. Beta vs Opt - PASS when both statements agree: |CostBeta| <= {cost_tolerance:g} EUR and avoided "
        f"congestion at Opt is within {resolution_tolerance:g} percentage points of 100%. A mismatch is REVIEW, "
        "not FAIL, because CostBeta may cover selected market constraints while the AC KPI can cover more assets.\n"
        f"5. Alpha vs Opt - the same test for |CostAlpha| <= {cost_tolerance:g} EUR and avoided voltage at Opt "
        f"within {resolution_tolerance:g} percentage points of 100%. A mismatch is REVIEW for the same scope reason.\n"
        f"6. No deterioration - PASS when all six avoided KPIs (voltage and congestion at Std, Det, and Opt) are "
        f">= -{resolution_tolerance:g}%. A negative value means the post-market AC result contains more violating "
        "cells than the pre-market result at that same threshold, so it is REVIEW.\n"
        "Overall result - FAIL if rules 1-3 fail; otherwise REVIEW if rules 4-6 raise a warning; otherwise PASS."
    )
    return _save_figure(
        fig, output_dir, "05_ConsistencyStatusMatrix.html",
        "Consistency check - Scenario status matrix",
        figure_note=(
            "Row shapes: circle = P, square = Q, diamond = PQ; row numbers 1, 2, ... identify F01, F02, ....\n" + rule_note
        ),
    )


def _frontier_figure(data: pd.DataFrame, output_dir: Path) -> str:
    fig = go.Figure()
    for product in ("P", "Q", "PQ"):
        subset = data.loc[data["product"] == product].sort_values("flex_number")
        if subset.empty:
            continue
        border_colors, border_widths = _status_border(subset["overall_status"])
        fig.add_trace(go.Scatter(
            x=subset["analysis_total_cost_eur"], y=subset["combined_optimization_effectiveness_pct"],
            mode="lines+markers+text", text=_scenario_number_labels(subset), textposition="top center",
            name=product, legendgroup=product, line=dict(color=PRODUCT_COLORS[product], width=2.2),
            marker=dict(
                size=13, color=PRODUCT_COLORS[product], symbol=PRODUCT_SYMBOLS[product],
                line=dict(color=border_colors, width=border_widths), showscale=False,
            ),
            customdata=np.column_stack([subset.index, subset["cost_alpha_eur"], subset["cost_beta_eur"], subset["overall_status"]]),
            hovertemplate="Scenario: %{customdata[0]}<br>Total analyzed cost: %{x:,.3f} EUR<br>Combined optimization effectiveness: %{y:.3f}%<br>CostAlpha: %{customdata[1]:,.3f} EUR<br>CostBeta: %{customdata[2]:,.3f} EUR<br>Status: %{customdata[3]}<extra></extra>",
        ))
    fig.add_hline(y=100.0, line_dash="dash", line_color="rgba(0,87,184,0.45)")
    # TotalCost includes the not served flexibility penalty.
    fig.update_xaxes(title_text="Total cost incl. not served flexibility penalty [EUR]", rangemode="tozero")
    fig.update_yaxes(title_text="Mean avoided KPI at optimization threshold [%]")
    fig.update_layout(height=980, margin=dict(l=125, r=95, t=140, b=205), legend=dict(orientation="h", y=-0.12, x=0.5, xanchor="center"))
    return _save_figure(
        fig, output_dir, "06_CostEffectivenessFrontier.html",
        "Consistency check - Cost and technical-effectiveness frontier",
        figure_note=(
            f"Labels 1, 2, ... identify the flexibility cases (bid depths) F01, F02, .... Marker shapes: circle = P, square = Q, diamond = PQ. "
            f"Amber/red marker borders identify REVIEW/FAIL scenarios. {STATUS_NOTE}"
        ),
    )


def _write_reports(data: pd.DataFrame, output_dir: Path, workbook: Path, resolution_tolerance: float, cost_tolerance: float) -> Tuple[str, str]:
    csv_path = output_dir / "ConsistencyCheck_Details.csv"
    data.reset_index().to_csv(csv_path, index=False)
    failures = data.loc[data["overall_status"] == "FAIL"]
    reviews = data.loc[data["overall_status"] == "REVIEW"]
    deterioration = data.loc[data["deterioration_detected"]]
    beta_review = data.loc[~data["congestion_cost_resolution_match"]]
    alpha_review = data.loc[~data["voltage_cost_resolution_match"]]

    def scenario_list(frame: pd.DataFrame) -> str:
        return "None." if frame.empty else "\n".join(f"- `{scenario}`" for scenario in frame.index)

    report = f"""# enginIITe cross-scenario consistency check

## Scope

- KPI workbook: `{workbook}`
- Analysed scenarios: `{len(data)}`
- Resolution comparison tolerance: `{resolution_tolerance:g}`
- Zero-cost tolerance: `{cost_tolerance:g} EUR`
- PASS: `{int((data['overall_status'] == 'PASS').sum())}`
- REVIEW: `{len(reviews)}`
- FAIL: `{len(failures)}`

The primary structural checks verify worksheet completeness, the expected
standard -> detection -> optimization threshold ordering, and monotonic
congestion counts when the threshold becomes stricter.

The cost-resolution rule is reported as a
**review signal**, not as a mathematical identity. `CostAlpha_Total` and
`CostBeta_Total` belong to the selected market constraints, while avoided KPIs
may include a wider AC-evaluation scope. Therefore a mismatch can identify a
scope, indexing, tolerance, or penalty-normalization question without proving
that the optimization itself is incorrect.

## Structural failures

{scenario_list(failures)}

## CostBeta versus optimization-threshold congestion reviews

{scenario_list(beta_review)}

## CostAlpha versus optimization-threshold voltage reviews

{scenario_list(alpha_review)}

## Scenarios with a negative avoided KPI

{scenario_list(deterioration)}

Negative avoided values mean that the post-market AC evaluation contains more
violating asset-hour or bus-hour cells than the corresponding pre-market case
at that same named threshold.
"""
    report_path = output_dir / "ConsistencyCheck_Report.md"
    report_path.write_text(report, encoding="utf-8")
    return str(csv_path), str(report_path)


def run_consistency_check(
    bundle_root: Optional[os.PathLike] = None,
    workbook_path: Optional[os.PathLike] = None,
    output_dir: Optional[os.PathLike] = None,
    resolution_tolerance: float = 1e-9,
    cost_tolerance: float = 1e-6,
) -> Dict[str, str]:
    """Run all current-workbook consistency checks and figures."""
    bundle, workbook = _resolve_bundle_root(
        Path(workbook_path) if workbook_path else None,
        Path(bundle_root) if bundle_root else None,
    )
    if not workbook.is_file():
        raise FileNotFoundError(f"KPI workbook not found: {workbook}")
    destination = Path(output_dir).expanduser().resolve() if output_dir else bundle / "ConsistencyCheck"
    destination.mkdir(parents=True, exist_ok=True)
    # Every figure consumes the same
    # threshold-aware dataframe and is stored beside the comparison folder.
    data = _evaluate_consistency(_join_current_results(workbook), resolution_tolerance, cost_tolerance)
    outputs = {
        "technical_effectiveness": _technical_effectiveness_figure(data, destination),
        "cost_resolution": _cost_resolution_figure(data, destination),
        "threshold_impact": _threshold_impact_figure(data, destination),
        "cost_heatmap": _cost_heatmap_figure(data, destination),
        "status_matrix": _status_matrix_figure(data, destination),
        "cost_effectiveness_frontier": _frontier_figure(data, destination),
    }
    outputs["details_csv"], outputs["report_md"] = _write_reports(
        data, destination, workbook, resolution_tolerance, cost_tolerance
    )
    outputs["output_dir"] = str(destination)
    return outputs


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate threshold-aware cross-scenario consistency figures.")
    parser.add_argument("--bundle-root", type=Path, default=None, help="Scenario bundle containing KPI_results_*.")
    parser.add_argument("--workbook", type=Path, default=None, help="Explicit KPI workbook path.")
    parser.add_argument("--output-dir", type=Path, default=None, help="Override the default bundle/ConsistencyCheck folder.")
    parser.add_argument("--resolution-tolerance", type=float, default=1e-9)
    parser.add_argument("--cost-tolerance", type=float, default=1e-6)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.resolution_tolerance < 0 or args.cost_tolerance < 0:
        raise ValueError("Tolerances must be non-negative.")
    outputs = run_consistency_check(
        bundle_root=args.bundle_root,
        workbook_path=args.workbook,
        output_dir=args.output_dir,
        resolution_tolerance=args.resolution_tolerance,
        cost_tolerance=args.cost_tolerance,
    )
    for name, path in outputs.items():
        print(f"{name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
