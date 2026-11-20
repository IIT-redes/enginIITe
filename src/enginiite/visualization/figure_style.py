"""Readability helpers shared by the economic and strategic figure families.

Three recurring problems are solved here instead of in every figure:

1. Crowded provider figures.  Plotting all 101-140 flexibility service providers
   on one axis makes the figure unreadable and hides the result.  Only the
   providers that carry the outcome are drawn, and the remainder is folded into
   one honest ``Others`` entry so no volume, revenue or share is lost.
2. Overlapping labels.  Plotly has no label repulsion, so a scatter of a hundred
   named points becomes a block of ink.  Only the most significant points are
   labelled, their label side alternates, and the full identity stays in the
   hover text.
3. Inconsistent identity between paired subfigures.  When a bar chart on the
   left and a scatter on the right describe the same providers, one shared
   colour per provider lets the reader follow a provider between the panels.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

from . import window_mode

# Qualitative palette that stays distinguishable in print and on screen.
_PALETTE = [
    "#4C78A8", "#F58518", "#54A24B", "#E45756", "#72B7B2", "#EECA3B",
    "#B279A2", "#FF9DA6", "#9D755D", "#BAB0AC", "#1B9E77", "#D95F02",
    "#7570B3", "#E7298A", "#66A61E", "#E6AB02", "#A6761D", "#666666",
]
OTHERS_COLOR = "#C9CDD2"
OTHERS_LABEL = "Others"
# A lighter grey again, for a background population that must be visible as a
# population but must not compete with the result.  OTHERS_COLOR stays darker
# because it is used for an aggregated bar, which has to be readable on its own.
FAINT_COLOR = "#DDE1E6"
FAINT_OPACITY = 0.5

# A provider is only worth its own axis slot above this share of the panel total.
DEFAULT_MIN_SHARE = 0.01
# Keep adding providers until they explain this much of the panel total.
DEFAULT_COVERAGE = 0.92
# Hard cap on named categories per panel, so an axis stays readable.
DEFAULT_MAX_ITEMS = 12
# Hard cap on drawn text labels in a scatter panel.
DEFAULT_MAX_LABELS = 8


def top_significant(
    frame,
    value_column,
    label_column=None,
    max_items=DEFAULT_MAX_ITEMS,
    coverage=DEFAULT_COVERAGE,
    min_share=DEFAULT_MIN_SHARE,
    keep_columns=None,
):
    """Split a provider frame into the significant rows and one ``Others`` row.

    Returns ``(kept, others, note)``.  ``others`` is ``None`` when nothing was
    folded.  ``note`` is a sentence stating exactly what was aggregated, so the
    figure can remain self-explanatory.
    """
    if frame is None or getattr(frame, "empty", True) or value_column not in frame.columns:
        return frame, None, ""
    work = frame.copy()
    work["_magnitude"] = pd.to_numeric(work[value_column], errors="coerce").abs().fillna(0.0)
    work = work.sort_values("_magnitude", ascending=False)
    total = float(work["_magnitude"].sum())
    if total <= 0.0:
        return work.drop(columns="_magnitude"), None, ""

    shares = work["_magnitude"] / total
    cumulative = shares.cumsum()
    significant = (shares >= float(min_share)) & (cumulative - shares < float(coverage))
    significant.iloc[0] = True                       # never drop the largest
    keep_mask = significant.copy()
    if int(max_items) > 0:
        allowed = np.zeros(len(work), dtype=bool)
        allowed[: int(max_items)] = True
        keep_mask = keep_mask & allowed

    kept = work[keep_mask].drop(columns="_magnitude")
    dropped = work[~keep_mask]
    if dropped.empty:
        return kept, None, ""

    dropped_total = float(dropped["_magnitude"].sum())
    others = pd.DataFrame([{value_column: dropped_total}])
    if label_column:
        others[label_column] = "{label} ({n} providers)".format(
            label=OTHERS_LABEL, n=len(dropped)
        )
    for column in keep_columns or []:
        if column in dropped.columns:
            numeric = pd.to_numeric(dropped[column], errors="coerce")
            others[column] = float(numeric.sum()) if numeric.notna().any() else ""
    note = (
        "Readability: the {n} providers that each hold less than {share:.0f}% of the "
        "panel total are folded into one {label} entry ({folded:.4g} of {total:.4g}, "
        "{pct:.1f}%). No volume is discarded; the full provider list stays in the CSV."
    ).format(
        n=len(dropped), share=100.0 * float(min_share), label=OTHERS_LABEL,
        folded=dropped_total, total=total, pct=100.0 * dropped_total / total,
    )
    return kept, others, note


def split_significant(frame, value_column, label_column=None,
                      max_items=DEFAULT_MAX_ITEMS, coverage=DEFAULT_COVERAGE,
                      min_share=DEFAULT_MIN_SHARE):
    """Split a dense provider frame into the named rows and the grey rows.

    Unlike :func:`top_significant`, the tail is returned as its own frame rather
    than aggregated, so a scatter can still draw those points - de-emphasised and
    unlabelled - to show that the population exists without naming every member.
    Returns ``(significant, minor, note)``.
    """
    if frame is None or getattr(frame, "empty", True) or value_column not in frame.columns:
        return frame, None, ""
    kept, _others, _note = top_significant(
        frame, value_column, label_column=label_column, max_items=max_items,
        coverage=coverage, min_share=min_share,
    )
    if kept is None or kept.empty:
        return frame, None, ""
    minor = frame.loc[~frame.index.isin(kept.index)]
    if minor.empty:
        return kept, None, ""
    note = (
        "Readability: {n} of {total} providers each hold less than {share:.0f}% of the "
        "panel total. They are drawn grey and unlabelled, so their presence is visible "
        "without their names colliding; hover gives the identity of every point."
    ).format(n=len(minor), total=len(frame), share=100.0 * float(min_share))
    return kept, minor, note


def minor_scatter(x, y, labels, name="Minor providers (hover for identity)",
                  size=6, extra_hover="", hovertemplate=None, customdata=None,
                  showlegend=True):
    """A de-emphasised light-grey trace for the providers that are not named.

    These points are drawn, not dropped.  A reader has to be able to see that a
    large population sits near the origin -- that fact is itself the result in a
    concentrated market -- while still reading the providers that carry the
    outcome.  So the population is plotted in a grey light enough not to compete
    with the coloured points, and every one of them keeps its identity in the
    hover text.
    """
    import plotly.graph_objects as go
    return go.Scatter(
        x=x, y=y, mode="markers", name=name,
        marker=dict(size=size, color=FAINT_COLOR, opacity=FAINT_OPACITY,
                    line=dict(color="rgba(255,255,255,0.85)", width=0.4)),
        text=[str(v) for v in labels],
        customdata=customdata,
        hovertemplate=(hovertemplate if hovertemplate is not None else
                       "Provider: %{text}<br>x: %{x:.6g}<br>y: %{y:.6g}"
                       + extra_hover + "<extra></extra>"),
        showlegend=showlegend,
    )


def provider_palette(labels):
    """Return one stable colour per label, shared by every panel of a figure."""
    unique = []
    for label in labels:
        text = str(label)
        if text not in unique:
            unique.append(text)
    colours = {}
    for index, text in enumerate(unique):
        colours[text] = (OTHERS_COLOR if text.startswith(OTHERS_LABEL)
                         else _PALETTE[index % len(_PALETTE)])
    return colours


def colours_for(labels, palette):
    """Map a label sequence through a palette, defaulting to the Others grey."""
    return [palette.get(str(label), OTHERS_COLOR) for label in labels]


def declutter_labels(values, texts, max_labels=DEFAULT_MAX_LABELS):
    """Return a text array where only the most significant points are named.

    Every point keeps its hover text; only the drawn labels are thinned, which
    is what actually causes the unreadable block of overlapping names.
    """
    magnitude = pd.to_numeric(pd.Series(list(values)), errors="coerce").abs().fillna(0.0)
    if magnitude.empty:
        return list(texts), ""
    order = magnitude.sort_values(ascending=False).index[: max(int(max_labels), 0)]
    keep = set(order)
    labelled = [str(t) if i in keep else "" for i, t in enumerate(list(texts))]
    hidden = len(labelled) - len(keep)
    note = ""
    if hidden > 0:
        note = (
            "Readability: only the {n} most significant points are labelled; "
            "hover shows the identity of every point."
        ).format(n=len(keep))
    return labelled, note


def alternating_text_positions(count, base="top center", other="bottom center"):
    """Alternate the label side so neighbouring labels do not collide."""
    return [base if index % 2 == 0 else other for index in range(int(count))]


def short_provider_name(name, width=18):
    """Shorten a provider name for an on-bar or on-point label."""
    text = str(name)
    if len(text) <= width:
        return text
    return text[: width - 1] + "…"


def retitle_window_hovers(fig):
    """Rewrite ``Hour %{x}`` hovers when the windows are independent scenarios.

    The hover templates are plain strings spread over thousands of lines, so they
    are corrected once on the finished figure instead of at every call site.
    """
    if window_mode.window_as_timesteps():
        return fig
    replacements = (
        ("Hour %{x}", "Scenario %{x}"),
        ("Hour: %{x}", "Scenario: %{x}"),
        ("Hour %{y}", "Scenario %{y}"),
        ("hour %{x}", "scenario %{x}"),
        ("Studied hour", "Independent scenario"),
    )
    for trace in fig.data:
        for attribute in ("hovertemplate", "hovertext"):
            value = getattr(trace, attribute, None)
            if isinstance(value, str):
                new = value
                for old, replacement in replacements:
                    new = new.replace(old, replacement)
                if new != value:
                    try:
                        setattr(trace, attribute, new)
                    except Exception:
                        pass
    return fig


_WINDOW_TITLE_PATTERN = re.compile(
    r"^\s*(selected\s+|compared\s+|reference\s+)?studied\s+hours?(\s*\[h\])?\s*$"
    r"|^\s*hours?(\s*\[h\])?\s*$"
    r"|^\s*time\s*(step)?s?(\s*\[h\])?\s*$",
    re.I,
)


def retitle_window_axes(fig):
    """Correct any axis still titled as time when the windows are scenarios.

    The audit over one finished run found 378 pages whose window axis still read
    "Studied hour [h]" although the configuration declares independent
    scenarios.  Those titles are written as plain strings in four different
    modules, so they are corrected once on the finished figure rather than at
    every call site -- the same approach already used for the hover text.

    A qualifier such as "Compared" or "Reference" is kept, because on a
    window-versus-window heatmap it is the only thing distinguishing the two
    axes.
    """
    if window_mode.window_as_timesteps():
        return fig
    target = window_mode.axis_title()
    for name in list(fig.layout):
        if not re.match(r"^[xy]axis\d*$", str(name)):
            continue
        axis = fig.layout[name]
        title = getattr(getattr(axis, "title", None), "text", None)
        if not isinstance(title, str) or not title.strip():
            continue
        if not _WINDOW_TITLE_PATTERN.match(title):
            continue
        qualifier = ""
        lowered = title.strip().lower()
        for word in ("compared", "reference", "selected"):
            if lowered.startswith(word):
                qualifier = word.capitalize() + " "
                break
        try:
            axis.title.text = qualifier + (target[0].lower() + target[1:]
                                           if qualifier else target)
        except Exception:
            pass
    return fig


def _visible_colorbar(trace):
    """Return the colorbar object a trace will actually draw, or ``None``.

    Plotly exposes the bar in two different places: heatmap-like traces own it
    directly, while a scatter owns it through ``marker``.  A bar is only drawn
    when the corresponding ``showscale`` is not switched off.
    """
    kind = str(getattr(trace, "type", "") or "")
    if kind in ("heatmap", "heatmapgl", "contour", "histogram2d",
                "histogram2dcontour", "surface", "volume", "isosurface",
                "choropleth", "densitymapbox"):
        if getattr(trace, "showscale", True) is False:
            return None
        return getattr(trace, "colorbar", None)
    marker = getattr(trace, "marker", None)
    if marker is None:
        return None
    if getattr(marker, "showscale", False) is not True:
        return None
    return getattr(marker, "colorbar", None)


def _panel_y_domain(fig, trace):
    """The vertical extent of the subplot a trace belongs to, in paper units."""
    axis = getattr(trace, "yaxis", None) or "y"
    key = "yaxis" + (str(axis)[1:] if len(str(axis)) > 1 else "")
    try:
        domain = fig.layout[key].domain
    except Exception:
        return (0.0, 1.0)
    if domain is None or len(domain) != 2:
        return (0.0, 1.0)
    return (float(domain[0]), float(domain[1]))


def deconflict_right_margin(fig, legend_to_bottom=True):
    """Stop colorbars and the legend from being drawn on top of each other.

    Plotly places a colorbar with no explicit ``x`` just right of the plotting
    area, and it places a vertical legend in the same place.  A figure with two
    colour scales therefore stacks both bars and the legend at the same spot.
    Auditing one finished run found this on 643 pages, which is why it is fixed
    here once rather than in each figure.

    Each bar is tied to the vertical extent of its own subplot, so on a two by
    two grid the upper bar sits beside the upper row and the lower bar beside
    the lower row, which also tells the reader which panel each scale belongs
    to.  Bars sharing one panel are offset sideways instead.  When any bar is
    present the legend moves below the figure, because the right margin is
    taken.
    """
    bars = []
    for trace in fig.data:
        bar = _visible_colorbar(trace)
        if bar is None:
            continue
        if str(getattr(trace, "type", "")) in ("surface", "volume", "isosurface"):
            bars.append((bar, (0.0, 1.0)))
            continue
        bars.append((bar, _panel_y_domain(fig, trace)))
    if not bars:
        return fig

    by_panel = {}
    for bar, domain in bars:
        by_panel.setdefault((round(domain[0], 3), round(domain[1], 3)), []).append(bar)

    for (low, high), group in by_panel.items():
        span = max(high - low, 0.05)
        centre = 0.5 * (low + high)
        for index, bar in enumerate(group):
            try:
                bar.x = 1.02 + 0.085 * index
                bar.xanchor = "left"
                bar.y = centre
                bar.yanchor = "middle"
                bar.len = span * 0.86
                bar.lenmode = "fraction"
                bar.thickness = 15
                bar.xpad = 4
                title = getattr(bar, "title", None)
                if title is not None and getattr(title, "text", None):
                    bar.title.side = "right"
            except Exception:
                continue

    if legend_to_bottom:
        widest = max(1 + len(group) for group in by_panel.values())
        try:
            legend = fig.layout.legend
            horizontal = str(getattr(legend, "orientation", "") or "") == "h"
            if not horizontal:
                # Several figures already carry an interpretation line and a
                # readability note under the axes.  Dropping the legend at a
                # fixed offset would land it on top of them, so it goes below
                # whatever is already there.
                lowest = 0.0
                for annotation in (fig.layout.annotations or []):
                    if getattr(annotation, "yref", None) != "paper":
                        continue
                    y_value = getattr(annotation, "y", None)
                    if isinstance(y_value, (int, float)) and float(y_value) < lowest:
                        lowest = float(y_value)
                fig.update_layout(legend=dict(
                    orientation="h", yanchor="top", y=min(-0.16, lowest - 0.09),
                    xanchor="center", x=0.5,
                    bgcolor="rgba(255,255,255,0.94)",
                    bordercolor="rgba(120,120,120,0.25)", borderwidth=1,
                ))
            # Leave room for the bars and their titles.
            margin = fig.layout.margin
            needed = 90 + 70 * (widest - 1)
            if getattr(margin, "r", None) is None or float(margin.r or 0) < needed:
                fig.update_layout(margin=dict(r=needed))
        except Exception:
            pass
    return fig


def space_stacked_panels(fig, min_gap_px=30):
    """Widen the gap between stacked panels until a subplot title fits in it.

    ``make_subplots`` writes each subplot title as an annotation anchored to the
    top of its panel, but it does not check that the gap left by
    ``vertical_spacing`` is tall enough to hold that text.  When it is not, the
    caption of the upper panel is drawn over the title of the lower one.  The
    audit found this on eight pages, with gaps as small as 0.014 of the figure
    height -- about ten pixels for a line that needs nearly thirty.

    The panel domains are recomputed here rather than the spacing guessed at
    each call site, and the subplot titles are moved onto the new panel tops so
    they continue to sit where they belong.
    """
    height = getattr(fig.layout, "height", None)
    try:
        height = float(height)
    except (TypeError, ValueError):
        return fig
    if height <= 0:
        return fig

    rows = {}
    for name in list(fig.layout):
        if not re.match(r"^yaxis\d*$", str(name)):
            continue
        domain = getattr(fig.layout[name], "domain", None)
        if domain is None or len(domain) != 2:
            return fig
        key = (round(float(domain[0]), 4), round(float(domain[1]), 4))
        rows.setdefault(key, []).append(name)
    if len(rows) < 2:
        return fig

    ordered = sorted(rows, key=lambda d: d[0], reverse=True)   # top row first
    gap_needed = float(min_gap_px) / height
    gaps = [ordered[i][0] - ordered[i + 1][1] for i in range(len(ordered) - 1)]
    if not gaps or min(gaps) >= gap_needed:
        return fig
    if gap_needed * (len(ordered) - 1) >= 0.7:
        # Too many rows to fit; making the panels thinner would be worse.
        return fig

    count = len(ordered)
    panel = (1.0 - gap_needed * (count - 1)) / count
    new_domains = []
    top = 1.0
    for _ in range(count):
        new_domains.append((round(top - panel, 4), round(top, 4)))
        top -= panel + gap_needed

    old_tops = [d[1] for d in ordered]
    remap = {}
    for old, new in zip(ordered, new_domains):
        remap[old[1]] = new[1]
        for axis_name in rows[old]:
            try:
                fig.layout[axis_name].domain = list(new)
            except Exception:
                pass

    # Carry the subplot titles onto the new panel tops.
    for annotation in (fig.layout.annotations or []):
        if getattr(annotation, "yref", None) != "paper":
            continue
        if getattr(annotation, "yanchor", None) != "bottom":
            continue
        y_value = getattr(annotation, "y", None)
        if not isinstance(y_value, (int, float)):
            continue
        nearest = min(old_tops, key=lambda t: abs(t - float(y_value)))
        if abs(nearest - float(y_value)) <= 0.02:
            try:
                annotation.y = remap[nearest]
            except Exception:
                pass
    return fig


def ensure_axis_titles(fig, fallback_x=None, fallback_y=None):
    """Give every axis a title, so no subfigure is left unlabelled.

    A missing title is only filled when a sensible fallback is known, because a
    wrong label is worse than none.  Window-like categorical axes are detected
    from their tick labels and always receive the window title.
    """
    window_title = window_mode.axis_title()
    window_pattern = "S" if window_mode.scenario_mode() else "h"

    def looks_like_window(axis_name):
        for trace in fig.data:
            axis_ref = getattr(trace, "xaxis", "x") or "x"
            expected = "xaxis" if axis_ref == "x" else "xaxis" + axis_ref[1:]
            if expected != axis_name:
                continue
            values = getattr(trace, "x", None)
            if values is None:
                continue
            for value in list(values)[:4]:
                text = str(value)
                if text.startswith(window_pattern) and text[1:].isdigit():
                    return True
        return False

    layout = fig.layout
    for axis_name in [key for key in layout if str(key).startswith("xaxis")]:
        axis = layout[axis_name]
        current = getattr(getattr(axis, "title", None), "text", None)
        if current and str(current).strip():
            continue
        if looks_like_window(axis_name):
            axis.title.text = window_title
        elif fallback_x:
            axis.title.text = fallback_x
    if fallback_y:
        for axis_name in [key for key in layout if str(key).startswith("yaxis")]:
            axis = layout[axis_name]
            current = getattr(getattr(axis, "title", None), "text", None)
            if not (current and str(current).strip()):
                axis.title.text = fallback_y
    return fig


def readability_note(fig, note, y=-0.16):
    """Attach a readability sentence under a figure, if there is one to make."""
    if not note:
        return fig
    # A Plotly annotation can be dropped by a later layout pass, so the note is
    # also stashed on the figure.  The themed HTML writer renders it as a caption
    # under the figure, which no layout manipulation can remove.
    try:
        meta = dict(fig.layout.meta) if isinstance(fig.layout.meta, dict) else {}
        existing = str(meta.get("readability_note", "") or "")
        meta["readability_note"] = (existing + " " + note).strip() if existing else note
        fig.layout.meta = meta
    except Exception:
        pass
    fig.add_annotation(
        x=0.0, y=y, xref="paper", yref="paper", showarrow=False, align="left",
        text=note, bgcolor="rgba(255,255,255,0.94)",
        bordercolor="rgba(107,114,128,0.35)", font=dict(size=11),
    )
    return fig
