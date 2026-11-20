"""Interpretation of ``simulation_window``: time steps or independent scenarios.

``simulation_window`` was originally read as a list of consecutive time steps of
one scenario, so every market index could be pooled over it.  A package such as
``SB_12AGGR`` instead puts twelve *independent* scenarios in one execution, one
per window, only to run and compare them conveniently.  Pooling them would mix
twelve unrelated markets: a provider activated in windows 1, 5 and 11 would look
like one provider earning three times, and revenue shares, HHI, market power and
substitutability would describe a market that never existed.

The YAML key ``simulation_window_as_timesteps`` selects the interpretation:

``True``
    The windows are consecutive time steps of one scenario.  Indices pool over
    them exactly as before.
``False``
    Each window is an independent scenario.  Every index is computed inside one
    window and never across windows, and a figure that would otherwise pool them
    shows one subfigure per window so the scenarios stay comparable but separate.

The mode is process-wide state set once by each visualization entry point, so
the hundreds of existing plotting call sites keep their current signatures.
"""

from __future__ import annotations

import math

TIME = "time"
SCENARIO = "scenario"

_STATE = {"as_timesteps": True}


def set_window_mode(as_timesteps):
    """Set the interpretation for every figure produced afterwards."""
    _STATE["as_timesteps"] = bool(True if as_timesteps is None else as_timesteps)
    return _STATE["as_timesteps"]


def window_as_timesteps():
    """Return True when the windows are consecutive time steps of one scenario."""
    return bool(_STATE["as_timesteps"])


def scenario_mode():
    """Return True when each window is an independent scenario."""
    return not window_as_timesteps()


def mode_name():
    return TIME if window_as_timesteps() else SCENARIO


def noun(plural=False):
    if window_as_timesteps():
        return "hours" if plural else "hour"
    return "scenarios" if plural else "scenario"


def axis_title():
    """Axis title for the window dimension."""
    if window_as_timesteps():
        return "Selected studied hour [h]"
    return "Independent scenario (simulation window)"


def display_index(value):
    """Return the number shown to the reader for one window.

    Time steps keep their own index, because it is the real studied hour.
    Independent scenarios are counted from 1, because "scenario 0" reads as
    "no scenario" to a reader and the twelve designed cases are scenario 1 to 12.
    """
    try:
        index = int(value)
    except (TypeError, ValueError):
        return value
    return index if window_as_timesteps() else index + 1


def tick_text(value):
    """Text shown on the window axis for one window value.

    This is display only, and deliberately so.  The internal window label is
    also a DataFrame column key -- market result sheets are intersected against
    it, and in one place it is parsed back to an integer -- so rewriting the
    label itself silently drops every column that no longer matches.  Plotly is
    therefore given the untouched labels as tick values and this text as the
    tick captions, which changes what the reader sees and nothing else.

    Time steps keep their bare number, because the axis already says the unit.
    Independent scenarios are counted from 1, because "scenario 0" reads as
    "no scenario" and the designed cases are scenario 1 to 12.
    """
    try:
        index = int(value)
    except (TypeError, ValueError):
        return str(value)
    return str(index) if window_as_timesteps() else "S{0}".format(index + 1)


def tick_texts(values):
    """Tick captions for a sequence of window values."""
    return [tick_text(v) for v in values]


def point_label(value):
    """Label one window value."""
    try:
        index = int(value)
    except (TypeError, ValueError):
        return str(value)
    if window_as_timesteps():
        return f"h{index}"
    return f"S{index + 1}"


def file_label(value):
    """Zero-padded label for filenames, using the same numbering as the axes."""
    try:
        index = int(value)
    except (TypeError, ValueError):
        return str(value)
    prefix = "h" if window_as_timesteps() else "S"
    return f"{prefix}{display_index(index):02d}"


def labels(values):
    """Label a sequence of window values."""
    return [point_label(v) for v in values]


def panel_title(value):
    """Subfigure title for one window."""
    try:
        index = int(value)
    except (TypeError, ValueError):
        return str(value)
    if window_as_timesteps():
        return f"Hour {index}"
    return f"Scenario {index + 1}"


def panels(frame, window_column="hour"):
    """Split a frame into the panels a figure should draw.

    In time mode this yields exactly one panel holding the whole frame, so the
    caller keeps its present pooled behaviour.  In scenario mode it yields one
    panel per window, in ascending window order, so no index is ever computed
    across two independent scenarios.
    """
    if frame is None or getattr(frame, "empty", True):
        return []
    if window_as_timesteps() or window_column not in getattr(frame, "columns", []):
        return [(None, frame)]
    out = []
    for value in sorted(frame[window_column].dropna().unique()):
        panel = frame[frame[window_column] == value]
        if not panel.empty:
            out.append((value, panel))
    return out


def grid_shape(count, max_columns=4):
    """Return (rows, cols) for a small-multiples grid of ``count`` panels."""
    count = max(int(count), 1)
    columns = min(max_columns, count)
    rows = int(math.ceil(count / columns))
    return rows, columns


def pooling_note():
    """One sentence stating how the window dimension was treated."""
    if window_as_timesteps():
        return (
            "simulation_window is read as consecutive time steps of one scenario, "
            "so this index pools every studied hour."
        )
    return (
        "simulation_window is read as independent scenarios, so this index is "
        "computed inside one scenario and is never pooled across scenarios."
    )
