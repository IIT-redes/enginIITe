"""Layout and file helpers shared by the Plotly figures of the comparison folder.
"""
from __future__ import annotations

import os
import re
import html
import textwrap
import warnings
from typing import Optional, Dict, Any, List, Tuple

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from . import figure_style


# Numerical activation tolerance used in all economic-market plots.
# Values below this threshold are treated as solver residuals, not real
# accepted flexibility. Units follow the product: MW for P and MVAr for Q.
# Example: 1e-6 MW = 1 W, so e-9/e-12 spreadsheet noise is ignored.
ACTIVATION_ZERO_TOL = 1e-6


def _ensure_folder(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def _extract_market_tag_from_text(text: Any) -> Optional[str]:
    if text is None:
        return None
    # scenario/network and final suffix
    # identifiers may contain underscores (for example SB_DER_LOC_LOW).
    m = re.search(
        r"[A-Za-z0-9]+(?:_[A-Za-z0-9]+)+_(?:PQ|P|Q)_VL\d+_F\d+_SK\d+(?:_[A-Za-z0-9]+(?:_[A-Za-z0-9]+)*)?",
        str(text),
    )
    return m.group(0) if m else None


def _scenario_group_from_market_tag(market_tag: str) -> Optional[str]:
    parts = _market_tag_parts(market_tag)
    if not parts:
        return None
    return "_".join(
        filter(None, (parts['country'], parts['market'], parts['storage_case'], parts['ess_case']))
    )


def _resolve_scenario_visualization_folder(output_folder: str, market_tag: str) -> str:
    """
    Always resolve to:
        data_out/<scenario_group>/<market_tag>/visualization
    """
    if market_tag is None:
        market_tag = _extract_market_tag_from_text(output_folder)
    if market_tag is None:
        raise ValueError(
            "The comparison figures require a full market_tag, e.g. "
            "'net_CMVC_PQ_VL01_F05_SK01_T1'."
        )

    norm = os.path.normpath(str(output_folder))
    parts = norm.split(os.sep)

    if market_tag in parts:
        idx = parts.index(market_tag)
        return _ensure_folder(os.path.join(os.sep.join(parts[: idx + 1]), "visualization"))

    if os.path.basename(norm).lower() == "visualization":
        parent = os.path.dirname(norm)
        if os.path.basename(parent) == market_tag:
            return _ensure_folder(norm)

    if "data_out" in parts:
        idx = parts.index("data_out")
        base = os.sep.join(parts[: idx + 1])
        group = _scenario_group_from_market_tag(market_tag)
        if group:
            return _ensure_folder(os.path.join(base, group, market_tag, "visualization"))

    return _ensure_folder(os.path.join(norm, "visualization"))


def _scenario_root_from_visualization(visualization_root: str) -> str:
    if os.path.basename(os.path.normpath(visualization_root)).lower() == "visualization":
        return os.path.dirname(os.path.normpath(visualization_root))
    return visualization_root


def _scenario_description(market_tag: Optional[str]) -> str:
    if not market_tag:
        return ""
    parts = _market_tag_parts(market_tag)
    if not parts:
        return "Scenario: " + str(market_tag)
    return (
        f"Scenario: {parts['country']} | Market: {parts['market']} | Product: {parts['product']} | "
        f"Voltage level: {parts['vl_case']} | Flexibility case: {parts['flex_case']} | "
        f"Storage case: {parts['storage_case']} | {parts['ess_case']}"
    )


def _trace_has_visible_colorbar(trace: Any) -> bool:
    trace_type = str(getattr(trace, "type", "")).lower()
    if trace_type in {"heatmap", "contour", "histogram2d", "histogram2dcontour"}:
        # Plotly uses None for the default-visible heatmap colorbar.
        return getattr(trace, "showscale", None) is not False
    if hasattr(trace, "showscale") and bool(getattr(trace, "showscale", False)):
        return True
    for component in (getattr(trace, "marker", None), getattr(trace, "line", None)):
        if component is None:
            continue
        component_showscale = getattr(component, "showscale", None)
        if component_showscale is True:
            return True
        # graph-object scatter traces may
        # render an explicitly configured colorbar while showscale remains None.
        # Detect that case so its title receives the same overlap-safe styling.
        colorbar = getattr(component, "colorbar", None)
        colorscale = getattr(component, "colorscale", None)
        try:
            colorbar_is_configured = bool(colorbar and colorbar.to_plotly_json())
        except Exception:
            colorbar_is_configured = colorbar is not None
        if component_showscale is not False and colorbar_is_configured and colorscale is not None:
            return True
    return False


def _update_colorbar_ieee(colorbar: Any) -> None:
    if colorbar is None:
        return
    try:
        title_text = str(colorbar.title.text or "")
    except Exception:
        title_text = ""
    # Preserve the trace-specific
    # x/y/length geometry. Overwriting len made independent subplot colorbars
    # span the full figure and superimpose contradictory-looking tick ranges.
    geometry = {}
    if getattr(colorbar, "len", None) is None:
        geometry.update(len=0.92, lenmode="fraction")
    try:
        colorbar.update(
            title=dict(
                text=title_text,
                side="right",
                font=dict(size=12, family="Times New Roman, Times, serif"),
            ),
            thickness=20,
            tickfont=dict(size=14, family="Times New Roman, Times, serif"),
            xpad=8,
            ypad=6,
            **geometry,
        )
    except Exception:
        colorbar.update(
            title=dict(
                text=title_text,
                font=dict(size=12, family="Times New Roman, Times, serif"),
            ),
            thickness=20,
            tickfont=dict(size=14, family="Times New Roman, Times, serif"),
            xpad=8,
            ypad=6,
            **geometry,
        )


def _enforce_ascending_numeric_ranges(fig: go.Figure) -> go.Figure:
    """Keep every numeric axis and continuous scale ordered low-to-high.

    Categorical ranking axes may intentionally be reversed; only finite numeric
    two-value ranges are normalized here.
    """

    def normalize_pair(owner: Any, low_name: str, high_name: str) -> None:
        low = getattr(owner, low_name, None)
        high = getattr(owner, high_name, None)
        try:
            low_value = float(low)
            high_value = float(high)
        except (TypeError, ValueError):
            return
        if np.isfinite(low_value) and np.isfinite(high_value) and low_value > high_value:
            owner.update(**{low_name: high_value, high_name: low_value})

    for layout_name in list(fig.layout):
        obj = fig.layout[layout_name]
        if str(layout_name).startswith(("xaxis", "yaxis")):
            axis_range = getattr(obj, "range", None)
            if axis_range is not None and len(axis_range) == 2:
                try:
                    low_value, high_value = float(axis_range[0]), float(axis_range[1])
                except (TypeError, ValueError):
                    continue
                if np.isfinite(low_value) and np.isfinite(high_value) and low_value > high_value:
                    obj.update(range=[high_value, low_value])
        elif str(layout_name).startswith("coloraxis"):
            normalize_pair(obj, "cmin", "cmax")

    for trace in fig.data:
        normalize_pair(trace, "zmin", "zmax")
        normalize_pair(trace, "cmin", "cmax")
        for component_name in ("marker", "line"):
            component = getattr(trace, component_name, None)
            if component is not None:
                normalize_pair(component, "cmin", "cmax")
    return fig


def _apply_ieee_layout(
    fig: go.Figure,
    market_tag: str,
    height: int = 820,
    show_legend: bool = True,
) -> go.Figure:
    _enforce_ascending_numeric_ranges(fig)
    fig.update_layout(
        title=dict(
            text=_scenario_description(market_tag),
            x=0.5,
            y=0.975,
            xanchor="center",
            yanchor="top",
            font=dict(size=17, family="Times New Roman, Times, serif", color="#111827"),
        ),
        autosize=True,
        width=None,
        height=max(height, 760),
        hovermode="closest",
        paper_bgcolor="white",
        plot_bgcolor="rgba(248,250,252,0.72)",
        colorway=["#0057B8", "#00A6D6", "#00843D", "#F77F00", "#7B2CBF", "#D62828", "#2A9D8F", "#6C757D"],
        font=dict(family="Times New Roman, Times, serif", size=15, color="#111827"),
        margin=dict(l=95, r=140, t=112, b=125),
        hoverlabel=dict(
            bgcolor="rgba(255,255,255,0.98)",
            bordercolor="rgba(75,85,99,0.55)",
            font=dict(family="Times New Roman, Times, serif", size=14, color="#111827"),
            namelength=-1,
        ),
    )

    fig.update_xaxes(
        showgrid=True,
        gridcolor="rgba(148,163,184,0.24)",
        automargin=True,
        title_standoff=16,
        title_font=dict(size=17, family="Times New Roman, Times, serif"),
        tickfont=dict(size=14, family="Times New Roman, Times, serif"),
        showline=True,
        linewidth=1,
        linecolor="rgba(17,24,39,0.45)",
    )
    fig.update_yaxes(
        showgrid=True,
        gridcolor="rgba(148,163,184,0.24)",
        automargin=True,
        title_standoff=16,
        title_font=dict(size=17, family="Times New Roman, Times, serif"),
        tickfont=dict(size=14, family="Times New Roman, Times, serif"),
        showline=True,
        linewidth=1,
        linecolor="rgba(17,24,39,0.45)",
    )

    if show_legend:
        fig.update_layout(
            legend=dict(
                orientation="h",
                yanchor="top",
                y=-0.18,
                xanchor="center",
                x=0.5,
                bgcolor="rgba(255,255,255,0.92)",
                bordercolor="rgba(148,163,184,0.35)",
                borderwidth=1,
                font=dict(size=14, family="Times New Roman, Times, serif"),
            )
        )

    for trace in fig.data:
        if _trace_has_visible_colorbar(trace):
            if hasattr(trace, "colorbar") and trace.colorbar is not None:
                _update_colorbar_ieee(trace.colorbar)
            for component_name in ("marker", "line"):
                component = getattr(trace, component_name, None)
                if component is not None and hasattr(component, "colorbar") and component.colorbar is not None:
                    _update_colorbar_ieee(component.colorbar)
    # Traces may share a layout-level
    # coloraxis, whose colorbar must follow the same side-title policy.
    for layout_name in list(fig.layout):
        if str(layout_name).startswith("coloraxis"):
            coloraxis = fig.layout[layout_name]
            if coloraxis is not None and getattr(coloraxis, "colorbar", None) is not None:
                _update_colorbar_ieee(coloraxis.colorbar)

    return fig


def _polish_axis_units_and_overlap(fig: go.Figure) -> go.Figure:
    """Final pass before saving: keep axis units visible and reduce label/legend overlap.

    The plotting functions set semantic titles such as [MW], [MVAr], [MVA], [pu],
    [%], [EUR] or [-]. This helper does not change the meaning of those titles;
    it only enforces automargins, sensible standoff, and readable tick labels.
    """
    try:
        fig.update_xaxes(automargin=True, title_standoff=14, tickfont=dict(size=13))
        fig.update_yaxes(automargin=True, title_standoff=16, tickfont=dict(size=13))
        # Plotly axis objects are named xaxis, xaxis2, ... and yaxis, yaxis2, ...
        for ax_name in list(fig.layout):
            if str(ax_name).startswith('xaxis'):
                ax = fig.layout[ax_name]
                # Rotate only categorical/text-like x axes or axes with many labels.
                if getattr(ax, 'type', None) == 'category' or getattr(ax, 'categoryarray', None) is not None:
                    ax.update(tickangle=-30)
            if str(ax_name).startswith('yaxis'):
                ax = fig.layout[ax_name]
                ax.update(automargin=True)
        # Prevent bottom legends/annotations from being clipped.
        m = fig.layout.margin or {}
        b = getattr(m, 'b', None) if hasattr(m, 'b') else (m.get('b') if isinstance(m, dict) else None)
        l = getattr(m, 'l', None) if hasattr(m, 'l') else (m.get('l') if isinstance(m, dict) else None)
        r = getattr(m, 'r', None) if hasattr(m, 'r') else (m.get('r') if isinstance(m, dict) else None)
        t = getattr(m, 't', None) if hasattr(m, 't') else (m.get('t') if isinstance(m, dict) else None)
        top_required = max(t or 105, 105)
        bottom_required = max(b or 135, 135)
        title_obj = getattr(fig.layout, "title", None)
        if title_obj is not None:
            title_text = str(getattr(title_obj, "text", "") or "")
            if "<br>" not in title_text and len(re.sub(r"<[^>]+>", "", title_text)) > 60:
                wrapped = textwrap.wrap(title_text, width=54, break_long_words=False, break_on_hyphens=False)
                title_obj.update(text="<br>".join(wrapped[:3]))
                top_required = max(top_required, 135)
        if getattr(fig.layout, "annotations", None):
            kept = []
            wrapped_subplot_title = False
            for ann in fig.layout.annotations:
                try:
                    y = float(ann.y)
                    yref = str(ann.yref or "")
                except Exception:
                    kept.append(ann)
                    continue
                # Explanatory notes below the plot are now moved into the
                # dedicated Takeaway page to keep the figure itself clean.
                if yref == "paper" and y < 0:
                    continue
                # Plotly creates subplot
                # titles as paper annotations.  Wrap and shrink them inside the
                # panel domain instead of allowing adjacent titles to collide.
                xref = str(getattr(ann, "xref", "") or "")
                showarrow = bool(getattr(ann, "showarrow", False))
                text = str(getattr(ann, "text", "") or "")
                visible_text = re.sub(r"<[^>]+>", "", text)
                is_subplot_title = (
                    yref == "paper" and xref == "paper" and not showarrow and y >= 0
                    and ("<br>" in text or len(visible_text) > 34)
                )
                if is_subplot_title:
                    if "<br>" not in text:
                        lines = textwrap.wrap(text, width=32, break_long_words=False, break_on_hyphens=False)
                        if len(lines) > 3:
                            lines = lines[:2] + [" ".join(lines[2:])]
                        ann.update(text="<br>".join(lines))
                    current_size = getattr(getattr(ann, "font", None), "size", None)
                    ann.update(
                        align="center",
                        font=dict(size=min(int(current_size or 14), 13), family="Times New Roman, Times, serif"),
                        yshift=max(int(getattr(ann, "yshift", 0) or 0), 6),
                    )
                    wrapped_subplot_title = True
                    if y >= 0.95:
                        top_required = max(top_required, 145)
                kept.append(ann)
            # Direct replacement is required here: update_layout merges annotation tuples by index.
            fig.layout.annotations = tuple(kept)
        # Reserve a separate bottom band for horizontal legends instead of
        # placing them on top of x-axis titles or rotated tick labels.
        for layout_name in list(fig.layout):
            if not str(layout_name).startswith("legend"):
                continue
            legend_obj = fig.layout[layout_name]
            if legend_obj is None or str(getattr(legend_obj, "orientation", "") or "") != "h":
                continue
            legend_y = getattr(legend_obj, "y", None)
            if legend_y is not None and float(legend_y) < 0.08:
                legend_obj.update(y=min(float(legend_y), -0.20), yanchor="top", xanchor="center", x=0.5, tracegroupgap=5)
                bottom_required = max(bottom_required, 175)
        fig.update_layout(margin=dict(l=max(l or 95, 95), r=max(r or 130, 130), t=top_required, b=bottom_required))
        # Improve colorbar readability for all heatmap-like traces.
        for tr in fig.data:
            # Do not create/style a
            # colorbar object for categorical markers or showscale=False data.
            if not _trace_has_visible_colorbar(tr):
                continue
            if hasattr(tr, 'colorbar') and tr.colorbar is not None:
                try:
                    title_text = str(tr.colorbar.title.text or "")
                except Exception:
                    title_text = ""
                tr.colorbar.update(
                    title=dict(text=title_text, side="right", font=dict(size=12, family="Times New Roman, Times, serif")),
                    thickness=18,
                    xpad=18,
                    ypad=6,
                    tickfont=dict(size=12, family="Times New Roman, Times, serif"),
                )
            for component_name in ("marker", "line"):
                component = getattr(tr, component_name, None)
                if component is None or not hasattr(component, "colorbar") or component.colorbar is None:
                    continue
                try:
                    title_text = str(component.colorbar.title.text or "")
                except Exception:
                    title_text = ""
                component.colorbar.update(
                    title=dict(text=title_text, side="right", font=dict(size=12, family="Times New Roman, Times, serif")),
                    thickness=18,
                    xpad=18,
                    ypad=6,
                    tickfont=dict(size=12, family="Times New Roman, Times, serif"),
                )
        for layout_name in list(fig.layout):
            if not str(layout_name).startswith("coloraxis"):
                continue
            coloraxis = fig.layout[layout_name]
            if coloraxis is not None and getattr(coloraxis, "colorbar", None) is not None:
                _update_colorbar_ieee(coloraxis.colorbar)
    except Exception:
        pass
    return fig


def _numeric_examples_from_fig(fig: go.Figure, limit: int = 4) -> str:
    examples = []
    try:
        for tr in fig.data:
            x_vals = list(getattr(tr, "x", []) or [])
            y_vals = list(getattr(tr, "y", []) or [])
            name = str(getattr(tr, "name", "") or "first plotted series")
            n = min(len(x_vals), len(y_vals))
            for i in range(n):
                y = pd.to_numeric(pd.Series([y_vals[i]]), errors="coerce").iloc[0]
                if pd.notna(y):
                    examples.append(f"'{name}': at x = {x_vals[i]}, y = {float(y):.4g}.")
                    break
            if len(examples) >= limit:
                break
    except Exception:
        pass
    if examples:
        return " ".join(examples)
    return "A numerical example could not be extracted automatically from the plotted trace arrays, so use the axis units and CSV/Excel source saved beside the figure for exact numerical auditing."


def _curve_guide_from_fig(fig: go.Figure, limit: int = 8) -> str:
    rows = []
    try:
        for tr in fig.data:
            name = str(getattr(tr, "name", "") or "").strip()
            if not name or name.lower() in {"none", "error scale"}:
                continue
            axis_id = str(getattr(tr, "yaxis", "") or "y")
            panel = "main panel" if axis_id in {"", "y", "y1"} else f"subplot linked to {axis_id}"
            x_vals = list(getattr(tr, "x", []) or [])
            y_vals = pd.to_numeric(pd.Series(list(getattr(tr, "y", []) or [])), errors="coerce")
            valid = y_vals.dropna()
            if valid.empty:
                continue
            rows.append(
                f"<li><strong>{html.escape(name)}</strong> ({html.escape(panel)}): {len(valid)} plotted values; "
                f"min = {float(valid.min()):.4g}, max = {float(valid.max()):.4g}, mean = {float(valid.mean()):.4g}. "
                f"The first visible numeric point is at x = {html.escape(str(x_vals[valid.index[0]])) if x_vals and valid.index[0] < len(x_vals) else 'n/a'}, "
                f"y = {float(valid.iloc[0]):.4g}.</li>"
            )
            if len(rows) >= limit:
                break
    except Exception:
        pass
    if not rows:
        return "<p>The figure does not expose a simple numeric trace summary, but the plotted values remain available through the hover labels and companion CSV/Excel outputs.</p>"
    return "<ul>" + "".join(rows) + "</ul>"


def _takeaway_text_blocks(header_title: str) -> Dict[str, str]:
    title = str(header_title or "").lower()
    if "accuracy" in title or "linear" in title or "ac" in title:
        return {
            "meaning": "This figure tests whether the linear sensitivity-based market representation remains close to the exact AC power-flow validation. Points close to the diagonal or small heatmap values indicate that the simplified model is reliable for the shown operating range.",
            "dso": "Use it as a screening tool for operational confidence. Large errors identify hours, buses, or congested assets where the DSO should validate the market result with AC power flow before implementation.",
            "fsp": "A low error region means FSP activation is being translated into network impact consistently. High-error regions warn that the same bid could be valued differently after exact AC validation.",
            "regulator": "Persistent high errors indicate where regulatory rules should require AC validation, conservative margins, or periodic recalibration of sensitivities.",
        }
    if "revenue" in title or "payment" in title or "engagement" in title:
        return {
            "meaning": "This figure translates accepted flexibility into market-attractiveness signals. Payment values are a bid-cost-based proxy, useful for comparing participation incentives across providers, technologies, and hours.",
            "dso": "Look for whether procurement is broad and repeatable or concentrated in a few scarcity hours. Stable engagement reduces operational dependency on one provider.",
            "fsp": "Providers can see whether revenue is frequent enough to justify participation costs, or whether income depends on rare congestion and voltage events.",
            "regulator": "A healthy design should create enough revenue opportunity to attract customers while avoiding excessive concentration or dependence on one technology class.",
        }
    if "regulatory" in title or "policy" in title or "market-power" in title or "concentration" in title:
        return {
            "meaning": "This figure converts technical relief, activation burden, market concentration, and residual risk into regulatory evidence. The goal is not only solving today network issue, but testing whether the market design remains efficient, competitive, and scalable.",
            "dso": "Use it to identify designs that deliver security with manageable activation volume and low residual-risk hours.",
            "fsp": "The most attractive designs combine clear procurement needs with diverse participation, so the market does not depend on only one dominant resource.",
            "regulator": "Prioritize designs that reduce constraints while maintaining low HHI, low top-provider dependency, and transparent residual-risk treatment.",
        }
    if "sensitivity" in title:
        return {
            "meaning": "This figure links activated providers to their physical network sensitivity. A provider with high sensitivity and high activation is technically important; high activation with low sensitivity may signal economic or locational inefficiency.",
            "dso": "Use high-sensitivity providers as priority candidates for prequalification and operational monitoring.",
            "fsp": "A resource located at a sensitive bus has stronger technical value and may be more competitive for local flexibility services.",
            "regulator": "Sensitivity-based evidence helps define locational products and justify why some bids are more valuable than others even at similar prices.",
        }
    return {
        "meaning": "This figure summarizes one operational or market-design aspect of the flexibility platform. Read the axes first, then compare the relative position, color, and size of the plotted elements.",
        "dso": "Focus on whether the figure reveals remaining operational risk, excessive activation effort, or a need for better locational procurement.",
        "fsp": "Focus on how often resources are activated, how large the accepted volumes are, and whether participation appears predictable enough to be attractive.",
        "regulator": "Focus on whether the market design produces secure outcomes without excessive concentration, opacity, or unfair access barriers.",
    }


def _takeaway_html(header_title: str, fig: go.Figure) -> str:
    blocks = _takeaway_text_blocks(header_title)
    example = _numeric_examples_from_fig(fig)
    curve_guide = _curve_guide_from_fig(fig)
    return f"""
        <section class="takeaway-page">
            <h2>Takeaway</h2>
            <div class="takeaway-grid">
                <article>
                    <h3>How to Read This Figure</h3>
                    <p>{html.escape(blocks["meaning"])}</p>
                    <p><strong>Numerical example.</strong> {html.escape(example)}</p>
                </article>
                <article>
                    <h3>Curve and Subfigure Guide</h3>
                    {curve_guide}
                </article>
                <article>
                    <h3>DSO Interpretation</h3>
                    <p>{html.escape(blocks["dso"])} Hidden value: compare not only the highest point, but also whether the response is persistent, diversified, and located where network sensitivity is high.</p>
                </article>
                <article>
                    <h3>FSP Interpretation</h3>
                    <p>{html.escape(blocks["fsp"])} Hidden value: the most bankable opportunity is often not the largest single activation, but repeated activation with moderate competition and clear locational need.</p>
                </article>
                <article>
                    <h3>Regulatory Interpretation</h3>
                    <p>{html.escape(blocks["regulator"])} Hidden value: a design can be technically successful but still fragile if it depends on one provider, one bus, or one product family.</p>
                </article>
            </div>
        </section>
    """


def _write_themed_plotly_html(
    fig: go.Figure,
    html_path: str,
    header_title: str,
    figure_note: str = "",
) -> None:
    _enforce_ascending_numeric_ranges(fig)
    # Every figure passes through here, so
    # the window wording in hover text and any axis left without a title are
    # corrected once for the whole visualization batch.
    try:
        figure_style.retitle_window_hovers(fig)
        figure_style.retitle_window_axes(fig)
        figure_style.deconflict_right_margin(fig)
        figure_style.space_stacked_panels(fig)
        figure_style.ensure_axis_titles(fig)
        if not str(figure_note or "").strip():
            meta = fig.layout.meta if isinstance(fig.layout.meta, dict) else {}
            figure_note = str(meta.get("readability_note", "") or "")
    except Exception:
        pass
    config = {
        "displaylogo": False,
        "responsive": True,
        "scrollZoom": True,
        "modeBarButtonsToRemove": ["lasso2d", "select2d", "autoScale2d", "toggleSpikelines"],
        "toImageButtonOptions": {
            "format": "png",
            "filename": os.path.basename(html_path).replace(".html", ""),
            "scale": 2,
        },
    }

    _polish_axis_units_and_overlap(fig)

    div_html = fig.to_html(
        full_html=False,
        include_plotlyjs="cdn",
        config=config,
        default_width="100%",
        default_height=str(max(int(fig.layout.height or 820), 820)) + "px",
    )

    css_text = """
        :root {
            --ieee-blue: #003A70;
            --ieee-cyan: #007C89;
            --ieee-bg: #F6F8FB;
            --ieee-card: #FFFFFF;
            --ieee-border: #D8E0EA;
            --ieee-text: #111827;
        }
        body {
            margin: 0;
            padding: 0;
            font-family: "Times New Roman", Times, serif;
            background: var(--ieee-bg);
            color: var(--ieee-text);
        }
        .page-header {
            background: linear-gradient(90deg, var(--ieee-blue) 0%, var(--ieee-cyan) 100%);
            color: white;
            padding: 18px 32px;
            text-align: center;
            box-shadow: 0 4px 18px rgba(0,0,0,0.18);
        }
        .page-header h1 {
            margin: 0 auto;
            max-width: 1650px;
            font-size: 25px;
            line-height: 1.30;
            font-weight: 700;
            letter-spacing: 0.005em;
            white-space: normal;
        }
        .wrapper {
            max-width: 1800px;
            margin: 0 auto;
            padding: 22px 28px 28px 28px;
            box-sizing: border-box;
        }
        .figure-card {
            background: var(--ieee-card);
            border: 1px solid var(--ieee-border);
            border-radius: 14px;
            box-shadow: 0 8px 26px rgba(16, 42, 67, 0.075);
            padding: 16px 22px 22px 22px;
            box-sizing: border-box;
            overflow: visible;
            text-align: center;
        }
        .figure-card > div {
            margin-left: auto;
            margin-right: auto;
        }
        .figure-card .js-plotly-plot,
        .figure-card .plot-container,
        .figure-card .svg-container {
            width: 100% !important;
            margin-left: auto !important;
            margin-right: auto !important;
        }
        .figure-note {
            max-width: 1500px;
            margin: 8px auto 0 auto;
            padding: 12px 16px;
            border-top: 1px solid var(--ieee-border);
            color: var(--ieee-text);
            font-size: 15px;
            line-height: 1.45;
            text-align: left;
            white-space: pre-line;
        }
        .takeaway-page {
            margin-top: 38px;
            padding: 28px 30px;
            background: #FFFFFF;
            border: 1px solid var(--ieee-border);
            border-radius: 14px;
            box-shadow: 0 8px 26px rgba(16, 42, 67, 0.075);
            page-break-before: always;
            break-before: page;
        }
        .takeaway-page h2 {
            margin: 0 0 16px 0;
            color: var(--ieee-blue);
            font-size: 26px;
            line-height: 1.2;
        }
        .takeaway-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 16px;
        }
        .takeaway-grid article {
            border-left: 4px solid var(--ieee-cyan);
            background: #F8FBFD;
            padding: 14px 16px;
        }
        .takeaway-grid h3 {
            margin: 0 0 8px 0;
            font-size: 18px;
            color: #003A70;
        }
        .takeaway-grid p {
            margin: 0 0 8px 0;
            font-size: 16px;
            line-height: 1.45;
        }
        @media (max-width: 900px) {
            .takeaway-grid { grid-template-columns: 1fr; }
        }
    """

    # Consistency figures can define
    # compact threshold and review codes immediately below the plotted image.
    note_html = (
        f'<div class="figure-note">{html.escape(str(figure_note))}</div>'
        if str(figure_note or "").strip()
        else ""
    )

    html_text = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8"/>
    <title>{html.escape(str(header_title))}</title>
    <style>
{css_text}
    </style>
</head>
<body>
    <header class="page-header">
        <h1>{html.escape(str(header_title))}</h1>
    </header>
    <main class="wrapper">
        <section class="figure-card">
            {div_html}
            {note_html}
        </section>
        {_takeaway_html(header_title, fig)}
    </main>
</body>
</html>
"""
    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(html_text)


def _safe_read_csv(path: str) -> Optional[pd.DataFrame]:
    if path is None or not os.path.exists(path):
        return None
    try:
        return pd.read_csv(path)
    except Exception as exc:
        warnings.warn(f"Could not read CSV {path}: {exc}")
        return None


def _safe_read_excel(path: str, sheet_name: Optional[str] = None) -> Optional[pd.DataFrame]:
    if path is None or not os.path.exists(path):
        return None
    try:
        return pd.read_excel(path, sheet_name=sheet_name or 0)
    except Exception as exc:
        warnings.warn(f"Could not read Excel {path}: {exc}")
        return None


def _find_file(folder: str, filename: str) -> Optional[str]:
    if folder is None or not os.path.exists(folder):
        return None
    for root, _, files in os.walk(folder):
        for f in files:
            if f == filename:
                return os.path.join(root, f)
    return None


def _hour_value_columns(df: pd.DataFrame) -> List[str]:
    """
    Return columns that represent actual time-series values, excluding index
    columns such as Unnamed: 0, hour, index, time.
    """
    out = []
    for c in df.columns:
        s = str(c).strip()
        low = s.lower()
        if low.startswith("unnamed") or low in {"hour", "index", "time", "timestep"}:
            continue
        if pd.to_numeric(df[c], errors="coerce").notna().sum() > 0:
            out.append(c)
    return out


def _read_loading_exposure_from_folder(folder: str, threshold_percent: float) -> pd.DataFrame:
    """
    Read pandapower loading_percent.csv files and calculate exposure above a
    threshold in percentage-points.

    Unit:
        percentage-points above threshold.
    """
    rows = []
    if folder is None or not os.path.exists(folder):
        return pd.DataFrame(columns=["hour", "asset_group", "exposure_percent_point", "max_loading_percent"])

    targets = [
        ("res_line/loading_percent.csv", "Line"),
        ("res_trafo/loading_percent.csv", "Transformer"),
        ("res_trafo3w/loading_percent.csv", "Three-winding transformer"),
    ]

    for rel, group in targets:
        path = os.path.join(folder, rel)
        df = _safe_read_csv(path)
        if df is None or df.empty:
            continue

        value_cols = _hour_value_columns(df)
        hour_col = "Unnamed: 0" if "Unnamed: 0" in df.columns else None

        for ridx, row in df.iterrows():
            hour = int(row[hour_col]) if hour_col else int(ridx)
            vals = pd.to_numeric(row[value_cols], errors="coerce").dropna()
            if vals.empty:
                continue
            exposure = float(np.maximum(vals - threshold_percent, 0).sum())
            rows.append(
                {
                    "hour": hour,
                    "asset_group": group,
                    "exposure_percent_point": exposure,
                    "max_loading_percent": float(vals.max()),
                }
            )

    if not rows:
        return pd.DataFrame(columns=["hour", "asset_group", "exposure_percent_point", "max_loading_percent"])

    return pd.DataFrame(rows)


def _read_voltage_exposure_from_folder(folder: str, vmin: float, vmax: float) -> pd.DataFrame:
    """
    Read res_bus/vm_pu.csv and calculate voltage exposure.

    Unit:
        pu-deviation exposure.
    """
    path = os.path.join(folder, "res_bus", "vm_pu.csv") if folder else None
    df = _safe_read_csv(path)
    rows = []

    if df is None or df.empty:
        return pd.DataFrame(columns=["hour", "voltage_exposure_pu", "max_vm_pu", "min_vm_pu"])

    value_cols = _hour_value_columns(df)
    hour_col = "Unnamed: 0" if "Unnamed: 0" in df.columns else None

    for ridx, row in df.iterrows():
        hour = int(row[hour_col]) if hour_col else int(ridx)
        vals = pd.to_numeric(row[value_cols], errors="coerce").dropna()
        if vals.empty:
            continue
        exposure = float(np.maximum(vals - vmax, 0).sum() + np.maximum(vmin - vals, 0).sum())
        rows.append(
            {
                "hour": hour,
                "voltage_exposure_pu": exposure,
                "max_vm_pu": float(vals.max()),
                "min_vm_pu": float(vals.min()),
            }
        )

    return pd.DataFrame(rows)


def _read_cm_need_xlsx(path: Optional[str], stage: str) -> pd.DataFrame:
    """
    Read total_cm_PreMKT.xlsx or total_cm_postMKT.xlsx.

    Unit:
        MVA above congestion-detection threshold
        100 - tol_i.
    """
    df = _safe_read_excel(path, sheet_name="Congestion needs")
    if df is None or df.empty:
        return pd.DataFrame(columns=["hour", "asset", "cm_need_mva", "stage"])

    # First column is usually hour or index.
    first_col = df.columns[0]
    if str(first_col).lower().startswith("unnamed") or str(first_col).lower() != "hour":
        df = df.rename(columns={first_col: "hour"})

    value_cols = [c for c in df.columns if c != "hour"]

    long = df.melt(id_vars=["hour"], value_vars=value_cols, var_name="asset", value_name="cm_need_mva")
    long["cm_need_mva"] = pd.to_numeric(long["cm_need_mva"], errors="coerce").fillna(0.0)

    # Drop total rows where hour is NaN for hourly figures.
    long["hour_numeric"] = pd.to_numeric(long["hour"], errors="coerce")
    long = long[long["hour_numeric"].notna()].copy()
    long["hour"] = long["hour_numeric"].astype(int)
    long.drop(columns=["hour_numeric"], inplace=True)
    long["stage"] = stage

    return long


def _matrix_sheet_to_long(
    xlsx_path: str,
    sheet_name: str,
    resource_type: str,
    variable: str,
    unit: str,
    service: str,
) -> pd.DataFrame:
    """
    Convert a model_results matrix sheet into long form.

    Rows:
        FSP index

    Columns:
        studied hours

    Values:
        activation/dispatched flexibility values.
    """
    try:
        df = pd.read_excel(xlsx_path, sheet_name=sheet_name)
    except Exception:
        return pd.DataFrame()

    if df.empty:
        return pd.DataFrame()

    id_col = df.columns[0]
    hour_cols = []
    for c in df.columns[1:]:
        if re.fullmatch(r"\d+", str(c).strip()):
            hour_cols.append(c)

    if not hour_cols:
        return pd.DataFrame()

    df = df.copy()
    df["_fsp_row_position"] = np.arange(len(df), dtype=int)
    long = df.melt(id_vars=[id_col, "_fsp_row_position"], value_vars=hour_cols, var_name="hour", value_name="value")
    long["hour"] = pd.to_numeric(long["hour"], errors="coerce")
    fsp_numeric = pd.to_numeric(long[id_col], errors="coerce")
    long["fsp_index"] = fsp_numeric.where(fsp_numeric.notna(), long["_fsp_row_position"])
    long["value"] = pd.to_numeric(long["value"], errors="coerce").fillna(0.0)
    long = long.dropna(subset=["hour", "fsp_index"]).copy()
    long["hour"] = long["hour"].astype(int)
    long["fsp_index"] = long["fsp_index"].astype(int)

    # Storage is "ESS", so its labels never read like scenarios S1, S2, ...
    prefix = {"Load": "L", "Generator": "G", "Storage": "ESS"}.get(resource_type, "F")
    resource_label = long[id_col].astype(str).str.strip()
    unnamed = resource_label.eq("") | resource_label.str.lower().isin(["nan", "none"])
    positional_label = prefix + (long["fsp_index"] + 1).astype(str)
    long["resource"] = resource_label.where(~unnamed & fsp_numeric.isna(), positional_label)
    long["resource_type"] = resource_type
    long["variable"] = variable
    long["unit"] = unit
    long["service"] = service
    long["sheet"] = sheet_name

    return long[["hour", "resource", "fsp_index", "resource_type", "variable", "unit", "service", "value", "sheet"]]


def _read_storage_signed_p_from_winj_wads(model_results_file: str) -> pd.DataFrame:
    """
    Fallback reader for old result files where DW_C is missing.

    The platform keeps the original storage Excel export convention:
        Winj_C is exported with the opposite sign of internal injection,
        Wads_C is exported as a positive absorption magnitude.

    Therefore the grid-support signed final storage active power is:
        -Winj_C - Wads_C

    Important:
        This is the final signed storage operating point, not necessarily
        the flexibility activation unless Winit_C is zero. For normal
        current result files, converted DW_C is the preferred activation sheet.
    """
    winj = _matrix_sheet_to_long(
        model_results_file,
        "Winj_C",
        "Storage",
        "Active flexibility P",
        "MW",
        "Active power",
    )
    wads = _matrix_sheet_to_long(
        model_results_file,
        "Wads_C",
        "Storage",
        "Active flexibility P",
        "MW",
        "Active power",
    )

    if winj.empty or wads.empty:
        return pd.DataFrame()

    key_cols = ["hour", "fsp_index"]
    merged = winj[key_cols + ["value"]].rename(columns={"value": "winj_mw"}).merge(
        wads[key_cols + ["value"]].rename(columns={"value": "wads_mw"}),
        on=key_cols,
        how="outer",
    )
    merged[["winj_mw", "wads_mw"]] = merged[["winj_mw", "wads_mw"]].fillna(0.0)
    # Return the same export-side convention as DW_C, then the common
    # load/storage sign conversion below turns it into grid-support sign.
    merged["value"] = merged["winj_mw"] + merged["wads_mw"]

    merged["resource"] = "ESS" + (merged["fsp_index"].astype(int) + 1).astype(str)
    merged["resource_type"] = "Storage"
    merged["variable"] = "Active flexibility P"
    merged["unit"] = "MW"
    merged["service"] = "Active power"
    merged["sheet"] = "Winj_C+Wads_C fallback (export convention; converted after reading)"

    return merged[["hour", "resource", "fsp_index", "resource_type", "variable", "unit", "service", "value", "sheet"]]


def _read_corrected_activation_long(model_results_file: str) -> pd.DataFrame:
    """
    Read only true activation sheets from model_results_*.xlsx.

    This avoids the previous mistake of mixing VA, beta, SOC, RATIO, SMVA, and
    binary variables with market activation quantities.
    """
    if model_results_file is None or not os.path.exists(model_results_file):
        return pd.DataFrame(
            columns=["hour", "resource", "resource_type", "product", "service", "signed_value", "abs_value", "unit", "sheet"]
        )

    sheet_specs = [
        # Loads: active and reactive changes.
        ("DW_A", "Load", "Active flexibility P", "MW", "Active power"),
        ("DR_A", "Load", "Reactive flexibility Q", "MVAr", "Reactive power"),
        # Generators.
        ("DW_B", "Generator", "Active flexibility P", "MW", "Active power"),
        ("DR_B", "Generator", "Reactive flexibility Q", "MVAr", "Reactive power"),
        # Storage reactive power is directly read from DR_C.
        ("DR_C", "Storage", "Reactive flexibility Q", "MVAr", "Reactive power"),
    ]

    frames = []
    for sheet, rtype, variable, unit, service in sheet_specs:
        tmp = _matrix_sheet_to_long(model_results_file, sheet, rtype, variable, unit, service)
        if not tmp.empty:
            frames.append(tmp)

    # Storage active-power flexibility: keep the original platform Excel export
    # convention in the solver/output pipeline, then convert only for
    # visualization interpretation.
    #
    # With ess_conv = ['DR_', 'R_', 'DW_', 'W_', 'Winj_', 'Wads_', 'RATIO_'],
    # exported DW_C follows the pandapower/storage-profile convention:
    #     DW_C_excel > 0 -> more charging / absorption  -> DOWNWARD grid support
    #     DW_C_excel < 0 -> more discharging / injection -> UPWARD grid support
    #
    # For economic plots we want the grid-support sign:
    #     signed_storage_P = -DW_C_excel
    #     positive -> upward flexibility, negative -> downward flexibility.
    storage_p = _matrix_sheet_to_long(
        model_results_file,
        "DW_C",
        "Storage",
        "Active flexibility P",
        "MW",
        "Active power",
    )
    if not storage_p.empty:
        storage_p["sheet"] = "DW_C (export convention; converted to grid-support sign after reading)"
    else:
        storage_p = _read_storage_signed_p_from_winj_wads(model_results_file)
    if not storage_p.empty:
        frames.append(storage_p)

    if not frames:
        return pd.DataFrame(
            columns=["hour", "resource", "resource_type", "product", "service", "signed_value", "abs_value", "unit", "sheet"]
        )

    out = pd.concat(frames, ignore_index=True)
    out = out.rename(columns={"value": "signed_value"})

    # Convert exported resource-variable signs into a common grid-support
    # convention for all economic figures:
    #   positive signed_value -> upward / injection-side system support
    #   negative signed_value -> downward / absorption-side system support
    #
    # Load sheets are exported in load convention, so increased consumption is
    # positive in the workbook but downward from the system viewpoint.
    # Storage sheets are exported with the original platform convention, so
    # charging/absorption appears positive in DW_C/DR_C.
    # Generators are already in the grid-injection convention.
    sign_flip_mask = out["resource_type"].isin(["Load", "Storage"])
    out.loc[sign_flip_mask, "signed_value"] = -out.loc[sign_flip_mask, "signed_value"]

    out["abs_value"] = out["signed_value"].abs()

    # Remove tiny numerical noise.
    out.loc[out["abs_value"] < ACTIVATION_ZERO_TOL, ["signed_value", "abs_value"]] = 0.0

    out["direction"] = np.where(
        out["signed_value"] > ACTIVATION_ZERO_TOL,
        "Upward / injection-side support",
        np.where(out["signed_value"] < -ACTIVATION_ZERO_TOL, "Downward / absorption-side support", "Zero activation"),
    )

    return out


def _build_security_tables(
    pre_ts_root: Optional[str],
    post_ts_root: Optional[str],
    scenario_root: str,
    vmin: float,
    vmax: float,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Build corrected technical security tables.
    """
    total_cm_pre = _read_cm_need_xlsx(os.path.join(scenario_root, "total_cm_PreMKT.xlsx"), "Pre-market")
    total_cm_post = _read_cm_need_xlsx(os.path.join(scenario_root, "total_cm_postMKT.xlsx"), "Post-market")

    cm_need = pd.concat([total_cm_pre, total_cm_post], ignore_index=True)

    pre_100 = _read_loading_exposure_from_folder(pre_ts_root, threshold_percent=100.0)
    pre_100["stage"] = "Pre-market"
    post_100 = _read_loading_exposure_from_folder(post_ts_root, threshold_percent=100.0)
    post_100["stage"] = "Post-market"
    overload_100 = pd.concat([pre_100, post_100], ignore_index=True)

    pre_v = _read_voltage_exposure_from_folder(pre_ts_root, vmin=vmin, vmax=vmax)
    pre_v["stage"] = "Pre-market"
    post_v = _read_voltage_exposure_from_folder(post_ts_root, vmin=vmin, vmax=vmax)
    post_v["stage"] = "Post-market"
    voltage = pd.concat([pre_v, post_v], ignore_index=True)

    return cm_need, overload_100, voltage


def _activation_product_label(row_or_value: Any) -> str:
    """
    Return a compact P/Q product label from a row or variable/unit string.
    """
    text = str(row_or_value)
    if "Reactive" in text or "MVAr" in text or "DR_" in text:
        return "Q"
    return "P"


def _activation_product_unit(product: str) -> str:
    return "MW" if product == "P" else "MVAr"


def _activation_with_product(activation: pd.DataFrame) -> pd.DataFrame:
    """
    Add product and product_unit columns without summing MW and MVAr.
    """
    if activation is None or activation.empty:
        return pd.DataFrame()
    df = activation.copy()
    df["product"] = df["variable"].apply(_activation_product_label)
    df["product_unit"] = df["product"].apply(_activation_product_unit)
    return df


def _market_tag_parts(market_tag: str) -> Dict[str, str]:
    # Both the network identifier and
    # simulation tag may contain underscores (for example SB_DER_LOC_LOW).
    # The trailing simulation suffix is
    # optional because duplicate scenario identifiers are now omitted.
    m = re.match(r"^(.+)_([^_]+)_(PQ|P|Q)_(VL\d+)_(F\d+)_(SK\d+)(?:_(.+))?$", str(market_tag))
    if not m:
        return {}
    country, market, product, vl_case, flex_case, storage_case, ess_case = m.groups()
    return {
        "country": country,
        "market": market,
        "product": product,
        "vl_case": vl_case,
        "flex_case": flex_case,
        "storage_case": storage_case,
        "ess_case": ess_case or "",
    }


def _to_int_hour(value: Any) -> Optional[int]:
    """Convert hour labels such as 0, 0.0, "0", or "h0" to int."""
    if pd.isna(value):
        return None
    text = str(value).strip()
    if text.lower().startswith("h"):
        text = text[1:]
    try:
        return int(float(text))
    except Exception:
        return None
