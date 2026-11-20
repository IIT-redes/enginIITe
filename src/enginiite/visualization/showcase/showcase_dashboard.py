"""
showcase_dashboard.py  —  Showcase  (v2)
================================================

Six genuinely new, non-redundant, interpretation-focused figures for the
enginIITe Local Flexibility Market platform.

Every figure addresses a specific question that no existing platform module
answers, and every data item is read from real platform output files using
the same conventions as market_analytics.py.

Figures
-------
  Fig 1  Capacity Utilisation Heatmap
         How much of each FSP's offered P-capacity did the market actually
         dispatch, hour by hour?  Source: DW_U_Lim_A/B (offered) vs DW_A/B
         (dispatched).  Ratio = |DW| / DW_U_Lim, clamped to [0,1].

  Fig 2  P–Q Operating Envelope per FSP
         Each provider plotted in the P-Q plane: initial operating point
         (Winit, Rinit) and activated adjustment (DW_A + DW_A, DR_A + DR_A).
         Shows whether providers hit their physical limits and which direction
         they moved.  Source: Winit_A/B, Rinit_A/B, DW_A/B, DR_A/B.

  Fig 3  Storage SOC Trajectory
         State-of-charge over studied hours for all storage units, with the
         activation P-dispatch overlaid on a secondary axis.  Reveals energy
         buffering, charge/discharge cycles, and SOC boundary constraints.
         Source: SOC_C, DW_C.

  Fig 4  Merit-Order Dispatch — Cost vs Activation
         Scatter of each FSP's bid price (Pup_cost / Qup_cost from
         W_U_Cost_A/B/C) against its total dispatched volume.  The market
         objective (maximize welfare surplus) means cheaper providers should
         be activated more — this figure confirms or challenges that.
         Source: W_U_Cost_A/B/C, R_U_Cost_A/B/C, DW_A/B/C, DR_A/B/C.

  Fig 5  Per-Asset Congestion Decomposition
         total_cm_PreMKT and total_cm_postMKT, broken down by individual line
         / transformer, per hour.  Diverging bar: pre = positive side,
         post = negative side.  Immediately shows which assets were solved and
         which retain residual congestion.
         Source: total_cm_PreMKT.xlsx, total_cm_postMKT.xlsx.

  Fig 6  Voltage Bus Profiler — Worst Buses Over Time
         For the N worst buses (ranked by cumulative deviation from nominal),
         show the full vm_pu trajectory pre- and post-market on the same axes,
         with the voltage band [vmin, vmax] shaded.  Unlike heatmaps, this
         preserves the continuous voltage signal and shows the exact pu values.
         Source: res_bus/vm_pu.csv (pre and post).

Entry point
-----------
    from enginiite.visualization.showcase.showcase_dashboard import generate_showcase

    generate_showcase(
        pre_ts_root        = "…/timeseries/pre_market/",
        post_ts_root       = "…/timeseries/post_market/",
        market_result_file = "…/model_results_…xlsx",
        output_folder      = "…/visualization/",
        market_tag         = "net_CMVC_PQ_VL01_F05_SK01_T1",
        vmin               = 0.95,
        vmax               = 1.05,
    )

Outputs saved to:  output_folder/showcase/
"""

from __future__ import annotations

import os
import math
import re
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


# =============================================================================
# 0.  THEME
# =============================================================================

C = dict(
    bg        = "#0F1117",
    bg2       = "#1A1F2E",
    bg3       = "#222840",
    grid      = "#252D42",
    border    = "#334155",
    text      = "#E2E8F0",
    muted     = "#94A3B8",
    blue      = "#60A5FA",
    green     = "#34D399",
    red       = "#F87171",
    amber     = "#FBBF24",
    purple    = "#A78BFA",
    sky       = "#38BDF8",
    rose      = "#FB7185",
    teal      = "#2DD4BF",
    load_col  = "#60A5FA",
    gen_col   = "#34D399",
    sto_col   = "#A78BFA",
    pre_col   = "#F87171",
    post_col  = "#34D399",
)

FONT = "Inter, 'Segoe UI', Arial, sans-serif"

_BASE_LAYOUT = dict(
    paper_bgcolor = C["bg"],
    plot_bgcolor  = C["bg2"],
    font          = dict(family=FONT, color=C["text"], size=13),
    hoverlabel    = dict(
        bgcolor     = C["bg3"],
        bordercolor = C["border"],
        font_color  = C["text"],
        font_size   = 12,
    ),
    legend = dict(
        bgcolor     = C["bg3"],
        bordercolor = C["border"],
        borderwidth = 1,
        font        = dict(size=11),
    ),
    margin = dict(l=70, r=40, t=70, b=60),
)

_AX = dict(
    gridcolor     = C["grid"],
    linecolor     = C["border"],
    zerolinecolor = C["grid"],
    tickfont      = dict(color=C["muted"], size=11),
    title_font    = dict(color=C["muted"], size=12),
)


def _theme(fig: go.Figure, title: str = "", height: int = 620) -> go.Figure:
    kw = dict(**_BASE_LAYOUT, height=height)
    if title:
        kw["title"] = dict(text=title, x=0.013, xanchor="left",
                           font=dict(size=15, color=C["text"]))
    fig.update_layout(**kw)
    fig.update_xaxes(**_AX)
    fig.update_yaxes(**_AX)
    return fig


# =============================================================================
# 1.  I/O HELPERS  (same conventions as platform modules)
# =============================================================================

def _read_csv(path: str) -> Optional[pd.DataFrame]:
    if path and os.path.exists(path):
        try:
            return pd.read_csv(path, index_col=0)
        except Exception:
            pass
    return None


def _read_sheet(xlsx_path: str, sheet: str) -> Optional[pd.DataFrame]:
    if not xlsx_path or not os.path.exists(xlsx_path):
        return None
    try:
        xf = pd.ExcelFile(xlsx_path)
        if sheet in xf.sheet_names:
            return pd.read_excel(xf, sheet_name=sheet, index_col=0)
    except Exception:
        pass
    return None


def _read_sheet_no_index(xlsx_path: str, sheet: str) -> Optional[pd.DataFrame]:
    """Read without assuming index column (for total_cm xlsx)."""
    if not xlsx_path or not os.path.exists(xlsx_path):
        return None
    try:
        xf = pd.ExcelFile(xlsx_path)
        if sheet in xf.sheet_names:
            return pd.read_excel(xf, sheet_name=sheet)
    except Exception:
        pass
    return None


def _numeric(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    if df is None:
        return None
    return df.apply(pd.to_numeric, errors="coerce")


def _ts_to_asset_hour(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    """
    Standard timeseries CSV: rows=hours, cols=assets  →  rows=assets, cols=hours.
    Returns None if input is None.
    """
    if df is None:
        return None
    df = _numeric(df)
    out = df.T
    out.index   = [str(i) for i in out.index]
    out.columns = [str(c) for c in out.columns]
    return out


def _market_sheet_to_asset_hour(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    """
    Market result sheet: rows=FSP index, cols=hours  (already asset×hour).
    Just ensure numeric and string labels.
    """
    if df is None:
        return None
    df = _numeric(df)
    df.index   = [str(i) for i in df.index]
    df.columns = [str(c) for c in df.columns]
    return df


def _hour_cols(df: pd.DataFrame) -> List[str]:
    """Return only the hour columns (numeric strings like '0','7','18')."""
    return [c for c in df.columns if re.fullmatch(r"\d+", str(c).strip())]


def _activation_long(xlsx: str) -> pd.DataFrame:
    """
    Return long-form activation: hour, resource, resource_type, product,
    signed_value (grid-support convention), abs_value, unit.
    """
    mapping = [
        ("DW_A", "Load",      "P", "MW"),
        ("DR_A", "Load",      "Q", "MVAr"),
        ("DW_B", "Generator", "P", "MW"),
        ("DR_B", "Generator", "Q", "MVAr"),
        ("DW_C", "Storage",   "P", "MW"),
        ("DR_C", "Storage",   "Q", "MVAr"),
    ]
    if not xlsx or not os.path.exists(xlsx):
        return pd.DataFrame(
            columns=["hour","resource","resource_type","product","signed_value","abs_value","unit"])
    try:
        xf = pd.ExcelFile(xlsx)
    except Exception:
        return pd.DataFrame(
            columns=["hour","resource","resource_type","product","signed_value","abs_value","unit"])

    frames = []
    for sheet, rtype, prod, unit in mapping:
        if sheet not in xf.sheet_names:
            continue
        try:
            df = pd.read_excel(xf, sheet_name=sheet)
        except Exception:
            continue
        if df.empty:
            continue
        id_col    = df.columns[0]
        hour_cols = [c for c in df.columns[1:] if re.fullmatch(r"\d+", str(c).strip())]
        if not hour_cols:
            continue
        long = df.melt(id_vars=[id_col], value_vars=hour_cols,
                       var_name="hour", value_name="value")
        long["hour"]    = pd.to_numeric(long["hour"],    errors="coerce")
        long["fsp_idx"] = pd.to_numeric(long[id_col],   errors="coerce")
        long["value"]   = pd.to_numeric(long["value"],  errors="coerce").fillna(0.0)
        long = long.dropna(subset=["hour","fsp_idx"]).copy()
        long["hour"]    = long["hour"].astype(int)
        long["fsp_idx"] = long["fsp_idx"].astype(int)
        prefix = {"Load":"L","Generator":"G","Storage":"S"}.get(rtype, "F")
        long["resource"]      = prefix + (long["fsp_idx"] + 1).astype(str)
        long["resource_type"] = rtype
        long["product"]       = prod
        long["unit"]          = unit
        # Grid-support sign convention: positive = upward/injection support
        long["signed_value"] = -long["value"] if rtype in ("Load", "Storage") else long["value"]
        long["abs_value"]    = long["signed_value"].abs()
        frames.append(long[["hour","resource","resource_type","product",
                             "signed_value","abs_value","unit"]])

    if frames:
        return pd.concat(frames, ignore_index=True)
    return pd.DataFrame(
        columns=["hour","resource","resource_type","product","signed_value","abs_value","unit"])


def _cm_need_long(path: Optional[str], stage: str) -> pd.DataFrame:
    """
    Read total_cm_PreMKT.xlsx or total_cm_postMKT.xlsx.
    Returns long form: hour, asset, cm_need_mva, stage.
    """
    empty = pd.DataFrame(columns=["hour","asset","cm_need_mva","stage"])
    if not path or not os.path.exists(path):
        return empty
    df = _read_sheet_no_index(path, "Congestion needs")
    if df is None or df.empty:
        return empty
    first = df.columns[0]
    df = df.rename(columns={first: "hour"})
    vcols = [c for c in df.columns if c != "hour"]
    long = df.melt(id_vars=["hour"], value_vars=vcols,
                   var_name="asset", value_name="cm_need_mva")
    long["cm_need_mva"] = pd.to_numeric(long["cm_need_mva"], errors="coerce").fillna(0.0)
    long["hour_n"]      = pd.to_numeric(long["hour"], errors="coerce")
    long = long[long["hour_n"].notna()].copy()
    long["hour"]  = long["hour_n"].astype(int)
    long["stage"] = stage
    return long[["hour","asset","cm_need_mva","stage"]]


# =============================================================================
# 2.  OUTPUT
# =============================================================================

_HTML_WRAP = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{title}</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:{bg};font-family:Inter,'Segoe UI',Arial,sans-serif;color:{text}}}
  .hdr{{padding:20px 28px 12px;border-bottom:1px solid {border};display:flex;
         align-items:baseline;gap:14px}}
  .hdr h1{{font-size:17px;font-weight:600;letter-spacing:-0.2px}}
  .hdr .sub{{font-size:12px;color:{muted}}}
  .badge{{font-size:11px;padding:2px 8px;border-radius:20px;background:{bg3};
           border:1px solid {border};color:{blue};margin-left:auto;white-space:nowrap}}
  .wrap{{padding:14px 22px 20px}}
  .foot{{padding:10px 28px;border-top:1px solid {border};font-size:11px;
          color:{muted};display:flex;justify-content:space-between}}
</style>
</head>
<body>
<div class="hdr">
  <h1>{title}</h1>
  <span class="sub">{subtitle}</span>
  <span class="badge">{tag}</span>
</div>
<div class="wrap">{plotly_div}</div>
<div class="foot">
  <span>enginIITe Local Flexibility Market Platform</span>
  <span>Showcase · showcase_dashboard.py</span>
</div>
</body></html>"""


def _save(fig: go.Figure, path: str, title: str, subtitle: str, tag: str) -> str:
    # Keep every continuous-scale title
    # vertically beside its colorbar so it cannot collide with panel headings.
    for trace in fig.data:
        for owner in (trace, getattr(trace, "marker", None), getattr(trace, "line", None)):
            colorbar = getattr(owner, "colorbar", None) if owner is not None else None
            if colorbar is None:
                continue
            try:
                title_text = str(colorbar.title.text or "")
                colorbar.update(
                    title=dict(text=title_text, side="right", font=dict(size=11)),
                    xpad=8,
                    ypad=6,
                )
            except Exception:
                pass
    for layout_name in list(fig.layout):
        if not str(layout_name).startswith("coloraxis"):
            continue
        coloraxis = fig.layout[layout_name]
        colorbar = getattr(coloraxis, "colorbar", None) if coloraxis is not None else None
        if colorbar is None:
            continue
        try:
            title_text = str(colorbar.title.text or "")
            colorbar.update(
                title=dict(text=title_text, side="right", font=dict(size=11)),
                xpad=8,
                ypad=6,
            )
        except Exception:
            pass
    div = fig.to_html(
        full_html=False, include_plotlyjs="cdn",
        config=dict(displaylogo=False, responsive=True,
                    toImageButtonOptions=dict(format="png", width=1800, height=900)),
    )
    html = _HTML_WRAP.format(
        title=title, subtitle=subtitle, tag=tag,
        plotly_div=div, **{k: v for k, v in C.items()},
    )
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"    Saved: {path}")
    return path


# =============================================================================
# 3.  FIG 1 — CAPACITY UTILISATION HEATMAP
# =============================================================================

def fig_capacity_utilisation(
    market_result_file: str,
    output_folder: str,
    market_tag: str,
) -> Optional[str]:
    """
    For each FSP and each studied hour:
        utilisation_ratio = |dispatched| / offered_limit

    DW_U_Lim_A/B  = upward P-limit offered by loads / generators [MW]
    DW_A / DW_B   = actual dispatched P-change [MW]

    A ratio of 1.0 means the provider was dispatched to its full bid.
    A ratio of 0.0 means it was registered but not called.
    This reveals which providers the market consistently relies on
    and which are never fully used (potential over-sizing or cost issues).
    """
    if not market_result_file or not os.path.exists(market_result_file):
        print("  [CapUtil] market_result_file not found — skipped.")
        return None

    xf = pd.ExcelFile(market_result_file)
    sheets = xf.sheet_names

    frames = []
    for lim_sheet, act_sheet, rtype, color in [
        ("DW_U_Lim_A", "DW_A", "Load",      C["load_col"]),
        ("DW_U_Lim_B", "DW_B", "Generator", C["gen_col"]),
        ("DW_U_Lim_C", "DW_C", "Storage",   C["sto_col"]),
    ]:
        if lim_sheet not in sheets or act_sheet not in sheets:
            continue
        lim = _market_sheet_to_asset_hour(
            pd.read_excel(xf, sheet_name=lim_sheet, index_col=0))
        act = _market_sheet_to_asset_hour(
            pd.read_excel(xf, sheet_name=act_sheet, index_col=0))
        if lim is None or act is None:
            continue

        # Align hours
        common_h = [h for h in _hour_cols(lim) if h in _hour_cols(act)]
        if not common_h:
            continue
        lim_v = lim[common_h].fillna(0).abs()
        act_v = act[common_h].fillna(0).abs()

        # utilisation = dispatched / limit, clamped [0,1]
        util = act_v.divide(lim_v.replace(0, np.nan)).clip(0, 1).fillna(0)
        prefix = {"Load": "L", "Generator": "G", "Storage": "S"}[rtype]
        util.index = [f"{prefix}{int(i)+1}" for i in range(len(util))]
        util["_rtype"] = rtype
        frames.append(util)

    if not frames:
        print("  [CapUtil] DW_U_Lim and DW sheets not present — skipped.")
        return None

    combined = pd.concat([f for f in frames], axis=0)
    rtypes   = combined.pop("_rtype")
    hour_cols_sorted = sorted(
        [c for c in combined.columns if re.fullmatch(r"\d+", str(c))],
        key=lambda x: int(x))

    z   = combined[hour_cols_sorted].values.astype(float)
    y   = combined.index.tolist()
    x   = [f"h{h}" for h in hour_cols_sorted]

    # Colour each row annotation by resource type
    rtype_colors = {"Load": C["load_col"], "Generator": C["gen_col"], "Storage": C["sto_col"]}
    row_colors   = [rtype_colors.get(rtypes[fsp], C["muted"]) for fsp in y]

    fig = go.Figure(go.Heatmap(
        z=z, x=x, y=y,
        zmin=0, zmax=1,
        colorscale=[
            [0.0,   C["bg2"]],
            [0.001, "#1e3a5f"],
            [0.35,  C["blue"]   + "99"],
            [0.70,  C["amber"]],
            [1.0,   C["green"]],
        ],
        colorbar=dict(
            title=dict(text="Utilisation ratio [0–1]", font=dict(color=C["muted"], size=11)),
            tickvals=[0, 0.25, 0.5, 0.75, 1],
            ticktext=["0% (unused)", "25%", "50%", "75%", "100% (fully dispatched)"],
            tickfont=dict(color=C["muted"], size=10),
            thickness=14, len=0.85,
        ),
        hovertemplate=(
            "FSP: <b>%{y}</b><br>"
            "Hour: <b>%{x}</b><br>"
            "Utilisation: <b>%{z:.1%}</b><br>"
            "<extra></extra>"
        ),
    ))

    # Horizontal separator lines between resource types
    sep_rows = {}
    prev = None
    for i, fsp in enumerate(y):
        rt = rtypes[fsp]
        if prev is not None and rt != prev:
            sep_rows[i] = rt
        prev = rt
    for sep_i in sep_rows:
        fig.add_shape(type="line",
                      x0=-0.5, x1=len(x) - 0.5,
                      y0=sep_i - 0.5, y1=sep_i - 0.5,
                      line=dict(color=C["border"], width=2, dash="dot"))

    # Annotations for resource-type group labels
    seen = set()
    for fsp, rt in rtypes.items():
        if rt not in seen:
            seen.add(rt)
            fig.add_annotation(
                x=len(x) - 0.5, y=fsp,
                text=f"  {rt}", showarrow=False,
                xanchor="left", font=dict(size=10, color=rtype_colors[rt]),
            )

    _theme(fig, height=max(380, 36 * len(y) + 120))
    fig.update_layout(
        xaxis=dict(**_AX, title="Studied hour", type="category"),
        yaxis=dict(**_AX, title="Flexibility service provider",
                   autorange="reversed"),
    )

    out = os.path.join(output_folder, "01_capacity_utilisation.html")
    return _save(fig, out,
                 "Capacity Utilisation — How much of each FSP's bid was dispatched?",
                 "Ratio of dispatched power to offered bid limit · 1.0 = fully used · 0.0 = not called",
                 market_tag)


# =============================================================================
# 4.  FIG 2 — P–Q OPERATING ENVELOPE
# =============================================================================

def fig_pq_operating_envelope(
    market_result_file: str,
    output_folder: str,
    market_tag: str,
) -> Optional[str]:
    """
    Shows each FSP as an arrow in the P-Q plane:
      Tail  = initial operating point  (Winit, Rinit)
      Head  = post-activation point    (Winit + DW, Rinit + DR)
    Capacity ellipse from WUB_ULim and RUB_ULim is overlaid.

    This reveals:
      · Direction of activation (upward vs downward, P vs Q)
      · Distance from physical limit (is the market straining resources?)
      · Whether P and Q are activated jointly or independently
    """
    if not market_result_file or not os.path.exists(market_result_file):
        print("  [PQEnvelope] market_result_file not found — skipped.")
        return None

    xf = pd.ExcelFile(market_result_file)
    sheets = xf.sheet_names

    # Read all needed sheets for Load (A) and Generator (B)
    type_map = {"A": ("Load", C["load_col"]), "B": ("Generator", C["gen_col"])}

    fig = go.Figure()
    any_trace = False

    for fsp_type, (rtype, col) in type_map.items():
        winit_df = _market_sheet_to_asset_hour(
            pd.read_excel(xf, sheet_name=f"Winit_{fsp_type}", index_col=0)
            if f"Winit_{fsp_type}" in sheets else None)
        rinit_df = _market_sheet_to_asset_hour(
            pd.read_excel(xf, sheet_name=f"Rinit_{fsp_type}", index_col=0)
            if f"Rinit_{fsp_type}" in sheets else None)
        dw_df = _market_sheet_to_asset_hour(
            pd.read_excel(xf, sheet_name=f"DW_{fsp_type}", index_col=0)
            if f"DW_{fsp_type}" in sheets else None)
        dr_df = _market_sheet_to_asset_hour(
            pd.read_excel(xf, sheet_name=f"DR_{fsp_type}", index_col=0)
            if f"DR_{fsp_type}" in sheets else None)
        wub_df = _market_sheet_to_asset_hour(
            pd.read_excel(xf, sheet_name=f"WUB_ULim_{fsp_type}", index_col=0)
            if f"WUB_ULim_{fsp_type}" in sheets else None)
        rub_df = _market_sheet_to_asset_hour(
            pd.read_excel(xf, sheet_name=f"RUB_ULim_{fsp_type}", index_col=0)
            if f"RUB_ULim_{fsp_type}" in sheets else None)

        if winit_df is None or dw_df is None:
            continue

        prefix = {"Load": "L", "Generator": "G"}[rtype]

        # Use the first studied hour for initial operating point,
        # and aggregate across all hours for total activation arrow
        hours = [h for h in _hour_cols(dw_df) if winit_df is not None and h in _hour_cols(winit_df)]
        if not hours:
            hours = _hour_cols(dw_df)

        n_fsp = len(dw_df)
        for i in range(n_fsp):
            fsp_name = f"{prefix}{i+1}"

            # Initial operating point: use first available hour
            h0 = hours[0] if hours else None
            w0 = float(winit_df.iloc[i][h0]) if h0 and h0 in winit_df.columns else 0.0
            r0 = float(rinit_df.iloc[i][h0]) if (rinit_df is not None and h0 and h0 in rinit_df.columns) else 0.0

            # Total activation across all hours (sum, not per-hour)
            dw_total = sum(float(dw_df.iloc[i][h]) for h in hours if h in dw_df.columns)
            dr_total = sum(float(dr_df.iloc[i][h]) if (dr_df is not None and h in dr_df.columns) else 0.0
                           for h in hours)

            # Apply sign correction (Load/Storage: DW>0 means more absorption → downward grid)
            if rtype == "Load":
                dw_gs = -dw_total
                dr_gs = -dr_total
            else:
                dw_gs = dw_total
                dr_gs = dr_total

            w_end = w0 + dw_gs
            r_end = r0 + dr_gs

            # Capacity limit (mean across hours as representative)
            wub = float(wub_df.iloc[i].mean()) if wub_df is not None else abs(w0) * 1.5
            rub = float(rub_df.iloc[i].mean()) if rub_df is not None else abs(r0) * 1.5

            # Arrow: initial → activated endpoint
            if abs(dw_gs) > 1e-4 or abs(dr_gs) > 1e-4:
                fig.add_trace(go.Scatter(
                    x=[w0, w_end], y=[r0, r_end],
                    mode="lines+markers",
                    marker=dict(
                        size=[8, 14], color=col,
                        symbol=["circle", "arrow"],
                        angleref="previous",
                        line=dict(color=C["bg"], width=1),
                    ),
                    line=dict(color=col, width=2),
                    name=f"{fsp_name} ({rtype})",
                    legendgroup=rtype,
                    showlegend=(i == 0),
                    hovertemplate=(
                        f"<b>{fsp_name}</b> ({rtype})<br>"
                        "Initial P: %{customdata[0]:.3f} MW<br>"
                        "Initial Q: %{customdata[1]:.3f} MVAr<br>"
                        "Post-activation P: %{customdata[2]:.3f} MW<br>"
                        "Post-activation Q: %{customdata[3]:.3f} MVAr<br>"
                        "ΔP (total): %{customdata[4]:.3f} MW<br>"
                        "ΔQ (total): %{customdata[5]:.3f} MVAr"
                        "<extra></extra>"
                    ),
                    customdata=[[w0, r0, w_end, r_end, dw_gs, dr_gs],
                                [w0, r0, w_end, r_end, dw_gs, dr_gs]],
                ))
                any_trace = True

    if not any_trace:
        print("  [PQEnvelope] No Winit/DW data found — skipped.")
        return None

    # Zero-axis reference lines
    fig.add_hline(y=0, line=dict(color=C["border"], width=1, dash="dash"))
    fig.add_vline(x=0, line=dict(color=C["border"], width=1, dash="dash"))

    # Quadrant labels
    for x_pos, y_pos, label in [
        ( 0.97,  0.97, "↗ Inject P + absorb Q"),
        (-0.97,  0.97, "↖ Reduce P + absorb Q"),
        (-0.97, -0.97, "↙ Reduce P + inject Q"),
        ( 0.97, -0.97, "↘ Inject P + inject Q"),
    ]:
        fig.add_annotation(
            x=x_pos, y=y_pos, xref="paper", yref="paper",
            text=label, showarrow=False,
            font=dict(size=9, color=C["muted"]),
            align="center",
        )

    _theme(fig, height=620)
    fig.update_layout(
        xaxis=dict(**_AX, title="Active power P [MW]  (grid-support convention: + = injection)"),
        yaxis=dict(**_AX, title="Reactive power Q [MVAr]  (grid-support convention: + = injection)"),
        showlegend=True,
    )

    out = os.path.join(output_folder, "02_pq_operating_envelope.html")
    return _save(fig, out,
                 "P–Q Operating Envelope — Activation trajectories in the complex power plane",
                 "Tail = initial operating point · Head = post-activation · Arrow length = total dispatch across all studied hours",
                 market_tag)


# =============================================================================
# 5.  FIG 3 — STORAGE SOC TRAJECTORY
# =============================================================================

def fig_storage_soc_trajectory(
    market_result_file: str,
    output_folder: str,
    market_tag: str,
) -> Optional[str]:
    """
    SOC_C: state-of-charge [0–1] for each storage unit per studied hour.
    DW_C:  active power dispatch of storage per studied hour [MW].

    Two-panel figure:
      Top: SOC trajectories (lines, one per storage unit)
      Bottom: P dispatch (bars, signed — positive = injection, negative = charging)

    This is the only figure that exposes the intertemporal constraints:
    you can see that the market trades off early-hour charging for
    late-hour injection (or vice versa), and whether SOC limits are binding.
    """
    if not market_result_file or not os.path.exists(market_result_file):
        print("  [SOC] market_result_file not found — skipped.")
        return None

    xf = pd.ExcelFile(market_result_file)
    sheets = xf.sheet_names

    soc_raw = pd.read_excel(xf, sheet_name="SOC_C", index_col=0) if "SOC_C" in sheets else None
    dw_raw  = pd.read_excel(xf, sheet_name="DW_C",  index_col=0) if "DW_C"  in sheets else None

    soc = _market_sheet_to_asset_hour(soc_raw)
    dw  = _market_sheet_to_asset_hour(dw_raw)

    if soc is None:
        print("  [SOC] SOC_C sheet not found — skipped.")
        return None

    hours_soc = sorted(_hour_cols(soc), key=lambda x: int(x))
    hours_dw  = sorted(_hour_cols(dw),  key=lambda x: int(x)) if dw is not None else []

    n_sto = len(soc)
    if n_sto == 0:
        return None

    sto_colors = [C["sto_col"], C["sky"], C["teal"], C["rose"], C["amber"]]

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        row_heights=[0.55, 0.45],
        vertical_spacing=0.07,
        subplot_titles=[
            "State of charge [pu]  —  one curve per storage unit",
            "Active power dispatch [MW]  (positive = injection / grid support, negative = charging)",
        ],
    )

    # --- Row 1: SOC trajectories ---
    for i in range(n_sto):
        col = sto_colors[i % len(sto_colors)]
        sto_name = f"ESS{i+1}"  # Not to be read as scenario S1, S2, ...
        soc_vals = [float(soc.iloc[i][h]) for h in hours_soc
                    if h in soc.columns]
        fig.add_trace(go.Scatter(
            x=[f"h{h}" for h in hours_soc],
            y=soc_vals,
            mode="lines+markers",
            name=sto_name,
            line=dict(color=col, width=2.5),
            marker=dict(size=8, color=col, line=dict(color=C["bg"], width=1.5)),
            hovertemplate=f"<b>{sto_name}</b><br>Hour: %{{x}}<br>SoC: <b>%{{y:.3f}} pu</b><extra></extra>",
        ), row=1, col=1)

    # SoC limit bands (typical 20–80%)
    fig.add_hrect(y0=0.0,  y1=0.20, row=1, col=1,
                  fillcolor="rgba(248,113,113,0.13)", line_width=0,
                  annotation_text="SoC min zone (0–20%)",
                  annotation_position="top left",
                  annotation_font=dict(size=9, color=C["red"]))
    fig.add_hrect(y0=0.80, y1=1.0, row=1, col=1,
                  fillcolor="rgba(16,185,129,0.13)", line_width=0,
                  annotation_text="SoC max zone (80–100%)",
                  annotation_position="bottom left",
                  annotation_font=dict(size=9, color=C["green"]))

    # --- Row 2: P dispatch bars ---
    if dw is not None and hours_dw:
        for i in range(n_sto):
            col = sto_colors[i % len(sto_colors)]
            sto_name = f"ESS{i+1}"  # Not to be read as scenario S1, S2, ...
            # Grid-support sign: DW_C>0 in Excel means more charging → negative grid view
            dw_vals = [-float(dw.iloc[i][h]) for h in hours_dw if h in dw.columns]
            fig.add_trace(go.Bar(
                x=[f"h{h}" for h in hours_dw],
                y=dw_vals,
                name=sto_name,
                showlegend=False,
                marker_color=col,
                marker_line=dict(color=C["bg"], width=0.5),
                hovertemplate=(
                    f"<b>{sto_name}</b><br>Hour: %{{x}}<br>"
                    "P dispatch: <b>%{y:.3f} MW</b><br>"
                    "(+ = injection, − = charging)<extra></extra>"
                ),
            ), row=2, col=1)

        fig.add_hline(y=0, line=dict(color=C["border"], width=1.5), row=2, col=1)

    _theme(fig, height=680)
    fig.update_layout(
        barmode="group",
        yaxis=dict(**_AX, title="State of charge [pu]", range=[-0.05, 1.05]),
        yaxis2=dict(**_AX, title="P dispatch [MW]"),
        showlegend=True,
        legend=dict(
            **{k: v for k, v in _BASE_LAYOUT["legend"].items()},
            title=dict(text="Storage unit", font=dict(color=C["muted"])),
            x=1.01, y=1.0,
        ),
    )
    for ann in fig.layout.annotations:
        ann.font.color = C["muted"]
        ann.font.size  = 11

    out = os.path.join(output_folder, "03_storage_soc_trajectory.html")
    return _save(fig, out,
                 "Storage SOC Trajectory — Intertemporal energy buffering",
                 "Top: state-of-charge [pu] · Bottom: signed P dispatch [MW] · shaded = SoC constraint zones",
                 market_tag)


# =============================================================================
# 6.  FIG 4 — MERIT-ORDER DISPATCH (Cost vs Activation)
# =============================================================================

def fig_merit_order_dispatch(
    market_result_file: str,
    output_folder: str,
    market_tag: str,
) -> Optional[str]:
    """
    Scatter plot of bid price vs dispatched volume for each FSP.

    The market objective is to maximise welfare surplus (highest-value
    providers dispatched first for the aggregator).  Cheaper providers
    should receive higher dispatch volumes.  This figure reveals:

      · Whether the market respects merit order
      · Which providers are expensive but still dispatched (binding constraints)
      · Market clearing price proxy (marginal provider)

    Source sheets: W_U_Cost_A/B/C (bid prices), DW_A/B/C (dispatched P).
    Separate panels for P [MW] and Q [MVAr].
    """
    if not market_result_file or not os.path.exists(market_result_file):
        print("  [MeritOrder] market_result_file not found — skipped.")
        return None

    xf = pd.ExcelFile(market_result_file)
    sheets = xf.sheet_names

    fig = make_subplots(
        rows=1, cols=2,
        subplot_titles=[
            "Active-power merit order  [MW dispatched vs bid €/MWh]",
            "Reactive-power merit order  [MVAr dispatched vs bid €/MVArh]",
        ],
        horizontal_spacing=0.10,
    )

    type_map = [
        ("A", "Load",      C["load_col"]),
        ("B", "Generator", C["gen_col"]),
        ("C", "Storage",   C["sto_col"]),
    ]

    any_trace = False
    for fsp_type, rtype, col in type_map:
        prefix = {"Load": "L", "Generator": "G", "Storage": "S"}[rtype]

        # P: bid W_U_Cost, dispatch DW
        cost_p_sheet = f"W_U_Cost_{fsp_type}"
        act_p_sheet  = f"DW_{fsp_type}"
        # Q: bid R_U_Cost, dispatch DR
        cost_q_sheet = f"R_U_Cost_{fsp_type}"
        act_q_sheet  = f"DR_{fsp_type}"

        for col_idx, (cost_sh, act_sh, product, unit) in enumerate([
            (cost_p_sheet, act_p_sheet, "P", "MW"),
            (cost_q_sheet, act_q_sheet, "Q", "MVAr"),
        ], start=1):
            if cost_sh not in sheets or act_sh not in sheets:
                continue

            cost_df = _numeric(pd.read_excel(xf, sheet_name=cost_sh, index_col=0))
            act_df  = _market_sheet_to_asset_hour(
                _numeric(pd.read_excel(xf, sheet_name=act_sh, index_col=0)))

            if cost_df is None or act_df is None:
                continue

            n_fsp = len(act_df)
            hours = _hour_cols(act_df)
            if not hours:
                continue

            # Cost: W_U_Cost is saved as a single row per FSP or scalar per hour
            # Take mean across hours as representative bid price
            cost_vals = cost_df.values.flatten()
            if len(cost_vals) == 1:
                cost_per_fsp = [float(cost_vals[0])] * n_fsp
            elif len(cost_vals) == n_fsp:
                cost_per_fsp = [float(v) for v in cost_vals]
            else:
                # Try to pick the diagonal (one cost per FSP per hour → mean)
                try:
                    cost_per_fsp = [float(cost_df.values[i].mean()) for i in range(n_fsp)]
                except Exception:
                    cost_per_fsp = [0.0] * n_fsp

            # Total dispatched volume per FSP (absolute value sum across hours)
            vol_per_fsp = [
                float(act_df.iloc[i][hours].abs().sum()) for i in range(n_fsp)
            ]

            fsp_names = [f"{prefix}{i+1}" for i in range(n_fsp)]

            # Sort by cost ascending for step overlay
            order = sorted(range(n_fsp), key=lambda i: cost_per_fsp[i])
            sorted_cost = [cost_per_fsp[i] for i in order]
            sorted_vol  = [vol_per_fsp[i]  for i in order]
            sorted_name = [fsp_names[i]     for i in order]

            # Bubble scatter
            max_vol = max(max(vol_per_fsp), 1e-3)
            bubble_sz = [max(6, min(40, v / max_vol * 40)) for v in sorted_vol]

            fig.add_trace(go.Scatter(
                x=sorted_cost, y=sorted_vol,
                mode="markers+text",
                text=sorted_name,
                textposition="top center",
                textfont=dict(size=9, color=C["muted"]),
                marker=dict(
                    size=bubble_sz,
                    color=col, opacity=0.80,
                    sizemode="diameter",
                    line=dict(color=C["bg"], width=1.5),
                ),
                name=f"{rtype} ({product})",
                legendgroup=rtype,
                showlegend=(col_idx == 1),
                hovertemplate=(
                    f"<b>%{{text}}</b> ({rtype})<br>"
                    "Bid price: <b>%{x:.2f} €/" + unit + "h</b><br>"
                    "Total dispatched: <b>%{y:.3f} " + unit + "</b>"
                    "<extra></extra>"
                ),
            ), row=1, col=col_idx)

            # Marginal cost line (highest dispatched provider)
            dispatched = [(c, v, n) for c, v, n in zip(sorted_cost, sorted_vol, sorted_name)
                          if v > 1e-4]
            if dispatched:
                marginal_cost = max(c for c, v, n in dispatched)
                fig.add_vline(
                    x=marginal_cost, row=1, col=col_idx,
                    line=dict(color=C["amber"], width=1.5, dash="dash"),
                    annotation_text=f"Marginal bid ≈ {marginal_cost:.1f}",
                    annotation_font=dict(size=9, color=C["amber"]),
                    annotation_position="top right",
                )
            any_trace = True

    if not any_trace:
        print("  [MeritOrder] Cost and dispatch sheets not found — skipped.")
        return None

    _theme(fig, height=540)
    fig.update_layout(
        xaxis=dict(**_AX,  title="Bid price [€/MWh]"),
        xaxis2=dict(**_AX, title="Bid price [€/MVArh]"),
        yaxis=dict(**_AX,  title="Total dispatched [MW]"),
        yaxis2=dict(**_AX, title="Total dispatched [MVAr]"),
        showlegend=True,
    )
    for ann in fig.layout.annotations:
        ann.font.color = C["muted"]
        ann.font.size  = 11

    out = os.path.join(output_folder, "04_merit_order_dispatch.html")
    return _save(fig, out,
                 "Merit-Order Dispatch — Cost vs activation volume per FSP",
                 "Each bubble = one FSP · bubble size ∝ dispatched volume · dashed line = marginal bid price",
                 market_tag)


# =============================================================================
# 7.  FIG 5 — PER-ASSET CONGESTION DECOMPOSITION
# =============================================================================

def fig_congestion_by_asset(
    scenario_root: str,
    output_folder: str,
    market_tag: str,
) -> Optional[str]:
    """
    total_cm_PreMKT.xlsx and total_cm_postMKT.xlsx, broken down to individual
    assets (lines/trafos), per studied hour.

    A diverging grouped bar chart:
      · Each asset is a cluster on the x-axis
      · Pre-market bar (red, positive) = congestion need before market
      · Post-market bar (green, negative) = residual congestion after market
      · If post = 0, the market fully resolved that congestion event
      · If post > 0, residual risk remains

    This is the only view that names the specific assets that are congested,
    tells the operator exactly which line/trafo remains problematic.
    """
    pre_path  = os.path.join(scenario_root, "total_cm_PreMKT.xlsx")
    post_path = os.path.join(scenario_root, "total_cm_postMKT.xlsx")

    pre_df  = _cm_need_long(pre_path,  "Pre-market")
    post_df = _cm_need_long(post_path, "Post-market")

    if pre_df.empty:
        print("  [CongestionAsset] No pre-market CM need data — skipped.")
        return None

    # Aggregate by asset (sum across hours for overall view)
    pre_by_asset  = pre_df.groupby("asset")["cm_need_mva"].sum().reset_index()
    post_by_asset = post_df.groupby("asset")["cm_need_mva"].sum().reset_index() \
                    if not post_df.empty else pd.DataFrame(columns=["asset","cm_need_mva"])

    merged = pre_by_asset.rename(columns={"cm_need_mva": "pre_mva"}).merge(
        post_by_asset.rename(columns={"cm_need_mva": "post_mva"}),
        on="asset", how="left"
    ).fillna(0.0)

    merged = merged[merged["pre_mva"] > 1e-6].sort_values("pre_mva", ascending=False)
    if merged.empty:
        print("  [CongestionAsset] All assets have zero CM need — skipped.")
        return None

    merged["relief_mva"]  = merged["pre_mva"] - merged["post_mva"]
    merged["relief_pct"]  = (merged["relief_mva"] / merged["pre_mva"] * 100).clip(0, 100)
    merged["residual_pct"] = (100 - merged["relief_pct"]).clip(0, 100)

    # Per-hour breakdown for hovered detail
    pre_hourly  = pre_df.pivot_table(index="asset", columns="hour",
                                     values="cm_need_mva", aggfunc="sum", fill_value=0)
    post_hourly = post_df.pivot_table(index="asset", columns="hour",
                                      values="cm_need_mva", aggfunc="sum", fill_value=0) \
                  if not post_df.empty else pd.DataFrame()

    assets    = merged["asset"].tolist()
    pre_vals  = merged["pre_mva"].tolist()
    post_vals = merged["post_mva"].tolist()

    # Hover: list hours where this asset was congested
    def _hour_summary(asset: str, pivot: pd.DataFrame) -> str:
        if pivot.empty or asset not in pivot.index:
            return "—"
        row = pivot.loc[asset]
        active = row[row > 1e-6]
        if active.empty:
            return "—"
        return ", ".join([f"h{h}: {v:.3f} MVA" for h, v in active.items()])

    pre_hover  = [_hour_summary(a, pre_hourly)  for a in assets]
    post_hover = [_hour_summary(a, post_hourly) for a in assets]

    fig = make_subplots(
        rows=2, cols=1,
        row_heights=[0.62, 0.38],
        vertical_spacing=0.10,
        subplot_titles=[
            "Pre-market (red) vs post-market (green) congestion need per asset  [MVA above detection threshold]",
            "Relief efficiency per asset  [%]",
        ],
    )

    # Row 1: diverging bars
    fig.add_trace(go.Bar(
        x=assets, y=pre_vals,
        name="Pre-market CM need [MVA]",
        marker_color=C["pre_col"],
        marker_line=dict(color=C["bg"], width=0.5),
        customdata=[[pv, ph] for pv, ph in zip(pre_vals, pre_hover)],
        hovertemplate=(
            "Asset: <b>%{x}</b><br>"
            "Pre-market total: <b>%{customdata[0]:.4f} MVA</b><br>"
            "Per hour: %{customdata[1]}"
            "<extra></extra>"
        ),
    ), row=1, col=1)

    fig.add_trace(go.Bar(
        x=assets, y=[-v for v in post_vals],
        name="Post-market CM need [MVA]",
        marker_color=C["post_col"],
        marker_line=dict(color=C["bg"], width=0.5),
        customdata=[[pv, ph] for pv, ph in zip(post_vals, post_hover)],
        hovertemplate=(
            "Asset: <b>%{x}</b><br>"
            "Post-market total: <b>%{customdata[0]:.4f} MVA</b><br>"
            "Per hour: %{customdata[1]}"
            "<extra></extra>"
        ),
    ), row=1, col=1)

    fig.add_hline(y=0, row=1, col=1,
                  line=dict(color=C["text"], width=1.2))

    # Row 2: relief % bar
    bar_colors = [C["green"] if r >= 99.9 else (C["amber"] if r >= 50 else C["red"])
                  for r in merged["relief_pct"]]

    fig.add_trace(go.Bar(
        x=assets,
        y=merged["relief_pct"].tolist(),
        name="Relief efficiency [%]",
        marker_color=bar_colors,
        marker_line=dict(color=C["bg"], width=0.5),
        hovertemplate=(
            "Asset: <b>%{x}</b><br>"
            "Relief: <b>%{y:.1f}%</b>"
            "<extra></extra>"
        ),
    ), row=2, col=1)

    fig.add_hline(y=100, row=2, col=1,
                  line=dict(color=C["green"], width=1, dash="dot"),
                  annotation_text="100% = fully resolved",
                  annotation_font=dict(size=9, color=C["green"]),
                  annotation_position="bottom right")

    _theme(fig, height=700)
    fig.update_layout(
        barmode="overlay",
        xaxis=dict(**_AX, type="category", tickangle=-30),
        yaxis=dict(**_AX, title="CM need [MVA]  (pre +, post −)"),
        xaxis2=dict(**_AX, type="category", tickangle=-30),
        yaxis2=dict(**_AX, title="Relief [%]", range=[0, 105]),
        showlegend=True,
    )
    for ann in fig.layout.annotations:
        ann.font.color = C["muted"]
        ann.font.size  = 11

    out = os.path.join(output_folder, "05_congestion_by_asset.html")
    return _save(fig, out,
                 "Per-Asset Congestion Decomposition — Which lines/trafos remain at risk?",
                 "Top: pre-market (↑) and post-market (↓) CM need per individual asset · Bottom: % of congestion resolved",
                 market_tag)


# =============================================================================
# 8.  FIG 6 — VOLTAGE BUS PROFILER
# =============================================================================

def fig_voltage_bus_profiler(
    pre_ts_root: Optional[str],
    post_ts_root: Optional[str],
    vmin: float,
    vmax: float,
    output_folder: str,
    market_tag: str,
    n_worst: int = 8,
) -> Optional[str]:
    """
    Continuous vm_pu trajectories for the N worst buses (ranked by cumulative
    violation area), overlaid pre-market (dashed red) and post-market (solid
    green), with the admissible band [vmin, vmax] shaded.

    Unlike a heatmap, this preserves the actual voltage values in pu,
    shows how close each bus is to its limit, and makes it immediately
    clear which buses the market corrected and which it could not.

    A violation severity score is annotated per bus:
        severity = sum over hours of max(|v - nearest_limit|, 0)
    """
    pre_csv  = os.path.join(pre_ts_root,  "res_bus", "vm_pu.csv") if pre_ts_root  else None
    post_csv = os.path.join(post_ts_root, "res_bus", "vm_pu.csv") if post_ts_root else None

    pre_raw  = _read_csv(pre_csv)
    post_raw = _read_csv(post_csv)

    if pre_raw is None:
        print("  [VoltageBusProfiler] Pre-market vm_pu.csv not found — skipped.")
        return None

    # Standardise: rows=hours, cols=buses
    pre_df  = _numeric(pre_raw)
    post_df = _numeric(post_raw) if post_raw is not None else None

    # Rank buses by cumulative deviation outside limits
    def _violation_score(df: pd.DataFrame) -> pd.Series:
        over  = (df - vmax).clip(lower=0)
        under = (vmin - df).clip(lower=0)
        return (over + under).sum(axis=0)  # sum across hours, per bus

    scores = _violation_score(pre_df)
    worst_buses = scores.nlargest(min(n_worst, len(scores))).index.tolist()

    if not worst_buses:
        print("  [VoltageBusProfiler] No buses with violations — skipped.")
        return None

    n_buses = len(worst_buses)
    # Layout: up to 4 per row
    cols = min(4, n_buses)
    rows = math.ceil(n_buses / cols)


    fig = make_subplots(
        rows=rows, cols=cols,
        shared_yaxes=False,
        vertical_spacing=0.10,
        horizontal_spacing=0.06,
        subplot_titles=[f"Bus {b}" for b in worst_buses],
    )

    hours_pre  = [str(h) for h in pre_df.index]
    x_pre      = [f"h{h}" for h in hours_pre]
    hours_post = [str(h) for h in post_df.index] if post_df is not None else []
    x_post     = [f"h{h}" for h in hours_post]

    for idx, bus in enumerate(worst_buses):
        r = idx // cols + 1
        c = idx %  cols + 1

        # Admissible band
        fig.add_hrect(
            y0=vmin, y1=vmax, row=r, col=c,
            fillcolor="rgba(16,185,129,0.09)",
            line_width=0,
        )
        fig.add_hline(y=vmax, row=r, col=c,
                      line=dict(color="rgba(52,211,153,0.40)", width=1, dash="dot"))
        fig.add_hline(y=vmin, row=r, col=c,
                      line=dict(color="rgba(248,113,113,0.40)", width=1, dash="dot"))

        # Pre-market (dashed red)
        if bus in pre_df.columns:
            y_pre = pre_df[bus].tolist()
            fig.add_trace(go.Scatter(
                x=x_pre, y=y_pre,
                mode="lines+markers",
                name="Pre-market" if idx == 0 else "Pre-market",
                showlegend=(idx == 0),
                legendgroup="pre",
                line=dict(color=C["pre_col"], width=1.8, dash="dash"),
                marker=dict(size=5, color=C["pre_col"]),
                hovertemplate=f"<b>Bus {bus}</b><br>Hour: %{{x}}<br>Vm (pre): <b>%{{y:.4f}} pu</b><extra></extra>",
            ), row=r, col=c)

        # Post-market (solid green)
        if post_df is not None and bus in post_df.columns:
            y_post = post_df[bus].tolist()
            fig.add_trace(go.Scatter(
                x=x_post, y=y_post,
                mode="lines+markers",
                name="Post-market" if idx == 0 else "Post-market",
                showlegend=(idx == 0),
                legendgroup="post",
                line=dict(color=C["post_col"], width=2.2),
                marker=dict(size=5, color=C["post_col"]),
                hovertemplate=f"<b>Bus {bus}</b><br>Hour: %{{x}}<br>Vm (post): <b>%{{y:.4f}} pu</b><extra></extra>",
            ), row=r, col=c)

        # Severity annotation
        sev = float(scores.get(bus, 0.0))
        fig.add_annotation(
            row=r, col=c,
            x=0.98, y=0.98,
            xref="x domain", yref="y domain",
            text=f"Σ={sev:.4f} pu·h",
            showarrow=False,
            font=dict(size=9, color=C["amber"]),
            # Bundled Plotly versions
            # require rgba() rather than an 8-digit hexadecimal alpha color.
            bgcolor="rgba(34,40,64,0.80)",
            bordercolor=C["border"],
            borderwidth=1, borderpad=3,
            align="right",
        )

    _theme(fig, height=max(300, 260 * rows + 80))
    fig.update_yaxes(**_AX, title_text="Vm [pu]")
    fig.update_xaxes(**_AX, type="category")
    fig.update_layout(
        showlegend=True,
        legend=dict(
            **_BASE_LAYOUT["legend"],
            x=1.01, y=1.0,
        ),
    )
    for ann in fig.layout.annotations:
        if "Bus" in str(ann.text):
            ann.font.color = C["text"]
            ann.font.size  = 11

    out = os.path.join(output_folder, "06_voltage_bus_profiler.html")
    return _save(fig, out,
                 f"Voltage Bus Profiler — Top {n_worst} worst buses, pre vs post market",
                 f"Dashed red = pre-market · Solid green = post-market · Shaded band = [{vmin}, {vmax}] pu · Σ = cumulative violation",
                 market_tag)


# =============================================================================
# 9.  ENTRY POINT
# =============================================================================

def generate_showcase(
    pre_ts_root:        Optional[str],
    post_ts_root:       Optional[str],
    market_result_file: Optional[str],
    output_folder:      str,
    market_tag:         str  = "scenario",
    vmin:               float = 0.95,
    vmax:               float = 1.05,
    loading_limit:      float = 100.0,
    n_worst_buses:      int   = 8,
) -> Dict[str, Optional[str]]:
    """
    Generate all six showcase figures and save them to
        output_folder/showcase/

    Parameters
    ----------
    pre_ts_root        : root folder containing res_bus/vm_pu.csv etc. (pre-market)
    post_ts_root       : root folder containing res_bus/vm_pu.csv etc. (post-market)
    market_result_file : path to model_results_*.xlsx
    output_folder      : scenario visualization root
    market_tag         : scenario label for titles and file names
    vmin, vmax         : voltage limits [pu]
    loading_limit      : branch loading limit [%]  (unused here, kept for API compat)
    n_worst_buses      : how many worst buses to show in Fig 6
    """
    out_dir = os.path.join(output_folder, "showcase")
    os.makedirs(out_dir, exist_ok=True)

    # Infer scenario root (parent of visualization folder)
    scenario_root = os.path.dirname(output_folder) if output_folder else "."
    if market_result_file:
        scenario_root = os.path.dirname(market_result_file)

    print(f"\n{'='*64}")
    print(f"  Showcase — 6 new informative figures")
    print(f"  Scenario : {market_tag}")
    print(f"  Output   : {out_dir}")
    print(f"{'='*64}")

    saved: Dict[str, Optional[str]] = {}

    steps = [
        ("capacity_utilisation",
         "[1/6] Capacity Utilisation Heatmap …",
         lambda: fig_capacity_utilisation(market_result_file, out_dir, market_tag)),
        ("pq_envelope",
         "[2/6] P–Q Operating Envelope …",
         lambda: fig_pq_operating_envelope(market_result_file, out_dir, market_tag)),
        ("soc_trajectory",
         "[3/6] Storage SOC Trajectory …",
         lambda: fig_storage_soc_trajectory(market_result_file, out_dir, market_tag)),
        ("merit_order",
         "[4/6] Merit-Order Dispatch …",
         lambda: fig_merit_order_dispatch(market_result_file, out_dir, market_tag)),
        ("congestion_by_asset",
         "[5/6] Per-Asset Congestion Decomposition …",
         lambda: fig_congestion_by_asset(scenario_root, out_dir, market_tag)),
        ("voltage_profiler",
         "[6/6] Voltage Bus Profiler …",
         lambda: fig_voltage_bus_profiler(pre_ts_root, post_ts_root,
                                          vmin, vmax, out_dir, market_tag,
                                          n_worst_buses)),
    ]

    for key, msg, func in steps:
        print(f"  {msg}")
        try:
            saved[key] = func()
        except Exception as exc:
            saved[key] = None
            print(f"    ERROR: {exc}")

    print(f"\n  Summary:")
    for k, p in saved.items():
        # Keep Windows console output
        # ASCII-safe so figure generation cannot fail on cp1252 terminals.
        print(f"    {k:25s} {'[ok] ' + p if p else '-- skipped'}")
    print()
    return saved


# =============================================================================
# 10.  DEMO  (synthetic data — runs without any real output files)
# =============================================================================

def _make_synthetic(root: str) -> Tuple[str, str, str, str]:
    """Generate synthetic platform-compatible output files in root/."""
    import math as _math
    rng = np.random.default_rng(0)
    pre_ts  = os.path.join(root, "pre_ts")
    post_ts = os.path.join(root, "post_ts")
    scen    = os.path.join(root, "scenario_out")
    for d in [pre_ts, post_ts, scen,
              pre_ts  + "/res_bus", pre_ts  + "/res_line", pre_ts  + "/res_trafo",
              post_ts + "/res_bus", post_ts + "/res_line", post_ts + "/res_trafo"]:
        os.makedirs(d, exist_ok=True)

    hours      = list(range(24))
    peak_hours = [7, 8, 9, 17, 18, 19, 20]
    n_bus, n_line, n_trafo = 18, 14, 3
    n_load, n_gen, n_sto   = 6, 4, 3

    # Timeseries: rows=hours, cols=assets
    def _vm_pre() -> pd.DataFrame:
        vm = pd.DataFrame(index=hours,
                          columns=[f"bus_{i}" for i in range(n_bus)],
                          dtype=float)
        for h in hours:
            v = rng.normal(1.0, 0.012, n_bus)
            if h in peak_hours:
                v[rng.integers(0, n_bus, 3)] += rng.uniform(0.04, 0.07, 3)
                v[rng.integers(0, n_bus, 2)] -= rng.uniform(0.04, 0.06, 2)
            vm.loc[h] = np.clip(v, 0.89, 1.12)
        return vm

    vm_pre = _vm_pre()
    vm_pre.to_csv(pre_ts + "/res_bus/vm_pu.csv")
    vm_post = vm_pre.copy()
    for h in peak_hours:
        r = vm_post.loc[h].astype(float).values.copy()
        r = np.where(r > 1.05, r - rng.uniform(0.035, 0.06, len(r)), r)
        r = np.where(r < 0.95, r + rng.uniform(0.035, 0.06, len(r)), r)
        vm_post.loc[h] = np.clip(r, 0.91, 1.09)
    vm_post.to_csv(post_ts + "/res_bus/vm_pu.csv")

    ll_pre = pd.DataFrame(
        {f"line_{i}": [rng.uniform(20, 70) +
                       (rng.uniform(20, 55) if h in peak_hours and i < 4 else 0)
                       for h in hours]
         for i in range(n_line)}, index=hours)
    ll_pre.to_csv(pre_ts  + "/res_line/loading_percent.csv")
    ll_post = ll_pre.copy().astype(float)
    for h in peak_hours:
        for i in range(4):
            if ll_post.loc[h, f"line_{i}"] > 100:
                ll_post.loc[h, f"line_{i}"] -= rng.uniform(15, 30)
    ll_post.to_csv(post_ts + "/res_line/loading_percent.csv")

    tl_pre = pd.DataFrame(
        {f"trafo_{i}": [rng.uniform(25, 65) + (rng.uniform(30, 55) if h in peak_hours and i == 0 else 0)
                        for h in hours]
         for i in range(n_trafo)}, index=hours)
    tl_pre.to_csv(pre_ts  + "/res_trafo/loading_percent.csv")
    tl_post = tl_pre.copy().astype(float)
    for h in peak_hours:
        tl_post.loc[h, "trafo_0"] = max(0, float(tl_post.loc[h, "trafo_0"]) - rng.uniform(18, 35))
    tl_post.to_csv(post_ts + "/res_trafo/loading_percent.csv")

    # model_results Excel
    studied = sorted(set(peak_hours))
    xlsx = os.path.join(scen, "model_results_demo.xlsx")
    with pd.ExcelWriter(xlsx, engine="openpyxl") as w:
        def _act(n, hours, scale=2.0):
            return pd.DataFrame(
                {h: rng.uniform(-scale, scale, n) for h in hours},
                index=range(n))

        def _lim(n, hours, scale=3.5):
            return pd.DataFrame(
                {h: np.abs(rng.uniform(scale * 0.6, scale, n)) for h in hours},
                index=range(n))

        def _init(n, hours, base=1.0):
            return pd.DataFrame(
                {h: rng.normal(base, 0.2, n) for h in hours},
                index=range(n))

        def _cost(n, hours, lo=5, hi=30):
            return pd.DataFrame(
                {h: rng.uniform(lo, hi, n) for h in hours},
                index=range(n))

        def _soc(n, hours):
            soc = np.zeros((n, len(hours)))
            for i in range(n):
                s = rng.uniform(0.4, 0.6)
                for t, h in enumerate(hours):
                    delta = rng.uniform(-0.12, 0.12)
                    s = float(np.clip(s + delta, 0.15, 0.90))
                    soc[i, t] = s
            return pd.DataFrame(soc, columns=hours, index=range(n))

        for sheet, df in [
            ("DW_A", _act(n_load, studied)),   ("DR_A", _act(n_load, studied, 1.5)),
            ("DW_B", _act(n_gen,  studied)),   ("DR_B", _act(n_gen,  studied, 1.5)),
            ("DW_C", _act(n_sto,  studied)),   ("DR_C", _act(n_sto,  studied, 1.0)),
            ("DW_U_Lim_A", _lim(n_load, studied)),  ("DW_U_Lim_B", _lim(n_gen, studied)),
            ("DW_U_Lim_C", _lim(n_sto,  studied)),
            ("Winit_A", _init(n_load, studied, base=0.8)),
            ("Rinit_A", _init(n_load, studied, base=0.3)),
            ("Winit_B", _init(n_gen,  studied, base=1.2)),
            ("Rinit_B", _init(n_gen,  studied, base=0.4)),
            ("WUB_ULim_A", _lim(n_load, studied, 4.0)),
            ("RUB_ULim_A", _lim(n_load, studied, 2.0)),
            ("WUB_ULim_B", _lim(n_gen,  studied, 4.0)),
            ("RUB_ULim_B", _lim(n_gen,  studied, 2.0)),
            ("W_U_Cost_A", _cost(n_load, studied, 5, 18)),
            ("R_U_Cost_A", _cost(n_load, studied, 4, 12)),
            ("W_U_Cost_B", _cost(n_gen,  studied, 8, 25)),
            ("R_U_Cost_B", _cost(n_gen,  studied, 6, 20)),
            ("W_U_Cost_C", _cost(n_sto,  studied, 10, 30)),
            ("R_U_Cost_C", _cost(n_sto,  studied, 8,  22)),
            ("SOC_C", _soc(n_sto, studied)),
            ("alpha_DVpu", _act(3, studied, 1e-4)),
            ("beta",       _act(3, studied, 0.02)),
        ]:
            df.index.name = "idx"
            df.to_excel(w, sheet_name=sheet)

    # CM need Excel files (per asset)
    for fname, factor in [("total_cm_PreMKT.xlsx", 1.0),
                           ("total_cm_postMKT.xlsx", 0.08)]:
        assets = ["line_0", "line_1", "line_2", "trafo_0"]
        rows_d = {"hour": studied}
        for a in assets:
            base = [max(0, rng.uniform(0.5, 3.0) * factor) if h in [17, 18, 19, 20] else 0.0
                    for h in studied]
            rows_d[a] = base
        pd.DataFrame(rows_d).to_excel(
            os.path.join(scen, fname), sheet_name="Congestion needs", index=False)

    return pre_ts, post_ts, xlsx, scen


def run_demo(output_root: str = "/tmp/enginiite_showcase_v2") -> Dict[str, Optional[str]]:
    """
    Run the full showcase on synthetic data.
    All six figures will be generated in output_root/scenario_out/visualization/showcase/
    """
    print("  Generating synthetic demo data …")
    pre_ts, post_ts, xlsx, scen = _make_synthetic(output_root)
    viz_root = os.path.join(scen, "visualization")
    return generate_showcase(
        pre_ts_root        = pre_ts,
        post_ts_root       = post_ts,
        market_result_file = xlsx,
        output_folder      = viz_root,
        market_tag         = "net_CMVC_PQ_VL01_F05_SK01_T1",
        vmin               = 0.95,
        vmax               = 1.05,
    )


if __name__ == "__main__":
    results = run_demo()
    print("Done. Open any .html file in a browser.")
